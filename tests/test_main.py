import unittest

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
