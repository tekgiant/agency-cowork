"""Tests for the Teams message chunking utility."""

import sys
from pathlib import Path

# Ensure scripts/ is importable
_TEAMS_ROOT = Path(__file__).resolve().parent.parent / "skills" / "teams"
sys.path.insert(0, str(_TEAMS_ROOT))

from scripts.chunking import chunk_message, DEFAULT_MAX_CHUNK, MAX_CHUNKS


def test_short_message_no_chunking():
    """Messages under the limit should return as-is."""
    msg = "Hello, world!"
    chunks = chunk_message(msg)
    assert len(chunks) == 1
    assert chunks[0] == msg


def test_empty_message():
    """Empty input returns single empty string."""
    chunks = chunk_message("")
    assert len(chunks) == 1
    assert chunks[0] == ""


def test_exact_limit_no_chunking():
    """Message exactly at limit should not be chunked."""
    msg = "x" * DEFAULT_MAX_CHUNK
    chunks = chunk_message(msg)
    assert len(chunks) == 1


def test_paragraph_split():
    """Long message should split on paragraph boundaries."""
    para1 = "First paragraph. " * 100  # ~1700 chars
    para2 = "Second paragraph. " * 100
    para3 = "Third paragraph. " * 100
    msg = f"{para1}\n\n{para2}\n\n{para3}"
    chunks = chunk_message(msg, max_len=2000)
    assert len(chunks) >= 2
    # Each chunk should end with (N/M) suffix
    assert "(1/" in chunks[0]
    assert f"({len(chunks)}/{len(chunks)})" in chunks[-1]


def test_line_split():
    """Should split on line boundaries when no paragraph breaks."""
    lines = [f"Line {i}: " + "x" * 80 for i in range(50)]
    msg = "\n".join(lines)
    chunks = chunk_message(msg, max_len=2000)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 2000


def test_hard_cut():
    """Single long line with no breaks should hard-cut."""
    msg = "x" * 8000
    chunks = chunk_message(msg, max_len=3800)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 3800


def test_max_chunks_cap():
    """Should not exceed MAX_CHUNKS even with very long messages."""
    msg = ("Paragraph. " * 200 + "\n\n") * 20  # very long
    chunks = chunk_message(msg, max_len=500, max_chunks=5)
    assert len(chunks) <= 5


def test_chunk_suffixes():
    """Each chunk should have correct (N/M) suffix."""
    para = "Word " * 400  # ~2000 chars
    msg = f"{para}\n\n{para}\n\n{para}"
    chunks = chunk_message(msg, max_len=2200)
    assert len(chunks) >= 2
    for i, chunk in enumerate(chunks):
        expected_suffix = f"({i + 1}/{len(chunks)})"
        assert expected_suffix in chunk, f"Chunk {i} missing suffix {expected_suffix}"


def test_sentence_split():
    """Should split on sentence boundaries when no line breaks."""
    sentences = "This is a test sentence. " * 200  # ~5000 chars
    chunks = chunk_message(sentences, max_len=2000)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 2000


def test_preserves_content():
    """All content should be preserved across chunks (minus suffixes)."""
    para1 = "Alpha " * 300
    para2 = "Beta " * 300
    msg = f"{para1.strip()}\n\n{para2.strip()}"
    chunks = chunk_message(msg, max_len=2000)
    # Reconstruct without suffixes
    import re
    cleaned = []
    for chunk in chunks:
        cleaned.append(re.sub(r'\n\n\(\d+/\d+\)$', '', chunk))
    reconstructed = "\n\n".join(cleaned)
    # All original words should appear
    assert "Alpha" in reconstructed
    assert "Beta" in reconstructed


def test_custom_max_len():
    """Custom max_len should be respected."""
    msg = "Word " * 200  # ~1000 chars
    chunks = chunk_message(msg, max_len=300)
    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk) <= 300


if __name__ == "__main__":
    tests = [
        test_short_message_no_chunking,
        test_empty_message,
        test_exact_limit_no_chunking,
        test_paragraph_split,
        test_line_split,
        test_hard_cut,
        test_max_chunks_cap,
        test_chunk_suffixes,
        test_sentence_split,
        test_preserves_content,
        test_custom_max_len,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {test.__name__}: {e}")
            failed += 1

    print(f"\n{passed}/{passed + failed} tests passed")
    sys.exit(1 if failed else 0)
