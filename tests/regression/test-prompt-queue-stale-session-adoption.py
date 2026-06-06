#!/usr/bin/env python3
"""
Regression test for issue #194.

Date: 2026-04-03
Bug: PromptQueue kept stale SessionInfo references after PTY bridge reconnects.
Root cause: _ensure_session() only adopted bridge sessions when cq.session_info was None,
so stale SessionInfo objects waited 120s on dead event_queue instances.
Reference: GitHub issue #194
"""

from __future__ import annotations

import asyncio
import pathlib
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.teams.scripts.monitor.config import DispatchConfig
from skills.teams.scripts.monitor.prompt_queue import ConversationQueue, PromptQueue
from skills.teams.scripts.monitor.pty_bridge import SessionInfo


class FakeBridge:
    def __init__(self, sessions=None):
        self._sessions = dict(sessions or {})
        self.spawn_calls = []

    @property
    def sessions(self):
        return dict(self._sessions)

    async def spawn_session(self, **kwargs):
        self.spawn_calls.append(kwargs)
        session = SessionInfo(session_key=kwargs["session_key"], ready=True)
        self._sessions[kwargs["session_key"]] = session
        return session


async def _reply(_conversation_id: str, _body: str) -> bool:
    return True


async def test_adopts_replacement_session_immediately():
    stale = SessionInfo(session_key="conv_key", ready=False)
    replacement = SessionInfo(session_key="conv_key", ready=True)
    bridge = FakeBridge({"conv_key": replacement})
    queue = PromptQueue(bridge, DispatchConfig(), _reply)
    cq = ConversationQueue(
        conversation_id="48:notes",
        session_key="conv_key",
        items=asyncio.Queue(),
        session_info=stale,
    )

    await queue._ensure_session(cq, is_self_chat=False)

    assert cq.session_info is replacement, "PromptQueue should adopt the replacement bridge session"
    assert not bridge.spawn_calls, "PromptQueue should not respawn when a replacement ready session exists"


async def test_respawns_when_stale_session_has_no_replacement():
    stale = SessionInfo(session_key="conv_key", ready=False)
    bridge = FakeBridge()
    queue = PromptQueue(bridge, DispatchConfig(), _reply)
    cq = ConversationQueue(
        conversation_id="48:notes",
        session_key="conv_key",
        items=asyncio.Queue(),
        session_info=stale,
    )

    await queue._ensure_session(cq, is_self_chat=False)

    assert cq.session_info is not stale, "PromptQueue should drop the stale session reference"
    assert bridge.spawn_calls, "PromptQueue should respawn when the bridge has no replacement session"


async def main():
    await test_adopts_replacement_session_immediately()
    await test_respawns_when_stale_session_has_no_replacement()
    print("PASS: stale SessionInfo references are replaced immediately after bridge reconnect")


if __name__ == "__main__":
    asyncio.run(main())
