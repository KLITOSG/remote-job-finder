import os
import unittest
from unittest.mock import Mock, patch

import email_notifications


class EmailNotificationTests(unittest.TestCase):

    def setUp(self):
        self.jobs = [{
            "title": "Graphic Designer",
            "company": "Example & Co",
            "location": "Hybrid",
            "experience_level": "mid",
            "work_arrangement": "hybrid",
            "score": 15,
            "url": "https://example.com/jobs/graphic-designer",
        }]

    def test_email_content_includes_match_details_and_escapes_untrusted_text(self):
        text, body = email_notifications.build_email_content(self.jobs)

        self.assertIn("Graphic Designer", text)
        self.assertIn("Level: Mid", text)
        self.assertIn("Hybrid", text)
        self.assertIn("https://example.com/jobs/graphic-designer", text)
        self.assertIn("Example &amp; Co", body)
        self.assertIn('href="https://example.com/jobs/graphic-designer"', body)

    def test_resend_uses_configured_sender_and_recipient_and_idempotency_key(self):
        response = Mock(ok=True, content=b'{"id":"email-123"}')
        response.json.return_value = {"id": "email-123"}
        with (
            patch.dict(
                os.environ,
                {"RESEND_API_KEY": "test-secret", "EMAIL_FROM": "jobs@example.com"},
                clear=True,
            ),
            patch.object(email_notifications.requests, "post", return_value=response) as post,
        ):
            result = email_notifications.send_job_alert(
                "user@example.com",
                self.jobs,
                idempotency_key="batch-hash",
            )

        self.assertEqual(result["id"], "email-123")
        self.assertEqual(post.call_args.args[0], email_notifications.RESEND_API_URL)
        self.assertEqual(post.call_args.kwargs["json"]["to"], ["user@example.com"])
        self.assertTrue(
            post.call_args.kwargs["headers"]["Authorization"].startswith("Bearer ")
        )
        self.assertEqual(post.call_args.kwargs["headers"]["Idempotency-Key"], "batch-hash")
        self.assertNotIn("test-secret", str(post.call_args.kwargs["json"]))

    def test_missing_resend_configuration_fails_explicitly(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaisesRegex(email_notifications.EmailDeliveryError, "RESEND_API_KEY"),
        ):
            email_notifications.send_job_alert("user@example.com", self.jobs)

    def test_resend_rejection_fails_explicitly_without_echoing_credentials(self):
        response = Mock(ok=False, status_code=403, content=b'{"message":"sender denied"}')
        response.json.return_value = {"message": "sender denied"}
        with (
            patch.dict(
                os.environ,
                {"RESEND_API_KEY": "test-secret", "EMAIL_FROM": "jobs@example.com"},
                clear=True,
            ),
            patch.object(email_notifications.requests, "post", return_value=response),
            self.assertRaisesRegex(email_notifications.EmailDeliveryError, "HTTP 403"),
        ):
            email_notifications.send_job_alert("user@example.com", self.jobs)

    def test_support_report_is_sent_to_configured_owner_with_escaped_details(self):
        response = Mock(ok=True, content=b'{"id":"support-456"}')
        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": "test-secret",
                    "EMAIL_FROM": "jobs@example.com",
                    "SUPPORT_EMAIL": "remotejobfinderco@gmail.com",
                },
                clear=True,
            ),
            patch.object(email_notifications.requests, "post", return_value=response) as post,
        ):
            result = email_notifications.send_support_report(
                "other",
                '<script>alert("bad")</script>\nThe page broke.',
                "person@example.com",
            )

        payload = post.call_args.kwargs["json"]
        self.assertTrue(result)
        self.assertEqual(payload["to"], ["remotejobfinderco@gmail.com"])
        self.assertEqual(payload["reply_to"], "person@example.com")
        self.assertIn("Other", payload["subject"])
        self.assertIn("&lt;script&gt;", payload["html"])
        self.assertNotIn("<script>", payload["html"])
        self.assertIn("The page broke.", payload["text"])

    def test_support_report_rejects_invalid_category_details_and_contact_email(self):
        with (
            patch.dict(
                os.environ,
                {
                    "RESEND_API_KEY": "test-secret",
                    "EMAIL_FROM": "jobs@example.com",
                },
                clear=True,
            ),
            patch.object(email_notifications.requests, "post") as post,
        ):
            with self.assertRaisesRegex(ValueError, "listed problem types"):
                email_notifications.send_support_report("invalid", "It failed.")
            with self.assertRaisesRegex(ValueError, "2,000 characters"):
                email_notifications.send_support_report("other", " ")
            with self.assertRaisesRegex(ValueError, "valid email"):
                email_notifications.send_support_report(
                    "other",
                    "It failed.",
                    "not-an-email",
                )

        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()