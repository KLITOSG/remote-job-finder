import os
import base64
import unittest
from unittest.mock import patch

import cloud_store
from generate_vapid_keys import generate_vapid_keys
from py_vapid import Vapid
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class CloudStoreTests(unittest.TestCase):

    def test_config_never_exposes_the_service_role_key(self):
        environment = {
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_ANON_KEY": "public-key",
            "SUPABASE_SERVICE_ROLE_KEY": "server-secret",
            "VAPID_PUBLIC_KEY": "public-vapid-key",
        }
        with patch.dict(os.environ, environment, clear=True):
            config = cloud_store.get_cloud_config()

        self.assertEqual(config["supabase_anon_key"], "public-key")
        self.assertNotIn("service_role", str(config))
        self.assertNotIn("server-secret", str(config))

    def test_global_jobs_only_receive_the_signed_in_users_statuses(self):
        rows = [
            {"url": "https://example.com/new", "score": 20},
            {"url": "https://example.com/saved", "score": 2},
            {"url": "https://example.com/other-user", "score": 3},
        ]
        statuses = [
            {"job_url": "https://example.com/saved", "status": "saved"},
        ]
        with patch.object(
            cloud_store,
            "_service_request",
            side_effect=[rows, statuses],
        ) as request:
            jobs = cloud_store.get_jobs_for_user("user-123")

        self.assertEqual(
            [(job["url"], job.get("status")) for job in jobs],
            [
                ("https://example.com/new", None),
                ("https://example.com/saved", "saved"),
                ("https://example.com/other-user", None),
            ],
        )
        self.assertEqual(request.call_args_list[1].kwargs["params"]["user_id"], "eq.user-123")

    def test_import_only_preserves_saved_and_applied_statuses(self):
        jobs = [
            {
                "url": "https://example.com/saved",
                "title": "Saved frontend role",
                "status": "saved",
            },
            {
                "url": "https://example.com/applied",
                "title": "Applied frontend role",
                "status": "applied",
            },
            {
                "url": "https://example.com/new",
                "title": "Untracked role",
                "status": "new",
            },
        ]
        with (
            patch.object(cloud_store, "record_new_jobs") as insert_jobs,
            patch.object(cloud_store, "_service_request") as request,
        ):
            imported = cloud_store.import_user_jobs("user-123", jobs)

        self.assertEqual(imported, 2)
        inserted_rows = insert_jobs.call_args.args[0]
        self.assertEqual(
            {job["url"] for job in inserted_rows},
            {"https://example.com/saved", "https://example.com/applied"},
        )
        self.assertFalse(insert_jobs.call_args.kwargs["create_events"])
        status_rows = request.call_args.kwargs["data"]
        self.assertEqual({row["user_id"] for row in status_rows}, {"user-123"})
        self.assertEqual({row["status"] for row in status_rows}, {"saved", "applied"})

    def test_import_rejects_more_than_two_hundred_jobs(self):
        with self.assertRaisesRegex(ValueError, "no more than 200"):
            cloud_store.import_user_jobs("user-123", [{}] * 201)

    def test_preferences_are_validated_and_saved_locked_to_google_user(self):
        user = {"id": "user-123", "email": "person@example.com"}
        preferences = {
            "role_families": ["digital_marketing", "graphic_design"],
            "experience_levels": ["entry", "mid"],
            "work_arrangements": ["remote", "hybrid"],
            "preferred_locations": ["gr", "it", "es", "pt"],
            "email_notifications": True,
        }
        with (
            patch.object(cloud_store, "get_user_preferences", return_value=None),
            patch.object(cloud_store, "_service_request") as request,
        ):
            cloud_store.save_user_preferences(user, preferences)

        row = request.call_args.kwargs["data"][0]
        self.assertEqual(row["user_id"], "user-123")
        self.assertEqual(row["notification_email"], "person@example.com")
        self.assertTrue(row["email_notifications"])
        self.assertTrue(row["profile_locked"])
        self.assertEqual(set(row["role_families"]), {"digital_marketing", "graphic_design"})
        self.assertEqual(set(row["preferred_locations"]), {"gr", "it", "es", "pt"})

    def test_locked_preferences_cannot_be_changed_without_unlocking(self):
        with (
            patch.object(
                cloud_store,
                "get_user_preferences",
                return_value={"profile_locked": True},
            ),
            patch.object(cloud_store, "_service_request") as request,
            self.assertRaisesRegex(ValueError, "Unlock your saved search"),
        ):
            cloud_store.save_user_preferences(
                {"id": "user-123", "email": "person@example.com"},
                {},
            )

        request.assert_not_called()

    def test_invalid_empty_or_unknown_preference_values_are_rejected(self):
        invalid_profiles = [
            {
                "role_families": [],
                "experience_levels": ["entry"],
                "work_arrangements": ["remote"],
                "email_notifications": False,
            },
            {
                "role_families": ["unknown"],
                "experience_levels": ["entry"],
                "work_arrangements": ["remote"],
                "email_notifications": False,
            },
            {
                "role_families": ["graphic_design"],
                "experience_levels": [],
                "work_arrangements": ["remote"],
                "email_notifications": False,
            },
            {
                "role_families": ["graphic_design"],
                "experience_levels": ["entry"],
                "work_arrangements": ["remote"],
                "preferred_locations": ["not-an-eu-country"],
                "email_notifications": False,
            },
        ]
        with patch.object(cloud_store, "get_user_preferences", return_value=None):
            for profile in invalid_profiles:
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    cloud_store.save_user_preferences(
                        {"id": "user-123", "email": "person@example.com"},
                        profile,
                    )

    def test_email_alerts_require_the_signing_in_users_email(self):
        preferences = {
            "role_families": ["digital_marketing"],
            "experience_levels": ["mid"],
            "work_arrangements": ["remote"],
            "preferred_locations": ["gr", "it", "es", "pt"],
            "email_notifications": True,
        }
        with (
            patch.object(cloud_store, "get_user_preferences", return_value=None),
            patch.object(cloud_store, "_service_request") as request,
            self.assertRaisesRegex(ValueError, "valid email address"),
        ):
            cloud_store.save_user_preferences({"id": "user-123"}, preferences)
        request.assert_not_called()

    def test_matching_jobs_are_queued_and_pending_notifications_can_be_cancelled(self):
        jobs = [{
            "url": "https://example.com/job",
            "title": "Remote Designer",
        }]
        with patch.object(cloud_store, "_service_request") as request:
            cloud_store.queue_email_notifications("user-123", "user@example.com", jobs)
            cloud_store.cancel_pending_email_notifications("user-123")

        queued = request.call_args_list[0].kwargs["data"][0]
        self.assertEqual(queued["user_id"], "user-123")
        self.assertEqual(queued["notification_email"], "user@example.com")
        self.assertEqual(request.call_args_list[1].kwargs["params"]["status"], "eq.pending")

    def test_notification_baseline_uses_latest_persisted_event(self):
        with patch.object(
            cloud_store,
            "_service_request",
            return_value=[{"id": 123456}],
        ) as request:
            latest_id = cloud_store.get_latest_notification_id()

        self.assertEqual(latest_id, "123456")
        self.assertEqual(request.call_args.kwargs["params"]["order"], "id.desc")

    def test_notifications_group_jobs_from_one_collection_check(self):
        events = [
            {
                "id": 11,
                "job_url": "https://example.com/a",
                "created_at": "t1",
                "job": {"url": "https://example.com/a", "title": "Frontend A"},
            },
            {
                "id": 12,
                "job_url": "https://example.com/b",
                "created_at": "t2",
                "job": {"url": "https://example.com/b", "title": "Frontend B"},
            },
        ]
        with patch.object(
            cloud_store,
            "_service_request",
            return_value=events,
        ) as request:
            notifications = cloud_store.get_notifications(10)

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["id"], "12")
        self.assertEqual(
            [job["title"] for job in notifications[0]["jobs"]],
            ["Frontend A", "Frontend B"],
        )
        self.assertIn("job:jobs", request.call_args.kwargs["params"]["select"])

    def test_push_subscription_requires_https_endpoint_and_encryption_keys(self):
        with self.assertRaisesRegex(ValueError, "supported browser push subscription"):
            cloud_store.save_push_subscription(
                "user-123",
                {"endpoint": "http://example.com", "keys": {}},
            )

    def test_push_subscription_rejects_untrusted_notification_endpoints(self):
        subscription = {
            "endpoint": "https://attacker.example/collect",
            "keys": {"p256dh": "public", "auth": "secret"},
        }
        with self.assertRaisesRegex(ValueError, "supported browser push subscription"):
            cloud_store.save_push_subscription("user-123", subscription)

    def test_browser_push_subscription_is_saved_for_its_user(self):
        subscription = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/example",
            "keys": {"p256dh": "public", "auth": "secret"},
        }
        with patch.object(cloud_store, "_service_request") as request:
            cloud_store.save_push_subscription("user-123", subscription)

        self.assertEqual(request.call_args.kwargs["data"][0]["user_id"], "user-123")

    def test_generated_vapid_public_and_private_keys_are_a_matching_pair(self):
        private_key, public_key = generate_vapid_keys()
        decoded_public_key = Vapid.from_string(private_key).public_key.public_bytes(
            encoding=Encoding.X962,
            format=PublicFormat.UncompressedPoint,
        )
        expected_public_key = base64.urlsafe_b64encode(decoded_public_key).rstrip(b"=").decode()

        self.assertEqual(public_key, expected_public_key)


if __name__ == "__main__":
    unittest.main()
