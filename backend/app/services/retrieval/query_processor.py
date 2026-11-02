"""Query processor for ASTRAVA knowledge retrieval.

Validates query bounds, normalizes search tokens, and sanitizes input for PostgreSQL
tsquery evaluation.
"""

import re
from typing import NamedTuple


class ProcessedQuery(NamedTuple):
    raw_query: str | None
    normalized_text: str | None
    tokens: list[str]
    is_empty: bool


class QueryProcessor:
    """Validates and processes raw retrieval queries."""

    MAX_QUERY_LENGTH = 500

    @classmethod
    def process(cls, query_text: str | None) -> ProcessedQuery:
        """Sanitizes and normalizes a retrieval query.

        Raises:
            ValueError: If query_text exceeds MAX_QUERY_LENGTH or contains null bytes.
        """
        if query_text is None:
            return ProcessedQuery(raw_query=None, normalized_text=None, tokens=[], is_empty=True)

        if "\x00" in query_text:
            raise ValueError("Query text cannot contain null bytes.")

        if len(query_text) > cls.MAX_QUERY_LENGTH:
            raise ValueError(
                f"Query text exceeds maximum length of {cls.MAX_QUERY_LENGTH} characters."
            )

        # Normalize whitespace
        normalized = " ".join(query_text.split()).strip()
        if not normalized:
            return ProcessedQuery(
                raw_query=query_text, normalized_text=None, tokens=[], is_empty=True
            )

        # Extract search tokens (alphanumeric, underscores, hyphens)
        tokens = re.findall(r"[\w-]+", normalized.lower())

        return ProcessedQuery(
            raw_query=query_text,
            normalized_text=normalized,
            tokens=tokens,
            is_empty=False,
        )

    @classmethod
    def build_tsquery_terms(cls, processed: ProcessedQuery) -> str | None:
        """Builds a formatted plain tsquery string using tokens joined by & (AND)."""
        if processed.is_empty or not processed.tokens:
            return None
        # Clean each token to be safe alphanumeric words
        clean_tokens = [
            re.sub(r"[^\w]", "", t) for t in processed.tokens if re.sub(r"[^\w]", "", t)
        ]
        if not clean_tokens:
            return None
        return " & ".join(clean_tokens)
