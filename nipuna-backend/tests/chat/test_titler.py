"""Titler unit tests.

Pure function — no DB, no LLM. We test the contract: takes a
first-user-message, returns a 5-7 word title or None.
"""

from __future__ import annotations

from app.services.conversations.titler import (
    DEFAULT_MAX_WORDS,
    _capitalize_first,
    _normalize,
    _truncate_at_word_boundary,
    generate_title,
)


def test_simple_question():
    assert generate_title("What is our current cash position?") == "What is our current cash position"


def test_strips_trailing_punctuation():
    assert generate_title("Hello there!") == "Hello there"
    assert generate_title("Is this on?") == "Is this on"
    assert generate_title("Help me out....") == "Help me out"


def test_capitalizes_first_letter():
    out = generate_title("show me the top 5 customers")
    assert out is not None
    assert out[0].isupper()


def test_collapses_whitespace():
    assert generate_title("  What   is   the   cash   position  ") == "What is the cash position"


def test_unicode_normalize_fullwidth():
    # Fullwidth "hello" → ASCII "hello".
    out = generate_title("Ｈｅｌｌｏ")
    assert out is not None and out.lower() == "hello"


def test_empty_returns_none():
    assert generate_title("") is None
    assert generate_title(None) is None
    assert generate_title("   ") is None
    # Punctuation-only collapses to empty after the strip.
    assert generate_title("???") is None


def test_strips_surrounding_quotes():
    assert generate_title('"show me revenue"') == "Show me revenue"
    assert generate_title("'overdue invoices'") == "Overdue invoices"


def test_word_count_cap():
    text = " ".join(f"word{i}" for i in range(20))
    out = generate_title(text)
    assert out is not None
    assert len(out.split()) == DEFAULT_MAX_WORDS


def test_long_message_truncated_at_word_boundary():
    # Build a message that's > 240 chars.
    long = ("alpha " * 60).strip()
    out = generate_title(long)
    assert out is not None
    assert len(out) <= 240
    # No partial last word — should end on a complete word.
    assert not out.endswith("alph")  # not mid-word


def test_single_long_word_does_not_crash():
    long_word = "a" * 1000
    out = generate_title(long_word)
    # Truncation at the single word returns a long-but-non-empty
    # string. The LLM will still see a sensible-looking token.
    assert out is not None


def test_max_words_override():
    out = generate_title("a b c d e f g h i", max_words=3)
    assert out is not None
    assert out == "A b c"


def test_capitalize_first_helper():
    assert _capitalize_first("hello") == "Hello"
    assert _capitalize_first("") == ""


def test_normalize_strips_quotes_and_collapses_whitespace():
    assert _normalize('  "  hello   world  "  ') == "hello world"


def test_truncate_at_word_boundary_short_text():
    # No truncation needed.
    assert _truncate_at_word_boundary("hello world", 100) == "hello world"


def test_truncate_at_word_boundary_long_text():
    text = "the quick brown fox jumps over the lazy dog"
    out = _truncate_at_word_boundary(text, 20)
    # We cut at index 20, then rfind(" ") — should land on
    # "the quick brown" (15 chars, last space at 14) or similar.
    assert len(out) <= 20
    # No trailing partial word.
    assert out == out.rstrip()
