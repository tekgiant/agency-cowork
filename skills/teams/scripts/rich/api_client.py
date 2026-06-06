"""API client for Microsoft Teams — uses the browser session for all calls.

All HTTP requests are executed *inside the Playwright browser context* via
``TeamsSession.fetch()`` and ``TeamsSession.fetch_upload()``, which means
cookies, auth tokens, and CORS headers are handled automatically by the
browser.

People / chat lookups are handled by the MCP ``microsoft-teams`` server —
this module handles sending messages and file attachments.

Public functions:
  - ``send_message()``           — send a rich (HTML / mention / Adaptive Card) message.
  - ``upload_to_sharepoint()``   — upload a file to OneDrive "Microsoft Teams Chat Files".
  - ``create_ams_object()``      — register an AMS object for in-message preview.
  - ``upload_to_ams()``          — upload file content to AMS.
  - ``attach_and_send()``        — full orchestrator: SPO + AMS + send in one call.
  - ``resolve_spo_item()``       — resolve a SharePoint/OneDrive URL to item metadata.
  - ``attach_existing_and_send()``— send an existing SPO/OneDrive file (no re-upload).
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from .auth import TeamsSession
from .utils import (
    AMS_BASE,
    build_file_property,
    build_file_property_reference,
    build_message_body,
    detect_ams_content_type,
    detect_ams_view_name,
    encode_conversation_id,
)

# ---------------------------------------------------------------------------
# Base URLs
# ---------------------------------------------------------------------------

# Region is dynamic — set via TEAMS_CHATSVC_REGION env var or auto-discovered.
import os as _os
_CHATSVC_REGION = _os.environ.get("TEAMS_CHATSVC_REGION", "amer")
CHATSVC_BASE = f"https://teams.cloud.microsoft/api/chatsvc/{_CHATSVC_REGION}/v1/users/ME"

# SharePoint upload base — uses the logged-in user's OneDrive
# The actual tenant URL is discovered at runtime from the session.
_SPO_UPLOAD_PATH = "_api/v2.0/drive/root:/Microsoft Teams Chat Files"


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------

async def send_message(
    session: TeamsSession,
    conversation_id: str,
    content_html: str,
    *,
    mentions: list[dict] | None = None,
    cards: list[dict] | None = None,
    importance: str = "",
    subject: str = "",
    ams_references: list[str] | None = None,
    files: list[dict] | None = None,
) -> dict:
    """Send a rich message to a Teams conversation.

    Args:
        session: An active ``TeamsSession`` (from ``async with TeamsSession()``).
        conversation_id: Raw (un-encoded) conversation ID.
        content_html: HTML content — wrap text in ``<p>`` tags.
        mentions: Optional list of mention property dicts
            (see ``utils.build_mention_property``).
        cards: Optional list of Adaptive Card dicts
            (see ``utils.build_adaptive_card``).
        importance: ``""`` for normal, ``"HIGH"`` for important, ``"URGENT"``
            for urgent.
        subject: Optional subject line (channels).
        ams_references: Optional list of AMS object IDs for attached files.
        files: Optional list of file property dicts for attached files.

    Returns:
        The parsed JSON response from the Teams API.

    Raises:
        RuntimeError: On API errors (4xx / 5xx).
    """
    assert session.user is not None, "TeamsSession not connected"

    body = build_message_body(
        conversation_id=conversation_id,
        user_mri=session.user.user_mri,
        display_name=session.user.display_name,
        content_html=content_html,
        mentions=mentions,
        cards=cards,
        importance=importance,
        subject=subject,
        ams_references=ams_references,
        files=files,
    )

    url = (
        f"{CHATSVC_BASE}/conversations/"
        f"{encode_conversation_id(conversation_id)}/messages"
    )

    return await session.fetch("POST", url, body=body)


# ---------------------------------------------------------------------------
# SharePoint upload — Step 1 of the attachment flow
# ---------------------------------------------------------------------------

async def upload_to_sharepoint(
    session: TeamsSession,
    file_path: str,
    *,
    spo_base_url: str | None = None,
) -> dict:
    """Upload a file to the user's OneDrive *Microsoft Teams Chat Files* folder.

    Uses the **classic SharePoint REST API** (``/_api/web/.../Files/add``)
    with cookie + request-digest auth.  A temporary page is opened on the
    SharePoint domain so fetch calls are same-origin.

    After uploading, the ListItem metadata is fetched to obtain the
    ``listItemUniqueId`` needed for the message properties.

    Args:
        session: An active ``TeamsSession``.
        file_path: Absolute local path to the file.
        spo_base_url: SharePoint personal site base URL.  If ``None``,
            auto-discovered from the JWT claims.

    Returns:
        A normalised dict matching the shape expected by
        ``build_file_property`` — contains ``sharepointIds``, ``webUrl``,
        ``size``, and optionally ``image``.
    """
    import base64 as b64mod
    import asyncio as _aio

    fp = Path(file_path)
    filename = fp.name

    if not spo_base_url:
        spo_base_url = await _discover_spo_url(session)

    # Read and base64-encode file content
    raw_bytes = fp.read_bytes()
    b64_data = b64mod.b64encode(raw_bytes).decode("ascii")
    file_size = len(raw_bytes)

    # ── Build paths ──────────────────────────────────────────────────
    # spo_base_url = "https://microsoft-my.sharepoint.com/personal/user_domain_com"
    # We need the server-relative path for the SP REST API.
    from urllib.parse import urlparse
    parsed = urlparse(spo_base_url)
    site_relative = parsed.path.rstrip("/")  # e.g. "/personal/user_domain_com"
    folder_relative = f"{site_relative}/Documents/Microsoft Teams Chat Files"

    spo_page = await session._context.new_page()
    try:
        await spo_page.goto(
            spo_base_url + "/_layouts/15/onedrive.aspx",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await _aio.sleep(2)

        # Single JS call: get digest → upload file → get ListItem metadata
        result = await spo_page.evaluate("""
        async ([spo, folder, filename, b64, fileSize]) => {
            try {
                // 1. Get request digest
                const dResp = await fetch(spo + "/_api/contextinfo", {
                    method: "POST",
                    headers: { "Accept": "application/json;odata=verbose" },
                    body: "",
                });
                const dData = await dResp.json();
                const digest = dData.d?.GetContextWebInformation?.FormDigestValue;
                if (!digest) return { error: "no_digest" };

                // 2. Upload file via classic REST
                const binary = atob(b64);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

                const uploadUrl = spo + `/_api/web/GetFolderByServerRelativeUrl('${folder}')/Files/add(url='${filename}',overwrite=true)`;
                const uploadResp = await fetch(uploadUrl, {
                    method: "POST",
                    headers: {
                        "Accept": "application/json;odata=verbose",
                        "X-RequestDigest": digest,
                    },
                    body: bytes.buffer,
                });
                if (!uploadResp.ok) {
                    const errText = await uploadResp.text();
                    return { error: "upload_failed", status: uploadResp.status, detail: errText.substring(0, 500) };
                }
                const fileData = await uploadResp.json();
                const serverRelUrl = fileData.d?.ServerRelativeUrl || "";
                const uniqueId = fileData.d?.UniqueId || "";

                // 3. Fetch ListItem metadata to get the list-item GUID
                const listItemUrl = spo + `/_api/web/GetFileByServerRelativePath(decodedurl='${serverRelUrl}')/ListItemAllFields`;
                const liResp = await fetch(listItemUrl, {
                    method: "GET",
                    headers: {
                        "Accept": "application/json;odata=verbose",
                        "X-RequestDigest": digest,
                    },
                });
                let listItemUniqueId = uniqueId;
                if (liResp.ok) {
                    const liData = await liResp.json();
                    listItemUniqueId = liData.d?.__metadata?.id || uniqueId;
                    // The metadata.id IS the GUID we need
                }

                // 4. Get site info (siteId, webId)
                const siteResp = await fetch(spo + "/_api/site?$select=Id", {
                    method: "GET",
                    headers: { "Accept": "application/json;odata=verbose" },
                });
                let siteId = "";
                if (siteResp.ok) {
                    const siteData = await siteResp.json();
                    siteId = siteData.d?.Id || "";
                }

                return {
                    ok: true,
                    serverRelativeUrl: serverRelUrl,
                    uniqueId: uniqueId,
                    listItemUniqueId: listItemUniqueId,
                    siteId: siteId,
                    siteUrl: spo,
                    fileSize: fileSize,
                };
            } catch (e) {
                return { error: "exception", detail: e.message };
            }
        }
        """, [spo_base_url, folder_relative, filename, b64_data, file_size])
    finally:
        await spo_page.close()

    if result.get("error"):
        raise RuntimeError(
            f"SharePoint upload failed: {result.get('error')} — {result.get('detail', '')}"
        )

    # Build the webUrl for the file
    site_url = result["siteUrl"]
    server_rel = result["serverRelativeUrl"]
    web_url = f"{parsed.scheme}://{parsed.netloc}{server_rel}"

    # Detect image
    ext = fp.suffix.lower()
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".heic"}
    image_info = {} if ext in image_exts else None

    # Return a normalised dict matching the shape build_file_property expects
    return {
        "sharepointIds": {
            "listItemUniqueId": result["listItemUniqueId"],
            "siteId": result["siteId"],
            "siteUrl": site_url,
            "webId": "",
        },
        "webUrl": web_url,
        "size": file_size,
        "image": image_info,
    }


# ---------------------------------------------------------------------------
# AMS object creation — Step 2 of the attachment flow
# ---------------------------------------------------------------------------

async def create_ams_object(
    session: TeamsSession,
    filename: str,
    conversation_id: str,
) -> str:
    """Create an AMS (Azure Media Service) object and return its ID.

    AMS hosts the in-message preview/thumbnail for attached files.

    Args:
        session: An active ``TeamsSession``.
        filename: The original filename (used to determine content type).
        conversation_id: Conversation this file will be sent to.

    Returns:
        The AMS object ID string (e.g. ``"0-wus-d9-abcdef..."``).
    """
    ams_type = detect_ams_content_type(filename)

    payload = {
        "type": ams_type,
        "permissions": {conversation_id: ["read"]},
        "sharingMode": "Attached",
        "filename": filename,
    }

    url = f"{AMS_BASE}/v1/objects/"
    # AMS uses skype_token auth (injected by session.fetch) and its own headers
    result = await session.fetch("POST", url, body=payload, extra_headers={
        "BehaviorOverride": None,       # not used by AMS
        "x-ms-client-type": None,       # not used by AMS
        "x-ms-client-version": "1415/26021215116",
        "x-ams-post-sharing-mode": "Attached",
    })
    ams_id = result.get("id", "")
    if not ams_id:
        raise RuntimeError(f"AMS object creation returned no id: {result}")
    return ams_id


# ---------------------------------------------------------------------------
# AMS binary upload — Step 3 of the attachment flow
# ---------------------------------------------------------------------------

async def upload_to_ams(
    session: TeamsSession,
    file_path: str,
    ams_id: str,
    filename: str,
) -> dict:
    """Upload the actual file content to AMS.

    Args:
        session: An active ``TeamsSession``.
        file_path: Absolute local path to the file.
        ams_id: The AMS object ID from ``create_ams_object()``.
        filename: Original filename (used to pick the view name).

    Returns:
        The parsed JSON response (usually ``{"id": "..."}``).
    """
    view = detect_ams_view_name(filename)
    mime, _ = mimetypes.guess_type(filename)
    content_type = mime or "application/octet-stream"

    url = f"{AMS_BASE}/v1/objects/{ams_id}/content/{view}"

    return await session.fetch_upload(
        "PUT", url, file_path, content_type=content_type,
        extra_headers={
            "x-ms-client-version": "1415/26021215116",
        },
    )


# ---------------------------------------------------------------------------
# Full attachment orchestrator
# ---------------------------------------------------------------------------

async def attach_and_send(
    session: TeamsSession,
    conversation_id: str,
    content_html: str,
    file_path: str,
    *,
    mentions: list[dict] | None = None,
    cards: list[dict] | None = None,
    importance: str = "",
    subject: str = "",
) -> dict:
    """Upload a file and send it as a message attachment — full flow.

    Executes the 4-step Teams attachment protocol:
      1. PUT file to SharePoint OneDrive (``Microsoft Teams Chat Files``).
      2. POST to AMS to create a preview object.
      3. PUT file content to AMS.
      4. POST the message with ``amsreferences`` and ``properties.files``.

    Args:
        session: An active ``TeamsSession``.
        conversation_id: Target conversation ID.
        content_html: HTML message body (can be empty ``"<p></p>"``).
        file_path: Absolute path to the local file to attach.
        mentions: Optional @mention properties.
        cards: Optional Adaptive Card envelopes.
        importance: Message importance.
        subject: Message subject.

    Returns:
        The parsed JSON response from the message POST.
    """
    fp = Path(file_path)
    filename = fp.name

    print(f"  [1/4] Uploading to SharePoint: {filename} ...", flush=True)
    spo_item = await upload_to_sharepoint(session, file_path)

    print(f"  [2/4] Creating AMS object ...", flush=True)
    ams_id = await create_ams_object(session, filename, conversation_id)

    print(f"  [3/4] Uploading to AMS: {ams_id} ...", flush=True)
    await upload_to_ams(session, file_path, ams_id, filename)

    print(f"  [4/4] Sending message ...", flush=True)
    file_prop = build_file_property(
        filename=filename,
        spo_item=spo_item,
        ams_id=ams_id,
        conversation_id=conversation_id,
    )

    return await send_message(
        session,
        conversation_id,
        content_html,
        mentions=mentions,
        cards=cards,
        importance=importance,
        subject=subject,
        ams_references=[ams_id],
        files=[file_prop],
    )


# ---------------------------------------------------------------------------
# Resolve existing SharePoint / OneDrive file
# ---------------------------------------------------------------------------

async def resolve_spo_item(
    session: TeamsSession,
    spo_url: str,
) -> dict:
    """Resolve a SharePoint / OneDrive file URL to its drive-item metadata.

    Uses the SharePoint ``shares`` API (v2.0) with a Base64-encoded sharing
    URL.  The resolution happens in a temporary browser page on the
    SharePoint origin so SSO cookies are sent automatically.

    Args:
        session: An active ``TeamsSession``.
        spo_url: Full URL to the file on SharePoint / OneDrive
            (e.g. ``https://…sharepoint.com/…/Documents/file.docx``).

    Returns:
        A normalised dict matching the shape expected by
        ``build_file_property_reference`` — contains ``sharepointIds``,
        ``webUrl``, ``name``, ``file``, etc.
    """
    import asyncio as _aio
    import base64 as _b64
    from urllib.parse import urlparse

    # Build the sharing-token: "u!" + base64url(url)
    encoded = _b64.urlsafe_b64encode(spo_url.encode()).decode().rstrip("=")
    share_token = f"u!{encoded}"

    # Determine the host for the shares API call
    parsed = urlparse(spo_url)
    spo_host = f"{parsed.scheme}://{parsed.netloc}"

    # Open a temporary page on the SPO domain for same-origin auth
    spo_page = await session._context.new_page()
    try:
        await spo_page.goto(
            spo_host + "/_layouts/15/onedrive.aspx",
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        await _aio.sleep(2)

        result = await spo_page.evaluate("""
        async ([host, token]) => {
            try {
                const url = host + "/_api/v2.0/shares/" + token + "/driveItem?$select=*,sharepointIds";
                const resp = await fetch(url, {
                    method: "GET",
                    headers: { "Accept": "application/json" },
                });
                if (!resp.ok) {
                    const err = await resp.text();
                    return { error: "resolve_failed", status: resp.status, detail: err.substring(0, 500) };
                }
                return await resp.json();
            } catch (e) {
                return { error: "exception", detail: e.message };
            }
        }
        """, [spo_host, share_token])
    finally:
        await spo_page.close()

    if result.get("error"):
        raise RuntimeError(
            f"SharePoint file resolution failed: {result.get('error')} — "
            f"{result.get('detail', '')}"
        )

    return result


# ---------------------------------------------------------------------------
# Attach an existing SPO/OneDrive file (no upload)
# ---------------------------------------------------------------------------

async def attach_existing_and_send(
    session: TeamsSession,
    conversation_id: str,
    content_html: str,
    spo_url: str,
    *,
    mentions: list[dict] | None = None,
    cards: list[dict] | None = None,
    importance: str = "",
    subject: str = "",
) -> dict:
    """Send an existing SharePoint / OneDrive file as a message attachment.

    Unlike ``attach_and_send()`` which uploads a local file, this function
    takes a SharePoint / OneDrive URL and sends a *reference* to the
    already-uploaded file.  No SPO or AMS upload is needed.

    The protocol:
      1. Resolve the SPO URL via the shares API to get item metadata.
      2. Build a "reference" file property (no AMS preview).
      3. POST the message with ``amsreferences: []`` and the file property.

    Args:
        session: An active ``TeamsSession``.
        conversation_id: Target conversation ID.
        content_html: HTML message body.
        spo_url: Full SharePoint / OneDrive URL to the file.
        mentions: Optional @mention properties.
        cards: Optional Adaptive Card envelopes.
        importance: Message importance.
        subject: Message subject.

    Returns:
        The parsed JSON response from the message POST.
    """
    print(f"  [1/2] Resolving SharePoint file ...", flush=True)
    spo_item = await resolve_spo_item(session, spo_url)

    filename = spo_item.get("name", spo_url.rsplit("/", 1)[-1])
    print(f"  [2/2] Sending message with {filename} ...", flush=True)

    file_prop = build_file_property_reference(
        filename=filename,
        spo_item=spo_item,
        conversation_id=conversation_id,
    )

    return await send_message(
        session,
        conversation_id,
        content_html,
        mentions=mentions,
        cards=cards,
        importance=importance,
        subject=subject,
        ams_references=[],
        files=[file_prop],
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _discover_spo_url(session: TeamsSession) -> str:
    """Discover the user's personal SharePoint (OneDrive for Business) URL.

    Tries the Teams ``me/properties`` endpoint first, then falls back to
    constructing the URL from the user's JWT UPN claim.
    """
    # Strategy 1: Teams user properties endpoint
    try:
        result = await session.fetch(
            "GET",
            # Note: mt/ uses "part/msft" path, NOT the chatsvc region slug.
            f"https://teams.cloud.microsoft/api/mt/part/msft/beta/me/properties",
        )
        my_site = (
            result.get("mySiteUrl")
            or result.get("oneDriveUrl")
            or result.get("spoMyUrl")
            or ""
        )
        if my_site:
            return my_site.rstrip("/")
    except Exception:
        pass

    # Strategy 2: Derive from JWT token claims
    try:
        import base64 as _b64
        token = session._tokens.get("chatsvc", "")
        if token:
            payload_b64 = token.split(".")[1]
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            claims = json.loads(_b64.urlsafe_b64decode(payload_b64))
            upn = claims.get("upn", "")
            tenant_domain = claims.get("tid", "")
            if upn and "@" in upn:
                # "user@domain.com" → "user_domain_com"
                safe_upn = upn.replace("@", "_").replace(".", "_")
                # Derive the tenant's SPO hostname from the UPN domain
                email_domain = upn.split("@")[1]  # "microsoft.com"
                spo_tenant = email_domain.split(".")[0]  # "microsoft"
                spo_url = f"https://{spo_tenant}-my.sharepoint.com/personal/{safe_upn}"
                return spo_url
    except Exception:
        pass

    raise RuntimeError(
        "Could not discover SharePoint personal site URL. "
        "Please provide it via spo_base_url parameter."
    )
