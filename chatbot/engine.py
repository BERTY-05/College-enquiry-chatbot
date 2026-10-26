"""Core logic of the multilingual college assistant (standard library only).

Pipeline for every user message
-------------------------------
1. Language detection  - Unicode script ranges (Tamil, Devanagari, Telugu, ...).
                         For Latin text, romanised hints ("evlo", "kitna") tell
                         Tanglish / Hinglish apart from plain English.
2. Normalisation       - NFC, lower-case, punctuation removed.
3. Entity detection    - department names (CSE, ECE, ...) in any language.
4. Intent scoring      - weighted keyword matching across all languages.
5. Answer generation   - pre-written answers in English / Tamil / Hindi filled
                         with the college facts from data/college_data.json.
6. Translation (opt.)  - other languages go through `Translator`.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from .web_search import CollegeWebSearch

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA = BASE_DIR / "data" / "college_data.json"
DEFAULT_DIRECTORY = BASE_DIR / "data" / "chennai_colleges.json"

NATIVE_LANGS = ("en", "ta", "hi")

LANGUAGES = {
    "en": "English",
    "ta": "தமிழ்",
    "hi": "हिन्दी",
    "te": "తెలుగు",
    "ml": "മലയാളം",
    "kn": "ಕನ್ನಡ",
    "bn": "বাংলা",
    "gu": "ગુજરાતી",
    "pa": "ਪੰਜਾਬੀ",
    "or": "ଓଡ଼ିଆ",
    "ur": "اردو",
}

# (language code, first code point, last code point)
_SCRIPTS = [
    ("ta", 0x0B80, 0x0BFF),
    ("hi", 0x0900, 0x097F),  # Devanagari: Hindi (also Marathi / Nepali)
    ("te", 0x0C00, 0x0C7F),
    ("kn", 0x0C80, 0x0CFF),
    ("ml", 0x0D00, 0x0D7F),
    ("bn", 0x0980, 0x09FF),
    ("gu", 0x0A80, 0x0AFF),
    ("pa", 0x0A00, 0x0A7F),
    ("or", 0x0B00, 0x0B7F),
    ("ur", 0x0600, 0x06FF),
]


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------
def detect_script(text: str) -> Optional[str]:
    """Return the language code of the dominant non-Latin script, or None."""
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for lang, lo, hi in _SCRIPTS:
            if lo <= cp <= hi:
                counts[lang] = counts.get(lang, 0) + 1
                break
    return max(counts, key=counts.get) if counts else None  # type: ignore[arg-type]


def normalize(text: str) -> str:
    """NFC + lower-case + punctuation/symbols/format chars removed."""
    text = unicodedata.normalize("NFC", text).lower()
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if cat == "Cf":  # zero-width joiners etc.
            continue
        out.append(" " if cat[0] in "PSZC" else ch)
    return re.sub(r"\s+", " ", "".join(out)).strip()


@dataclass(frozen=True)
class _Kw:
    text: str
    latin: bool
    weight: float
    group: str
    pattern: Optional[re.Pattern]


def _compile_kw(raw: str, group: str) -> Optional[_Kw]:
    t = normalize(raw)
    if not t:
        return None
    latin = t.isascii()
    # longer / multi-word keywords are more specific, so they weigh more
    weight = 1 + 0.1 * len(t) + 0.5 * t.count(" ")
    pattern = None
    if latin:
        body = r"\s+".join(re.escape(w) for w in t.split(" "))
        pattern = re.compile(r"(?<![a-z0-9])" + body + r"(?:s|es)?(?![a-z0-9])")
    return _Kw(t, latin, weight, group, pattern)


def _spans(kw: _Kw, text: str) -> list[tuple[int, int]]:
    """All places where `kw` occurs in the normalised `text`."""
    if kw.latin:
        return [m.span() for m in kw.pattern.finditer(text)]  # type: ignore[union-attr]
    if len(kw.text) <= 3:  # very short Indic words must match a whole token
        spans, pos = [], 0
        for tok in text.split(" "):
            if tok == kw.text:
                spans.append((pos, pos + len(tok)))
            pos += len(tok) + 1
        return spans
    spans, start = [], 0  # longer words match as stems (handles suffixes)
    while True:
        i = text.find(kw.text, start)
        if i < 0:
            return spans
        spans.append((i, i + len(kw.text)))
        start = i + len(kw.text)


def _blank(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for s, e in spans:
        chars[s:e] = [" "] * (e - s)
    return re.sub(r"\s+", " ", "".join(chars)).strip()


class _Safe(dict):
    def __missing__(self, key: str) -> str:  # leave unknown {placeholders} visible
        return "{" + key + "}"


# --------------------------------------------------------------------------
# Result object
# --------------------------------------------------------------------------
@dataclass
class Reply:
    text: str
    lang: str  # language the answer is written in
    detected_lang: str  # language the question was written in
    intent: str  # intent id, "department" or "fallback"
    confidence: float = 0.0
    matched: list[str] = field(default_factory=list)
    notice: Optional[str] = None  # e.g. translation unavailable


# --------------------------------------------------------------------------
# The assistant
# --------------------------------------------------------------------------
class CollegeAssistant:
    def __init__(self, data_path: Optional[Path] = None, translator=None,
                 log_path: Optional[Path] = None, directory_mode: bool = True,
                 web_search=None) -> None:
        path = Path(data_path) if data_path else DEFAULT_DATA
        with open(path, encoding="utf-8") as fh:
            self.data = json.load(fh)
        with open(DEFAULT_DIRECTORY, encoding="utf-8") as fh:
            self.directory = json.load(fh)
        self.translator = translator
        self.log_path = Path(log_path) if log_path else None
        self.directory_mode = directory_mode
        self.web_search = web_search if web_search is not None else CollegeWebSearch()

        # compile intents: list of (intent dict, [keywords])
        self._intents = []
        for it in self.data["intents"]:
            kws = []
            for group, words in it["keywords"].items():
                for w in words:
                    k = _compile_kw(w, group)
                    if k:
                        kws.append(k)
            self._intents.append((it, kws))

        # compile departments
        self._depts = []
        for d in self.data["departments"]:
            kws = [k for a in d["aliases"] if (k := _compile_kw(a, "dept"))]
            self._depts.append((d, kws))

        hints = self.data.get("romanized_hints", {})
        self._hints = {
            lang: [k for w in words if (k := _compile_kw(w, "hint"))]
            for lang, words in hints.items()
        }

    # ------------------------------------------------------------------ API
    def reply(self, text: str, preferred: str = "auto") -> Reply:
        """Answer one user message. `preferred` is 'auto' or a language code."""
        text = (text or "").strip()
        norm = normalize(text)
        script = detect_script(text)

        notice = None
        work = norm
        if script and script not in NATIVE_LANGS:
            # other Indian language -> translate question to English first
            en = self.translator.translate(text, script, "en") if self.translator else None
            work = normalize(en) if en else ""
            if not en:
                notice = "Translation service unavailable, so I could not understand this language. Showing English."

        intent_id, dept, score, matched, groups = self._understand(work)

        if script:
            detected = script
        else:
            detected = self._latin_language(work, groups)

        target = detected if preferred == "auto" else preferred
        answer_lang = target if target in NATIVE_LANGS else "en"
        directory_answer = self._directory_answer(work, intent_id, answer_lang) if self.directory_mode else None
        matching_college = self._matching_college(work) if self.directory_mode else None
        if (self.directory_mode and self.web_search and
            (directory_answer is None or intent_id == "fallback"
             or (matching_college is not None and self._needs_current_details(work, intent_id)))):
            results = self.web_search.search(work, matching_college)
            if results:
                directory_answer = self._format_search_results(results, answer_lang)
        if directory_answer is not None:
            intent_id, dept = "chennai_directory", None
            answer = directory_answer
        else:
            answer = self._compose(intent_id, dept, answer_lang)

        final_lang = answer_lang
        if target not in NATIVE_LANGS:
            translated = (self.translator.translate_markdown(answer, "en", target)
                          if self.translator else None)
            if translated:
                answer, final_lang = translated, target
            elif notice is None:
                notice = "Translation service unavailable. Showing the answer in English."

        result = Reply(answer, final_lang, detected, intent_id, round(score, 2), matched, notice)
        self._log(text, result)
        return result

    def welcome(self, lang: str = "en") -> str:
        lang = lang if lang in NATIVE_LANGS else "en"
        if self.directory_mode:
            return {
                "en": "Welcome to Chennai College Explorer! Ask me to find Chennai-area colleges by name, type, or area.",
                "ta": "சென்னை கல்லூரி தேடலுக்கு வரவேற்கிறோம்! கல்லூரியின் பெயர், வகை அல்லது பகுதியின் அடிப்படையில் கேளுங்கள்.",
                "hi": "चेन्नई कॉलेज एक्सप्लोरर में आपका स्वागत है! कॉलेज का नाम, प्रकार या क्षेत्र बताकर खोजें।",
            }[lang]
        return self._compose("greeting", None, lang)

    def suggestions(self, lang: str = "en") -> list[str]:
        lang = lang if lang in NATIVE_LANGS else "en"
        return self.data["suggestions"][lang]

    def ui(self, key: str, lang: str = "en") -> str:
        lang = lang if lang in NATIVE_LANGS else "en"
        return self.data["ui"][key][lang]

    def college_name(self, lang: str = "en") -> str:
        lang = lang if lang in NATIVE_LANGS else "en"
        return self.data["college"]["name"][lang]

    # ------------------------------------------------------------ internals
    def _scan(self, text: str):
        scores: dict[str, float] = {}
        matched: list[str] = []
        groups: list[str] = []
        for it, kws in self._intents:
            for kw in kws:
                if _spans(kw, text):
                    scores[it["id"]] = scores.get(it["id"], 0.0) + kw.weight
                    matched.append(kw.text)
                    groups.append(kw.group)
        return scores, matched, groups

    def _find_dept(self, text: str):
        """Return (department dict or None, text with department words blanked)."""
        best, best_pos, all_spans = None, 10**9, []
        for d, kws in self._depts:
            for kw in kws:
                sp = _spans(kw, text)
                if sp:
                    all_spans.extend(sp)
                    if sp[0][0] < best_pos:
                        best, best_pos = d, sp[0][0]
        return best, (_blank(text, all_spans) if all_spans else text)

    def _understand(self, text: str):
        dept, rest = self._find_dept(text)
        scores, matched, groups = self._scan(rest)
        best, best_score = None, 0.0
        for it, _ in self._intents:  # file order = tie-break priority
            s = scores.get(it["id"], 0.0)
            if s > best_score:
                best, best_score = it["id"], s
        if dept and best in (None, "courses"):
            return "department", dept, max(best_score, 1.0), matched, groups
        if best is None:
            return "fallback", None, 0.0, matched, groups
        return best, None, best_score, matched, groups

    def _latin_language(self, text: str, groups: list[str]) -> str:
        """Tell English from Tanglish / Hinglish for Latin-script input."""
        ta = sum(1 for k in self._hints.get("ta", []) if _spans(k, text)) + groups.count("ta_rom")
        hi = sum(1 for k in self._hints.get("hi", []) if _spans(k, text)) + groups.count("hi_rom")
        if ta == 0 and hi == 0:
            return "en"
        return "ta" if ta > hi else "hi"

    def _directory_answer(self, text: str, intent_id: str, lang: str = "en") -> Optional[str]:
        """Answer from verified directory fields, never from the sample profile."""
        norm = normalize(text)
        colleges = self.directory["colleges"]
        basic_responses = {
            "en": {
                "greeting": "Hello! Ask me to find Chennai colleges by name, type, or area.",
                "thanks": "You're welcome! Ask me about another Chennai college.",
                "bye": "Goodbye! Check the linked official college websites for current details.",
            },
            "ta": {
                "greeting": "வணக்கம்! சென்னை கல்லூரிகளை பெயர், வகை அல்லது பகுதியால் தேடுங்கள்.",
                "thanks": "மகிழ்ச்சி! வேறு சென்னை கல்லூரி பற்றியும் கேளுங்கள்.",
                "bye": "வணக்கம்! தற்போதைய விவரங்களுக்கு கல்லூரியின் அதிகாரப்பூர்வ இணையதளத்தைப் பாருங்கள்.",
            },
            "hi": {
                "greeting": "नमस्ते! चेन्नई के कॉलेज नाम, प्रकार या क्षेत्र से खोजें।",
                "thanks": "आपका स्वागत है! किसी और चेन्नई कॉलेज के बारे में पूछें।",
                "bye": "अलविदा! नवीनतम जानकारी के लिए कॉलेज की आधिकारिक वेबसाइट देखें।",
            },
        }
        lang = lang if lang in basic_responses else "en"
        if intent_id in basic_responses[lang]:
            return basic_responses[lang][intent_id]

        matching = [
            college for college in colleges
            if normalize(college["name"]) in norm
            or any(normalize(alias) in norm for alias in college.get("aliases", []))
        ]

        category_terms = {
            "engineering": ("engineering", "engineer", "btech", "b tech", "b.e"),
            "medical": ("medical", "medicine", "mbbs"),
            "Arts & Science": ("arts", "science", "arts and science"),
            "University": ("university", "universities"),
        }
        requested_categories = [
            label for label, terms in category_terms.items()
            if any(term in norm for term in terms)
        ]
        requested_area = next(
            (college["area"] for college in colleges if normalize(college["area"]) in norm),
            None,
        )

        detail_question = intent_id in {
            "admission", "courses", "fees", "scholarship", "hostel", "transport",
            "placements", "exams", "facilities", "events", "about", "contact", "timings",
        }
        directory_question = bool(
            matching or requested_categories or requested_area
            or any(term in norm for term in ("college", "colleges", "campus", "institute"))
            or detail_question
        )
        if not directory_question:
            return {
                "en": "I can help find colleges in Chennai by name, type, or area. Tell me which college or what kind you're looking for.",
                "ta": "சென்னை கல்லூரிகளை பெயர், வகை அல்லது பகுதியால் தேட உதவுகிறேன். கல்லூரி பெயர் அல்லது வகையைச் சொல்லுங்கள்.",
                "hi": "मैं चेन्नई के कॉलेज नाम, प्रकार या क्षेत्र से खोज सकता हूँ। कॉलेज का नाम या प्रकार बताइए।",
            }[lang]

        if not matching and detail_question and not requested_categories and not requested_area:
            return (
                {
                    "en": "Which Chennai college are you asking about? The directory has links and locations, but it does not store verified current fees, courses, or admission details. Name a college (for example, IIT Madras or Loyola College) and I can show its official website.",
                    "ta": "எந்த சென்னை கல்லூரியைப் பற்றி கேட்கிறீர்கள்? தற்போதைய கட்டணம், படிப்புகள், சேர்க்கை விவரங்கள் இங்கு இல்லை. கல்லூரியின் பெயரைச் சொல்லுங்கள்; அதன் அதிகாரப்பூர்வ இணையதளத்தைத் தருகிறேன்.",
                    "hi": "आप चेन्नई के किस कॉलेज के बारे में पूछ रहे हैं? यहाँ सत्यापित वर्तमान फीस, पाठ्यक्रम या प्रवेश विवरण उपलब्ध नहीं हैं। कॉलेज का नाम बताइए, मैं उसकी आधिकारिक वेबसाइट दिखाऊँगा।",
                }[lang]
            )

        if not matching:
            matching = colleges
            if requested_categories:
                matching = [
                    college for college in matching
                    if any(category.casefold() in college["category"].casefold()
                           for category in requested_categories)
                ]
            if requested_area:
                matching = [college for college in matching if college["area"] == requested_area]

        if not matching:
            return (
                "I couldn't find a matching college in the current Chennai directory. "
                "Try a college name, type (engineering, medical, arts and science), or area."
            )

        if len(matching) == 1:
            college = matching[0]
            response = (
                f"**{college['name']}**\n"
                f"- Type: {college['category']}\n"
                f"- Area: {college['area']}\n"
                f"- Official website: {college['website']}"
            )
        else:
            lines = ["**Matching colleges in the Chennai directory**"]
            for college in matching:
                lines.append(
                    f"- **{college['name']}** — {college['category']} · {college['area']}\n"
                    f"  Official website: {college['website']}"
                )
            response = "\n".join(lines)

        if detail_question:
            response += (
                "\n\nThe directory currently stores only college type, area, and official website; "
                "it does not contain verified current fees, courses, admissions, or placement figures. "
                "Open the official website above for those details."
            )
        return response

    def _matching_college(self, text: str) -> Optional[dict]:
        norm = normalize(text)
        return next((
            college for college in self.directory["colleges"]
            if normalize(college["name"]) in norm
            or any(normalize(alias) in norm for alias in college.get("aliases", []))
        ), None)

    @staticmethod
    def _needs_current_details(text: str, intent_id: str) -> bool:
        current_topics = {
            "admission", "courses", "fees", "scholarship", "hostel", "transport",
            "placements", "exams", "facilities", "events", "about", "contact", "timings",
        }
        return intent_id in current_topics or any(
            term in normalize(text)
            for term in ("fee", "fees", "course", "admission", "placement", "cutoff", "scholarship", "hostel")
        )

    @staticmethod
    def _format_search_results(results: list[dict[str, str]], lang: str) -> str:
        headings = {
            "en": "**Latest information found on the web**",
            "ta": "**இணையத்தில் கண்ட சமீபத்திய தகவல்**",
            "hi": "**वेब पर मिली नवीनतम जानकारी**",
        }
        lines = [headings.get(lang, headings["en"])]
        for result in results[:4]:
            snippet = result["snippet"]
            if len(snippet) > 1600:
                snippet = snippet[:1597].rsplit(" ", 1)[0] + "..."
            lines.append(f"- **{result['title']}**\n  {snippet or 'Open the source for the full details.'}\n  Source: {result['url']}")
        lines.append(
            "\nThis is page text retrieved live. Confirm important decisions on the linked official site."
        )
        return "\n".join(lines)

    def _fields(self, lang: str) -> _Safe:
        fields = _Safe()
        for source in (self.data["facts"], self.data["college"]):
            for key, val in source.items():
                fields[key] = val.get(lang) or val.get("en") if isinstance(val, dict) else val
        return fields

    def _compose(self, intent_id: str, dept: Optional[dict], lang: str) -> str:
        fields = self._fields(lang)
        if intent_id == "department" and dept:
            fields.update(dept=dept["name"][lang], intake=dept["intake"], focus=dept["focus"][lang])
            template = self.data["department_template"][lang]
        elif intent_id == "fallback":
            template = self.data["fallback"][lang]
        else:
            intent = next(i for i, _ in self._intents if i["id"] == intent_id)
            template = intent["answers"].get(lang) or intent["answers"]["en"]
        return template.format_map(fields)

    def _log(self, question: str, r: Reply) -> None:
        if not self.log_path:
            return
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            new = not self.log_path.exists()
            with open(self.log_path, "a", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                if new:
                    w.writerow(["timestamp", "question", "detected_lang", "reply_lang", "intent", "score"])
                w.writerow([datetime.now().isoformat(timespec="seconds"), question,
                            r.detected_lang, r.lang, r.intent, r.confidence])
        except OSError:
            pass  # logging must never break the chat
