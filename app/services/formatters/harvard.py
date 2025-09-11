# citation_generator/app/services/formatters/harvard.py
"""Harvard-style formatter (concise subset for M6 previews).

Simplified templates for previews:
- Book:
    Last, F. (Year) Title. Publisher.
- Journal Article:
    Last, F. (Year) 'Title', Journal, volume(issue), pages. DOI/URL
- Website:
    Last, F. (Year) Title. Available at: URL

Other types raise NotImplementedError for now.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.formatters.base import BaseFormatter


class HarvardFormatter(BaseFormatter):
    """Harvard style formatter (simplified)."""

    # ---------------------------- Author rendering ----------------------------
    def _render_author(self, author: Any) -> str:
        """Harvard short form: 'Last, F. M.' (similar to APA)."""
        first = ""
        last = ""
        if isinstance(author, dict):
            first = self._trim(author.get("first")) or ""
            last = self._trim(author.get("last")) or ""
        elif isinstance(author, str):
            first, last = self._split_author(author)

        if not first and not last:
            return ""
        if not last:
            return self._initials(str(first))
        if not first:
            return str(last)
        return f"{last}, {self._initials(str(first))}"

    def _render_authors(self, authors: Any) -> str:
        if not authors:
            return ""
        rendered: list[str] = []

        if isinstance(authors, list):
            for a in authors:
                piece = self._render_author(a)
                if piece:
                    rendered.append(piece)
        elif isinstance(authors, str):
            piece = self._render_author(authors)
            if piece:
                rendered.append(piece)

        n = len(rendered)
        if n == 0:
            return ""
        if n == 1:
            return rendered[0]
        if n == 2:
            return f"{rendered[0]} and {rendered[1]}"
        return f"{rendered[0]} et al."

    # ------------------------------ Source types ------------------------------
    def format_book(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = self._sentence_case(str(facts.get("title") or ""))
        publisher = str(facts.get("publisher") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors)
        if year:
            parts.append(f"({year})")
        if title:
            parts.append(title + ".")
        if publisher:
            parts.append(publisher + ".")
        return " ".join(parts).replace(" )", ")").strip()

    def format_journal_article(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = self._sentence_case(str(facts.get("title") or ""))
        journal = self._title_case(str(facts.get("journal") or ""))
        volume = str(facts.get("volume") or "").strip()
        issue = str(facts.get("issue") or "").strip()
        pages = str(facts.get("pages") or "").strip()
        doi = str(facts.get("doi") or "").strip()
        url = str(facts.get("url") or "").strip()

        vol_issue = ""
        if volume and issue:
            vol_issue = f"{volume}({issue})"
        elif volume:
            vol_issue = volume

        link = doi or url

        parts: list[str] = []
        if authors:
            parts.append(authors)
        if year:
            parts.append(f"({year})")
        if title:
            parts.append(f"'{title}',")
        if journal:
            parts.append(f"{journal},")
        if vol_issue:
            parts.append(vol_issue + ",")
        if pages:
            parts.append(pages + ".")
        if link:
            parts.append(link)
        return " ".join(p.strip() for p in parts if p).replace(" ,", ",").strip()

    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("Harvard magazine/newspaper formatting not implemented yet.")

    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("Harvard encyclopedia formatting not implemented yet.")

    def format_website(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = self._sentence_case(str(facts.get("title") or ""))
        url = str(facts.get("url") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors)
        if year:
            parts.append(f"({year})")
        if title:
            parts.append(title + ".")
        if url:
            parts.append("Available at: " + url)
        return " ".join(parts).strip()


def get_formatter() -> HarvardFormatter:
    """Factory expected by `FormatService`."""
    return HarvardFormatter()
