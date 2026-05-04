from datetime import date
import unittest

from services import followup_service as fs


class FollowupServiceTests(unittest.TestCase):
    def test_parse_iso_date_handles_date_and_datetime(self):
        self.assertEqual(fs.parse_iso_date("2026-05-04"), date(2026, 5, 4))
        self.assertEqual(fs.parse_iso_date("2026-05-04T09:10:11Z"), date(2026, 5, 4))
        self.assertIsNone(fs.parse_iso_date("not-a-date"))

    def test_add_business_days_skips_weekends(self):
        # Friday + 1 business day should become Monday.
        start = date(2026, 5, 1)
        self.assertEqual(fs.add_business_days(start, 1), date(2026, 5, 4))

    def test_compute_followup_due_date(self):
        anchor = date(2026, 5, 4)  # Monday
        self.assertEqual(fs.compute_followup_due_date("application_confirmation", anchor), date(2026, 5, 18))
        self.assertIsNone(fs.compute_followup_due_date("offer", anchor))

    def test_email_type_for_application_status(self):
        self.assertEqual(fs.email_type_for_application_status("Recruiter Reply"), "recruiter_reply")
        self.assertEqual(fs.email_type_for_application_status("unknown"), "application_confirmation")

    def test_days_since(self):
        self.assertEqual(fs.days_since(date(2026, 5, 1), today=date(2026, 5, 4)), 3)
        self.assertIsNone(fs.days_since(None))


if __name__ == "__main__":
    unittest.main()
