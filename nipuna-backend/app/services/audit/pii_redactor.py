"""PII redaction for logs, Sentry, and per-turn metrics.

A single source of truth for what counts as PII in this product.
Apply to:
  - LangChain LLM call loggers
  - Sentry ``before_send``
  - the ``request_timing`` writer (per-turn metrics, future PR)
  - any structured log emitted from ``app/services/ai/*``

The redaction is conservative: we err on the side of *narrow* regexes
that require a contextual cue (e.g. an ``Aadhaar:`` keyword) so we
don't strip 12-digit invoice numbers by accident. A false negative
(an unredacted PII) is acceptable for v1; a false positive (a
redacted invoice number) breaks the user.

The companion column-level encryption in
``app/services/security/encryption.py`` (future PR) is the real fix
for data-at-rest. This module is the runtime-safety layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# Replacements are short and consistent so log consumers can spot
# what's been touched.
PAN_REPLACEMENT = "[PAN]"
AADHAAR_REPLACEMENT = "[AADHAAR]"
GSTIN_REPLACEMENT = "[GSTIN]"
PHONE_REPLACEMENT = "[PHONE]"
EMAIL_REPLACEMENT = "[EMAIL]"
CARD_REPLACEMENT = "[CARD]"
ACCOUNT_REPLACEMENT = "[ACCOUNT]"


# PAN: 5 uppercase letters + 4 digits + 1 uppercase letter.
# e.g. ABCDE1234F
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

# Aadhaar: 4-4-4 digit groups, but only when preceded by a context cue
# to avoid matching invoice numbers. The cue is case-insensitive.
_AADHAAR_RE = re.compile(
    r"(?i)(?:aadhaar|uid|uidai)\s*[:#-]?\s*(\d{4}\s?\d{4}\s?\d{4})\b"
)

# GSTIN: 2 digits + 5 uppercase letters + 4 digits + 1 uppercase + 1
# digit + Z + 1 alphanumeric. e.g. 27ABCDE1234F1Z5
_GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]\b")

# Indian phone: +91 or 0 prefix, 10 digits. Optional separators.
_INDIAN_PHONE_RE = re.compile(r"(?:\+91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}\b")

# US phone: 10 digits with optional separators, requires context.
# `-` and `.` go at the END of the character class to avoid
# `re.error: bad character range`.
_US_PHONE_RE = re.compile(
    r"(?i)(?:phone|mobile|cell|tel)\s*[:#\-]?\s*(\(?\d{3}\)?[\s\-.]\d{3}[\s\-.]\d{4})\b"
)

# Standard email pattern.
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Credit-card: 13-19 digits with optional separators, requires
# Luhn-shaped context (we don't actually run Luhn, just length).
_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# Indian bank account: 9-18 digits, requires context.
_ACCOUNT_RE = re.compile(
    r"(?i)(?:a/c|account)\s*(?:no\.?|number)?\s*[:#-]?\s*(\d{9,18})\b"
)


@dataclass
class RedactionResult:
    text: str
    """The redacted text — safe to log / persist in low-trust stores."""
    types: list[str]
    """The kinds of PII that were replaced. Useful for metrics."""


def _apply(text: str, regex: re.Pattern[str], replacement: str, types: list[str]) -> str:
    def _sub(match: re.Match[str]) -> str:
        types.append(replacement.strip("[]"))
        return replacement

    return regex.sub(_sub, text)


def redact(text: str | None) -> RedactionResult:
    """Return the redacted text and the list of PII kinds replaced.

    Idempotent: redacting an already-redacted string is a no-op.
    """
    if not text:
        return RedactionResult(text or "", [])

    types: list[str] = []
    out = text

    # Order matters: longer/more-specific patterns first so they win
    # over the generic email/phone regexes.
    out = _apply(out, _AADHAAR_RE, AADHAAR_REPLACEMENT, types)
    out = _apply(out, _ACCOUNT_RE, ACCOUNT_REPLACEMENT, types)
    out = _apply(out, _PAN_RE, PAN_REPLACEMENT, types)
    out = _apply(out, _GSTIN_RE, GSTIN_REPLACEMENT, types)
    out = _apply(out, _US_PHONE_RE, PHONE_REPLACEMENT, types)
    out = _apply(out, _INDIAN_PHONE_RE, PHONE_REPLACEMENT, types)
    out = _apply(out, _EMAIL_RE, EMAIL_REPLACEMENT, types)
    # Cards last: the pattern is the noisiest and we only run it on
    # long digit runs that survived everything above.
    out = _apply(out, _CARD_RE, CARD_REPLACEMENT, types)

    return RedactionResult(text=out, types=types)


__all__ = [
    "ACCOUNT_REPLACEMENT",
    "AADHAAR_REPLACEMENT",
    "CARD_REPLACEMENT",
    "EMAIL_REPLACEMENT",
    "GSTIN_REPLACEMENT",
    "PAN_REPLACEMENT",
    "PHONE_REPLACEMENT",
    "RedactionResult",
    "redact",
]
