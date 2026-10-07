import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import main
import web_ui


class WebUiTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            web_ui.JobFinderRequestHandler
        )
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True
        )
        cls.server_thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    def request(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        headers = response.getheaders()
        connection.close()
        return response.status, headers, body

    def post_json(self, path, data):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        body = json.dumps(data)
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        response_body = response.read()
        connection.close()
        return response.status, json.loads(response_body)

    def test_jobs_endpoint_returns_saved_json_jobs(self):
        jobs = [
            {"title": "Junior React Developer", "score": 3},
            {
                "title": "Full Stack Engineer",
                "description": "React, JavaScript, HTML and CSS.",
                "score": 25
            },
            {
                "title": "Front End Engineer",
                "description": (
                    "&lt;p&gt;This is a senior engineering role.&lt;/p&gt;"
                    "&lt;p&gt;We have adopted a hybrid approach.&lt;/p&gt;"
                ),
                "score": 25
            }
        ]
        expected_jobs = [{
            "title": "Junior React Developer",
            "score": 18,
            "match_category": "Excellent Match",
            "description_text": "",
            "description_preview": "",
            "skills": ["React"]
        }]

        with tempfile.TemporaryDirectory() as directory:
            jobs_file = Path(directory) / "jobs.json"
            jobs_file.write_text(json.dumps(jobs), encoding="utf-8")

            with patch.object(web_ui, "JOBS_FILE", jobs_file):
                status, headers, body = self.request("/api/jobs")

        self.assertEqual(status, 200)
        self.assertIn(
            ("Content-Type", "application/json; charset=utf-8"),
            headers
        )
        self.assertEqual(json.loads(body), expected_jobs)

    def test_description_html_is_stripped_and_skills_are_detected(self):
        job = {
            "title": "Frontend Developer",
            "description": (
                "<p>Build with React and TypeScript.</p>"
                "<script>stealCredentials()</script>"
                "<li>Use HTML5, CSS3 and GitHub.</li>"
            )
        }

        result = web_ui.prepare_job_for_display(job)

        self.assertEqual(
            result["description_text"],
            "Build with React and TypeScript. Use HTML5, CSS3 and GitHub."
        )
        self.assertEqual(
            result["skills"],
            ["TypeScript", "React", "HTML", "CSS", "GitHub"]
        )
        self.assertNotIn("stealCredentials", result["description_text"])

    def test_missing_jobs_file_returns_clear_api_error(self):
        with tempfile.TemporaryDirectory() as directory:
            missing_file = Path(directory) / "missing.json"

            with patch.object(web_ui, "JOBS_FILE", missing_file):
                status, _, body = self.request("/api/jobs")

        self.assertEqual(status, 404)
        self.assertIn("jobs.json not found", json.loads(body)["error"])

    def test_home_page_is_served(self):
        status, headers, body = self.request("/")

        self.assertEqual(status, 200)
        self.assertIn(
            ("Content-Type", "text/html; charset=utf-8"),
            headers
        )
        self.assertIn(b"Remote Job Finder", body)

    def test_server_does_not_expose_other_project_files(self):
        status, _, _ = self.request("/main.py")

        self.assertEqual(status, 404)

    def test_saved_job_moves_to_applied_and_persists(self):
        url = "https://example.com/frontend-job"
        jobs = [{"title": "Frontend Developer", "url": url}]

        with tempfile.TemporaryDirectory() as directory:
            jobs_file = Path(directory) / "jobs.json"
            jobs_file.write_text(json.dumps(jobs), encoding="utf-8")

            with patch.object(web_ui, "JOBS_FILE", jobs_file):
                saved_status, saved_body = self.post_json(
                    "/api/job-status",
                    {"url": url, "status": "saved"}
                )
                applied_status, applied_body = self.post_json(
                    "/api/job-status",
                    {"url": url, "status": "applied"}
                )
                get_status, _, get_body = self.request("/api/jobs")
                persisted_jobs = json.loads(jobs_file.read_text(encoding="utf-8"))

        self.assertEqual(saved_status, 200)
        self.assertEqual(saved_body["status"], "saved")
        self.assertEqual(applied_status, 200)
        self.assertEqual(applied_body["status"], "applied")
        self.assertEqual(get_status, 200)
        self.assertEqual(json.loads(get_body)[0]["status"], "applied")
        self.assertEqual(persisted_jobs[0]["status"], "applied")

    def test_status_update_rejects_invalid_status(self):
        status, body = self.post_json(
            "/api/job-status",
            {"url": "https://example.com/job", "status": "ignored"}
        )

        self.assertEqual(status, 400)
        self.assertIn("Status must be", body["error"])

    def test_notifications_endpoint_returns_events_after_cursor(self):
        scheduler = web_ui.JobScheduler(3600)
        job = {
            "title": "Junior React Developer",
            "score": 20,
            "match_category": "Excellent Match"
        }
        with patch.object(web_ui, "SCHEDULER", scheduler):
            with scheduler.lock:
                scheduler.events = [
                    {"id": 10, "created_at": 1, "jobs": [job]},
                    {"id": 20, "created_at": 2, "jobs": [job]}
                ]
            status, _, body = self.request("/api/notifications?after=10")

        self.assertEqual(status, 200)
        self.assertEqual([event["id"] for event in json.loads(body)], [20])

    def test_scheduler_adds_new_jobs_to_notification_queue(self):
        scheduler = web_ui.JobScheduler(3600)
        job = {
            "title": "Junior React Developer",
            "score": 20,
            "match_category": "Excellent Match",
            "url": "https://example.com/job"
        }

        with patch.object(main, "run_job_finder", return_value=[job]) as run:
            returned_jobs = scheduler.run_check()

        run.assert_called_once_with(show_notification=False)
        self.assertEqual(returned_jobs, [job])
        events = scheduler.get_notifications(after_id=0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["jobs"][0]["title"], job["title"])
        self.assertTrue(scheduler.get_status()["last_check"])
        self.assertFalse(scheduler.get_status()["checking"])

    def test_scheduler_records_errors_and_can_retry(self):
        scheduler = web_ui.JobScheduler(3600)
        with patch.object(
            main,
            "run_job_finder",
            side_effect=[OSError("temporary file problem"), []]
        ):
            self.assertEqual(scheduler.run_check(), [])
            self.assertIn("temporary file problem", scheduler.get_status()["last_error"])
            self.assertEqual(scheduler.run_check(), [])

        self.assertIsNone(scheduler.get_status()["last_error"])
        self.assertFalse(scheduler.get_status()["checking"])


if __name__ == "__main__":
    unittest.main()
