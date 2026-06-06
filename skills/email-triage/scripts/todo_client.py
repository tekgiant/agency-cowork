"""Microsoft Todo client via Outlook REST API v2.0.

Provides task CRUD operations against outlook.office365.com/api/v2.0/me/tasks.
Tasks created here sync automatically to Microsoft Todo app.

Usage:
    from scripts.todo_client import TodoClient
    client = TodoClient()
    folders = client.list_folders()
    tasks = client.list_tasks(folder_id)
    task = client.create_task(folder_id, "Review email", body="From: sender@...")
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

# Lazy import — avoid circular dependency at module load
_auth_module = None

API_BASE = "https://outlook.office365.com/api/v2.0/me"


def _get_auth():
    global _auth_module
    if _auth_module is None:
        from scripts import todo_auth
        _auth_module = todo_auth
    return _auth_module


class TodoClient:
    """Outlook Tasks REST API client with auto-refresh."""

    def __init__(self, token: Optional[str] = None):
        self._token = token
        self._session = requests.Session()
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def _ensure_token(self) -> str:
        if not self._token:
            self._token = _get_auth().get_token()
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._ensure_token()}"}

    def _get(self, path: str, params: Optional[Dict] = None) -> requests.Response:
        r = self._session.get(f"{API_BASE}{path}", headers=self._headers(), params=params, timeout=15)
        if r.status_code == 401:
            # Token expired — re-auth
            self._token = None
            self._token = _get_auth().ensure_token()
            r = self._session.get(f"{API_BASE}{path}", headers=self._headers(), params=params, timeout=15)
        return r

    def _post(self, path: str, data: Dict) -> requests.Response:
        r = self._session.post(f"{API_BASE}{path}", headers=self._headers(), json=data, timeout=15)
        if r.status_code == 401:
            self._token = None
            self._token = _get_auth().ensure_token()
            r = self._session.post(f"{API_BASE}{path}", headers=self._headers(), json=data, timeout=15)
        return r

    def _patch(self, path: str, data: Dict) -> requests.Response:
        r = self._session.patch(f"{API_BASE}{path}", headers=self._headers(), json=data, timeout=15)
        if r.status_code == 401:
            self._token = None
            self._token = _get_auth().ensure_token()
            r = self._session.patch(f"{API_BASE}{path}", headers=self._headers(), json=data, timeout=15)
        return r

    def _delete(self, path: str) -> requests.Response:
        r = self._session.delete(f"{API_BASE}{path}", headers=self._headers(), timeout=15)
        if r.status_code == 401:
            self._token = None
            self._token = _get_auth().ensure_token()
            r = self._session.delete(f"{API_BASE}{path}", headers=self._headers(), timeout=15)
        return r

    # ── Folder (List) Operations ──

    def list_folders(self) -> List[Dict]:
        """List all task folders (= Todo lists)."""
        r = self._get("/taskfolders")
        r.raise_for_status()
        return r.json().get("value", [])

    def get_folder(self, folder_id: str) -> Dict:
        """Get a specific task folder."""
        r = self._get(f"/taskfolders('{folder_id}')")
        r.raise_for_status()
        return r.json()

    def create_folder(self, name: str) -> Dict:
        """Create a new task folder."""
        r = self._post("/taskfolders", {"Name": name})
        r.raise_for_status()
        return r.json()

    def get_or_create_folder(self, name: str) -> Dict:
        """Find folder by name or create it."""
        folders = self.list_folders()
        for f in folders:
            if f.get("Name", "").lower() == name.lower():
                return f
        return self.create_folder(name)

    # ── Task Operations ──

    def list_tasks(
        self,
        folder_id: Optional[str] = None,
        top: int = 50,
        filter_expr: Optional[str] = None,
        orderby: str = "LastModifiedDateTime desc",
    ) -> List[Dict]:
        """List tasks in a folder, or all tasks if no folder specified."""
        if folder_id:
            path = f"/taskfolders('{folder_id}')/tasks"
        else:
            path = "/tasks"

        params = {"$top": str(top), "$orderby": orderby}
        if filter_expr:
            params["$filter"] = filter_expr

        r = self._get(path, params=params)
        r.raise_for_status()
        return r.json().get("value", [])

    def get_task(self, task_id: str) -> Dict:
        """Get a specific task."""
        r = self._get(f"/tasks('{task_id}')")
        r.raise_for_status()
        return r.json()

    def create_task(
        self,
        folder_id: str,
        subject: str,
        body: Optional[str] = None,
        importance: str = "Normal",
        due_date: Optional[str] = None,
        categories: Optional[List[str]] = None,
    ) -> Dict:
        """Create a task in the specified folder.

        Args:
            folder_id: Task folder ID
            subject: Task title
            body: Optional body text (plain text)
            importance: "Low", "Normal", or "High"
            due_date: ISO 8601 date string (YYYY-MM-DD)
            categories: List of category strings (colored labels)

        Returns:
            Created task dict
        """
        data: Dict[str, Any] = {
            "Subject": subject,
            "Importance": importance,
        }

        if body:
            data["Body"] = {"ContentType": "Text", "Content": body}

        if due_date:
            data["DueDateTime"] = {
                "DateTime": f"{due_date}T23:59:59",
                "TimeZone": "Pacific Standard Time",
            }

        if categories:
            data["Categories"] = categories

        r = self._post(f"/taskfolders('{folder_id}')/tasks", data)
        r.raise_for_status()
        return r.json()

    def update_task(self, task_id: str, **kwargs) -> Dict:
        """Update task fields.

        Supported kwargs:
            Subject, Body (dict), Status, Importance, DueDateTime (dict),
            Categories (list), CompletedDateTime (dict)
        """
        r = self._patch(f"/tasks('{task_id}')", kwargs)
        r.raise_for_status()
        return r.json()

    def complete_task(self, task_id: str) -> Dict:
        """Mark a task as completed."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return self.update_task(
            task_id,
            Status="Completed",
            CompletedDateTime={"DateTime": now, "TimeZone": "UTC"},
        )

    def delete_task(self, task_id: str) -> None:
        """Delete a task."""
        r = self._delete(f"/tasks('{task_id}')")
        r.raise_for_status()

    # ── Email-Linked Task Helpers ──

    def create_email_task(
        self,
        folder_id: str,
        subject: str,
        sender: str,
        message_id: str,
        summary: str = "",
        importance: str = "Normal",
        due_date: Optional[str] = None,
        categories: Optional[List[str]] = None,
    ) -> Dict:
        """Create a task linked to an email.

        Stores the message_id in the body for dedup matching.
        """
        body_lines = []
        if sender:
            body_lines.append(f"From: {sender}")
        if summary:
            body_lines.append(summary)
        body_lines.append("")
        from urllib.parse import quote
        encoded_id = quote(message_id, safe="")
        body_lines.append(f"[Open in Outlook](https://outlook.office365.com/mail/deeplink/read/{encoded_id}?popoutv2=1&version=20260306001.08)")
        body_lines.append("")
        body_lines.append(f"<!-- msg_id:{message_id} -->")

        body_text = "\n".join(body_lines)

        return self.create_task(
            folder_id=folder_id,
            subject=subject,
            body=body_text,
            importance=importance,
            due_date=due_date,
            categories=categories,
        )

    def find_task_by_message_id(
        self,
        folder_id: str,
        message_id: str,
    ) -> Optional[Dict]:
        """Find a task linked to a specific email (dedup check).

        Searches task bodies for the msg_id marker comment.
        """
        tasks = self.list_tasks(folder_id=folder_id, top=100)
        marker = f"msg_id:{message_id}"
        for task in tasks:
            body = task.get("Body", {}).get("Content", "")
            if marker in body:
                return task
        return None

    # ── Batch / Cleanup Operations ──

    def list_incomplete_tasks(self, folder_id: str) -> List[Dict]:
        """List only incomplete tasks in a folder."""
        return self.list_tasks(
            folder_id=folder_id,
            filter_expr="Status ne 'Completed'",
        )

    def cleanup_completed(
        self,
        folder_id: str,
        older_than_days: int = 7,
    ) -> int:
        """Delete completed tasks older than N days. Returns count deleted."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        tasks = self.list_tasks(
            folder_id=folder_id,
            filter_expr="Status eq 'Completed'",
            top=100,
        )
        deleted = 0
        for task in tasks:
            completed_str = task.get("CompletedDateTime", {}).get("DateTime", "")
            if completed_str:
                try:
                    completed = datetime.fromisoformat(
                        completed_str.replace("Z", "+00:00")
                    )
                    if completed.tzinfo is None:
                        completed = completed.replace(tzinfo=timezone.utc)
                    if completed < cutoff:
                        self.delete_task(task["Id"])
                        deleted += 1
                except ValueError:
                    pass
        return deleted

    def get_task_stats(self, folder_id: str) -> Dict[str, int]:
        """Get task count statistics for a folder."""
        tasks = self.list_tasks(folder_id=folder_id, top=200)
        stats = {"total": len(tasks), "not_started": 0, "in_progress": 0, "completed": 0}
        for t in tasks:
            status = t.get("Status", "NotStarted")
            if status == "Completed":
                stats["completed"] += 1
            elif status == "InProgress":
                stats["in_progress"] += 1
            else:
                stats["not_started"] += 1
        return stats
