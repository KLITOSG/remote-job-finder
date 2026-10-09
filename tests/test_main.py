import unittest
from unittest.mock import patch

import main


def make_job(title, url="https://example.com/job", description=""):
    return {
        "title": title,
        "company": "Example Company",
        "location": "Remote",
        "description": description,
        "url": url,
        "source": "Test"
    }


class JobScoringTests(unittest.TestCase):

    def test_target_title_scores_higher_than_description_only_mention(self):
        junior_react_job = make_job(
            "Junior React Developer",
            description="Build user interfaces."
        )
        marketing_job = make_job(
            "Marketing Manager",
            description="Our team uses React."
        )

        self.assertGreater(
            main.calculate_score(junior_react_job),
            main.calculate_score(marketing_job)
        )

    def test_senior_and_unrelated_roles_are_rejected(self):
        self.assertFalse(
            main.is_relevant_frontend_job(make_job("Senior React Developer"))
        )
        self.assertFalse(
            main.is_relevant_frontend_job(make_job("Marketing Manager"))
        )

    def test_full_stack_and_generic_junior_titles_are_not_frontend_matches(self):
        full_stack_job = make_job(
            "Full Stack Engineer (m/f/d)",
            description="Build a React frontend and JavaScript backend."
        )
        junior_software_job = make_job(
            "Junior Software Developer",
            description="Our team uses React, HTML, CSS and JavaScript."
        )

        self.assertFalse(main.is_relevant_frontend_job(full_stack_job))
        self.assertFalse(main.is_relevant_frontend_job(junior_software_job))
        self.assertLess(main.calculate_score(full_stack_job), 18)
        self.assertLess(main.calculate_score(junior_software_job), 18)

    def test_explicit_frontend_job_title_can_score_excellent(self):
        job = make_job(
            "Junior React Developer",
            description="Use TypeScript, HTML, CSS, Git and REST API."
        )

        self.assertTrue(main.is_relevant_frontend_job(job))
        self.assertGreaterEqual(main.calculate_score(job), 18)

    def test_senior_hybrid_frontend_job_is_rejected_from_description(self):
        job = make_job(
            "Front End Engineer",
            description=(
                "&lt;p&gt;You’ll work mainly in TypeScript and React.&lt;/p&gt;"
                "&lt;p&gt;This is a senior engineering role.&lt;/p&gt;"
                "&lt;p&gt;Teams are in the office around four days a week.&lt;/p&gt;"
                "&lt;p&gt;We have adopted a hybrid approach.&lt;/p&gt;"
            )
        )

        self.assertEqual(
            main.get_description_text(job["description"]),
            "You’ll work mainly in TypeScript and React. "
            "This is a senior engineering role. "
            "Teams are in the office around four days a week. "
            "We have adopted a hybrid approach."
        )
        self.assertTrue(main.is_senior_job(job))
        self.assertFalse(main.is_remote_work_arrangement(job))
        self.assertFalse(main.is_relevant_frontend_job(job))
        self.assertEqual(main.calculate_score(job), 0)

    def test_match_categories_follow_score_ranges(self):
        self.assertEqual(main.get_match_category(18), "Excellent Match")
        self.assertEqual(main.get_match_category(14), "Strong Match")
        self.assertEqual(main.get_match_category(10), "Good Match")
        self.assertEqual(main.get_match_category(6), "Weak Match")
        self.assertEqual(main.get_match_category(5), "Poor Match")

    def test_classifies_requested_job_families(self):
        jobs = {
            "frontend_web": make_job("Frontend Developer"),
            "software_it": make_job("Senior Software Engineer"),
            "digital_marketing": make_job("Digital Marketing Specialist"),
            "social_media": make_job("Social Media Manager"),
            "graphic_design": make_job("Graphic Designer"),
            "writing_content": make_job("Technical Writer"),
            "customer_support": make_job("Customer Success Specialist"),
            "sales_business": make_job("Business Development Representative"),
            "product_project": make_job("Product Manager"),
            "data_analytics": make_job("Data Analyst"),
            "hr_recruiting": make_job("Talent Acquisition Specialist"),
            "operations_admin": make_job("Operations Coordinator"),
            "finance_accounting": make_job("Accountant"),
            "education_training": make_job("Instructional Designer"),
        }

        for family, job in jobs.items():
            with self.subTest(family=family):
                self.assertIn(family, main.classify_role_families(job))

    def test_social_media_manager_is_not_automatically_classified_as_senior(self):
        self.assertEqual(
            main.classify_experience_level(make_job("Social Media Manager")),
            "unspecified"
        )

    def test_experience_level_uses_explicit_title_description_and_years(self):
        self.assertEqual(
            main.classify_experience_level(make_job("Senior Graphic Designer")),
            "senior"
        )
        self.assertEqual(
            main.classify_experience_level(make_job(
                "Graphic Designer",
                description="This is a senior design role."
            )),
            "senior"
        )
        self.assertEqual(
            main.classify_experience_level(make_job(
                "Digital Marketing Specialist",
                description="Requires 1-2 years of experience."
            )),
            "entry"
        )
        self.assertEqual(
            main.classify_experience_level(make_job(
                "Digital Marketing Specialist",
                description="Requires 3-5 years of experience."
            )),
            "mid"
        )

    def test_profile_matching_honors_role_level_and_work_arrangement(self):
        preferences = {
            "role_families": ["digital_marketing"],
            "experience_levels": ["entry"],
            "work_arrangements": ["remote"],
            "preferred_locations": ["gr", "it", "es", "pt", "fr"],
        }
        remote_entry_marketing_job = make_job(
            "Entry-Level Digital Marketing Specialist",
            description="We work fully remote. Requires 1-2 years of experience."
        )
        senior_marketing_job = make_job(
            "Senior Digital Marketing Specialist",
            url="https://example.com/senior",
            description="Remote role."
        )
        hybrid_design_job = make_job(
            "Graphic Designer",
            url="https://example.com/design",
            description="Hybrid role."
        )
        unclear_marketing_job = make_job(
            "Digital Marketing Coordinator",
            url="https://example.com/unclear"
        )

        matched = main.score_job_for_profile(remote_entry_marketing_job, preferences)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["experience_level"], "entry")
        self.assertEqual(matched["work_arrangement"], "remote")
        self.assertIsNone(main.score_job_for_profile(senior_marketing_job, preferences))
        self.assertIsNone(main.score_job_for_profile(hybrid_design_job, preferences))
        self.assertIsNotNone(main.score_job_for_profile(unclear_marketing_job, preferences))

    def test_location_preferences_match_selected_eu_countries_and_europe_wide_roles(self):
        preferences = {
            "role_families": ["digital_marketing"],
            "experience_levels": ["entry"],
            "work_arrangements": ["remote"],
            "preferred_locations": ["gr", "it", "es", "pt"],
        }
        greek_job = make_job(
            "Entry-Level Digital Marketing Specialist",
            description="Remote work. Requires 1-2 years of experience.",
        )
        greek_job["location"] = "Athens, Greece"
        italian_job = {**greek_job, "location": "Milan, Italy"}
        european_job = {**greek_job, "location": "Remote - Europe"}
        french_job = {**greek_job, "location": "Paris, France"}
        us_job = {**greek_job, "location": "Remote - United States"}
        unspecified_job = {**greek_job, "location": "Remote"}

        self.assertIsNotNone(main.score_job_for_profile(greek_job, preferences))
        self.assertIsNotNone(main.score_job_for_profile(italian_job, preferences))
        self.assertIsNotNone(main.score_job_for_profile(european_job, preferences))
        self.assertIsNone(main.score_job_for_profile(french_job, preferences))
        self.assertIsNone(main.score_job_for_profile(us_job, preferences))
        self.assertIsNotNone(main.score_job_for_profile(unspecified_job, preferences))

    def test_jobicy_fetches_eu_geo_filters_and_deduplicates_listing_urls(self):
        response = {
            "jobs": [{
                "jobTitle": "Remote Marketing Specialist",
                "companyName": "Example Co",
                "jobGeo": "Europe",
                "jobDescription": "SEO and campaigns.",
                "url": "https://jobicy.com/jobs/123-marketing",
            }]
        }
        with patch.object(main, "get_json_api_response", return_value=response) as request:
            jobs = main.get_jobicy_jobs()

        self.assertEqual(
            jobs,
            [{
                "title": "Remote Marketing Specialist",
                "company": "Example Co",
                "location": "Europe",
                "description": "SEO and campaigns.",
                "url": "https://jobicy.com/jobs/123-marketing",
                "work_arrangement": "remote",
                "source": "Jobicy",
            }],
        )
        self.assertEqual(
            [call.kwargs["params"] for call in request.call_args_list],
            [
                {"count": 200, "geo": geo}
                for geo in main.JOBICY_GEO_FILTERS
            ],
        )
        self.assertEqual(request.call_count, len(main.JOBICY_GEO_FILTERS))

    def test_jobicy_keeps_successful_geo_results_when_a_filter_fails(self):
        response = {"jobs": [{
            "jobTitle": "Remote Marketing Specialist",
            "url": "https://jobicy.com/jobs/123-marketing",
        }]}
        with patch.object(
            main,
            "get_json_api_response",
            side_effect=[response, main.requests.Timeout("offline"), response, response, response],
        ):
            jobs = main.get_jobicy_jobs()

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["url"], response["jobs"][0]["url"])

    def test_remote_ok_api_jobs_are_normalized_and_keep_source_link(self):
        response = [{
            "id": "123",
            "position": "Graphic Designer",
            "company": "Example Co",
            "location": "Worldwide",
            "description": "Remote design work.",
            "url": "https://remoteok.com/remote-jobs/123-graphic-designer",
        }]
        with patch.object(main, "get_json_api_response", return_value=response) as request:
            jobs = main.get_remoteok_jobs()

        self.assertEqual(jobs[0]["title"], "Graphic Designer")
        self.assertEqual(jobs[0]["url"], response[0]["url"])
        self.assertEqual(jobs[0]["source"], "Remote OK")
        self.assertEqual(jobs[0]["work_arrangement"], "remote")
        self.assertEqual(request.call_args.args[0], main.REMOTEOK_API_URL)
        self.assertIn("User-Agent", request.call_args.kwargs["headers"])

    def test_job_sources_continue_after_one_source_fails(self):
        jobicy_job = make_job("Graphic Designer")
        jobicy_job["source"] = "Jobicy"
        source_jobs = [jobicy_job]
        with (
            patch.object(
                main,
                "get_remotive_jobs",
                side_effect=main.requests.RequestException("offline"),
            ),
            patch.object(main, "get_arbeitnow_jobs", return_value=[]),
            patch.object(main, "get_jobicy_jobs", return_value=source_jobs),
            patch.object(main, "get_remoteok_jobs", return_value=[]),
        ):
            jobs = main.collect_jobs_from_sources()

        self.assertEqual(jobs, source_jobs)

    def test_job_sources_raise_clear_error_when_all_sources_fail(self):
        with (
            patch.object(main, "get_remotive_jobs", side_effect=OSError("offline")),
            patch.object(main, "get_arbeitnow_jobs", side_effect=OSError("offline")),
            patch.object(main, "get_jobicy_jobs", side_effect=OSError("offline")),
            patch.object(main, "get_remoteok_jobs", side_effect=OSError("offline")),
            self.assertRaisesRegex(main.JobSourceError, "All job sources failed"),
        ):
            main.collect_jobs_from_sources()


class JobProcessingTests(unittest.TestCase):

    def test_senior_hybrid_frontend_listing_is_not_added(self):
        job = make_job(
            "Front End Engineer",
            description=(
                "&lt;p&gt;This is a senior engineering role.&lt;/p&gt;"
                "&lt;p&gt;We have adopted a hybrid approach.&lt;/p&gt;"
            )
        )

        matched_jobs, frontend_matches, saveable_jobs = main.process_jobs(
            [job],
            []
        )

        self.assertEqual(frontend_matches, 0)
        self.assertEqual(matched_jobs, [])
        self.assertEqual(saveable_jobs, [])

    def test_existing_and_repeated_urls_are_only_saved_once(self):
        saved_job = make_job("Junior Web Developer", url="https://example.com/existing")
        duplicate_saved_job = make_job(
            "Junior React Developer",
            url="https://example.com/existing"
        )
        new_job = make_job("Junior React Developer", url="https://example.com/new")
        repeated_new_job = make_job(
            "Junior React Developer",
            url="https://example.com/new"
        )

        matched_jobs, frontend_matches, saveable_jobs = main.process_jobs(
            [duplicate_saved_job, new_job, repeated_new_job],
            [saved_job]
        )

        self.assertEqual(frontend_matches, 3)
        self.assertEqual(len(matched_jobs), 1)
        self.assertEqual(matched_jobs[0]["url"], "https://example.com/new")
        self.assertEqual(
            {job["url"] for job in saveable_jobs},
            {"https://example.com/existing", "https://example.com/new"}
        )

    def test_new_notification_only_includes_jobs_at_save_threshold(self):
        qualifying_job = make_job("Junior React Developer")
        qualifying_job["score"] = 12
        weak_job = make_job("Junior Web Developer", url="https://example.com/weak")
        weak_job["score"] = 5

        notification_jobs = main.get_notification_jobs(
            [qualifying_job, weak_job],
            minimum_save_score=6
        )

        self.assertEqual(notification_jobs, [qualifying_job])
        self.assertEqual(main.get_notification_jobs([], 6), [])

    def test_tracked_jobs_remain_saved_even_when_score_is_below_threshold(self):
        applied_job = make_job("Full Stack Engineer")
        applied_job["status"] = "applied"

        _, _, saveable_jobs = main.process_jobs([], [applied_job])

        self.assertEqual(len(saveable_jobs), 1)
        self.assertEqual(saveable_jobs[0]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
