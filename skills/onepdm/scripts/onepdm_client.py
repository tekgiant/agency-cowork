"""
OnePDM (Aras Innovator) SOAP/XML API Client.

Provides methods for searching, browsing, and downloading specifications
from the OnePDM PLM system (https://onepdm.plm.microsoft.com).

Auth is handled separately (auth.py) — this module accepts a requests.Session
with pre-configured cookies.
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

# OnePDM endpoints
BASE_URL = "https://s-onepdm.plm.microsoft.com"
VAULT_URL = "https://v-onepdm.plm.microsoft.com"
INNOVATOR = f"{BASE_URL}/onepdm/InnovatorServer.aspx"
AUTH_BROKER = f"{BASE_URL}/onepdm/AuthenticationBroker.asmx"
DB_NAME = "k8sonepdm-onepdm"

# SOAP envelope template
SOAP_ENVELOPE = """<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" ><SOAP-ENV:Body>{body}</SOAP-ENV:Body></SOAP-ENV:Envelope>"""


class OnePDMClient:
    """Client for OnePDM Aras Innovator SOAP API."""

    def __init__(self, session: requests.Session):
        """Initialize with an authenticated requests.Session (cookies set by auth.py)."""
        self.session = session

    def _soap_call(self, body: str, action: str = "ApplyItem") -> str:
        """Send a SOAP call to InnovatorServer.aspx and return the response XML."""
        envelope = SOAP_ENVELOPE.format(body=body)
        headers = {
            "Content-Type": "text/xml; charset=UTF-8",
            "SOAPAction": action,
        }
        resp = self.session.post(INNOVATOR, data=envelope.encode("utf-8"), headers=headers)
        resp.raise_for_status()
        return resp.text

    def _parse_result(self, xml_text: str) -> str:
        """Extract the <Result> content from a SOAP response."""
        # Handle namespace prefixes
        text = xml_text.replace("SOAP-ENV:", "").replace("xmlns:SOAP-ENV=", "xmlns=")
        match = re.search(r"<Result>(.*?)</Result>", text, re.DOTALL)
        if match:
            return match.group(1)
        return ""

    # ── Authentication ──

    def validate_user(self) -> dict:
        """Validate the current session. Returns user info dict."""
        body = "<ValidateUser></ValidateUser>"
        resp = self._soap_call(body, action="ValidateUser")
        result = self._parse_result(resp)
        info = {}
        for tag in ["id", "login_name", "database", "authentication_type"]:
            m = re.search(f"<{tag}>(.*?)</{tag}>", result)
            if m:
                info[tag] = m.group(1)
        return info

    # ── Search ──

    def global_search(self, query: str) -> list[dict]:
        """Search OnePDM by document number or keyword. Returns list of result dicts."""
        body = (
            f'<ApplyItem><Item isNew="1" isTemp="1" type="Method" action="m_API_GlobalSearch_Run">'
            f"<searchText>{_xml_escape(query)}</searchText>"
            f"<preference>Deviation,Document,ECR,Express ECO,M_Family,Manufacturer,"
            f"Manufacturer Part,Part,M_SavedConf,M_VComponent_Part,M_VComponent_ChangeRequest,"
            f"M_VComponent</preference>"
            f"</Item></ApplyItem>"
        )
        resp = self._soap_call(body)
        result = self._parse_result(resp)
        # Result is a JSON array inside the XML
        try:
            items = json.loads(result)
            # Filter out AI/FILE summary entries
            return [
                item for item in items
                if isinstance(item, dict) and item.get("_id") not in ("AI_SUMMARY", "FILE_SUMMARY")
            ]
        except (json.JSONDecodeError, TypeError):
            return []

    # ── Document Operations ──

    def get_document(self, doc_id: str) -> dict:
        """Get full document metadata by OnePDM ID."""
        body = (
            f'<ApplyItem><Item type="Document" levels="0" action="get" '
            f'select="*" id="{doc_id}"></Item></ApplyItem>'
        )
        resp = self._soap_call(body)
        result = self._parse_result(resp)
        return _parse_item_xml(result)

    def get_document_by_number(self, doc_number: str) -> Optional[dict]:
        """Search for a document by number and return its metadata, or None."""
        results = self.global_search(doc_number)
        for r in results:
            if r.get("_itemtype") == "Document" and r.get("_itemnumber") == doc_number:
                return self.get_document(r["_id"])
        return None

    def list_document_files(self, doc_id: str) -> list[dict]:
        """List all file attachments for a document."""
        body = (
            f'<ApplyItem><Item type="Document File" action="get" page="1" '
            f'select="m_external_distribution,m_filesubclass,modified_on,related_id,'
            f'config_id,created_by_id,created_on,modified_by_id,modified_on,locked_by_id,'
            f'major_rev,css,current_state,keyed_name,'
            f'related_id(comments,file_size,file_type,filename,config_id,created_by_id,'
            f'created_on,modified_by_id,modified_on,locked_by_id,major_rev,css,current_state,keyed_name),'
            f'source_id" pagesize="25" orderBy="related_id" '
            f'><source_id condition="eq">{doc_id}</source_id>'
            f"</Item></ApplyItem>"
        )
        resp = self._soap_call(body)
        result = self._parse_result(resp)
        return _parse_relationship_files(result)

    # ── File Operations ──

    def get_file_metadata(self, file_id: str) -> dict:
        """Get file metadata by file ID."""
        body = (
            f'<ApplyItem><Item type="File" levels="0" action="get" '
            f'select="*" id="{file_id}"></Item></ApplyItem>'
        )
        resp = self._soap_call(body)
        result = self._parse_result(resp)
        return _parse_item_xml(result)

    def get_file_vault_info(self, file_id: str) -> dict:
        """Get vault location for a file (vault_url, file_version)."""
        body = (
            f'<ApplyItem><Item type="File" action="get" select="id,filename">'
            f'<Relationships><Item type="Located" select="id,related_id,file_version" action="get">'
            f'<related_id><Item type="Vault" select="id,vault_url" action="get"/>'
            f'</related_id></Item></Relationships>'
            f'<id condition="in">{file_id}</id></Item></ApplyItem>'
        )
        resp = self._soap_call(body)
        result = self._parse_result(resp)
        # Extract vault ID and URL
        vault_id_match = re.search(r'type="Vault"[^>]*id="([^"]+)"', result)
        vault_url_match = re.search(r"<vault_url>([^<]+)</vault_url>", result)
        filename_match = re.search(r"<filename>([^<]+)</filename>", result)
        return {
            "vault_id": vault_id_match.group(1) if vault_id_match else "",
            "vault_url": vault_url_match.group(1) if vault_url_match else "",
            "filename": filename_match.group(1) if filename_match else "",
        }

    def get_download_token(self, file_id: str) -> str:
        """Get a temporary download token for a file."""
        resp = self.session.post(
            f"{AUTH_BROKER}/GetFileDownloadToken",
            json={"param": {"fileId": file_id}},
            headers={"Content-Type": "application/json; charset=UTF-8"},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("d", "")

    def download_file(self, file_id: str, dest_path: str, filename: str = "",
                      vault_id: str = "") -> str:
        """Download a file from the vault to dest_path. Returns the saved file path."""
        # Get vault info if not provided
        if not vault_id or not filename:
            vault_info = self.get_file_vault_info(file_id)
            vault_id = vault_id or vault_info.get("vault_id", "")
            filename = filename or vault_info.get("filename", "download")

        # Get download token
        token = self.get_download_token(file_id)
        if not token:
            raise RuntimeError(f"Failed to get download token for file {file_id}")

        # Build vault download URL
        url = (
            f"{VAULT_URL}/onepdm/vaultserver.aspx"
            f"?dbName={DB_NAME}"
            f"&fileId={file_id}"
            f"&fileName={quote(filename)}"
            f"&vaultId={vault_id}"
            f"&token={quote(token)}"
            f"&contentDispositionAttachment=1"
        )

        resp = self.session.get(url, stream=True)
        resp.raise_for_status()

        # Determine output path
        dest = Path(dest_path)
        if dest.is_dir():
            dest = dest / filename
        dest.parent.mkdir(parents=True, exist_ok=True)

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return str(dest)

    # ── Convenience: search + download by doc number ──

    def download_by_doc_number(self, doc_number: str, dest_dir: str) -> Optional[str]:
        """Search for a document by number, find the latest file, and download it."""
        doc = self.get_document_by_number(doc_number)
        if not doc:
            return None

        doc_id = doc.get("id", "")
        files = self.list_document_files(doc_id)
        if not files:
            return None

        # Pick the first (usually latest) file
        file_id = files[0].get("file_id", "")
        filename = files[0].get("filename", f"{doc_number}.bin")
        vault_id = files[0].get("vault_id", "")

        return self.download_file(file_id, dest_dir, filename=filename, vault_id=vault_id)


# ── Helpers ──

def _xml_escape(text: str) -> str:
    """Escape special XML characters."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _parse_item_xml(xml_fragment: str) -> dict:
    """Parse an Aras Item XML fragment into a flat dict of properties."""
    props = {}
    # Extract Item attributes
    item_match = re.search(r"<Item\s+([^>]*)>", xml_fragment)
    if item_match:
        for attr_match in re.finditer(r'(\w+)="([^"]*)"', item_match.group(1)):
            props[attr_match.group(1)] = attr_match.group(2)

    # Extract child elements (simple text values)
    for m in re.finditer(r"<(\w+)(?:\s[^>]*)?>([^<]*)</\1>", xml_fragment):
        tag, value = m.group(1), m.group(2).strip()
        if value and tag != "Item":
            props[tag] = value

    # Extract keyed_name attributes from elements like <created_by_id keyed_name="...">
    for m in re.finditer(r'<(\w+)\s+keyed_name="([^"]*)"', xml_fragment):
        props[f"{m.group(1)}_name"] = m.group(2)

    return props


def _parse_relationship_files(xml_fragment: str) -> list[dict]:
    """Parse Document File relationship XML into a list of file info dicts."""
    files = []
    # Find each related_id Item (the actual File items)
    for m in re.finditer(
        r'<related_id>.*?<Item\s+type="File"[^>]*id="([^"]*)"[^>]*>(.*?)</Item>',
        xml_fragment, re.DOTALL
    ):
        file_id = m.group(1)
        content = m.group(2)
        file_info = {"file_id": file_id}
        for tag in ["filename", "file_size", "file_type", "keyed_name", "created_on", "modified_on"]:
            tag_match = re.search(f"<{tag}>([^<]*)</{tag}>", content)
            if tag_match:
                file_info[tag] = tag_match.group(1)
        files.append(file_info)
    return files
