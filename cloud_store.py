import os
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests


REQUEST_TIMEOUT = 20
EXPERIENCE_LEVELS = {"entry", "mid", "senior"}
WORK_ARRANGEMENTS = {"remote", "hybrid"}

ROLE_FAMILY_IDS = {
    "frontend_web",
    "software_it",
    "digital_marketing",
    "social_media",
    "graphic_design",
    "writing_content",
    "customer_support",
    "sales_business",
    "product_project",
    "data_analytics",
    "hr_recruiting",
    "operations_admin",
    "finance_accounting",
    "education_training",
    "other",
}


class CloudServiceError(RuntimeError):

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def is_cloud_mode():
    return os.getenv("DEPLOYMENT_MODE", "").lower() == "cloud"


def get_cloud_config():
    required = (
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "VAPID_PUBLIC_KEY",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise CloudServiceError(
            f"Cloud configuration is missing: {', '.join(missing)}.",
            status=503
        )

    return {
        "supabase_url": os.environ["SUPABASE_URL"].rstrip("/"),
        "supabase_anon_key": os.environ["SUPABASE_ANON_KEY"],
        "vapid_public_key": os.environ["VAPID_PUBLIC_KEY"],
    }


def _service_request(method, path, *, params=None, data=None, headers=None):
    config = get_cloud_config()
    request_headers = {
        "apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"],
        "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_ROLE_KEY']}",
        "Content-Type": "application/json",
    }
    if headers:
        request_headers.update(headers)

    try:
        response = requests.request(
            method,
            f"{config['supabase_url']}/rest/v1/{path}",
            params=params,
            json=data,
            headers=request_headers,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise CloudServiceError(
            f"Could not reach the cloud database ({type(exc).__name__})."
        ) from exc

    if not response.ok:
        detail = ""
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("message") or payload.get("hint") or ""
        except ValueError:
            pass
        message = f"Cloud database request failed ({response.status_code})"
        if detail:
            message += f": {detail}"
        raise CloudServiceError(message, status=502)

    if not response.content:
        return None

    try:
        return response.json()
    except ValueError as exc:
        raise CloudServiceError("Cloud database returned invalid JSON.") from exc


def authenticate(access_token):
    config = get_cloud_config()
    try:
        response = requests.get(
            f"{config['supabase_url']}/auth/v1/user",
            headers={
                "apikey": config["supabase_anon_key"],
                "Authorization": f"Bearer {access_token}",
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise CloudServiceError(
            f"Could not verify the sign-in session ({type(exc).__name__}).",
            status=503
        ) from exc

    if response.status_code in {401, 403}:
        raise CloudServiceError("Your sign-in session has expired.", status=401)
    if not response.ok:
        raise CloudServiceError(
            f"Sign-in verification failed ({response.status_code}).",
            status=503
        )

    try:
        user = response.json()
    except ValueError as exc:
        raise CloudServiceError("Sign-in service returned invalid JSON.") from exc
    if not isinstance(user, dict) or not isinstance(user.get("id"), str):
        raise CloudServiceError("Sign-in service returned an invalid user.")
    return user


def _select_all_jobs():
    rows = []
    start = 0
    page_size = 1000
    while True:
        page = _service_request(
            "GET",
            "jobs",
            params={
                "select": (
                    "url,title,company,location,description,source,score,match_category,"
                    "role_families,experience_level,work_arrangement"
                ),
                "order": "score.desc,url.asc",
                "limit": str(page_size),
            },
            headers={
                "Range-Unit": "items",
                "Range": f"{start}-{start + page_size - 1}",
            },
        )
        if not isinstance(page, list):
            raise CloudServiceError("Cloud database returned an invalid jobs list.")
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def get_all_jobs():
    return _select_all_jobs()


def get_jobs_for_user(user_id):
    jobs = _select_all_jobs()
    status_rows = _service_request(
        "GET",
        "user_job_statuses",
        params={
            "select": "job_url,status",
            "user_id": f"eq.{user_id}",
        },
    )
    if not isinstance(status_rows, list):
        raise CloudServiceError("Cloud database returned invalid job statuses.")

    statuses = {row["job_url"]: row["status"] for row in status_rows}
    return [
        {
            **job,
            **({"status": statuses[job["url"]]} if job["url"] in statuses else {}),
        }
        for job in jobs
    ]


def get_user_preferences(user_id):
    rows = _service_request(
        "GET",
        "user_preferences",
        params={
            "select": (
                "user_id,role_families,experience_levels,work_arrangements,"
                "email_notifications,profile_locked"
            ),
            "user_id": f"eq.{user_id}",
        },
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid user preferences.")
    return rows[0] if rows else None


def get_user_profiles():
    rows = _service_request(
        "GET",
        "user_preferences",
        params={
            "select": (
                "user_id,notification_email,role_families,experience_levels,"
                "work_arrangements,email_notifications,profile_locked"
            ),
            "profile_locked": "eq.true",
        },
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid search profiles.")
    return rows


def save_user_preferences(user, preferences):
    if not isinstance(preferences, dict):
        raise ValueError("Preferences must be a JSON object.")
    existing = get_user_preferences(user["id"])
    if existing and existing.get("profile_locked"):
        raise ValueError("Unlock your saved search before changing it.")

    role_families = preferences.get("role_families")
    experience_levels = preferences.get("experience_levels")
    work_arrangements = preferences.get("work_arrangements")
    email_notifications = preferences.get("email_notifications")
    if (
        not isinstance(role_families, list)
        or not role_families
        or not all(isinstance(value, str) for value in role_families)
        or not set(role_families).issubset(ROLE_FAMILY_IDS)
    ):
        raise ValueError("Choose at least one supported job family.")
    if (
        not isinstance(experience_levels, list)
        or not experience_levels
        or not all(isinstance(value, str) for value in experience_levels)
        or not set(experience_levels).issubset(EXPERIENCE_LEVELS)
    ):
        raise ValueError("Choose at least one supported experience level.")
    if (
        not isinstance(work_arrangements, list)
        or not work_arrangements
        or not all(isinstance(value, str) for value in work_arrangements)
        or not set(work_arrangements).issubset(WORK_ARRANGEMENTS)
    ):
        raise ValueError("Choose Remote, Hybrid, or both.")
    if not isinstance(email_notifications, bool):
        raise ValueError("Email notifications must be enabled or disabled.")
    email = user.get("email")
    if email_notifications and (
        not isinstance(email, str) or "@" not in email
    ):
        raise ValueError("Your Google account does not provide a valid email address.")

    _service_request(
        "POST",
        "user_preferences",
        params={"on_conflict": "user_id"},
        data=[{
            "user_id": user["id"],
            "notification_email": email or "",
            "role_families": sorted(set(role_families)),
            "experience_levels": sorted(set(experience_levels)),
            "work_arrangements": sorted(set(work_arrangements)),
            "email_notifications": email_notifications,
            "profile_locked": True,
        }],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )
    if not email_notifications:
        cancel_pending_email_notifications(user["id"])


def unlock_user_preferences(user_id):
    rows = _service_request(
        "PATCH",
        "user_preferences",
        params={
            "user_id": f"eq.{user_id}",
            "select": "user_id",
        },
        data={"profile_locked": False},
        headers={"Prefer": "return=representation"},
    )
    if not isinstance(rows, list) or not rows:
        raise CloudServiceError("No saved search was found to unlock.", status=404)


def queue_email_notifications(user_id, recipient, jobs):
    if not jobs:
        return
    rows = [
        {
            "user_id": user_id,
            "job_url": job["url"],
            "notification_email": recipient,
        }
        for job in jobs
        if job.get("url")
    ]
    if not rows:
        return
    _service_request(
        "POST",
        "email_outbox",
        params={"on_conflict": "user_id,job_url"},
        data=rows,
        headers={"Prefer": "resolution=ignore-duplicates,return=minimal"},
    )


def get_pending_email_batches(limit=50):
    rows = _service_request(
        "GET",
        "email_outbox",
        params={
            "select": (
                "id,user_id,notification_email,job_url,"
                "job:jobs(url,title,company,location,description,source,"
                "score,match_category,role_families,experience_level,work_arrangement)"
            ),
            "status": "eq.pending",
            "order": "id.asc",
            "limit": str(limit),
        },
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid pending email alerts.")

    batches = {}
    for row in rows:
        if not isinstance(row.get("job"), dict):
            continue
        batch = batches.setdefault(
            row["user_id"],
            {
                "recipient": row["notification_email"],
                "ids": [],
                "jobs": [],
            },
        )
        batch["ids"].append(row["id"])
        batch["jobs"].append(row["job"])
    return batches


def mark_email_notifications_sent(outbox_ids):
    if not outbox_ids:
        return
    _service_request(
        "PATCH",
        "email_outbox",
        params={"id": f"in.({','.join(str(value) for value in outbox_ids)})"},
        data={
            "status": "sent",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        },
        headers={"Prefer": "return=minimal"},
    )


def record_email_notification_error(outbox_ids, message):
    if not outbox_ids:
        return
    _service_request(
        "POST",
        "rpc/record_email_failure",
        data={"outbox_ids": outbox_ids, "error_text": message[:1000]},
    )


def cancel_pending_email_notifications(user_id):
    _service_request(
        "DELETE",
        "email_outbox",
        params={
            "user_id": f"eq.{user_id}",
            "status": "eq.pending",
        },
    )


def set_job_status(user_id, job_url, status):
    if status == "new":
        _service_request(
            "DELETE",
            "user_job_statuses",
            params={
                "user_id": f"eq.{user_id}",
                "job_url": f"eq.{job_url}",
            },
        )
        return

    _service_request(
        "POST",
        "user_job_statuses",
        params={"on_conflict": "user_id,job_url"},
        data=[{
            "user_id": user_id,
            "job_url": job_url,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def get_notifications(after_id):
    events = _service_request(
        "GET",
        "job_events",
        params={
            "select": (
                "id,job_url,created_at,"
                "job:jobs(url,title,company,location,description,source,score,match_category)"
            ),
            "id": f"gt.{after_id}",
            "order": "id.asc",
            "limit": "500",
        },
    )
    if not isinstance(events, list):
        raise CloudServiceError("Cloud database returned invalid notifications.")
    if not events:
        return []

    jobs = [
        event["job"]
        for event in events
        if isinstance(event.get("job"), dict)
    ]
    if not jobs:
        return []
    return [{
        "id": str(events[-1]["id"]),
        "created_at": events[-1]["created_at"],
        "jobs": jobs,
    }]


def get_latest_notification_id():
    rows = _service_request(
        "GET",
        "job_events",
        params={"select": "id", "order": "id.desc", "limit": "1"},
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid notification status.")
    return str(rows[0]["id"]) if rows else "0"


def get_monitor_status(interval_seconds):
    rows = _service_request(
        "GET",
        "monitor_state",
        params={"select": "last_check,next_check,last_error,checking", "id": "eq.1"},
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid monitor status.")
    if not rows:
        return {
            "interval_seconds": interval_seconds,
            "last_check": None,
            "next_check": None,
            "last_error": None,
            "checking": False,
        }
    return {"interval_seconds": interval_seconds, **rows[0]}


def update_monitor_status(*, last_check, next_check, last_error, checking):
    _service_request(
        "POST",
        "monitor_state",
        params={"on_conflict": "id"},
        data=[{
            "id": 1,
            "last_check": last_check,
            "next_check": next_check,
            "last_error": last_error,
            "checking": checking,
        }],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def record_new_jobs(jobs, create_events):
    if not jobs:
        return []
    rows = _service_request(
        "POST",
        "rpc/record_new_jobs",
        data={"job_rows": jobs, "create_events": create_events},
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid new job records.")
    return rows


def get_push_subscriptions():
    rows = _service_request(
        "GET",
        "push_subscriptions",
        params={"select": "user_id,endpoint,subscription"},
    )
    if not isinstance(rows, list):
        raise CloudServiceError("Cloud database returned invalid push subscriptions.")
    return rows


def save_push_subscription(user_id, subscription):
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys")
    hostname = urlsplit(endpoint).hostname if isinstance(endpoint, str) else None
    trusted_push_hosts = {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
        "push.services.mozilla.com",
        "web.push.apple.com",
    }
    if (
        not isinstance(endpoint, str)
        or not endpoint.startswith("https://")
        or not hostname
        or (
            hostname.lower() not in trusted_push_hosts
            and hostname.lower() != "notify.windows.com"
            and not hostname.lower().endswith(".notify.windows.com")
        )
        or not isinstance(keys, dict)
        or not isinstance(keys.get("p256dh"), str)
        or not isinstance(keys.get("auth"), str)
    ):
        raise ValueError("A supported browser push subscription is required.")

    _service_request(
        "POST",
        "push_subscriptions",
        params={"on_conflict": "endpoint"},
        data=[{
            "user_id": user_id,
            "endpoint": endpoint,
            "subscription": subscription,
        }],
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
    )


def delete_push_subscription(user_id, endpoint):
    _service_request(
        "DELETE",
        "push_subscriptions",
        params={
            "user_id": f"eq.{user_id}",
            "endpoint": f"eq.{endpoint}",
        },
    )


def import_user_jobs(user_id, jobs):
    if not isinstance(jobs, list) or len(jobs) > 200:
        raise ValueError("The import must contain no more than 200 jobs.")

    valid_jobs = []
    valid_statuses = []
    seen_urls = set()
    for job in jobs:
        if not isinstance(job, dict):
            continue
        status = job.get("status")
        url = job.get("url")
        title = job.get("title")
        if (
            not isinstance(status, str)
            or status not in {"saved", "applied"}
            or not isinstance(url, str)
            or not url.startswith(("https://", "http://"))
            or not isinstance(title, str)
            or not title.strip()
            or url in seen_urls
        ):
            continue

        seen_urls.add(url)
        valid_jobs.append({
            "url": url,
            "title": title[:500],
            "company": str(job.get("company") or "")[:500],
            "location": str(job.get("location") or "")[:500],
            "description": str(job.get("description") or "")[:100_000],
            "source": str(job.get("source") or "Imported")[:200],
            "score": max(0, min(int(job.get("score") or 0), 100)),
            "match_category": str(job.get("match_category") or "Unrated")[:100],
        })
        valid_statuses.append({
            "user_id": user_id,
            "job_url": url,
            "status": status,
        })

    if valid_jobs:
        record_new_jobs(valid_jobs, create_events=False)
        _service_request(
            "POST",
            "user_job_statuses",
            params={"on_conflict": "user_id,job_url"},
            data=valid_statuses,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )
    return len(valid_jobs)


def remove_push_subscription_by_endpoint(subscription):
    endpoint = subscription.get("endpoint")
    if isinstance(endpoint, str) and endpoint.startswith("https://"):
        _service_request(
            "DELETE",
            "push_subscriptions",
            params={"endpoint": f"eq.{endpoint}"},
        )


def get_vapid_private_key():
    value = os.getenv("VAPID_PRIVATE_KEY")
    if not value:
        raise CloudServiceError("VAPID_PRIVATE_KEY is not configured.", status=503)
    return value


def get_vapid_claims_email():
    value = os.getenv("VAPID_CLAIMS_EMAIL")
    if not value:
        raise CloudServiceError("VAPID_CLAIMS_EMAIL is not configured.", status=503)
    return value
