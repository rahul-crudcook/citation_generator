# citation_generator/app/services/formatters/apa.py
"""APA formatter (concise, deterministic subset for M6).

This module provides a pragmatic APA implementation sufficient for previews.
It favors *determinism* and *readability* over exhaustive style coverage.

Rendered shape (simplified APA 7th):
- Book:
    Author(s). (Year). Title. Publisher.
- Journal Article:
    Author(s). (Year). Title. Journal, volume(issue), pages. DOI/URL
- Website:
    Author(s). (Year). Title. URL

Unimplemented types raise NotImplementedError for now.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.formatters.base import BaseFormatter


class APAFormatter(BaseFormatter):
    """APA style formatter."""

    # ---------------------------- Author rendering ----------------------------
    def _render_author(self, author: Any) -> str:
        """APA author: 'Last, F. M.'"""
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
        """Join authors with APA punctuation rules."""
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
            return f"{rendered[0]}, & {rendered[1]}"
        return ", ".join(rendered[:-1]) + f", & {rendered[-1]}"

    # ------------------------------ Source types ------------------------------
    def format_book(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = self._sentence_case(str(facts.get("title") or ""))
        publisher = str(facts.get("publisher") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if publisher:
            parts.append(f"{publisher}.")
        return " ".join(parts).strip()

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

        trailing = ""
        if pages and vol_issue:
            trailing = f"{vol_issue}, {pages}."
        elif vol_issue:
            trailing = f"{vol_issue}."
        elif pages:
            trailing = f"{pages}."

        link = doi or url

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if journal:
            parts.append(f"{journal},")
        if trailing:
            parts.append(trailing)
        if link:
            parts.append(link)

        return " ".join(p.strip() for p in parts if p).replace(" ,", ",").strip()

    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("APA magazine/newspaper formatting not implemented yet.")

    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("APA encyclopedia formatting not implemented yet.")

    def format_website(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        year = str(facts.get("year") or "").strip()
        title = self._sentence_case(str(facts.get("title") or ""))
        url = str(facts.get("url") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if year:
            parts.append(f"({year}).")
        if title:
            parts.append(f"{title}.")
        if url:
            parts.append(url)
        return " ".join(parts).strip()


def get_formatter() -> APAFormatter:
    """Factory expected by `FormatService`."""
    return APAFormatter()
