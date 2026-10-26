import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chatbot import CollegeAssistant, Translator, detect_script  # noqa: E402


class FakeTranslator(Translator):
    """Offline stand-in so translation paths can be tested without internet."""

    def __init__(self):
        super().__init__()
        self._cls = object()  # pretend the library is installed

    def translate(self, text, src, tgt):
        return "what is the fee" if tgt == "en" else f"<{tgt}>{text}"


class ScriptDetection(unittest.TestCase):
    def test_scripts(self):
        self.assertEqual(detect_script("கட்டணம்"), "ta")
        self.assertEqual(detect_script("फीस कितनी है"), "hi")
        self.assertEqual(detect_script("ఫీజు ఎంత"), "te")
        self.assertEqual(detect_script("fees"), None)
        self.assertEqual(detect_script("CSE கட்டணம்"), "ta")


class IntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = CollegeAssistant(directory_mode=False)

    def check(self, cases):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.bot.reply(text).intent, expected)

    def test_english(self):
        self.check([
            ("Hello", "greeting"),
            ("thanks a lot", "thanks"),
            ("bye", "bye"),
            ("What is the admission process?", "admission"),
            ("How much is the tuition fee", "fees"),
            ("Which courses do you offer", "courses"),
            ("Is there a scholarship for first graduate students", "scholarship"),
            ("What is the hostel fee?", "hostel"),
            ("Do you have hostel facilities", "hostel"),
            ("Is there bus facility", "transport"),
            ("Do you provide bus service", "transport"),
            ("Tell me about the library", "library"),
            ("Which companies visit for placement", "placements"),
            ("When will the exam results come out", "exams"),
            ("What sports and canteen facilities are there", "facilities"),
            ("When is the annual fest", "events"),
            ("Is the college NAAC accredited", "about"),
            ("phone number and email", "contact"),
            ("What is the college address", "location"),
            ("What are the office hours", "timings"),
        ])

    def test_tamil(self):
        self.check([
            ("வணக்கம்", "greeting"),
            ("நன்றி", "thanks"),
            ("சேர்க்கை எப்படி", "admission"),
            ("கட்டண விவரம்", "fees"),
            ("உதவித்தொகை உண்டா", "scholarship"),
            ("விடுதி வசதி இருக்கிறதா", "hostel"),
            ("பேருந்து வசதி இருக்கிறதா", "transport"),
            ("நூலகம் இருக்கிறதா", "library"),
            ("வேலைவாய்ப்பு எப்படி இருக்கும்", "placements"),
            ("தேர்வு முடிவுகள் எப்போது", "exams"),
            ("தொடர்பு எண்", "contact"),
            ("கல்லூரி முகவரி என்ன", "location"),
        ])

    def test_hindi(self):
        self.check([
            ("नमस्ते", "greeting"),
            ("धन्यवाद", "thanks"),
            ("प्रवेश कैसे लें", "admission"),
            ("फीस कितनी है", "fees"),
            ("छात्रवृत्ति मिलती है?", "scholarship"),
            ("हॉस्टल है क्या", "hostel"),
            ("बस सुविधा है?", "transport"),
            ("पुस्तकालय कहाँ है", "library"),
            ("प्लेसमेंट कैसा है", "placements"),
            ("परीक्षा परिणाम कब आएगा", "exams"),
            ("संपर्क नंबर", "contact"),
        ])

    def test_departments(self):
        self.check([
            ("Tell me about CSE", "department"),
            ("information technology department", "department"),
            ("AI&DS", "department"),
            ("ECE placements", "placements"),  # specific intent beats department
            ("கணினி அறிவியல் பற்றி சொல்லுங்கள்", "department"),
            ("मैकेनिकल विभाग", "department"),
            ("தகவல் தொடர்பு பொறியியல்", "department"),  # must not trigger 'contact'
        ])
        self.assertIn("Electronics and Communication", self.bot.reply("tell me about ECE").text)

    def test_fallback(self):
        r = self.bot.reply("asdfgh qwerty")
        self.assertEqual(r.intent, "fallback")
        self.assertEqual(self.bot.reply("").intent, "fallback")


class LanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = CollegeAssistant(directory_mode=False)

    def test_auto_follows_question_language(self):
        self.assertEqual(self.bot.reply("What is the fee?").lang, "en")
        self.assertEqual(self.bot.reply("கட்டணம் என்ன").lang, "ta")
        self.assertEqual(self.bot.reply("फीस कितनी है").lang, "hi")

    def test_preferred_language_overrides(self):
        r = self.bot.reply("What is the fee?", preferred="ta")
        self.assertEqual(r.lang, "ta")
        self.assertEqual(detect_script(r.text), "ta")

    def test_romanised_tamil_and_hindi(self):
        r = self.bot.reply("fees kitni hai")
        self.assertEqual((r.intent, r.detected_lang, r.lang), ("fees", "hi", "hi"))
        r = self.bot.reply("hostel fees evlo")
        self.assertEqual((r.intent, r.detected_lang, r.lang), ("hostel", "ta", "ta"))
        r = self.bot.reply("vanakkam")
        self.assertEqual((r.intent, r.lang), ("greeting", "ta"))

    def test_other_language_with_translator(self):
        bot = CollegeAssistant(translator=FakeTranslator(), directory_mode=False)
        r = bot.reply("ఫీజు ఎంత")
        self.assertEqual((r.intent, r.detected_lang, r.lang), ("fees", "te", "te"))
        self.assertIn("<te>", r.text)

    def test_other_language_without_translator(self):
        r = CollegeAssistant(directory_mode=False).reply("ఫీజు ఎంత")
        self.assertEqual(r.intent, "fallback")
        self.assertEqual(r.lang, "en")
        self.assertIsNotNone(r.notice)

    def test_preferred_other_language_without_translator_falls_back_to_english(self):
        r = CollegeAssistant(directory_mode=False).reply("What is the fee?", preferred="te")
        self.assertEqual((r.intent, r.lang), ("fees", "en"))
        self.assertIsNotNone(r.notice)


class DataIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = CollegeAssistant(directory_mode=False)

    def test_every_answer_exists_and_has_no_unfilled_placeholder(self):
        for it, _ in self.bot._intents:
            for lang in ("en", "ta", "hi"):
                with self.subTest(intent=it["id"], lang=lang):
                    self.assertIn(lang, it["answers"])
                    text = self.bot._compose(it["id"], None, lang)
                    self.assertNotIn("{", text)
        for d, _ in self.bot._depts:
            for lang in ("en", "ta", "hi"):
                with self.subTest(dept=d["id"], lang=lang):
                    self.assertNotIn("{", self.bot._compose("department", d, lang))
        for lang in ("en", "ta", "hi"):
            self.assertNotIn("{", self.bot._compose("fallback", None, lang))

    def test_quick_suggestions_hit_the_right_intent(self):
        expected = ["admission", "courses", "fees", "hostel", "placements", "contact"]
        for lang in ("en", "ta", "hi"):
            for label, intent in zip(self.bot.suggestions(lang), expected):
                with self.subTest(lang=lang, label=label):
                    self.assertEqual(self.bot.reply(label).intent, intent)


if __name__ == "__main__":
    unittest.main(verbosity=1)
