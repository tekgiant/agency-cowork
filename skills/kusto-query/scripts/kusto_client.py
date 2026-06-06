"""
Kusto / Azure Data Explorer REST API client.

Auth: Azure CLI token → disk cache → refresh.
No pip dependencies beyond stdlib + requests (pre-installed on most systems).

Usage:
    from kusto_client import KustoClient
    client = KustoClient(cluster_uri="https://mycluster.westus2.kusto.windows.net", database="MyDB")
    rows = client.execute("MyTable | take 10")
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not found. Install with: pip install requests --break-system-packages", file=sys.stderr)
    sys.exit(1)


CACHE_DIR = Path.home() / ".agency-cowork"
TOKEN_CACHE = CACHE_DIR / "kusto-token-cache.json"
TOKEN_TTL = 1800  # 30 minutes


class KustoAuthError(Exception):
    pass


class KustoQueryError(Exception):
    pass


def _get_cached_token(resource: str) -> Optional[str]:
    """Return cached token if still valid."""
    if not TOKEN_CACHE.exists():
        return None
    try:
        cache = json.loads(TOKEN_CACHE.read_text())
        entry = cache.get(resource)
        if entry and entry.get("expires_at", 0) > time.time():
            return entry["token"]
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _cache_token(resource: str, token: str, ttl: int = TOKEN_TTL):
    """Persist token to disk cache."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = {}
    if TOKEN_CACHE.exists():
        try:
            cache = json.loads(TOKEN_CACHE.read_text())
        except json.JSONDecodeError:
            cache = {}
    cache[resource] = {"token": token, "expires_at": time.time() + ttl}
    TOKEN_CACHE.write_text(json.dumps(cache, indent=2))


def get_token(cluster_uri: str) -> str:
    """
    Acquire a bearer token for the given Kusto cluster.
    Resolution: disk cache → az CLI.
    """
    resource = cluster_uri.rstrip("/")

    # 1. Check cache
    cached = _get_cached_token(resource)
    if cached:
        return cached

    # 2. Azure CLI
    try:
        result = subprocess.run(
            ["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            token = result.stdout.strip()
            _cache_token(resource, token)
            return token
        else:
            stderr = result.stderr.strip()
            raise KustoAuthError(f"az CLI failed (rc={result.returncode}): {stderr}")
    except FileNotFoundError:
        raise KustoAuthError("Azure CLI ('az') not found. Run 'az login' first.")
    except subprocess.TimeoutExpired:
        raise KustoAuthError("az CLI token request timed out (15s)")


class KustoClient:
    """Lightweight Kusto REST API client."""

    def __init__(self, cluster_uri: str, database: str):
        # Normalize cluster URI
        self.cluster_uri = cluster_uri.rstrip("/")
        if not self.cluster_uri.startswith("https://"):
            self.cluster_uri = f"https://{self.cluster_uri}"
        # Ensure it ends with .kusto.windows.net (unless it's already a known FQDN)
        known_suffixes = (".kusto.windows.net", ".microsoft.com", ".azure.com",
                          ".kustodev.windows.net", ".kustomfa.windows.net")
        if not any(s in self.cluster_uri for s in known_suffixes):
            self.cluster_uri = f"{self.cluster_uri}.kusto.windows.net"

        self.database = database
        self._token: Optional[str] = None

    def _ensure_token(self):
        if not self._token:
            self._token = get_token(self.cluster_uri)

    def _headers(self) -> dict:
        self._ensure_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def execute(self, kql: str, timeout: int = 120) -> list[dict]:
        """
        Execute a KQL query and return rows as list of dicts.
        Uses the v1 REST query endpoint.
        """
        self._ensure_token()
        url = f"{self.cluster_uri}/v1/rest/query"
        payload = {
            "db": self.database,
            "csl": kql,
            "properties": json.dumps({
                "Options": {
                    "query_language": "kql",
                    "servertimeout": f"00:0{timeout // 60}:{timeout % 60:02d}"
                }
            })
        }

        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=timeout + 10)
        except requests.exceptions.RequestException as e:
            raise KustoQueryError(f"HTTP request failed: {e}")

        if resp.status_code == 401:
            # Token expired — clear cache, retry once
            self._token = None
            _cache_token(self.cluster_uri, "", ttl=0)
            self._ensure_token()
            try:
                resp = requests.post(url, json=payload, headers=self._headers(), timeout=timeout + 10)
            except requests.exceptions.RequestException as e:
                raise KustoQueryError(f"HTTP request failed on retry: {e}")

        if resp.status_code != 200:
            raise KustoQueryError(f"Kusto API returned {resp.status_code}: {resp.text[:500]}")

        return self._parse_response(resp.json())

    def _parse_response(self, data: dict) -> list[dict]:
        """Parse Kusto v1 REST response into list of row dicts."""
        rows = []
        tables = data.get("Tables", [])
        if not tables:
            return rows

        # Primary result is usually the first table
        primary = tables[0]
        columns = [col["ColumnName"] for col in primary.get("Columns", [])]
        for row in primary.get("Rows", []):
            rows.append(dict(zip(columns, row)))

        return rows

    def list_tables(self) -> list[str]:
        """List all tables in the database."""
        rows = self.execute(".show tables | project TableName")
        return [r.get("TableName", "") for r in rows if r.get("TableName")]

    def get_schema(self, table: str) -> list[dict]:
        """Get column schema for a table. Returns [{name, type}, ...]."""
        rows = self.execute(f".show table {table} schema as json")
        if not rows:
            return []

        # The schema command returns a single row with a Schema JSON column
        schema_json = rows[0].get("Schema", "")
        if isinstance(schema_json, str):
            try:
                schema = json.loads(schema_json)
            except json.JSONDecodeError:
                return []
        else:
            schema = schema_json

        # Extract ordered columns from schema
        columns = []
        if isinstance(schema, dict) and "OrderedColumns" in schema:
            for col in schema["OrderedColumns"]:
                columns.append({"name": col.get("Name", ""), "type": col.get("CslType", col.get("Type", ""))})
        return columns
