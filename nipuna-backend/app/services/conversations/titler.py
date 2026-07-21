"""Title generation for conversations.

PR4 ships *no LLM call* for titles. The first user message is truncated
to a 5-7 word noun-phrase, punctuation-stripped, and used as the
``Conversation.title``. The function is pure and synchronous — the
caller invokes it fire-and-forget after the user message is persisted.

Why no LLM?

  - Latency: a 200-400ms LLM call is a real fraction of the
    user-perceived response time for the first message of a
    conversation, and the title isn't worth holding the response for.
  - Cost: titles run once per new conversation; LLM costs are
    non-trivial at scale.
  - Quality: the first user message, truncated, is a good enough title
    for the sidebar. We can revisit when users complain.

The truncation algorithm:

  1. Strip leading/trailing whitespace and quotes.
  2. Replace any unicode whitespace with a single space.
  3. Drop trailing question marks / periods / exclamations.
  4. Take the first ``max_words`` words.
  5. Capitalize the first letter.
  6. If the result is empty, return ``None`` (the column stays NULL).

A title longer than the DB column (255 chars) is truncated at the
nearest word boundary.
"""

from __future__ import annotations

import re
import unicodedata

# Max number of words in a generated title. 5-7 is the user-facing
# sweet spot — long enough to be informative, short enough to fit a
# sidebar without truncation.
DEFAULT_MAX_WORDS = 7

# Drop trailing punctuation that turns a noun-phrase into a question
# or statement — titles read better without them.
_TRAILING_PUNCT = re.compile(r"[\?\!\.,;:]+$")

# Collapse any whitespace (incl. NBSP, tabs, newlines) to a single
# ASCII space. Use the ``re.UNICODE`` flag so the \s class matches
# the full unicode whitespace set.
_WHITESPACE = re.compile(r"\s+", re.UNICODE)

# Word boundary: a run of non-whitespace characters. Doesn't try to
# handle hyphenation specifically — "cash-flow" is one word, which is
# what we want.
_WORDS = re.compile(r"\S+", re.UNICODE)

# Cap for the title length. ``Conversation.title`` is VARCHAR(255) in
# the migration; anything longer gets truncated at a word boundary.
_MAX_TITLE_CHARS = 240  # leave headroom for word-boundary rounding


def _normalize(text: str) -> str:
    """Normalize unicode and collapse whitespace."""
    # NFKC form turns full-width characters into their ASCII cousins
    # so "ＨＥＬＬＯ" becomes "HELLO" before we count words.
    text = unicodedata.normalize("NFKC", text).strip()
    # Strip a single layer of surrounding quotes — common in
    # conversational messages where the user types "".
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1].strip()
    return _WHITESPACE.sub(" ", text)


def _capitalize_first(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _truncate_at_word_boundary(text: str, max_chars: int) -> str:
    """Truncate ``text`` to at most ``max_chars`` chars, never splitting
    a word in half. If the cut would land mid-word, the cut moves back
    to the last whitespace before it.
    """
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    last_space = cut.rfind(" ")
    if last_space > 0:
        return cut[:last_space]
    return cut  # single long word — best-effort, no whitespace to break on


def generate_title(
    first_user_message: str | None,
    *,
    max_words: int = DEFAULT_MAX_WORDS,
    max_chars: int = _MAX_TITLE_CHARS,
) -> str | None:
    """Return a 5-7 word title derived from the first user message, or
    ``None`` if the message is empty or too short to be useful.

    Pure function. No DB, no LLM.
    """
    if not first_user_message:
        return None

    text = _normalize(first_user_message)
    if not text:
        return None

    # Drop a single layer of trailing punctuation (a question mark,
    # period, etc). We don't recurse — a message that ends with "???"
    # after one strip becomes the same as the un-punctuated form.
    text = _TRAILING_PUNCT.sub("", text).strip()
    if not text:
        return None

    words = _WORDS.findall(text)
    if not words:
        return None

    title_words = words[:max_words]
    title = " ".join(title_words)
    title = _truncate_at_word_boundary(title, max_chars)
    return _capitalize_first(title)


__all__ = ["DEFAULT_MAX_WORDS", "generate_title"]
