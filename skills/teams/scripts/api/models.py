"""Data models for Teams API responses.

Maps the chatsvc/CSA JSON shapes (discovered via HAR analysis) to typed
Python dataclasses for clean consumption by the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Member:
    """A chat or channel member."""
    mri: str = ""
    object_id: str = ""
    display_name: str = ""
    role: str = ""
    is_muted: bool = False

    @classmethod
    def from_chatsvc(cls, data: dict) -> Member:
        return cls(
            mri=data.get("mri", ""),
            object_id=data.get("objectId", ""),
            display_name=data.get("displayName", data.get("imdisplayname", "")),
            role=data.get("role", ""),
            is_muted=data.get("isMuted", False),
        )


@dataclass
class Message:
    """A Teams chat/channel message."""
    id: str = ""
    conversation_id: str = ""
    sender_mri: str = ""
    sender_name: str = ""
    message_type: str = ""
    content: str = ""
    compose_time: str = ""
    client_message_id: str = ""
    properties: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict (excludes raw payload)."""
        return {
            "id": self.id,
            "messageType": self.message_type,
            "content": self.content,
            "senderName": self.sender_name,
            "senderId": self.sender_id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }

    @classmethod
    def from_chatsvc(cls, data: dict) -> Message:
        # Sender MRI is in the 'from' URL: .../contacts/8:orgid:GUID
        from_url = data.get("from", "")
        sender_mri = from_url.rsplit("/", 1)[-1] if "/" in from_url else from_url
        return cls(
            id=str(data.get("id", "")),
            conversation_id=data.get("conversationid", ""),
            sender_mri=sender_mri,
            sender_name=data.get("imdisplayname", ""),
            message_type=data.get("messagetype", ""),
            content=data.get("content", ""),
            compose_time=data.get("composetime", ""),
            client_message_id=str(data.get("clientmessageid", "")),
            properties=data.get("properties", {}),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversationId": self.conversation_id,
            "senderMri": self.sender_mri,
            "senderName": self.sender_name,
            "messageType": self.message_type,
            "content": self.content,
            "composeTime": self.compose_time,
        }


@dataclass
class Chat:
    """A Teams chat (1:1, group, or meeting)."""
    id: str = ""
    title: Optional[str] = None
    chat_type: str = ""  # "chat", "meeting", etc.
    thread_type: str = ""
    is_one_on_one: bool = False
    is_read: bool = True
    created_at: str = ""
    members: list[Member] = field(default_factory=list)
    last_message: Optional[dict] = None

    @classmethod
    def from_csa(cls, data: dict) -> Chat:
        members = [
            Member.from_chatsvc(m) for m in data.get("members", [])
        ]
        return cls(
            id=data.get("id", ""),
            title=data.get("title"),
            chat_type=data.get("chatType", ""),
            thread_type=data.get("threadType", ""),
            is_one_on_one=data.get("isOneOnOne", False),
            is_read=data.get("isRead", True),
            created_at=data.get("createdAt", ""),
            members=members,
            last_message=data.get("lastMessage"),
        )

    def display_name(self) -> str:
        """Derive a display name — title if set, else member names."""
        if self.title:
            return self.title
        names = [m.display_name for m in self.members if m.display_name]
        return ", ".join(names[:4]) or self.id[:40]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "displayName": self.display_name(),
            "chatType": self.chat_type,
            "threadType": self.thread_type,
            "isOneOnOne": self.is_one_on_one,
            "isRead": self.is_read,
            "createdAt": self.created_at,
            "memberCount": len(self.members),
            "members": [
                {"mri": m.mri, "displayName": m.display_name, "role": m.role}
                for m in self.members
            ],
        }


@dataclass
class Channel:
    """A Teams channel."""
    id: str = ""
    display_name: str = ""
    description: str = ""
    parent_team_id: str = ""
    is_general: bool = False
    is_favorite: bool = False
    is_member: bool = False

    @classmethod
    def from_csa(cls, data: dict) -> Channel:
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            description=data.get("description", ""),
            parent_team_id=data.get("parentTeamId", ""),
            is_general=data.get("isGeneral", False),
            is_favorite=data.get("isFavorite", False),
            is_member=data.get("isMember", False),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "description": self.description,
            "parentTeamId": self.parent_team_id,
            "isGeneral": self.is_general,
            "isFavorite": self.is_favorite,
        }


@dataclass
class Team:
    """A Teams team (workspace)."""
    id: str = ""
    display_name: str = ""
    channels: list[Channel] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "displayName": self.display_name,
            "channels": [c.to_dict() for c in self.channels],
        }
