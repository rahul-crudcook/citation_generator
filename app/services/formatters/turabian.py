# citation_generator/app/services/formatters/turabian.py
"""Turabian formatter (concise subset for M6 previews).

Turabian is closely related to Chicago. We implement pragmatic templates
for previews and keep behavior deterministic.

Implemented:
- Book
- Journal Article
- Website

Other types raise NotImplementedError for now.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.formatters.base import BaseFormatter


class TurabianFormatter(BaseFormatter):
    """Turabian style formatter (simplified)."""

    # ---------------------------- Author rendering ----------------------------
    def _render_author(self, author: Any) -> str:
        """'Last, First Middle' form."""
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
            return str(first)
        if not first:
            return str(last)
        return f"{last}, {first}"

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
        title = self._sentence_case(str(facts.get("title") or ""))
        city = str(facts.get("city_of_publication") or "").strip()
        publisher = str(facts.get("publisher") or "").strip()
        year = str(facts.get("year") or "").strip()

        imprint = ", ".join(p for p in (city, publisher, year) if p)
        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if title:
            parts.append(f"{title}.")
        if imprint:
            parts.append(imprint + ".")
        return " ".join(parts).strip()

    def format_journal_article(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        title = self._sentence_case(str(facts.get("title") or ""))
        journal = self._title_case(str(facts.get("journal") or ""))
        volume = str(facts.get("volume") or "").strip()
        issue = str(facts.get("issue") or "").strip()
        year = str(facts.get("year") or "").strip()
        pages = str(facts.get("pages") or "").strip()
        doi = str(facts.get("doi") or "").strip()
        url = str(facts.get("url") or "").strip()

        vol_issue = ""
        if volume and issue:
            vol_issue = f"{volume}, no. {issue}"
        elif volume:
            vol_issue = volume

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if title:
            parts.append(f'"{title}."')
        if journal:
            parts.append(f"{journal} {vol_issue} ({year}): {pages}.")
        if doi or url:
            parts.append((doi or url).strip())
        return " ".join(p for p in parts if p).replace("  ", " ").strip()

    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("Turabian magazine/newspaper formatting not implemented yet.")

    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("Turabian encyclopedia formatting not implemented yet.")

    def format_website(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        title = self._sentence_case(str(facts.get("title") or ""))
        site = self._title_case(str(facts.get("site_title") or facts.get("publisher") or ""))
        year = str(facts.get("year") or "").strip()
        url = str(facts.get("url") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if title:
            parts.append(f'"{title}."')
        if site:
            parts.append(site + ".")
        if year:
            parts.append(year + ".")
        if url:
            parts.append(url)
        return " ".join(parts).strip()


def get_formatter() -> TurabianFormatter:
    """Factory expected by `FormatService`."""
    return TurabianFormatter()
