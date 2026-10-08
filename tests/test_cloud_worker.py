import unittest
from unittest.mock import patch

import cloud_worker


class CloudWorkerTests(unittest.TestCase):

    def setUp(self):
        self.job = {
            "url": "https://example.com/role",
            "title": "Junior React Developer",
            "company": "Example Co",
            "location": "Remote",
            "description": "React",
            "source": "Test",
            "score": 18,
            "match_category": "Excellent Match",
        }

    def test_first_check_seeds_jobs_without_old_job_notifications(self):
        with (
            patch.object(cloud_worker, "get_interval_seconds", return_value=3600),
            patch.object(
                cloud_worker.cloud_store,
                "get_monitor_status",
                return_value={"last_check": None},
            ),
            patch.object(cloud_worker.cloud_store, "get_all_jobs", return_value=[]),
            patch.object(
                cloud_worker.main,
                "collect_job_listings",
                return_value=[self.job],
            ),
            patch.object(cloud_worker.cloud_store, "update_monitor_status"),
            patch.object(cloud_worker.cloud_store, "get_user_profiles", return_value=[]),
            patch.object(
                cloud_worker.cloud_store,
                "record_new_jobs",
                return_value=[self.job],
            ) as insert_jobs,
            patch.object(cloud_worker, "send_pending_email_notifications"),
            patch.object(cloud_worker, "send_push_notifications") as send_push,
        ):
            cloud_worker.run_check()

        self.assertEqual(insert_jobs.call_args.args[0][0]["role_families"], ["frontend_web"])
        self.assertFalse(insert_jobs.call_args.kwargs["create_events"])
        send_push.assert_not_called()

    def test_later_checks_persist_events_and_send_only_inserted_jobs(self):
        with (
            patch.object(cloud_worker, "get_interval_seconds", return_value=3600),
            patch.object(
                cloud_worker.cloud_store,
                "get_monitor_status",
                return_value={"last_check": 100},
            ),
            patch.object(cloud_worker.cloud_store, "get_all_jobs", return_value=[]),
            patch.object(
                cloud_worker.main,
                "collect_job_listings",
                return_value=[self.job],
            ),
            patch.object(cloud_worker.cloud_store, "update_monitor_status"),
            patch.object(
                cloud_worker.cloud_store,
                "get_user_profiles",
                return_value=[{
                    "user_id": "user-123",
                    "role_families": ["frontend_web"],
                    "experience_levels": ["entry"],
                    "work_arrangements": ["remote"],
                    "email_notifications": False,
                }],
            ),
            patch.object(cloud_worker.cloud_store, "queue_email_notifications") as queue_email,
            patch.object(
                cloud_worker.cloud_store,
                "record_new_jobs",
                return_value=[self.job],
            ) as insert_jobs,
            patch.object(cloud_worker, "send_pending_email_notifications"),
            patch.object(cloud_worker, "send_push_notifications") as send_push,
        ):
            cloud_worker.run_check()

        self.assertTrue(insert_jobs.call_args.kwargs["create_events"])
        self.assertFalse(queue_email.called)
        send_push.assert_called_once()

    def test_collection_failure_is_recorded_and_does_not_crash_the_worker(self):
        with (
            patch.object(cloud_worker, "get_interval_seconds", return_value=3600),
            patch.object(
                cloud_worker.cloud_store,
                "get_monitor_status",
                return_value={"last_check": 100},
            ),
            patch.object(cloud_worker.cloud_store, "get_all_jobs", return_value=[]),
            patch.object(
                cloud_worker.main,
                "collect_job_listings",
                side_effect=OSError("source unavailable"),
            ),
            patch.object(
                cloud_worker.cloud_store,
                "update_monitor_status",
            ) as update_status,
            patch.object(cloud_worker, "send_pending_email_notifications"),
        ):
            cloud_worker.run_check()

        final_status = update_status.call_args.kwargs
        self.assertIn("source unavailable", final_status["last_error"])
        self.assertFalse(final_status["checking"])

    def test_new_matching_jobs_are_queued_for_email_enabled_users(self):
        profile = {
            "user_id": "user-123",
            "notification_email": "person@example.com",
            "role_families": ["graphic_design"],
            "experience_levels": ["mid"],
            "work_arrangements": ["hybrid"],
            "email_notifications": True,
        }
        job = {
            "title": "Mid-level Graphic Designer",
            "url": "https://example.com/graphic",
            "description": "Hybrid schedule.",
        }
        with patch.object(
            cloud_worker.cloud_store,
            "queue_email_notifications",
        ) as queue_email:
            cloud_worker.queue_matching_email_notifications([job], [profile])

        queue_email.assert_called_once()
        args = queue_email.call_args.args
        self.assertEqual(args[0], "user-123")
        self.assertEqual(args[1], "person@example.com")
        self.assertEqual(args[2][0]["experience_level"], "mid")
        self.assertEqual(args[2][0]["work_arrangement"], "hybrid")

    def test_pending_email_failures_are_kept_for_retry(self):
        batch = {
            "recipient": "person@example.com",
            "ids": [1, 2],
            "jobs": [self.job],
        }
        with (
            patch.object(
                cloud_worker.cloud_store,
                "get_pending_email_batches",
                return_value={"user-123": batch},
            ),
            patch.object(
                cloud_worker.email_notifications,
                "send_job_alert",
                side_effect=cloud_worker.email_notifications.EmailDeliveryError(
                    "provider unavailable"
                ),
            ),
            patch.object(
                cloud_worker.cloud_store,
                "record_email_notification_error",
            ) as record_error,
            patch.object(cloud_worker.cloud_store, "mark_email_notifications_sent") as mark_sent,
        ):
            cloud_worker.send_pending_email_notifications()

        record_error.assert_called_once()
        self.assertEqual(record_error.call_args.args[0], [1, 2])
        self.assertIn("provider unavailable", record_error.call_args.args[1])
        mark_sent.assert_not_called()

if __name__ == "__main__":
    unittest.main()
