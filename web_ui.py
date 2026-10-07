import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import main
import requests


PROJECT_DIR = Path(__file__).resolve().parent
JOBS_FILE = PROJECT_DIR / "jobs.json"
HOST = "127.0.0.1"
PORT = 8000
JOBS_FILE_LOCK = threading.Lock()
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
        except (requests.RequestException, OSError, ValueError) as exc:
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
    server = ThreadingHTTPServer((HOST, PORT), JobFinderRequestHandler)
    print(f"Remote Job Finder UI: http://{HOST}:{PORT}")
    print(f"Checking job sources every {SCHEDULER.interval_seconds // 60} minutes while this server is running.")
    print("Press Ctrl+C to stop the web server.")

    SCHEDULER.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping the web server.")
    finally:
        server.server_close()
        SCHEDULER.stop()


if __name__ == "__main__":
    run_web_ui()
