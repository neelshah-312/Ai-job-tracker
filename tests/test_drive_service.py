import unittest

from services.drive_service import match_resume_for_role


class DriveServiceTests(unittest.TestCase):
    def setUp(self):
        self.available = {
            "resume_soc_analyst_v1.pdf": "soc-link",
            "resume_grc_v1.pdf": "grc-link",
            "resume_cloud_security_v1.pdf": "cloud-link",
            "resume_product_security_v1.pdf": "product-link",
            "resume_cybersecurity_analyst_general.pdf": "general-link",
        }

    def test_match_soc_role(self):
        self.assertEqual(match_resume_for_role("SOC Analyst Intern", self.available), "soc-link")

    def test_match_grc_role(self):
        self.assertEqual(match_resume_for_role("GRC Compliance Analyst", self.available), "grc-link")

    def test_match_cloud_role(self):
        self.assertEqual(match_resume_for_role("Cloud Security Engineer", self.available), "cloud-link")

    def test_match_product_security_role(self):
        self.assertEqual(match_resume_for_role("Product Security Engineer", self.available), "product-link")

    def test_match_general_analyst_role(self):
        self.assertEqual(match_resume_for_role("Cybersecurity Analyst", self.available), "general-link")

    def test_none_role_returns_none(self):
        self.assertIsNone(match_resume_for_role(None, self.available))


if __name__ == "__main__":
    unittest.main()
