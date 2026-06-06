"""Per-conversation prompt queue for the Teams monitor persistent PTY dispatch.

Buffers incoming prompts when the PTY session is busy and dispatches them
sequentially after each turn completes. Each conversation gets its own
independent queue and worker.

Usage (from message_handler.py):
    queue = PromptQueue(bridge, config, reply_fn, log_fn)
    await queue.start()
    await queue.enqueue(conversation_id, prompt, event)
    # ... later ...
    await queue.shutdown()
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional

from .pty_bridge import PtyBridge, SessionInfo, StaleSessionError
from .config import DispatchConfig
from .trouter_client import EventMessage

logger = logging.getLogger("monitor.prompt_queue")

# ── Constants ─────────────────────────────────────────────────────────────────
_SUMMARY_DELIMITER = "---SUMMARY---"
_MAX_REPLY = 30_000   # chunking handles splitting; this is the absolute cap
_MAX_SUMMARY = 1000
_NEW_SESSION_SETTLE_SECONDS = 20


def _md_to_html(text: str) -> str:
    """Convert basic markdown to Teams-compatible HTML."""
    # **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # *italic* → <i>italic</i>
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    # - list item → • list item
    text = re.sub(r'^- ', '• ', text, flags=re.MULTILINE)
    return text


def _split_reply_summary(text: str, prompt: str) -> tuple[str, str]:
    """Parse assistant response into (reply_body, summary_body)."""
    if _SUMMARY_DELIMITER in text:
        parts = text.split(_SUMMARY_DELIMITER, 1)
        reply = parts[0].strip()
        summary = parts[1].strip()
    else:
        reply = text.strip()
        summary = reply[:300] + ("…" if len(reply) > 300 else "")

    if not reply:
        reply = f"(No output for: {prompt[:100]})"
    if not summary:
        summary = reply[:300]

    if len(reply) > _MAX_REPLY:
        reply = reply[:_MAX_REPLY - 3] + "..."
    if len(summary) > _MAX_SUMMARY:
        summary = summary[:_MAX_SUMMARY - 3] + "..."

    # Convert markdown to Teams-compatible HTML
    summary = _md_to_html(summary)

    return reply, summary


def _session_key_for(conversation_id: str) -> str:
    """Derive a stable, filesystem-safe session key from a conversation ID."""
    # Conversation IDs can contain colons and long strings; hash for safety
    h = hashlib.sha256(conversation_id.encode()).hexdigest()[:16]
    # Keep a readable prefix
    safe = conversation_id.replace(":", "_").replace("/", "_")[:24]
    return f"{safe}_{h}"


@dataclass
class QueueItem:
    """A prompt waiting to be dispatched."""
    prompt: str
    event: EventMessage
    enqueued_at: float
    dispatch_id: str = ""  # ID in the persistent DispatchStore


@dataclass
class ConversationQueue:
    """Per-conversation queue state."""
    conversation_id: str
    session_key: str
    items: asyncio.Queue
    worker_task: Optional[asyncio.Task] = None
    session_info: Optional[SessionInfo] = None
    dispatch_count: int = 0
    last_activity: float = 0.0
    startup_grace_until: float = 0.0


# Type aliases for callback functions
ReplyFn = Callable[[str, str], Awaitable[bool]]  # (conversation_id, body) -> success
LogFn = Callable[..., None]  # logging callback


class PromptQueue:
    """Manages per-conversation prompt queues backed by persistent PTY sessions."""

    def __init__(
        self,
        bridge: PtyBridge,
        dispatch_config: DispatchConfig,
        reply_fn: ReplyFn,
        log_fn: Optional[LogFn] = None,
        dispatch_store=None,
    ):
        self._bridge = bridge
        self._config = dispatch_config
        self._reply_fn = reply_fn
        self._log_fn = log_fn or (lambda *a, **kw: None)
        self._queues: dict[str, ConversationQueue] = {}
        self._running = False
        self._idle_check_task: Optional[asyncio.Task] = None
        # Env vars to pass to spawned sessions
        self._session_env: dict[str, str] = {}
        self._dispatch_store = dispatch_store  # Optional DispatchStore for persistence

    @property
    def dispatch_store(self):
        """Access the dispatch store for resume/status operations."""
        return self._dispatch_store

    @property
    def queue_info(self) -> list[dict]:
        """Return status info for all conversation queues."""
        result = []
        for cq in self._queues.values():
            result.append({
                "conversation_id": cq.conversation_id,
                "session_key": cq.session_key,
                "queue_depth": cq.items.qsize(),
                "dispatch_count": cq.dispatch_count,
                "last_activity": cq.last_activity,
                "session_ready": cq.session_info.ready if cq.session_info else False,
                "session_busy": cq.session_info.busy if cq.session_info else False,
            })
        return result

    def set_session_env(self, env: dict[str, str]) -> None:
        """Set environment variables passed to new PTY sessions."""
        self._session_env = dict(env)

    async def start(self) -> None:
        """Start the queue system and idle timeout checker."""
        self._running = True
        self._idle_check_task = asyncio.create_task(self._idle_check_loop())
        logger.info("PromptQueue started")

    async def shutdown(self) -> None:
        """Stop all workers and kill all sessions."""
        self._running = False
        if self._idle_check_task:
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass

        for cq in self._queues.values():
            if cq.worker_task:
                cq.worker_task.cancel()
                try:
                    await cq.worker_task
                except asyncio.CancelledError:
                    pass
            if cq.session_info:
                try:
                    await self._bridge.kill_session(cq.session_key)
                except Exception:
                    pass

        self._queues.clear()
        logger.info("PromptQueue shut down")

    async def enqueue(
        self,
        conversation_id: str,
        prompt: str,
        event: EventMessage,
        response_conversation: str = "",
        is_self_chat: bool = False,
    ) -> None:
        """Add a prompt to the conversation's queue.

        If this is the first prompt, spawns a PTY session and starts the worker.
        If the queue is full, sends a "busy" message to the source conversation.
        """
        session_key = _session_key_for(conversation_id)
        cq = self._queues.get(session_key)

        if cq is None:
            cq = ConversationQueue(
                conversation_id=conversation_id,
                session_key=session_key,
                items=asyncio.Queue(maxsize=self._config.pty_queue_max),
                last_activity=time.time(),
            )
            self._queues[session_key] = cq

        # Check queue capacity
        max_q = self._config.pty_queue_max
        if cq.items.qsize() >= max_q:
            logger.warning(
                "Queue full for %s (%d items) — rejecting prompt",
                conversation_id, cq.items.qsize(),
            )
            await self._reply_fn(
                conversation_id,
                f"⏳ **Busy:** Queue is full ({max_q} pending). Please try again shortly."
            )
            return

        item = QueueItem(prompt=prompt, event=event, enqueued_at=time.time())

        # Persist to dispatch store (crash recovery)
        if self._dispatch_store:
            item.dispatch_id = self._dispatch_store.add(
                prompt=prompt,
                sender_name=event.sender_name,
                sender_mri=event.sender_mri,
                conversation_id=conversation_id,
                session_key=session_key,
            )

        # Send position receipt if worker is busy (processing another item).
        # Note: qsize() alone is insufficient — the actively-processing item
        # has already been dequeued, so qsize()==0 even when the worker is busy.
        worker_busy = cq.worker_task is not None and not cq.worker_task.done()
        position = cq.items.qsize()
        if worker_busy:
            display_pos = position + 2  # in-flight item + queued items + this one
            await self._reply_fn(
                conversation_id,
                f"⏳ <b>Queued</b> (position {display_pos}): {prompt[:150]}"
            )

        await cq.items.put(item)
        cq.last_activity = time.time()

        # Start worker if not already running
        if cq.worker_task is None or cq.worker_task.done():
            cq.worker_task = asyncio.create_task(
                self._worker(cq, response_conversation, is_self_chat)
            )

    async def _worker(
        self,
        cq: ConversationQueue,
        response_conversation: str,
        is_self_chat: bool,
    ) -> None:
        """Process prompts sequentially for a conversation."""
        try:
            # Ensure PTY session is alive
            await self._ensure_session(cq, is_self_chat)

            while self._running:
                try:
                    item: QueueItem = await asyncio.wait_for(
                        cq.items.get(), timeout=60
                    )
                except asyncio.TimeoutError:
                    # No items for 60s — worker goes idle; will restart on next enqueue
                    break

                await self._dispatch_item(cq, item, response_conversation)
                cq.dispatch_count += 1
                cq.last_activity = time.time()

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Worker error for %s: %s", cq.conversation_id, e)

    async def _ensure_session(self, cq: ConversationQueue, is_self_chat: bool) -> None:
        """Ensure the PTY session for this conversation is alive and ready."""
        if cq.session_info is None:
            existing_info = self._bridge.sessions.get(cq.session_key)
            if existing_info:
                cq.session_info = existing_info
                if existing_info.ready:
                    cq.startup_grace_until = 0.0
                    logger.info(
                        "Adopting pre-warmed ready session %s for conversation %s",
                        cq.session_key, cq.conversation_id[:30],
                    )
        else:
            # Bridge reconnect clears its session map and creates replacement SessionInfo
            # objects. Drop stale queue-held references immediately instead of waiting
            # on an event queue that will never receive a ready event.
            bridge_session = self._bridge.sessions.get(cq.session_key)
            if bridge_session is not cq.session_info:
                logger.info(
                    "Dropping stale session %s (bridge reconnected or session replaced)",
                    cq.session_key,
                )
                cq.session_info = bridge_session
                if bridge_session and bridge_session.ready:
                    cq.startup_grace_until = 0.0
                    logger.info(
                        "Adopting replacement ready session %s for conversation %s",
                        cq.session_key, cq.conversation_id[:30],
                    )

        if cq.session_info and cq.session_info.ready:
            return  # Already good

        # If session exists but isn't ready yet (e.g., pre-warmed), wait for it
        # instead of spawning a new one (which would kill the booting session).
        if cq.session_info and not cq.session_info.ready:
            logger.info(
                "Session %s exists but not ready — waiting for startup",
                cq.session_key,
            )
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    evt = await asyncio.wait_for(
                        cq.session_info.event_queue.get(), timeout=5,
                    )
                    if evt.get("event") == "ready":
                        cq.session_info.ready = True
                        cq.startup_grace_until = max(
                            cq.startup_grace_until,
                            time.time() + _NEW_SESSION_SETTLE_SECONDS,
                        )
                        logger.info(
                            "Session %s ready for conversation %s",
                            cq.session_key, cq.conversation_id[:30],
                        )
                        return
                    if evt.get("event") == "exit":
                        logger.warning(
                            "Session %s exited while waiting — will respawn",
                            cq.session_key,
                        )
                        cq.session_info = None
                        break
                except asyncio.TimeoutError:
                    continue
            else:
                logger.warning(
                    "Session %s timed out waiting for ready — will respawn",
                    cq.session_key,
                )
                cq.session_info = None

        # Determine resume ID
        resume_id = ""
        if is_self_chat and self._config.persistent_session_id:
            resume_id = self._config.persistent_session_id

        cwd = self._config.working_directory or ""

        # Build environment
        env = dict(os.environ)
        env.update(self._session_env)

        try:
            cq.session_info = await self._bridge.spawn_session(
                session_key=cq.session_key,
                resume_id=resume_id,
                cwd=cwd,
                env=env,
                wait_ready=True,
                ready_timeout=120,
            )
            cq.startup_grace_until = time.time() + _NEW_SESSION_SETTLE_SECONDS
            logger.info(
                "Session %s ready for conversation %s",
                cq.session_key, cq.conversation_id[:30],
            )
        except Exception as e:
            logger.error(
                "Failed to spawn session for %s: %s",
                cq.conversation_id, e,
            )
            raise

    async def _dispatch_item(
        self,
        cq: ConversationQueue,
        item: QueueItem,
        response_conversation: str,
    ) -> None:
        """Dispatch a single prompt to the PTY session and route the response."""
        event = item.event
        prompt = item.prompt
        source_conv = event.conversation_id
        is_same = source_conv == response_conversation

        logger.info(
            "Dispatching to %s: %s",
            cq.session_key, prompt[:150],
        )

        # Send processing receipt
        if self._config.send_receipt:
            await self._reply_fn(source_conv, f"⏳ <b>Processing:</b> {prompt[:200]}")

        # Wrap the prompt with routing instructions
        wrapped_prompt = (
            f"You received the following request from {event.sender_name} "
            f"in a Teams chat (conversation ID: {event.conversation_id}).\n\n"
            f"REQUEST: {prompt}\n\n"
            f"INSTRUCTIONS:\n"
            f"1. Execute the request above. Use the skills in AGENTS.md "
            f"whenever a matching skill exists — read the skill's SKILL.md "
            f"for usage. For general ADO tasks (query, search, create, "
            f"update, comment), use the ado skill (cd skills/ado && "
            f"python -m scripts.ado_query / ado_update). For Landing "
            f"Zone-specific tasks (LZ sync, grading, WoW, state machine), "
            f"use the landing-zone skill (cd skills/landing-zone && "
            f"python -m scripts.lz_update / lz_query / lz_sync / "
            f"lz_analyze). Do NOT write ad-hoc scripts or raw REST API "
            f"calls when a skill already handles the operation.\n"
            f"2. Respond directly with your answer — your response will be "
            f"captured automatically and delivered to the chat.\n"
            f"3. CRITICAL: Do NOT use the Teams skill, do NOT send messages, "
            f"do NOT open browsers, do NOT call any Teams API scripts. The "
            f"monitor service handles all Teams communication. Just respond "
            f"naturally.\n"
            f"4. Use Teams-compatible HTML for rich formatting (bold, lists, "
            f"links). Keep the response concise and conversational.\n"
            f"5. Do NOT include execution trace, tool output, or debugging "
            f"artifacts in your response — only the final message the "
            f"recipient should see.\n"
            f"6. MANDATORY: At the very end of your response, add a line "
            f"containing only '---SUMMARY---' followed by a structured "
            f"completion summary including:\n"
            f"   - What actions you took (1-2 sentences)\n"
            f"   - Any files generated, modified, or sent (list paths/names)\n"
            f"   - Any errors or issues encountered\n"
            f"   - Status: success / partial / failed\n"
            f"   This summary is required even if the task seems trivial. "
            f"It will be logged for the operator."
        )

        timeout = self._config.timeout_minutes * 60

        # Mark in_progress in persistent store
        if self._dispatch_store and item.dispatch_id:
            self._dispatch_store.update_status(item.dispatch_id, "in_progress")

        try:
            settle_remaining = cq.startup_grace_until - time.time()
            if settle_remaining > 0:
                logger.info(
                    "Session %s warming for %.1fs before first prompt dispatch",
                    cq.session_key,
                    settle_remaining,
                )
                await asyncio.sleep(settle_remaining)

            response = await self._bridge.write_prompt(
                cq.session_key, wrapped_prompt, timeout=timeout,
                activity_timeout=self._config.pty_stale_dispatch_timeout_minutes * 60,
            )

            reply_body, summary_body = _split_reply_summary(response, prompt)

            self._log_fn(
                prompt, event, kind="dispatch",
                result="success", output_summary=summary_body[:500],
            )

            # Mark done in persistent store
            if self._dispatch_store and item.dispatch_id:
                self._dispatch_store.update_status(
                    item.dispatch_id, "done",
                    result_summary=summary_body[:500],
                )

            # Send reply first, then summary — sequential to guarantee order
            reply_result = await self._reply_fn(source_conv, reply_body)

            # Send completion summary to the response conversation
            summary_results = []
            if response_conversation:
                if is_same:
                    if summary_body and summary_body != reply_body[:300]:
                        summary_results.append(await self._reply_fn(
                            response_conversation,
                            f"📋 <b>Summary:</b> {summary_body}",
                        ))
                else:
                    summary_results.append(await self._reply_fn(
                        response_conversation,
                        f"✅ <b>Done:</b> {prompt[:100]}\n\n{summary_body}",
                    ))

            results = [reply_result] + summary_results

            # Check delivery results — _reply_fn returns bool; exceptions mean crash
            delivery_failures = []
            for i, res in enumerate(results):
                if isinstance(res, Exception):
                    delivery_failures.append(f"task[{i}] raised {type(res).__name__}: {res}")
                elif res is False:
                    delivery_failures.append(f"task[{i}] returned False (delivery failed)")

            if delivery_failures:
                logger.warning(
                    "Dispatch for %s had %d delivery failure(s): %s",
                    cq.session_key, len(delivery_failures), "; ".join(delivery_failures),
                )
                self._log_fn(
                    prompt, event, kind="dispatch",
                    result="delivery_warning",
                    output_summary=f"Agent succeeded but {len(delivery_failures)} reply(s) failed to deliver",
                )

            logger.info(
                "Dispatch complete for %s: reply=%d chars, summary=%d chars",
                cq.session_key, len(reply_body), len(summary_body),
            )

        except StaleSessionError as e:
            logger.error(
                "Stale dispatch for %s — session contention detected: %s",
                cq.session_key, e,
            )
            self._log_fn(
                prompt, event, kind="dispatch",
                result="contention",
                output_summary=f"Session contention: {e}",
            )
            if self._dispatch_store and item.dispatch_id:
                self._dispatch_store.update_status(
                    item.dispatch_id, "timeout",
                    error=f"Session contention: {e}",
                )
            # Kill the contended session so next dispatch spawns fresh
            try:
                await self._bridge.kill_session(cq.session_key)
            except Exception:
                pass
            cq.session_info = None
            contention_msg = (
                f"⚠️ <b>Session contention:</b> {prompt[:100]}<br><br>"
                f"The PTY session appears to be occupied by another client. "
                f"A fresh session will be used for the next dispatch."
            )
            await self._reply_fn(source_conv, contention_msg)
            if response_conversation and not is_same:
                await self._reply_fn(response_conversation, contention_msg)

        except TimeoutError:
            logger.error(
                "Dispatch timed out for %s after %ds",
                cq.session_key, timeout,
            )
            self._log_fn(
                prompt, event, kind="dispatch",
                result="timeout", output_summary=f"Timed out after {timeout}s",
            )
            # Mark timeout in persistent store
            if self._dispatch_store and item.dispatch_id:
                self._dispatch_store.update_status(
                    item.dispatch_id, "timeout",
                    error=f"Timed out after {timeout}s",
                )
            timeout_msg = f"⏰ **Timed out:** {prompt[:100]} (after {timeout // 60}min)"
            await self._reply_fn(source_conv, timeout_msg)
            # Also notify response conversation if different
            if response_conversation and not is_same:
                await self._reply_fn(response_conversation, timeout_msg)

        except RuntimeError as e:
            logger.error("Dispatch error for %s: %s", cq.session_key, e)
            self._log_fn(
                prompt, event, kind="dispatch",
                result="error", output_summary=str(e)[:500],
            )
            # Mark failed in persistent store
            if self._dispatch_store and item.dispatch_id:
                self._dispatch_store.update_status(
                    item.dispatch_id, "failed",
                    error=str(e)[:500],
                )
            error_msg = f"❌ **Error:** {prompt[:100]}\n\n{str(e)[:200]}"
            await self._reply_fn(source_conv, error_msg)
            # Also notify response conversation if different
            if response_conversation and not is_same:
                await self._reply_fn(response_conversation, error_msg)
            # Session may have died — clear session info so next dispatch re-spawns
            cq.session_info = None

    async def _idle_check_loop(self) -> None:
        """Periodically kill idle PTY sessions to reclaim resources."""
        idle_timeout = self._config.pty_idle_timeout_minutes * 60
        try:
            while self._running:
                await asyncio.sleep(60)  # check every minute
                now = time.time()
                to_remove = []
                for key, cq in self._queues.items():
                    if (cq.items.qsize() == 0 and
                            cq.session_info and
                            not cq.session_info.busy and
                            now - cq.last_activity > idle_timeout):
                        logger.info(
                            "Idle timeout for %s (idle %ds) — killing session",
                            cq.conversation_id[:30],
                            int(now - cq.last_activity),
                        )
                        try:
                            await self._bridge.kill_session(key)
                        except Exception:
                            pass
                        cq.session_info = None
                        to_remove.append(key)

                for key in to_remove:
                    cq = self._queues[key]
                    if cq.worker_task and not cq.worker_task.done():
                        continue  # keep queue if worker is still running
                    del self._queues[key]

        except asyncio.CancelledError:
            pass
