# citation_generator/app/services/formatters/mla.py
"""MLA formatter (concise subset for M6 previews).

Rendered shape (simplified MLA 9th):
- Book:
    Last, First M., and Second Author. Title. Publisher, Year.
- Journal Article:
    Last, First M., and Second Author. "Title." Journal, vol. X, no. Y, Year, pp. N–N. DOI/URL
- Website:
    Last, First M., and Second Author. "Title." Site/Publisher, Year, URL.

Notes
-----
This is a pragmatic implementation intended for previews. Some rules
(italics, access dates, containers) are simplified for determinism.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.formatters.base import BaseFormatter


class MLAFormatter(BaseFormatter):
    """MLA style formatter (simplified)."""

    # ---------------------------- Author rendering ----------------------------
    def _render_author(self, author: Any) -> str:
        """MLA author long form: 'Last, First Middle'."""
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
        """Join authors per common MLA pattern."""
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
            # "Last, First, and Last, First"
            return f"{rendered[0]}, and {rendered[1]}"
        # 3+ authors — simplified: first author + et al.
        return f"{rendered[0]}, et al."

    # ------------------------------ Source types ------------------------------
    def format_book(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        title = self._title_case(str(facts.get("title") or ""))
        publisher = str(facts.get("publisher") or "").strip()
        year = str(facts.get("year") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if title:
            parts.append(f"{title}.")
        if publisher:
            parts.append(f"{publisher},")
        if year:
            parts.append(year + ".")
        return " ".join(parts).replace(" ,", ",").strip()

    def format_journal_article(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        title = self._title_case(str(facts.get("title") or ""))
        journal = self._title_case(str(facts.get("journal") or ""))
        volume = str(facts.get("volume") or "").strip()
        issue = str(facts.get("issue") or "").strip()
        year = str(facts.get("year") or "").strip()
        pages = str(facts.get("pages") or "").strip()
        doi = str(facts.get("doi") or "").strip()
        url = str(facts.get("url") or "").strip()

        vol = f"vol. {volume}" if volume else ""
        iss = f"no. {issue}" if issue else ""
        pp = f"pp. {pages}" if pages else ""
        link = doi or url

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if title:
            parts.append(f'"{title}."')
        if journal:
            parts.append(f"{journal},")
        if vol:
            parts.append(vol + ",")
        if iss:
            parts.append(iss + ",")
        if year:
            parts.append(year + ",")
        if pp:
            parts.append(pp + ".")
        if link:
            parts.append(link)
        return " ".join(p.strip() for p in parts if p).replace(" ,", ",").strip()

    def format_magazine_newspaper(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("MLA magazine/newspaper formatting not implemented yet.")

    def format_encyclopedia(self, facts: Mapping[str, Any]) -> str:
        raise NotImplementedError("MLA encyclopedia formatting not implemented yet.")

    def format_website(self, facts: Mapping[str, Any]) -> str:
        authors = self._render_authors(facts.get("authors"))
        title = self._title_case(str(facts.get("title") or ""))
        site = self._title_case(str(facts.get("site_title") or facts.get("publisher") or ""))
        year = str(facts.get("year") or "").strip()
        url = str(facts.get("url") or "").strip()

        parts: list[str] = []
        if authors:
            parts.append(authors if authors.endswith(".") else f"{authors}.")
        if title:
            parts.append(f'"{title}."')
        if site:
            parts.append(f"{site},")
        if year:
            parts.append(year + ",")
        if url:
            parts.append(url)
        return " ".join(parts).replace(" ,", ",").strip()


def get_formatter() -> MLAFormatter:
    """Factory expected by `FormatService`."""
    return MLAFormatter()
