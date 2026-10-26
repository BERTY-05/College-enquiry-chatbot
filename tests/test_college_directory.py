import json
import sys
import unittest
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "chennai_colleges.json"
sys.path.insert(0, str(DATA_PATH.parent.parent))
from chatbot import CollegeAssistant  # noqa: E402


class FakeWebSearch:
    def __init__(self):
        self.queries = []

    def search(self, query, college=None):
        self.queries.append((query, college))
        return [{
            "title": "Official fee details",
            "snippet": "Current fee information from the college site.",
            "url": "https://www.iitm.ac.in/",
        }]


class FeeCircularSearch:
    def search(self, query, college=None):
        return [{
            "title": "Official 2026-27 B.Tech fee circular",
            "snippet": (
                "Fees Structure for Undergraduate Programmes (B.Tech, B.S and Dual Degree) "
                "academic year 2026-27. Tuition Fee 100000. Total Fees Payable "
                "General/OBC/EWS above 5 Lakhs 141402. SC/ST/PwD 41402."
            ),
            "url": "https://fees.iitm.ac.in/assets/circular/fees_structure_2026_admission_ug_pg.pdf",
        }]


class ChennaiDirectoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(DATA_PATH, encoding="utf-8") as fh:
            cls.data = json.load(fh)

    def test_directory_has_expected_fields_and_unique_colleges(self):
        colleges = self.data["colleges"]
        self.assertGreaterEqual(len(colleges), 10)
        self.assertEqual(len({college["name"] for college in colleges}), len(colleges))
        for college in colleges:
            with self.subTest(college=college.get("name")):
                self.assertTrue(college["name"].strip())
                self.assertTrue(college["category"].strip())
                self.assertTrue(college["area"].strip())
                self.assertTrue(college["website"].startswith("https://"))

    def test_directory_covers_multiple_college_types(self):
        categories = {college["category"] for college in self.data["colleges"]}
        self.assertTrue(any("Arts & Science" in category for category in categories))
        self.assertTrue(any("Medical" in category for category in categories))
        self.assertTrue(any("Engineering" in category for category in categories))

    def test_chennai_college_question_uses_directory(self):
        bot = CollegeAssistant(web_search=FakeWebSearch())
        result = bot.reply("Tell me about IIT Madras")
        self.assertEqual(result.intent, "chennai_directory")
        self.assertIn("https://www.iitm.ac.in/", result.text)

    def test_missing_fee_information_does_not_use_sample_fees(self):
        class FailedSearch:
            def search(self, query, college=None):
                return []

        bot = CollegeAssistant(web_search=FailedSearch())
        result = bot.reply("What are the fees at IIT Madras?")
        self.assertEqual(result.intent, "chennai_directory")
        self.assertIn("does not contain verified current fees", result.text)
        self.assertNotIn("₹ 85,000", result.text)

    def test_unspecified_fee_question_asks_which_college(self):
        result = CollegeAssistant(web_search=FakeWebSearch()).reply("How much are the college fees?")
        self.assertEqual(result.intent, "chennai_directory")
        self.assertIn("Which Chennai college", result.text)

    def test_greeting_and_unknown_question_do_not_use_sample_profile(self):
        bot = CollegeAssistant(web_search=FakeWebSearch())
        greeting = bot.reply("hello")
        self.assertIn("Chennai colleges", greeting.text)
        self.assertNotIn("ABC Engineering College", greeting.text)
        unknown = bot.reply("asdfgh qwerty")
        self.assertNotIn("yourcollege.edu.in", unknown.text)
        self.assertIn("Latest information found on the web", unknown.text)

    def test_current_fee_question_returns_cited_search_result(self):
        search = FakeWebSearch()
        result = CollegeAssistant(web_search=search).reply("What are the fees at IIT Madras?")
        self.assertEqual(result.intent, "chennai_directory")
        self.assertIn("Current fee information", result.text)
        self.assertIn("Source: https://www.iitm.ac.in/", result.text)
        self.assertEqual(search.queries[0][1]["name"], "Indian Institute of Technology Madras (IIT Madras)")

    def test_real_time_fee_answer_includes_retrieved_amounts(self):
        result = CollegeAssistant(web_search=FeeCircularSearch()).reply(
            "What are the fees for IIT Madras B.Tech 2026-27?"
        )
        self.assertIn("Tuition Fee 100000", result.text)
        self.assertIn("Total Fees Payable", result.text)
        self.assertIn("fees.iitm.ac.in/assets/circular/fees_structure_2026_admission_ug_pg.pdf", result.text)

    def test_search_failure_falls_back_without_sample_data(self):
        class FailedSearch:
            def search(self, query, college=None):
                return []

        result = CollegeAssistant(web_search=FailedSearch()).reply("What are fees at IIT Madras?")
        self.assertIn("does not contain verified current fees", result.text)
        self.assertNotIn("₹ 85,000", result.text)


if __name__ == "__main__":
    unittest.main()
