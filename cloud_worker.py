import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time

import requests
from pywebpush import WebPushException, webpush

import cloud_store
import email_notifications
import main


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
LOGGER = logging.getLogger("remote-job-finder-worker")
STOP_EVENT = threading.Event()
MINIMUM_SAVE_SCORE = 6


def get_interval_seconds():
    raw_minutes = os.getenv("JOB_CHECK_INTERVAL_MINUTES", "60")
    try:
        minutes = int(raw_minutes)
    except ValueError as exc:
        raise ValueError("JOB_CHECK_INTERVAL_MINUTES must be an integer.") from exc
    if minutes < 1:
        raise ValueError("JOB_CHECK_INTERVAL_MINUTES must be at least 1.")
    return minutes * 60


def matching_jobs(jobs, preferences):
    return [
        matched_job
        for job in jobs
        if (matched_job := main.score_job_for_profile(job, preferences))
    ]


def send_push_notifications(jobs, profiles):
    if not jobs or not profiles:
        return

    subscriptions = cloud_store.get_push_subscriptions()
    if not subscriptions:
        LOGGER.info("No users have enabled push notifications.")
        return

    private_key = cloud_store.get_vapid_private_key()
    subject = cloud_store.get_vapid_claims_email()
    subscriptions_by_user = {}
    for row in subscriptions:
        subscriptions_by_user.setdefault(row["user_id"], []).append(row)

    for profile in profiles:
        profile_jobs = matching_jobs(jobs, profile)
        user_subscriptions = subscriptions_by_user.get(profile["user_id"], [])
        if not profile_jobs or not user_subscriptions:
            continue

        titles = [job.get("title") or "New job" for job in profile_jobs[:3]]
        remaining_count = len(profile_jobs) - len(titles)
        if remaining_count:
            titles.append(f"and {remaining_count} more")
        payload = json.dumps({
            "title": f"{len(profile_jobs)} new job match{'es' if len(profile_jobs) != 1 else ''}",
            "body": " · ".join(titles),
            "url": profile_jobs[0]["url"],
        })
        for row in user_subscriptions:
            try:
                webpush(
                    subscription_info=row["subscription"],
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims={"sub": f"mailto:{subject.removeprefix('mailto:')}"},
                    ttl=60 * 60 * 24,
                )
            except WebPushException as exc:
                response = getattr(exc, "response", None)
                status = getattr(response, "status_code", None)
                LOGGER.warning(
                    "Push delivery failed for one subscription (HTTP %s).",
                    status or "unknown"
                )
                if status in {404, 410}:
                    cloud_store.remove_push_subscription_by_endpoint(
                        row["subscription"]
                    )


def queue_matching_email_notifications(jobs, profiles):
    for profile in profiles:
        if not profile.get("email_notifications"):
            continue
        profile_jobs = matching_jobs(jobs, profile)
        if not profile_jobs:
            continue
        cloud_store.queue_email_notifications(
            profile["user_id"],
            profile["notification_email"],
            profile_jobs,
        )


def send_pending_email_notifications():
    for batch in cloud_store.get_pending_email_batches().values():
        try:
            idempotency_source = ",".join(str(value) for value in batch["ids"])
            idempotency_key = hashlib.sha256(
                idempotency_source.encode("utf-8")
            ).hexdigest()
            email_notifications.send_job_alert(
                batch["recipient"],
                batch["jobs"],
                idempotency_key=idempotency_key,
            )
            cloud_store.mark_email_notifications_sent(batch["ids"])
        except (
            email_notifications.EmailDeliveryError,
            requests.RequestException,
            ValueError,
            cloud_store.CloudServiceError,
        ) as exc:
            message = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("Email delivery failed; queued alerts will be retried.")
            cloud_store.record_email_notification_error(batch["ids"], message)


def run_check():
    interval_seconds = get_interval_seconds()
    previous_status = cloud_store.get_monitor_status(interval_seconds)
    first_check = previous_status["last_check"] is None
    started_at = time.time()
    cloud_store.update_monitor_status(
        last_check=previous_status["last_check"],
        next_check=started_at + interval_seconds,
        last_error=None,
        checking=True,
    )

    error = None
    try:
        saved_jobs = cloud_store.get_all_jobs()
        saved_urls = {str(job.get("url") or "") for job in saved_jobs}
        candidates = []
        for raw_job in main.collect_job_listings():
            job = main.normalize_job_profile(raw_job)
            job_url = str(job.get("url") or "")
            if (
                not job_url.startswith(("https://", "http://"))
                or job_url in saved_urls
                or not job["role_families"]
                or job["work_arrangement"] == "onsite"
            ):
                continue
            job["score"] = 0
            job["match_category"] = "Unrated"
            candidates.append(job)
            saved_urls.add(job_url)

        inserted_jobs = cloud_store.record_new_jobs(
            candidates,
            create_events=not first_check,
        )
        if not first_check:
            profiles = cloud_store.get_user_profiles()
            queue_matching_email_notifications(inserted_jobs, profiles)
            send_push_notifications(inserted_jobs, profiles)
        LOGGER.info(
            "Collection complete: %s candidate listings, %s inserted.",
            len(candidates),
            len(inserted_jobs),
        )
        error = None
    except (
        requests.RequestException,
        cloud_store.CloudServiceError,
        OSError,
        ValueError,
        main.JobSourceError,
    ) as exc:
        error = f"{type(exc).__name__}: {exc}"
        LOGGER.exception("Scheduled job check failed: %s", error)
    finally:
        try:
            send_pending_email_notifications()
        except cloud_store.CloudServiceError:
            LOGGER.exception("Could not process queued email alerts.")
        checked_at = time.time()
        cloud_store.update_monitor_status(
            last_check=checked_at,
            next_check=checked_at + interval_seconds,
            last_error=error,
            checking=False,
        )
    return error


def stop_worker(signum, _frame):
    del _frame
    LOGGER.info("Received signal %s; stopping after this check.", signum)
    STOP_EVENT.set()


def run_worker():
    cloud_store.get_cloud_config()
    cloud_store.get_vapid_private_key()
    cloud_store.get_vapid_claims_email()
    interval_seconds = get_interval_seconds()
    signal.signal(signal.SIGTERM, stop_worker)
    signal.signal(signal.SIGINT, stop_worker)
    LOGGER.info("Cloud job worker started; checks run every %s minutes.", interval_seconds // 60)

    while not STOP_EVENT.is_set():
        run_check()
        STOP_EVENT.wait(interval_seconds)


def run_once():
    cloud_store.get_cloud_config()
    cloud_store.get_vapid_private_key()
    cloud_store.get_vapid_claims_email()
    return 1 if run_check() else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        sys.exit(run_once())
    if sys.argv[1:]:
        raise SystemExit("Usage: python cloud_worker.py [--once]")
    run_worker()
