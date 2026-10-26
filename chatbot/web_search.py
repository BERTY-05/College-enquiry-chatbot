"""Optional web search for current, source-linked Chennai college answers."""

from __future__ import annotations

import re
from datetime import date
from typing import Optional
from urllib.parse import urlparse

_STOP_WORDS = {
    "what", "are", "is", "the", "for", "at", "of", "in", "on", "to", "a", "an",
    "how", "much", "can", "you", "tell", "me", "about", "please", "latest", "current",
}


class CollegeWebSearch:
    """Fetch a small set of web results; answers remain explicitly source-linked."""

    def __init__(self) -> None:
        try:
            from ddgs import DDGS
        except ImportError:
            self._ddgs = None
        else:
            self._ddgs = DDGS

    @property
    def available(self) -> bool:
        return self._ddgs is not None

    def search(self, query: str, college: Optional[dict] = None) -> list[dict[str, str]]:
        if self._ddgs is None:
            return []

        if college:
            domains = college.get("official_domains") or [
                college["website"].split("//", 1)[-1].split("/", 1)[0]
            ]
            name = college["name"]
            year = date.today().year
            keywords = " ".join(
                token for token in re.findall(r"[a-zA-Z0-9.-]+", query)
                if token.casefold() not in _STOP_WORDS
            )
            search_query = f"{name} {keywords} {year}"
        else:
            domains = [None]
            search_query = f"Chennai Tamil Nadu college {query} latest {date.today().year}"

        raw_results = []
        for domain in domains:
            if domain and college:
                name_terms = {
                    token.casefold()
                    for value in (college["name"], *college.get("aliases", []))
                    for token in re.findall(r"[a-zA-Z0-9]+", value)
                }
                topic_terms = " ".join(
                    token for token in re.findall(r"[a-zA-Z0-9.-]+", query)
                    if token.casefold() not in _STOP_WORDS
                    and token.casefold() not in name_terms
                )
                search_queries = [f"site:{domain} {topic_terms}".strip()]
                query_lower = query.casefold()
                if any(word in query_lower for word in ("fee", "cost", "tuition", "price")):
                    search_queries.extend((
                        f"site:{domain} fees B.Tech",
                        f"site:{domain} fees {year} B.Tech",
                    ))
                elif any(word in query_lower for word in ("admission", "apply", "application", "cutoff")):
                    search_queries.append(f"site:{domain} admission {year}")
            else:
                search_queries = [search_query]
            for scoped_query in search_queries:
                try:
                    found = self._ddgs(timeout=8).text(
                        scoped_query,
                        region="in-en",
                        safesearch="moderate",
                        max_results=4,
                    )
                except Exception:
                    continue
                raw_results.extend(found or [])

        cleaned = []
        seen_urls = set()
        for result in raw_results:
            url = result.get("href") or result.get("url")
            title = result.get("title")
            snippet = result.get("body") or result.get("description")
            if title and url and url.startswith(("https://", "http://")):
                if college and not any(
                    self._is_official_domain(url, domain) for domain in domains
                ):
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                matched_domain = next(
                    (domain for domain in domains if domain and self._is_official_domain(url, domain)),
                    None,
                )
                extracted = self._extract(url, matched_domain)
                content = extracted or str(snippet or "").strip()
                content = self._relevant_excerpt(content, query)
                cleaned.append({
                    "title": str(title).strip(),
                    "snippet": content,
                    "url": str(url).strip(),
                })
        if college and cleaned:
            current_year = str(date.today().year)
            previous_year = str(date.today().year - 1)
            def rank(result: dict[str, str]) -> tuple[int, int, int]:
                text = (result["title"] + " " + result["snippet"] + " " + result["url"]).casefold()
                current_cycle = int(current_year in text or f"{current_year}-{str(date.today().year + 1)[-2:]}" in text)
                fee_document = int(result["url"].casefold().endswith(".pdf") and
                                    any(term in text for term in ("fee", "fees", "circular")))
                stale = int(previous_year in text)
                return current_cycle, fee_document, -stale

            cleaned.sort(key=rank, reverse=True)
            if any(term in query.casefold() for term in ("fee", "fees", "tuition", "cost", "price")):
                current_pdfs = [
                    result for result in cleaned
                    if result["url"].casefold().endswith(".pdf") and rank(result)[0]
                ]
                if current_pdfs:
                    return current_pdfs[:2]
        return cleaned

    @staticmethod
    def _is_official_domain(url: str, domain: Optional[str]) -> bool:
        host = (urlparse(url).hostname or "").casefold()
        expected = (domain or "").casefold()
        return bool(host and expected and (host == expected or host.endswith("." + expected)))

    def _extract(self, url: str, domain: Optional[str]) -> str:
        parsed = urlparse(url)
        if parsed.scheme != "https" or (domain and not self._is_official_domain(url, domain)):
            return ""
        try:
            if parsed.path.casefold().endswith(".pdf"):
                if domain and parsed.hostname and parsed.hostname.casefold() != domain.casefold():
                    return ""
                import requests
                from io import BytesIO
                from pypdf import PdfReader

                response = requests.get(url, timeout=10, stream=True)
                response.raise_for_status()
                total = 0
                chunks = []
                for chunk in response.iter_content(65536):
                    total += len(chunk)
                    if total > 8_000_000:
                        return ""
                    chunks.append(chunk)
                pdf = PdfReader(BytesIO(b"".join(chunks)))
                return "\n".join((page.extract_text() or "") for page in pdf.pages[:10])

            extracted = self._ddgs(timeout=8).extract(url, fmt="text_plain")
            return str(extracted.get("content", "")) if isinstance(extracted, dict) else ""
        except Exception:
            return ""

    @staticmethod
    def _relevant_excerpt(content: str, query: str, max_chars: int = 2200) -> str:
        """Select fetched-page text relevant to the question, not just search snippets."""
        text = content.strip()
        if not text:
            return ""
        terms = [
            term for term in re.findall(r"[a-zA-Z0-9]+", query.casefold())
            if len(term) >= 3 and term not in _STOP_WORDS
        ]
        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        lines = [line for line in lines if line]
        if len(lines) > 1:
            query_is_fees = any(term in terms for term in ("fee", "fees", "tuition", "cost", "price"))
            if query_is_fees and any("total fees payable" in line.casefold() for line in lines):
                anchors = [
                    index for index, line in enumerate(lines)
                    if any(term in line.casefold() for term in (
                        "fee structure for undergraduate", "total fees payable", "tuition fee",
                        "total a (one time fees)", "total b (semester fees)",
                    ))
                ]
                selected_indexes = sorted({
                    neighbor
                    for index in anchors
                    for neighbor in range(max(0, index - 1), min(len(lines), index + 30))
                })
                excerpt = "\n".join(lines[index] for index in selected_indexes)
                if len(excerpt) > max_chars:
                    excerpt = excerpt[:max_chars].rsplit("\n", 1)[0] + "…"
                return excerpt

            ranked_lines = sorted(
                enumerate(lines),
                key=lambda item: sum(item[1].casefold().count(term) for term in terms),
                reverse=True,
            )
            matched_indexes = [index for index, line in ranked_lines if any(
                term in line.casefold() for term in terms
            )][:12]
            if matched_indexes:
                selected_indexes = sorted({
                    neighbor
                    for index in matched_indexes
                    for neighbor in (index - 1, index, index + 1)
                    if 0 <= neighbor < len(lines)
                })
                excerpt = "\n".join(lines[index] for index in selected_indexes)
                if len(excerpt) > max_chars:
                    return excerpt[:max_chars].rsplit("\n", 1)[0] + "…"
                return excerpt

        text = re.sub(r"\s+", " ", text)
        sentences = re.split(r"(?<=[.!?])\s+", text)
        ranked = sorted(
            enumerate(sentences),
            key=lambda item: sum(item[1].casefold().count(term) for term in terms),
            reverse=True,
        )
        selected = [sentence for _, sentence in ranked if any(term in sentence.casefold() for term in terms)]
        excerpt = " ".join(selected[:4]) if selected else text
        if len(excerpt) > max_chars:
            return excerpt[:max_chars].rsplit(" ", 1)[0] + "…"
        return excerpt
