"""Shared utility helpers for Teams Rich Messaging.

Includes conversation-ID helpers, @mention builders, Markdown-to-HTML
conversion, Adaptive Card builders, file-attachment metadata builders,
and the full message-body constructor.
"""

from __future__ import annotations

import json
import mimetypes
import os as _os
import random
import re
import string
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Conversation-ID helpers
# ---------------------------------------------------------------------------


def build_1on1_conversation_id(user1_guid: str, user2_guid: str) -> str:
    """Build a 1:1 conversation ID from two user GUIDs.

    Teams sorts the two GUIDs alphabetically to form a deterministic
    conversation identifier.

    Args:
        user1_guid: First user's object-id GUID (without the ``8:orgid:`` prefix).
        user2_guid: Second user's object-id GUID.

    Returns:
        Conversation ID in the format ``19:{sorted1}_{sorted2}@unq.gbl.spaces``.
    """
    sorted_guids = sorted([user1_guid.lower(), user2_guid.lower()])
    return f"19:{sorted_guids[0]}_{sorted_guids[1]}@unq.gbl.spaces"


def encode_conversation_id(conv_id: str) -> str:
    """URL-encode a conversation ID for use in API URL paths.

    Args:
        conv_id: Raw conversation ID (e.g. ``19:abc_def@unq.gbl.spaces``).

    Returns:
        URL-encoded string safe for inclusion in a URL path segment.
    """
    return quote(conv_id, safe="")


def generate_client_message_id() -> str:
    """Generate a random 19-digit numeric string used as ``clientmessageid``.

    Teams uses large numeric IDs to deduplicate messages on the client side.
    """
    first = random.choice(string.digits[1:])  # avoid leading zero
    rest = "".join(random.choices(string.digits, k=18))
    return first + rest


def utc_iso_now() -> str:
    """Return the current UTC time in ISO 8601 format with milliseconds.

    Example: ``2026-03-01T17:20:12.499Z``
    """
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def extract_guid_from_mri(mri: str) -> str:
    """Extract the bare GUID from an MRI string.

    ``"8:orgid:88d97a83-..."`` → ``"88d97a83-..."``
    """
    parts = mri.split(":")
    return parts[-1] if parts else mri


# ---------------------------------------------------------------------------
# @mention helpers
# ---------------------------------------------------------------------------


def build_mention_html(display_name: str, item_id: int) -> str:
    """Build the HTML element for an @mention inside message content.

    The mention is wrapped in a ``<readonly>`` tag (with ``skipProofing``
    and ``spellcheck="false"``) around the inner ``<span>``.  This matches
    the exact HTML structure the Teams web client emits when a user types
    an @mention.

    Args:
        display_name: The person's display name (e.g. ``"Alice Johnson"``).
        item_id: Zero-based index matching the entry in the mentions property array.

    Returns:
        An HTML string matching the Teams @mention format.
    """
    return (
        f'<readonly class="skipProofing" spellcheck="false" '
        f'itemtype="http://schema.skype.com/Mention">'
        f'<span itemtype="http://schema.skype.com/Mention" '
        f'itemscope itemid="{item_id}">{display_name}</span>'
        f'</readonly>'
    )


def build_mention_property(display_name: str, mri: str, item_id: int) -> dict:
    """Build the mention metadata dict for the ``properties.mentions`` array.

    Args:
        display_name: Display name of the mentioned person.
        mri: The user's MRI (e.g. ``8:orgid:<guid>``).
        item_id: Zero-based index matching the ``itemid`` in the HTML span.

    Returns:
        A dict matching the Teams mention schema.
    """
    return {
        "@type": "http://schema.skype.com/Mention",
        "itemid": item_id,
        "mri": mri,
        "mentionType": "person",
        "displayName": display_name,
    }


# ---------------------------------------------------------------------------
# Teams Emoji support
# ---------------------------------------------------------------------------

# CDN base for Teams animated emoticons (20px static variant)
_EMOJI_CDN = "https://statics.teams.cdn.office.net/evergreen-assets/personal-expressions/v2/assets/emoticons"

# Mapping of common shortcodes → (teams_id, title, alt_unicode).
# Supports both :github_style: and (teams_style) shortcodes.
# For the full catalog see TEAMS-EMOJIS.md alongside this skill's SKILL.md.
EMOJI_MAP: dict[str, tuple[str, str, str]] = {
    # --- Faces & expressions ---
    # IDs verified against Teams CDN (HAR-extracted catalog)
    "smile": ("smile", "Smile", "😊"),
    "happy": ("happyface", "Happy face", "😀"),
    "laugh": ("laugh", "Laughing", "😄"),
    "grinning": ("laugh", "Laughing", "😄"),
    "grin": ("grinningfacewithsmilingeyes", "Grinning face with smiling eyes", "😁"),
    "wink": ("wink", "Wink", "😉"),
    "blush": ("blush", "Blush", "😊"),
    "heart_eyes": ("inlove", "In love", "😍"),
    "cool": ("cool", "Cool", "😎"),
    "sunglasses": ("cool", "Cool", "😎"),
    "surprised": ("surprised", "Surprised", "😮"),
    "thinking": ("mmm", "Thinking", "🤔"),
    "mmm": ("mmm", "Thinking", "🤔"),
    "nerd": ("nerdy", "Nerdy", "🤓"),
    "nerd_face": ("nerdy", "Nerdy", "🤓"),
    "sad": ("sad", "Sad", "😢"),
    "cry": ("sad", "Sad", "😢"),
    "angry": ("angryface", "Angry", "😠"),
    "pensive": ("pensive", "Pensive", "😔"),
    "confused": ("confused", "Confused", "😕"),
    "expressionless": ("expressionless", "Expressionless", "😑"),
    "sleepy": ("sleepy", "Sleepy", "😴"),
    "puke": ("puke", "Puke", "🤮"),
    "skull": ("skull", "Skull", "💀"),
    "ghost": ("ghost", "Ghost", "👻"),
    "devil": ("devil", "Devil", "😈"),
    "angel": ("angel", "Angel", "😇"),
    "shrug": ("shrug", "Shrug", "🤷"),
    "facepalm": ("facepalm", "Facepalm", "🤦"),
    "salute": ("salute", "Salute", "🫡"),
    "melting": ("meltingface", "Melting face", "🫠"),
    # --- Hand gestures ---
    "thumbsup": ("yes", "Yes", "👍"),
    "+1": ("yes", "Yes", "👍"),
    "like": ("like", "Like", "👍"),
    "yes": ("yes", "Yes", "👍"),
    "thumbsdown": ("no", "No", "👎"),
    "-1": ("no", "No", "👎"),
    "no": ("no", "No", "👎"),
    "clap": ("clap", "Clap", "👏"),
    "muscle": ("muscle", "Muscle", "💪"),
    "pray": ("praying", "Praying", "🙏"),
    "praying": ("praying", "Praying", "🙏"),
    "wave": ("hi", "Hi", "👋"),
    "hi": ("hi", "Hi", "👋"),
    "handshake": ("handshake", "Handshake", "🤝"),
    "ok_hand": ("ok", "OK", "👌"),
    "victory": ("victory", "Victory", "✌️"),
    "punch": ("punch", "Punch", "👊"),
    "point_up": ("pointupindex", "Point up", "☝️"),
    "vulcan": ("vulcansalute", "Vulcan salute", "🖖"),
    "heart_hands": ("hearthands", "Heart hands", "🫶"),
    "finger_heart": ("fingerheart", "Finger heart", "🫰"),
    # --- Hearts & love ---
    "heart": ("heart", "Heart", "❤️"),
    "red_heart": ("heart", "Heart", "❤️"),
    "broken_heart": ("brokenheart", "Broken heart", "💔"),
    "sparkling_heart": ("sparklingheart", "Sparkling heart", "💖"),
    "two_hearts": ("twohearts", "Two hearts", "💕"),
    "growing_heart": ("growingheart", "Growing heart", "💗"),
    "heart_on_fire": ("heartonfire", "Heart on fire", "❤️‍🔥"),
    "rainbow_heart": ("rainbowheart2", "Rainbow heart", "🏳️‍🌈"),
    # --- Objects & symbols ---
    "rocket": ("launch", "Rocket launch", "🚀"),
    "launch": ("launch", "Rocket launch", "🚀"),
    "star": ("star", "Star", "⭐"),
    "sparkles": ("sparkler", "Sparkler", "✨"),
    "trophy": ("trophy", "Trophy", "🏆"),
    "medal": ("goldmedal", "Gold medal", "🥇"),
    "gold_medal": ("goldmedal", "Gold medal", "🥇"),
    "target": ("target", "Target", "🎯"),
    "dart": ("target", "Target", "🎯"),
    "bulb": ("idea", "Idea", "💡"),
    "idea": ("idea", "Idea", "💡"),
    "light_bulb": ("idea", "Idea", "💡"),
    "bell": ("bell", "Bell", "🔔"),
    "gift": ("gift", "Gift", "🎁"),
    "bomb": ("bomb", "Bomb", "💣"),
    "key": ("oldkey", "Key", "🔑"),
    "camera": ("camera", "Camera", "📷"),
    "phone": ("phone", "Phone", "📱"),
    "computer": ("computer", "Computer", "💻"),
    "headphones": ("headphones", "Headphones", "🎧"),
    "money": ("cash", "Cash", "💰"),
    "cash": ("cash", "Cash", "💰"),
    "recycle": ("recycle", "Recycle", "♻️"),
    "magic_wand": ("magicwand", "Magic wand", "🪄"),
    # Unicode-based IDs (verified via CDN, format: {codepoint}_{name})
    "brain": ("1f9e0_brain", "Brain", "🧠"),
    "lock": ("1f512_locked", "Locked", "🔒"),
    "link": ("1f517_linksymbol", "Link", "🔗"),
    "chain": ("1f517_linksymbol", "Link", "🔗"),
    "gear": ("2699_gear", "Gear", "⚙️"),
    "wrench": ("1f527_wrench", "Wrench", "🔧"),
    "hammer": ("1f528_hammer", "Hammer", "🔨"),
    "shield": ("1f6e1_shield", "Shield", "🛡️"),
    "crystal_ball": ("1f52e_crystalball", "Crystal ball", "🔮"),
    "plug": ("1f50c_electricplug", "Electric plug", "🔌"),
    "electric_plug": ("1f50c_electricplug", "Electric plug", "🔌"),
    "zap": ("26a1_highvoltagesign", "High voltage", "⚡"),
    "electric": ("26a1_highvoltagesign", "High voltage", "⚡"),
    "lightning": ("26a1_highvoltagesign", "High voltage", "⚡"),
    "balloon": ("1f388_balloon", "Balloon", "🎈"),
    "alien": ("1f47d_extraterrestrialalien", "Alien", "👽"),
    "eagle": ("1f985_eagle", "Eagle", "🦅"),
    "globe": ("1f30d_earthglobeeuropeafrica", "Globe", "🌍"),
    "world": ("1f30d_earthglobeeuropeafrica", "Globe", "🌍"),
    "warning": ("26a0_warningsign", "Warning", "⚠️"),
    "construction": ("1f6a7_constructionsign", "Construction", "🚧"),
    "building_construction": ("1f6a7_constructionsign", "Construction", "🚧"),
    "hourglass": ("231b_hourglassdone", "Hourglass", "⏳"),
    "arrow_right": ("27a1_blackrightwardsarrow", "Right arrow", "➡️"),
    # --- Communication & documents (unicode-based) ---
    "email": ("loveletter", "Letter", "💌"),
    "envelope": ("loveletter", "Letter", "💌"),
    "memo": ("1f4dd_memo", "Memo", "📝"),
    "pencil": ("270f_pencil", "Pencil", "✏️"),
    "writing_hand": ("270d_writinghand", "Writing hand", "✍️"),
    "clipboard": ("1f4cb_clipboard", "Clipboard", "📋"),
    "book": ("1f4d3_notebook", "Notebook", "📓"),
    "calendar": ("spiralcalendar", "Calendar", "📅"),
    "date": ("spiralcalendar", "Calendar", "📅"),
    "chart": ("1f4ca_barchart", "Bar chart", "📊"),
    "bar_chart": ("1f4ca_barchart", "Bar chart", "📊"),
    "speech_bubble": ("speechbubble", "Speech bubble", "💬"),
    "file_folder": ("1f4c1_filefolder", "File folder", "📁"),
    "floppy_disk": ("50th_floppy", "Floppy disk", "💾"),
    "mag": ("1f50d_magnifiertiltedleft", "Magnifying glass", "🔍"),
    "search": ("1f50d_magnifiertiltedleft", "Magnifying glass", "🔍"),
    # --- Status indicators ---
    "check": ("2705_whiteheavycheckmark", "Check mark", "✅"),
    "white_check_mark": ("2705_whiteheavycheckmark", "Check mark", "✅"),
    "x": ("274c_crossmark", "Cross mark", "❌"),
    "cross": ("274c_crossmark", "Cross mark", "❌"),
    "stop": ("stopsign", "Stop sign", "🛑"),
    # --- Celebration ---
    "tada": ("fireworks", "Fireworks", "🎉"),
    "party": ("fireworks", "Fireworks", "🎉"),
    "fireworks": ("fireworks", "Fireworks", "🎉"),
    "confetti": ("fireworks", "Fireworks", "🎉"),
    "champagne": ("champagne", "Champagne", "🍾"),
    "cheers": ("cheers", "Cheers", "🍻"),
    "cake": ("cake", "Cake", "🎂"),
    # --- Nature & weather ---
    "sun": ("sun", "Sun", "☀️"),
    "rainbow": ("rainbow", "Rainbow", "🌈"),
    "snowflake": ("snowflake", "Snowflake", "❄️"),
    "rain": ("rain", "Rain", "🌧️"),
    "flower": ("flower", "Flower", "🌸"),
    "rose": ("rose", "Rose", "🌹"),
    "tree": ("deciduoustree", "Tree", "🌳"),
    "cactus": ("cactus", "Cactus", "🌵"),
    # --- Animals ---
    "dog": ("dog", "Dog", "🐶"),
    "cat": ("cat", "Cat", "🐱"),
    "monkey": ("monkey", "Monkey", "🐵"),
    "penguin": ("penguin", "Penguin", "🐧"),
    "unicorn": ("unicornhead", "Unicorn", "🦄"),
    "butterfly": ("butterfly", "Butterfly", "🦋"),
    "bee": ("bee", "Bee", "🐝"),
    "snake": ("snake", "Snake", "🐍"),
    # --- Food & drink ---
    "coffee": ("coffee", "Coffee", "☕"),
    "pizza": ("pizzaslice", "Pizza", "🍕"),
    "burger": ("burger", "Burger", "🍔"),
    "fries": ("fries", "Fries", "🍟"),
    "beer": ("beer", "Beer", "🍺"),
    "wine": ("redwine", "Wine", "🍷"),
    "tea": ("chai", "Tea", "🍵"),
    "cookie": ("cookies", "Cookie", "🍪"),
    "avocado": ("avocadolove", "Avocado", "🥑"),
    # --- Activities ---
    "running": ("running", "Running", "🏃"),
    "dance": ("dance", "Dancing", "💃"),
    "yoga": ("yoga", "Yoga", "🧘"),
    "bike": ("bike", "Bike", "🚲"),
    # --- Misc popular ---
    "robot": ("coolrobot", "Robot", "🤖"),
    "ninja": ("ninja", "Ninja", "🥷"),
    "detective": ("detective", "Detective", "🕵️"),
    "battery": ("lowbattery", "Low battery", "🪫"),
    "wifi": ("wifi", "WiFi", "📶"),
}


def build_emoji_html(emoji_id: str, title: str, alt: str) -> str:
    """Build the HTML element for a Teams emoji.

    Uses the exact format the Teams web client emits — a ``<span>`` wrapper
    with ``contenteditable="false"`` around an ``<img>`` pointing to the
    Teams CDN.

    Args:
        emoji_id: The Teams emoticon ID (e.g. ``"launch"``, ``"cool"``).
        title: Human-readable title (e.g. ``"Rocket launch"``).
        alt: Unicode fallback character(s) (e.g. ``"🚀"``).

    Returns:
        HTML string matching the Teams emoji format.
    """
    return (
        f'<span contenteditable="false" title="{title}" type="({emoji_id})" '
        f'class="animated-emoticon-20-{emoji_id}" itemscope>'
        f'<img itemscope itemtype="http://schema.skype.com/Emoji" '
        f'itemid="{emoji_id}" '
        f'src="{_EMOJI_CDN}/{emoji_id}/default/20_f.png" '
        f'title="{title}" alt="{alt}" style="width:20px;height:20px;">'
        f'</span>'
    )


def _replace_emoji_shortcodes(html: str) -> str:
    """Replace ``:shortcode:`` emoji markers with Teams emoji HTML.

    Recognises both ``:name:`` (GitHub/Slack style) and ``(name)``
    (Teams/Skype native style).  Unknown shortcodes are left as-is.

    The ``:name:`` pass runs first and its output is stashed so that the
    ``(name)`` pass does not re-match ``type="(id)"`` inside generated HTML.
    """
    stash: list[str] = []

    def _stash(emoji_html: str) -> str:
        stash.append(emoji_html)
        return f"\x00EMOJI{len(stash) - 1}\x00"

    def _repl_colon(m: re.Match) -> str:
        name = m.group(1).lower()
        entry = EMOJI_MAP.get(name)
        if entry:
            return _stash(build_emoji_html(*entry))
        return m.group(0)  # leave unknown shortcodes as-is

    def _repl_parens(m: re.Match) -> str:
        name = m.group(1).lower()
        entry = EMOJI_MAP.get(name)
        if entry:
            return _stash(build_emoji_html(*entry))
        return m.group(0)

    # :shortcode: syntax (GitHub/Slack style) — process first
    html = re.sub(r":([a-zA-Z0-9_+-]+):", _repl_colon, html)
    # (shortcode) syntax (Teams/Skype native) — only at word boundary,
    # not inside HTML attributes (avoid matching type="(xxx)")
    html = re.sub(r'(?<![="\\])\(([a-zA-Z0-9_]+)\)', _repl_parens, html)

    # Restore stashed emoji HTML
    for i, emoji_html in enumerate(stash):
        html = html.replace(f"\x00EMOJI{i}\x00", emoji_html)

    return html


def _convert_markdown_table(html: str) -> str:
    """Convert Markdown table syntax to Teams-compatible HTML tables.

    Teams requires ``<figure class="table"><table class="copy-paste-table">``
    wrapping.  The header row (before the ``|---|`` separator) is rendered
    with ``<strong>`` tags.

    Args:
        html: Text potentially containing Markdown table syntax.

    Returns:
        Text with Markdown tables replaced by Teams HTML tables.
    """
    lines = html.split("\n")
    result: list[str] = []
    table_lines: list[str] = []
    in_table = False

    def _flush_table() -> None:
        """Convert accumulated table_lines into HTML and append to result."""
        if not table_lines:
            return
        # Find the separator row (|---|---|)
        sep_idx = -1
        for i, tl in enumerate(table_lines):
            if re.match(r"^\|[\s\-:|]+\|$", tl.strip()):
                sep_idx = i
                break

        header_rows = table_lines[:sep_idx] if sep_idx > 0 else []
        body_rows = table_lines[sep_idx + 1:] if sep_idx >= 0 else table_lines

        rows_html: list[str] = []
        for row_line in header_rows:
            cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
            cells_html = "".join(f"<td><strong>{c}</strong></td>" for c in cells)
            rows_html.append(f"<tr>{cells_html}</tr>")

        for row_line in body_rows:
            cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
            cells_html = "".join(f"<td>{c}</td>" for c in cells)
            rows_html.append(f"<tr>{cells_html}</tr>")

        table_html = (
            '<figure class="table"><table class="copy-paste-table"><tbody>'
            + "".join(rows_html)
            + "</tbody></table></figure>"
        )
        result.append(table_html)
        table_lines.clear()

    for line in lines:
        stripped = line.strip()
        # A table row starts and ends with |
        if re.match(r"^\|.+\|$", stripped):
            in_table = True
            table_lines.append(stripped)
        else:
            if in_table:
                _flush_table()
                in_table = False
            result.append(line)

    if in_table:
        _flush_table()

    return "\n".join(result)


# ---------------------------------------------------------------------------
# Markdown → Teams HTML converter
# ---------------------------------------------------------------------------

def markdown_to_teams_html(text: str) -> str:
    """Convert common Markdown formatting to Teams-compatible HTML.

    Supported syntax:
      - ``# Heading 1`` through ``###### Heading 6`` → ``<h1>``–``<h6>``
      - ``**bold**`` / ``__bold__``     → ``<b>bold</b>``
      - ``*italic*`` / ``_italic_``     → ``<i>italic</i>``
      - ``~~strikethrough~~``           → ``<s>strikethrough</s>``
      - ``[text](url)``                 → ``<a href="url">text</a>``
      - ``\\n- item`` (unordered list)  → ``<ul><li>item</li></ul>``
      - ``\\n1. item`` (ordered list)   → ``<ol><li>item</li></ol>``
      - `` `code` ``                    → ``<code>code</code>``
      - triple-backtick code blocks     → ``<pre>code</pre>``
      - ``> blockquote``               → ``<blockquote>text</blockquote>``
      - ``---``                         → ``<hr/>``
      - ``:emoji:`` / ``(emoji)``       → Teams animated emoji HTML
      - ``| col | col |`` tables        → ``<figure><table>`` HTML
      - Newlines                        → ``<br/>``

    The result is wrapped in ``<p>`` tags (Teams' expected container).

    Args:
        text: Markdown-formatted string.

    Returns:
        HTML string wrapped in ``<p>`` tags.
    """
    if not text:
        return "<p></p>"

    html = text

    # ── Code blocks (``` ... ```) — process first to protect contents ─
    code_blocks: list[str] = []

    def _stash_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1).strip())
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    html = re.sub(r"```(?:\w*)\n?([\s\S]*?)```", _stash_code_block, html)

    # ── Inline code (`...`) — stash to protect contents ──────────────
    inline_codes: list[str] = []

    def _stash_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    html = re.sub(r"`([^`]+)`", _stash_inline_code, html)

    # ── Markdown tables → Teams HTML tables ──────────────────────────
    html = _convert_markdown_table(html)

    # ── Horizontal rules ─────────────────────────────────────────────
    html = re.sub(r"^---+$", "<hr/>", html, flags=re.MULTILINE)

    # ── Headings: # H1, ## H2, ... ###### H6 ─────────────────────────
    html = re.sub(r"^######\s+(.+)$", r"<h6>\1</h6>", html, flags=re.MULTILINE)
    html = re.sub(r"^#####\s+(.+)$", r"<h5>\1</h5>", html, flags=re.MULTILINE)
    html = re.sub(r"^####\s+(.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^###\s+(.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^##\s+(.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^#\s+(.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)

    # ── Bold: **text** or __text__ ───────────────────────────────────
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html)
    html = re.sub(r"__(.+?)__", r"<b>\1</b>", html)

    # ── Italic: *text* or _text_ (careful not to match inside words) ─
    html = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", html)
    html = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", html)

    # ── Strikethrough: ~~text~~ ──────────────────────────────────────
    html = re.sub(r"~~(.+?)~~", r"<s>\1</s>", html)

    # ── Links: [text](url) ───────────────────────────────────────────
    html = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', html)

    # ── Bare URLs → clickable links (only if not already inside <a>) ─
    html = re.sub(
        r'(?<!href=")(?<!">)(https?://[^\s<>")\]]+)',
        r'<a href="\1">\1</a>',
        html,
    )

    # ── Blockquotes: > text ──────────────────────────────────────────
    bq_lines: list[str] = []
    out_lines: list[str] = []
    for line in html.split("\n"):
        stripped = line.strip()
        if stripped.startswith("> "):
            bq_lines.append(stripped[2:])
        else:
            if bq_lines:
                out_lines.append(
                    "<blockquote>" + "<br/>".join(bq_lines) + "</blockquote>"
                )
                bq_lines = []
            out_lines.append(line)
    if bq_lines:
        out_lines.append(
            "<blockquote>" + "<br/>".join(bq_lines) + "</blockquote>"
        )
    html = "\n".join(out_lines)

    # ── Unordered lists: lines starting with "- " ────────────────────
    html = _convert_list(html, r"^- (.+)$", "ul")

    # ── Ordered lists: lines starting with "1. ", "2. ", etc. ────────
    html = _convert_list(html, r"^\d+\.\s+(.+)$", "ol")

    # ── Restore inline code ──────────────────────────────────────────
    for i, code in enumerate(inline_codes):
        html = html.replace(f"\x00INLINE{i}\x00", f"<code>{code}</code>")

    # ── Restore code blocks ──────────────────────────────────────────
    for i, code in enumerate(code_blocks):
        html = html.replace(f"\x00CODEBLOCK{i}\x00", f"<pre>{code}</pre>")

    # ── Newlines → <br/> (but not around block-level elements) ───────
    html = re.sub(r"\n(?!<)", "<br/>", html)
    html = re.sub(r"(</h[1-6]>)<br/>", r"\1", html)

    # ── Emoji shortcodes → Teams emoji HTML ──────────────────────────
    html = _replace_emoji_shortcodes(html)

    # Wrap in <p> if not already
    html = html.strip()
    if not html.startswith("<p>"):
        html = f"<p>{html}</p>"

    return html


def _convert_list(html: str, pattern: str, tag: str) -> str:
    """Convert consecutive lines matching ``pattern`` into an HTML list."""
    lines = html.split("\n")
    result: list[str] = []
    in_list = False
    for line in lines:
        m = re.match(pattern, line.strip())
        if m:
            if not in_list:
                result.append(f"<{tag}>")
                in_list = True
            result.append(f"<li>{m.group(1)}</li>")
        else:
            if in_list:
                result.append(f"</{tag}>")
                in_list = False
            result.append(line)
    if in_list:
        result.append(f"</{tag}>")
    return "\n".join(result)


# ---------------------------------------------------------------------------
# Adaptive Card helpers
# ---------------------------------------------------------------------------

# Directory containing card JSON templates (skills/teams/templates/)
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"


def build_adaptive_card(
    body_elements: list[dict],
    *,
    actions: list[dict] | None = None,
    version: str = "1.4",
) -> dict:
    """Build a single Adaptive Card envelope ready for ``properties.cards``.

    Args:
        body_elements: List of Adaptive Card body elements (TextBlock,
            ColumnSet, Image, etc.).
        actions: Optional list of Action elements (Action.OpenUrl,
            Action.Submit, etc.).
        version: Adaptive Card schema version (default ``"1.4"``).

    Returns:
        A dict with ``cardId`` and ``card`` keys, suitable for inclusion
        in the ``properties.cards`` array of a Teams message.
    """
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": version,
        "body": body_elements,
    }
    if actions:
        card["actions"] = actions

    return {
        "cardId": str(uuid.uuid4()),
        "card": card,
    }


def build_card_from_template(
    template_name: str,
    data: dict[str, str],
) -> dict:
    """Load an Adaptive Card template and fill in ``{{variable}}`` placeholders.

    Templates live in the ``templates/`` directory at the project root.

    Args:
        template_name: Filename (without ``.json``) of the template
            (e.g. ``"info-card"``).
        data: Key-value pairs to substitute into ``{{key}}`` placeholders.

    Returns:
        A filled card envelope dict (same shape as ``build_adaptive_card``).

    Raises:
        FileNotFoundError: If the template file does not exist.
    """
    template_path = _TEMPLATES_DIR / f"{template_name}.json"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Card template not found: {template_path}\n"
            f"Available templates: {', '.join(t.stem for t in _TEMPLATES_DIR.glob('*.json'))}"
        )

    raw = template_path.read_text(encoding="utf-8")

    # Replace all {{key}} placeholders
    for key, value in data.items():
        # Escape the value for safe JSON embedding
        escaped = json.dumps(value)[1:-1]  # strip surrounding quotes
        raw = raw.replace("{{" + key + "}}", escaped)

    card = json.loads(raw)

    return {
        "cardId": str(uuid.uuid4()),
        "card": card,
    }


# ---------------------------------------------------------------------------
# File-attachment metadata builders
# ---------------------------------------------------------------------------

# AMS (Azure Media Service) endpoint — used for image preview hosting
AMS_BASE = "https://us-prod.asyncgw.teams.microsoft.com"


def detect_ams_content_type(filename: str) -> str:
    """Return the AMS ``type`` value and upload view name for a file.

    AMS uses its own content-type scheme (``pish/image``, ``sharing/file``).

    Returns:
        Tuple of (ams_type, view_name).
    """
    ext = Path(filename).suffix.lower()
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic"}
    if ext in image_exts:
        return "pish/image"
    return "sharing/file"


def detect_ams_view_name(filename: str) -> str:
    """Return the AMS view name for uploading file content."""
    ext = Path(filename).suffix.lower()
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic"}
    if ext in image_exts:
        return "imgpsh"
    return "original"


def build_file_property(
    *,
    filename: str,
    spo_item: dict,
    ams_id: str,
    conversation_id: str,
) -> dict:
    """Build a single entry for the ``properties.files`` array.

    Stitches together metadata from the SharePoint upload response and the
    AMS object ID to produce the file chiclet metadata that Teams expects.

    Args:
        filename: Original file name.
        spo_item: The full JSON response from the SharePoint PUT upload.
        ams_id: The AMS object ID (e.g. ``0-wus-d9-...``).
        conversation_id: The conversation this file is being sent to.

    Returns:
        A dict matching the Teams file property schema.
    """
    ext = Path(filename).suffix.lstrip(".")
    sp_ids = spo_item.get("sharepointIds", {})
    item_id = sp_ids.get("listItemUniqueId", str(uuid.uuid4()))
    site_id = sp_ids.get("siteId", "")
    site_url = sp_ids.get("siteUrl", "")
    web_id = sp_ids.get("webId", "")
    object_url = spo_item.get("webUrl", "")
    size = spo_item.get("size", 0)

    # Determine service name from conversation type
    if conversation_id.startswith("48:notes"):
        service_name = "p2p"
    elif conversation_id.startswith("19:") and "@thread" in conversation_id:
        service_name = "teams"
    else:
        service_name = "p2p"

    # Build preview URL if this is an image
    preview_info = {}
    image = spo_item.get("image")
    if image is not None:  # SharePoint returns {} for images
        preview_info = {
            "previewUrl": f"https://us-api.asm.skype.com/v1/objects/{ams_id}/views/imgo",
        }

    file_prop: dict = {
        "itemid": item_id,
        "fileName": filename,
        "fileType": ext,
        "fileInfo": {
            "itemId": None,
            "fileUrl": object_url,
            "siteUrl": site_url + "/",
            "serverRelativeUrl": "",
            "shareUrl": None,
            "shareId": None,
        },
        "fileChicletState": {
            "serviceName": service_name,
            "state": "active",
        },
        "@type": "http://schema.skype.com/File",
        "version": 2,
        "id": item_id,
        "baseUrl": site_url + "/",
        "objectUrl": object_url,
        "type": ext,
        "title": filename,
        "state": "active",
        "chicletBreadcrumbs": None,
        "providerData": "",
        "botFileProperties": {},
        "isUploadError": None,
        "progressComplete": None,
        "permissionScope": "organization",
        "sharepointIds": {
            "listId": None,
            "listItemUniqueId": item_id,
            "siteId": site_id,
            "siteUrl": None,
            "webId": None,
        },
        "publication": None,
        "site": None,
    }

    if preview_info:
        file_prop["filePreview"] = preview_info

    return file_prop


def build_file_property_reference(
    *,
    filename: str,
    spo_item: dict,
    conversation_id: str,
) -> dict:
    """Build a file property entry for an *existing* SharePoint/OneDrive file.

    Unlike ``build_file_property`` (which is for freshly-uploaded files with
    AMS references), this variant creates a "reference" chiclet that points to
    a file already stored in SharePoint — no upload or AMS step is needed.

    The Shares API ``driveItem`` response provides most of the metadata.  The
    ``siteUrl`` from ``sharepointIds`` is used to derive both ``baseUrl`` and
    the ``chicletBreadcrumbs`` (team/channel or personal-site path segments).

    Args:
        filename: Display file name (e.g. ``Cat.jpg``).
        spo_item: The raw JSON ``driveItem`` returned by the Shares API
            (``/_api/v2.0/shares/u!.../driveItem``).
        conversation_id: The conversation this file will be sent to.

    Returns:
        A dict matching the Teams *reference* file property schema.
    """
    ext = Path(filename).suffix.lstrip(".")
    sp_ids = spo_item.get("sharepointIds", {})
    item_id = sp_ids.get("listItemUniqueId", str(uuid.uuid4()))
    site_id = sp_ids.get("siteId", "")
    site_url = sp_ids.get("siteUrl", "")

    # Reconstruct the full file URL from siteUrl + parent path + filename
    parent_ref = spo_item.get("parentReference", {})
    # webUrl may be null in the shares response; fall back to siteUrl + path
    object_url = spo_item.get("webUrl") or ""
    if not object_url:
        # Derive from parentReference.path — extract the human-readable part
        # after "root:" and append the filename.
        parent_path = parent_ref.get("path", "")
        if "root:" in parent_path:
            relative_folder = parent_path.split("root:", 1)[1]
            from urllib.parse import quote

            object_url = (
                f"{site_url}{relative_folder}"
                f"/{quote(filename, safe='')}"
            )

    # Determine service name from conversation type
    if conversation_id.startswith("48:notes"):
        service_name = "p2p"
    elif conversation_id.startswith("19:") and "@thread" in conversation_id:
        service_name = "teams"
    else:
        service_name = "p2p"

    # Derive breadcrumbs from the site URL path — e.g.
    #   /personal/user_contoso_com  →  ("personal", "user_contoso_com")
    #   /sites/MyTeam                 →  ("sites", "MyTeam")
    from urllib.parse import urlparse

    site_path_parts = [
        p for p in urlparse(site_url).path.split("/") if p
    ]
    breadcrumbs: dict | None = None
    if len(site_path_parts) >= 2:
        breadcrumbs = {
            "sourceTeamName": site_path_parts[0],
            "sourceChannelName": site_path_parts[1],
        }

    return {
        "itemid": item_id,
        "fileName": filename,
        "fileType": ext,
        "fileInfo": {
            "itemId": None,
            "fileUrl": object_url,
            "siteUrl": site_url,
            "serverRelativeUrl": "",
            "shareUrl": "",
            "shareId": "",
        },
        "fileChicletState": {
            "serviceName": service_name,
            "state": "reference",
        },
        "@type": "http://schema.skype.com/File",
        "version": 2,
        "id": item_id,
        "baseUrl": site_url,
        "objectUrl": object_url,
        "type": ext,
        "title": filename,
        "state": "reference",
        "chicletBreadcrumbs": breadcrumbs,
        "providerData": "",
        "botFileProperties": {},
        "isUploadError": False,
        "progressComplete": None,
        "permissionScope": "organization",
        "filePreview": {
            "previewUrl": "",
            "previewHeight": None,
            "previewWidth": None,
        },
        "sharepointIds": {
            "listId": None,
            "listItemUniqueId": item_id,
            "siteId": site_id,
            "siteUrl": site_url,
            "webId": None,
        },
        "publication": {
            "level": None,
            "versionId": None,
        },
        "site": {
            "dataLocationCode": "",
            "template": {"id": ""},
        },
    }


# ---------------------------------------------------------------------------
# Message body constructor
# ---------------------------------------------------------------------------


def build_message_body(
    conversation_id: str,
    user_mri: str,
    display_name: str,
    content_html: str,
    mentions: list[dict] | None = None,
    cards: list[dict] | None = None,
    importance: str = "",
    subject: str = "",
    ams_references: list[str] | None = None,
    files: list[dict] | None = None,
) -> dict:
    """Construct the full JSON body for a POST message request.

    Args:
        conversation_id: The raw (un-encoded) conversation ID.
        user_mri: Sender's MRI (e.g. ``8:orgid:<guid>``).
        display_name: Sender's display name.
        content_html: HTML content for the message body (should include ``<p>`` wrapper).
        mentions: Optional list of mention property dicts (from ``build_mention_property``).
        cards: Optional list of Adaptive Card envelope dicts
            (from ``build_adaptive_card`` or ``build_card_from_template``).
        importance: ``""`` for normal, ``"HIGH"`` for important, ``"URGENT"`` for urgent.
        subject: Optional message subject (used in channels).
        ams_references: Optional list of AMS object IDs for attached files.
        files: Optional list of file property dicts (from ``build_file_property``).

    Returns:
        A dict ready to be JSON-serialized as the POST body.
    """
    now = utc_iso_now()
    client_message_id = generate_client_message_id()
    mentions_json = json.dumps(mentions or [])
    cards_json = json.dumps(cards or [])
    files_json = json.dumps(files or [])

    return {
        "id": "-1",
        "type": "Message",
        "conversationid": conversation_id,
        "conversationLink": (
            f"https://teams.cloud.microsoft/api/chatsvc/"
            f"{_os.environ.get('TEAMS_CHATSVC_REGION', 'amer')}/v1/users/ME"
            f"/conversations/{encode_conversation_id(conversation_id)}"
        ),
        "from": user_mri,
        "fromUserId": user_mri,
        "composetime": now,
        "originalarrivaltime": now,
        "content": content_html,
        "messagetype": "RichText/Html",
        "contenttype": "Text",
        "imdisplayname": display_name,
        "clientmessageid": client_message_id,
        "callId": "",
        "state": 0,
        "version": "0",
        "amsreferences": ams_references or [],
        "properties": {
            "importance": importance,
            "subject": subject,
            "title": "",
            "cards": cards_json,
            "links": "[]",
            "mentions": mentions_json,
            "onbehalfof": None,
            "files": files_json,
            "policyViolation": None,
            "formatVariant": "TEAMS",
        },
        "crossPostChannels": [],
    }
