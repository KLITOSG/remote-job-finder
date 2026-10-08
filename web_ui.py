import json
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import main
import requests
import cloud_store
import email_notifications


PROJECT_DIR = Path(__file__).resolve().parent
JOBS_FILE = PROJECT_DIR / "jobs.json"
HOST = "0.0.0.0" if cloud_store.is_cloud_mode() else "127.0.0.1"
PORT = int(os.getenv("PORT", "8000"))
JOBS_FILE_LOCK = threading.Lock()
SUPPORT_REPORT_LOCK = threading.Lock()
SUPPORT_REPORT_TIMES = {}
SUPPORT_REPORT_LIMIT = 3
SUPPORT_REPORT_WINDOW_SECONDS = 600
LOGGER = logging.getLogger("remote-job-finder-web")
SKILL_PATTERNS = [
    ("JavaScript", r"\bjavascript\b|\bjs\b"),
    ("TypeScript", r"\btypescript\b|\bts\b"),
    ("React", r"\breact(?:\.js)?\b"),
    ("HTML", r"\bhtml(?:5)?\b"),
    ("CSS", r"\bcss(?:3)?\b"),
    ("Node.js", r"\bnode\.?js\b"),
    ("REST API", r"\brest(?:ful)?\s+apis?\b"),
    ("Git", r"\bgit\b"),
    ("GitHub", r"\bgithub\b"),
    ("DOM", r"\bdom\b")
]

def prepare_job_for_display(job):
    description = main.get_description_text(job.get("description"))

    searchable = f"{job.get('title') or ''} {description}"
    skills = [
        label
        for label, pattern in SKILL_PATTERNS
        if re.search(pattern, searchable, flags=re.IGNORECASE)
    ]

    display_job = dict(job)
    display_job["description_text"] = description
    display_job["description_preview"] = description[:280].rstrip()
    if len(description) > 280:
        display_job["description_preview"] += "..."
    display_job["skills"] = skills
    return display_job


class JobScheduler:

    def __init__(self, interval_seconds):
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.events = []
        self.last_check = None
        self.next_check = None
        self.last_error = None
        self.checking = False
        self.thread = threading.Thread(
            target=self._run,
            name="job-collection-scheduler",
            daemon=True
        )

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def _run(self):
        while not self.stop_event.is_set():
            self.run_check()
            self.stop_event.wait(self.interval_seconds)

    def run_check(self):
        with self.lock:
            self.checking = True
            self.last_error = None

        try:
            with JOBS_FILE_LOCK:
                new_jobs = main.run_job_finder(show_notification=False)
        except (requests.RequestException, OSError, ValueError, main.JobSourceError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"Scheduled job check failed: {error}")
            with self.lock:
                self.last_check = time.time()
                self.next_check = self.last_check + self.interval_seconds
                self.last_error = error
                self.checking = False
            return []

        checked_at = time.time()
        with self.lock:
            self.last_check = checked_at
            self.next_check = checked_at + self.interval_seconds
            self.last_error = None
            self.checking = False
            if new_jobs:
                self.events.append({
                    "id": str(time.time_ns()),
                    "created_at": checked_at,
                    "jobs": [prepare_job_for_display(job) for job in new_jobs]
                })
                self.events = self.events[-100:]

        return new_jobs

    def get_status(self):
        with self.lock:
            return {
                "interval_seconds": self.interval_seconds,
                "last_check": self.last_check,
                "next_check": self.next_check,
                "last_error": self.last_error,
                "checking": self.checking
            }

    def get_notifications(self, after_id):
        with self.lock:
            return [
                event for event in self.events
                if int(event["id"]) > after_id
            ]


def get_check_interval_seconds():
    raw_minutes = os.getenv("JOB_CHECK_INTERVAL_MINUTES", "60")
    try:
        minutes = int(raw_minutes)
    except ValueError as exc:
        raise ValueError("JOB_CHECK_INTERVAL_MINUTES must be an integer.") from exc

    if minutes < 1:
        raise ValueError("JOB_CHECK_INTERVAL_MINUTES must be at least 1.")

    return minutes * 60


SCHEDULER = JobScheduler(get_check_interval_seconds())


class JobFinderRequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        if path == "/api/config":
            self.send_config()
            return
        if path == "/service-worker.js":
            self.send_static_file("service-worker.js", "text/javascript; charset=utf-8")
            return
        if path == "/icon.svg":
            self.send_static_file("icon.svg", "image/svg+xml")
            return
        if path == "/manifest.webmanifest":
            self.send_static_file("manifest.webmanifest", "application/manifest+json")
            return

        if cloud_store.is_cloud_mode():
            self.handle_cloud_get(path)
            return

        if path == "/api/jobs":
            self.send_jobs()
            return
        if path == "/api/status":
            self.send_json(200, SCHEDULER.get_status())
            return
        if path == "/api/notifications":
            query = parse_qs(urlsplit(self.path).query)
            try:
                after_id = int(query.get("after", ["0"])[0])
                if after_id < 0:
                    raise ValueError
            except ValueError:
                self.send_json_error(400, "The after value must be a non-negative integer.")
                return
            self.send_json(200, SCHEDULER.get_notifications(after_id))
            return

        if path in {"/", "/index.html"}:
            self.send_index()
            return

        self.send_error(404, "Not found")

    def do_POST(self):
        if urlsplit(self.path).path == "/api/support-report":
            self.handle_support_report()
            return

        if cloud_store.is_cloud_mode():
            self.handle_cloud_post()
            return

        if urlsplit(self.path).path != "/api/job-status":
            self.send_error(404, "Not found")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length < 1 or content_length > 16_384:
                self.send_json_error(400, "Request body is empty or too large.")
                return

            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")

            job_url = payload.get("url")
            status = payload.get("status")
            if not isinstance(job_url, str) or not job_url.startswith(("https://", "http://")):
                raise ValueError("A valid job URL is required.")
            if not isinstance(status, str) or status not in {"new", "saved", "applied"}:
                raise ValueError("Status must be new, saved, or applied.")

            with JOBS_FILE_LOCK:
                with JOBS_FILE.open("r", encoding="utf-8") as file:
                    jobs = json.load(file)
                if not isinstance(jobs, list):
                    raise ValueError("jobs.json must contain a JSON list.")

                matching_jobs = [
                    job for job in jobs
                    if isinstance(job, dict) and job.get("url") == job_url
                ]
                if not matching_jobs:
                    self.send_json_error(404, "Job was not found in jobs.json.")
                    return

                for job in matching_jobs:
                    if status == "new":
                        job.pop("status", None)
                    else:
                        job["status"] = status

                temporary_file = JOBS_FILE.with_suffix(".json.tmp")
                temporary_file.write_text(
                    json.dumps(jobs, indent=4, ensure_ascii=False),
                    encoding="utf-8"
                )
                temporary_file.replace(JOBS_FILE)

        except FileNotFoundError:
            self.send_json_error(404, "jobs.json not found. Run python main.py first.")
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json_error(400, f"Could not update job status: {exc}")
            return
        except OSError as exc:
            self.send_json_error(500, f"Could not save job status: {exc}")
            return

        self.send_json(200, {"url": job_url, "status": status})

    def handle_support_report(self):
        try:
            payload = self.read_json_body(8_192)
            if not isinstance(payload, dict):
                raise ValueError("Request body must be a JSON object.")
            if payload.get("website"):
                raise ValueError("The problem report could not be accepted.")

            issue_type = payload.get("issue_type")
            details = payload.get("details")
            contact_email = payload.get("contact_email", "")
            if not isinstance(issue_type, str) or issue_type not in email_notifications.SUPPORT_ISSUE_TYPES:
                raise ValueError("Please choose what kind of problem happened.")
            if not isinstance(details, str) or not details.strip():
                raise ValueError("Please describe what happened.")
            if len(details) > 2_000:
                raise ValueError("Please keep the description under 2,000 characters.")
            if not isinstance(contact_email, str):
                raise ValueError("Contact email must be text.")

            now = time.monotonic()
            client_ip = self.client_address[0]
            with SUPPORT_REPORT_LOCK:
                for stored_ip, timestamps in list(SUPPORT_REPORT_TIMES.items()):
                    valid_timestamps = [
                        submitted_at
                        for submitted_at in timestamps
                        if now - submitted_at < SUPPORT_REPORT_WINDOW_SECONDS
                    ]
                    if valid_timestamps:
                        SUPPORT_REPORT_TIMES[stored_ip] = valid_timestamps
                    else:
                        SUPPORT_REPORT_TIMES.pop(stored_ip, None)
                recent_reports = [
                    submitted_at
                    for submitted_at in SUPPORT_REPORT_TIMES.get(client_ip, [])
                    if now - submitted_at < SUPPORT_REPORT_WINDOW_SECONDS
                ]
                if len(recent_reports) >= SUPPORT_REPORT_LIMIT:
                    self.send_json_error(
                        429,
                        "Too many reports were sent from this connection. Please try again in a few minutes.",
                    )
                    return
                recent_reports.append(now)
                SUPPORT_REPORT_TIMES[client_ip] = recent_reports

            email_notifications.send_support_report(
                issue_type,
                details,
                contact_email.strip(),
            )
        except json.JSONDecodeError:
            self.send_json_error(400, "Please submit a valid problem report.")
            return
        except ValueError as exc:
            self.send_json_error(400, str(exc))
            return
        except (email_notifications.EmailDeliveryError, requests.RequestException):
            LOGGER.exception("Could not deliver a support report.")
            self.send_json_error(
                503,
                "Your report could not be emailed right now. Please email gaitanosklitos@gmail.com directly.",
            )
            return

        self.send_json(200, {"sent": True})

    def do_DELETE(self):
        if (
            cloud_store.is_cloud_mode()
            and urlsplit(self.path).path == "/api/push-subscription"
        ):
            self.handle_cloud_post()
            return
        self.send_error(404, "Not found")

    def handle_cloud_get(self, path):
        if path not in {
            "/api/jobs",
            "/api/status",
            "/api/notifications",
            "/api/notifications/latest",
            "/api/preferences",
        }:
            if path in {"/", "/index.html"}:
                self.send_index()
            else:
                self.send_error(404, "Not found")
            return

        user = self.authenticate_request()
        if user is None:
            return

        try:
            if path == "/api/preferences":
                self.send_json(
                    200,
                    cloud_store.get_user_preferences(user["id"])
                )
                return
            if path == "/api/jobs":
                profile = cloud_store.get_user_preferences(user["id"])
                if not profile or not profile.get("profile_locked"):
                    self.send_json(200, [])
                    return
                jobs = []
                for job in cloud_store.get_jobs_for_user(user["id"]):
                    matched_job = main.score_job_for_profile(job, profile)
                    if matched_job is None:
                        if job.get("status") not in {"saved", "applied"}:
                            continue
                        job = {**job, "score": 0, "match_category": "Outside saved search"}
                    else:
                        job = matched_job
                    jobs.append(prepare_job_for_display(job))
                self.send_json(200, jobs)
                return
            if path == "/api/status":
                self.send_json(
                    200,
                    cloud_store.get_monitor_status(get_check_interval_seconds())
                )
                return
            if path == "/api/notifications/latest":
                self.send_json(
                    200,
                    {"latest_id": cloud_store.get_latest_notification_id()}
                )
                return

            query = parse_qs(urlsplit(self.path).query)
            try:
                after_id = int(query.get("after", ["0"])[0])
                if after_id < 0:
                    raise ValueError
            except ValueError:
                self.send_json_error(400, "The after value must be a non-negative integer.")
                return
            events = cloud_store.get_notifications(after_id)
            profile = cloud_store.get_user_preferences(user["id"])
            if profile and profile.get("profile_locked"):
                filtered_events = []
                for event in events:
                    matched_jobs = [
                        matched_job
                        for job in event["jobs"]
                        if (
                            matched_job := main.score_job_for_profile(job, profile)
                        ) is not None
                    ]
                    if matched_jobs:
                        filtered_events.append({
                            **event,
                            "jobs": matched_jobs,
                        })
                events = filtered_events
            else:
                events = []
            self.send_json(200, [
                {
                    **event,
                    "jobs": [
                        prepare_job_for_display(job)
                        for job in event["jobs"]
                    ],
                }
                for event in events
            ])
        except cloud_store.CloudServiceError as exc:
            self.send_json_error(exc.status, str(exc))

    def handle_cloud_post(self):
        path = urlsplit(self.path).path
        if path not in {
            "/api/job-status",
            "/api/push-subscription",
            "/api/import-jobs",
            "/api/preferences",
            "/api/preferences/unlock",
        }:
            self.send_error(404, "Not found")
            return

        user = self.authenticate_request()
        if user is None:
            return

        maximum_size = 1_048_576 if path == "/api/import-jobs" else 16_384
        try:
            payload = self.read_json_body(maximum_size)
            if path == "/api/preferences":
                cloud_store.save_user_preferences(user, payload)
                self.send_json(200, {"locked": True})
                return
            if path == "/api/preferences/unlock":
                cloud_store.unlock_user_preferences(user["id"])
                self.send_json(200, {"locked": False})
                return
            if path == "/api/job-status":
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                job_url = payload.get("url")
                status = payload.get("status")
                if (
                    not isinstance(job_url, str)
                    or not job_url.startswith(("https://", "http://"))
                ):
                    raise ValueError("A valid job URL is required.")
                if not isinstance(status, str) or status not in {"new", "saved", "applied"}:
                    raise ValueError("Status must be new, saved, or applied.")
                cloud_store.set_job_status(user["id"], job_url, status)
                self.send_json(200, {"url": job_url, "status": status})
                return

            if path == "/api/push-subscription":
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                if self.command == "DELETE":
                    cloud_store.delete_push_subscription(
                        user["id"],
                        payload.get("endpoint", "")
                    )
                    self.send_json(200, {"enabled": False})
                else:
                    cloud_store.save_push_subscription(user["id"], payload)
                    self.send_json(200, {"enabled": True})
                return

            imported_count = cloud_store.import_user_jobs(user["id"], payload)
            self.send_json(200, {"imported": imported_count})
        except json.JSONDecodeError:
            self.send_json_error(400, "Request body must contain valid JSON.")
        except ValueError as exc:
            self.send_json_error(400, str(exc))
        except cloud_store.CloudServiceError as exc:
            self.send_json_error(exc.status, str(exc))

    def authenticate_request(self):
        authorization = self.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            self.send_json_error(401, "Please sign in to continue.")
            return None
        try:
            return cloud_store.authenticate(token)
        except cloud_store.CloudServiceError as exc:
            self.send_json_error(exc.status, str(exc))
            return None

    def read_json_body(self, maximum_size):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("A valid Content-Length header is required.") from exc
        if content_length < 1 or content_length > maximum_size:
            raise ValueError("Request body is empty or too large.")
        return json.loads(self.rfile.read(content_length))

    def send_config(self):
        if not cloud_store.is_cloud_mode():
            self.send_json(200, {"cloud": False})
            return
        try:
            self.send_json(200, {"cloud": True, **cloud_store.get_cloud_config()})
        except cloud_store.CloudServiceError as exc:
            self.send_json_error(exc.status, str(exc))

    def send_index(self):
        try:
            body = (PROJECT_DIR / "index.html").read_bytes()
        except OSError as exc:
            self.send_json_error(500, f"Could not read index.html: {exc}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_static_file(self, filename, content_type):
        try:
            body = (PROJECT_DIR / filename).read_bytes()
        except OSError as exc:
            self.send_json_error(500, f"Could not read {filename}: {exc}")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_jobs(self):
        try:
            with JOBS_FILE_LOCK:
                with JOBS_FILE.open("r", encoding="utf-8") as file:
                    jobs = json.load(file)

            if not isinstance(jobs, list):
                raise ValueError("jobs.json must contain a JSON list.")
            for job in jobs:
                if isinstance(job, dict):
                    job["score"] = main.calculate_score(job)
                    job["match_category"] = main.get_match_category(job["score"])

            jobs = [
                job for job in jobs
                if isinstance(job, dict) and (
                    job.get("score", 0) >= 6
                    or job.get("status") in {"saved", "applied"}
                )
            ]
            jobs = [prepare_job_for_display(job) for job in jobs]

        except FileNotFoundError:
            self.send_json_error(404, "jobs.json not found. Run python main.py first.")
            return
        except (json.JSONDecodeError, ValueError) as exc:
            self.send_json_error(500, f"Could not read jobs.json: {exc}")
            return

        self.send_json(200, jobs)

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, status, message):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def run_web_ui():
    cloud_mode = cloud_store.is_cloud_mode()
    if cloud_mode:
        cloud_store.get_cloud_config()

    server = ThreadingHTTPServer((HOST, PORT), JobFinderRequestHandler)
    print(f"Remote Job Finder UI: http://{HOST}:{PORT}")
    if cloud_mode:
        print("Job collection is handled by the separate hosted background worker.")
    else:
        print(f"Checking job sources every {SCHEDULER.interval_seconds // 60} minutes while this server is running.")
        print("Press Ctrl+C to stop the web server.")

    if not cloud_mode:
        SCHEDULER.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the web server.")
    finally:
        server.server_close()
        if not cloud_mode:
            SCHEDULER.stop()


if __name__ == "__main__":
    run_web_ui()
