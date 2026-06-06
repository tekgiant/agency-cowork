"""Message chunking for Teams long-message delivery.

Teams chat messages have a practical limit of ~28 KB, but messages over ~4000
characters render poorly in the Teams client (truncated preview, collapsed
body).  This module splits long messages into numbered chunks that are sent
as sequential messages, preserving readability.

Usage::

    from scripts.chunking import chunk_message

    chunks = chunk_message(text, max_len=3800)
    for chunk in chunks:
        await send(conversation_id, chunk)
"""

from __future__ import annotations

import re

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MAX_CHUNK = 3800  # per-chunk limit (leaves room for prefix/suffix)
MAX_CHUNKS = 8           # cap to prevent flooding a chat
CHUNK_OVERHEAD = 20      # reserved for " (1/N)" suffix + newline
INTER_CHUNK_DELAY = 0.3  # seconds between chunk sends (rate-limit safety)


def chunk_message(
    text: str,
    max_len: int = DEFAULT_MAX_CHUNK,
    *,
    max_chunks: int = MAX_CHUNKS,
) -> list[str]:
    """Split *text* into chunks that each fit within *max_len* characters.

    Splitting strategy (in priority order):
    1. Paragraph boundaries (``\\n\\n``)
    2. Line boundaries (``\\n``)
    3. Sentence boundaries (``. `` / ``! `` / ``? ``)
    4. Hard cut at *max_len* (last resort)

    Each chunk except the last gets a ``(1/N)`` suffix so the reader knows
    more messages are coming.  The last chunk gets ``(N/N)``.

    If the text fits in a single chunk, no suffix is added and the original
    text is returned as-is (single-element list).

    Returns:
        List of 1..max_chunks strings, each ≤ max_len characters.
    """
    if not text or not text.strip():
        return [""]

    # Fast path: fits in one message
    if len(text) <= max_len:
        return [text]

    usable = max_len - CHUNK_OVERHEAD
    if usable < 200:
        usable = max_len
        # Degenerate case — skip suffixes since there's no room
        raw_chunks = _split_on_boundaries(text, usable)
        if len(raw_chunks) > max_chunks:
            raw_chunks = raw_chunks[:max_chunks]
        return raw_chunks

    raw_chunks = _split_on_boundaries(text, usable)

    # Enforce max_chunks cap — merge trailing chunks into the last one
    if len(raw_chunks) > max_chunks:
        kept = raw_chunks[: max_chunks - 1]
        remainder = "\n\n".join(raw_chunks[max_chunks - 1 :])
        # Hard-truncate the overflow with ellipsis
        if len(remainder) > usable:
            remainder = remainder[: usable - 20] + "\n\n…(truncated)"
        kept.append(remainder)
        raw_chunks = kept

    # Single chunk after merging — return as-is
    if len(raw_chunks) == 1:
        return [raw_chunks[0]]

    # Add (N/M) suffixes
    total = len(raw_chunks)
    return [f"{chunk}\n\n({i + 1}/{total})" for i, chunk in enumerate(raw_chunks)]


def _split_on_boundaries(text: str, max_len: int) -> list[str]:
    """Recursively split text on the best available boundary."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        split_pos = _find_split_point(remaining, max_len)

        # Preserve paragraph/line boundary: keep one newline at the end of
        # the chunk instead of stripping all newlines at the boundary.
        if split_pos > 0 and remaining[split_pos - 1] == "\n":
            chunk = remaining[:split_pos]
            remaining = remaining[split_pos:].lstrip("\n")
        else:
            chunk = remaining[:split_pos].rstrip()
            remaining = remaining[split_pos:].lstrip("\n")

        if chunk:
            chunks.append(chunk)

        # Safety: if we couldn't advance, hard-cut to avoid infinite loop
        if not chunk and remaining:
            chunks.append(remaining[:max_len])
            remaining = remaining[max_len:]

    return chunks


def _find_split_point(text: str, max_len: int) -> int:
    """Find the best position to split *text* within *max_len* characters.

    Tries paragraph → line → sentence → hard cut.
    """
    window = text[:max_len]

    # 1. Paragraph boundary (\n\n)
    pos = window.rfind("\n\n")
    if pos > max_len // 4:  # don't split too early
        return pos + 1  # include one newline, strip the rest

    # 2. Line boundary (\n)
    pos = window.rfind("\n")
    if pos > max_len // 4:
        return pos + 1

    # 3. Sentence boundary (. ! ? followed by space or end)
    match = None
    for m in re.finditer(r'[.!?]\s', window):
        if m.end() > max_len // 4:
            match = m
    if match:
        return match.end()

    # 4. Word boundary (space)
    pos = window.rfind(" ")
    if pos > max_len // 4:
        return pos + 1

    # 5. Hard cut
    return max_len
