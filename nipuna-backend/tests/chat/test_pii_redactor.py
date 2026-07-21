"""PII redactor tests.

The redactor runs on every log line emitted from app/services/ai/*
and on the audit log. These tests pin the patterns so a future
refactor doesn't silently drop coverage.
"""

from __future__ import annotations

from app.services.audit.pii_redactor import redact


def test_pan_redacted():
    out = redact("My PAN is ABCDE1234F thanks")
    assert "[PAN]" in out.text
    assert "ABCDE1234F" not in out.text
    assert "PAN" in out.types


def test_aadhaar_requires_context_cue():
    # 4-4-4 digits with no cue are NOT redacted
    out = redact("Order number 1234 5678 9012 is pending")
    assert "1234 5678 9012" in out.text

    # With "Aadhaar:" cue, it IS
    out = redact("Aadhaar: 1234 5678 9012 is the customer id")
    assert "1234 5678 9012" not in out.text
    assert "[AADHAAR]" in out.text


def test_gstin_redacted():
    out = redact("Their GSTIN is 27ABCDE1234F1Z5")
    assert "27ABCDE1234F1Z5" not in out.text
    assert "[GSTIN]" in out.text


def test_indian_phone_redacted():
    out = redact("Call me on 9876543210")
    assert "9876543210" not in out.text
    assert "[PHONE]" in out.text


def test_email_redacted():
    out = redact("Reach me at john.doe@example.com please")
    assert "john.doe@example.com" not in out.text
    assert "[EMAIL]" in out.text


def test_redaction_is_idempotent():
    once = redact("My PAN is ABCDE1234F")
    twice = redact(once.text)
    assert once.text == twice.text


def test_redaction_handles_none_and_empty():
    assert redact(None).text == ""
    assert redact("").text == ""
    assert redact("no pii here").text == "no pii here"


def test_redaction_passes_through_normal_text():
    out = redact("The weather is great today, let's go for a walk")
    assert out.text == "The weather is great today, let's go for a walk"
    assert out.types == []
