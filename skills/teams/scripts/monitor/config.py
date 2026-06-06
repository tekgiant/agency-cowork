"""Configuration manager for the Teams monitor service.

Global config lives at ~/.agency-cowork/monitor-config.json.
Per-workspace settings (enabled, keyword, conversations, dispatch) are keyed
by normalised workspace path.  Identity and connection are global (one Teams
identity per user).  A single monitor service reads all workspaces and routes
messages to the correct agent CLI based on keyword + conversation matching.

Legacy per-repo config at skills/teams/monitor/monitor-config.json is
auto-migrated on first load.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("monitor.config")

# ── Global config location ──────────────────────────────────────────────────
_GLOBAL_DIR = Path.home() / ".agency-cowork"
_GLOBAL_CONFIG = _GLOBAL_DIR / "monitor-config.json"

# Legacy per-repo location (for migration only)
_LEGACY_MONITOR_DIR = Path(__file__).resolve().parent.parent.parent / "monitor"
_LEGACY_CONFIG_FILE = _LEGACY_MONITOR_DIR / "monitor-config.json"
# agentconfig.json at repo root (legacy — still read for backward compat)
_AGENT_CONFIG = Path(__file__).resolve().parent.parent.parent.parent.parent / "agentconfig.json"


def _normalise_workspace_key(workspace_dir: str | Path) -> str:
    """Normalise a workspace path to a stable dict key.

    On Windows paths are lowercased; on all platforms they are resolved to
    absolute form with forward slashes stripped and trailing separators removed.
    """
    p = str(Path(workspace_dir).resolve())
    if sys.platform == "win32":
        p = p.lower()
    return p


@dataclass
class MonitoredConversation:
    id: str
    name: str
    type: str  # "Self", "OneOnOne", "Group", "Channel", "Wildcard"
    added: str = ""

    def __post_init__(self):
        if not self.added:
            self.added = datetime.now(timezone.utc).isoformat()


@dataclass
class AuthorizedSender:
    """Global identity — one per user, shared across all workspaces."""
    mri: str = "8:orgid:00000000-0000-0000-0000-000000000000"
    displayName: str = "Your Name"
    upn: str = "user@contoso.com"


@dataclass
class DispatchConfig:
    command: str = "agency copilot"
    working_directory: str = ""  # defaults to workspace dir at runtime
    timeout_minutes: int = 30
    send_receipt: bool = True
    send_result_summary: bool = False
    response_conversation: str = "48:notes"
    persistent_session_id: str = ""
    # ── Persistent PTY bridge settings ──
    use_persistent_pty: bool = True
    pty_warmup_conversations: list = field(default_factory=lambda: ["48:notes"])
    pty_queue_max: int = 5
    pty_idle_timeout_minutes: int = 60
    pty_max_sessions: int = 5
    pty_stale_dispatch_timeout_minutes: int = 5  # activity timeout for contention detection


@dataclass
class ConnectionConfig:
    """Global connection settings — shared across all workspaces."""
    trouter_gateway: str = "go-msit.trouter.teams.microsoft.com"
    registrar_url: str = "https://teams.cloud.microsoft/registrar/prod/V2/registrations"
    app_id: str = "AgencyCoworkMonitor"
    reconnect_delay_seconds: int = 5
    max_reconnect_delay_seconds: int = 300
    token_refresh_minutes: int = 50
    heartbeat_interval_seconds: int = 30
    chatsvc_region: str = ""


@dataclass
class WorkspaceConfig:
    """Per-workspace monitor settings."""
    enabled: bool = False  # safe default: off
    keyword: str = "@agent"
    reply_prefix: str = "Agency Cowork: "
    monitored_conversations: list[MonitoredConversation] = field(default_factory=list)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)

    def __post_init__(self):
        if not self.monitored_conversations:
            self.monitored_conversations = [
                MonitoredConversation(
                    id="48:notes", name="Self (Notes)", type="Self",
                )
            ]
        if not self.dispatch.persistent_session_id:
            self.dispatch.persistent_session_id = str(uuid.uuid4())

    @property
    def monitored_ids(self) -> set[str]:
        return {c.id for c in self.monitored_conversations}

    def is_monitored(self, conversation_id: str) -> bool:
        return "*" in self.monitored_ids or conversation_id in self.monitored_ids

    def add_conversation(self, conv_id: str, name: str, conv_type: str) -> bool:
        if self.is_monitored(conv_id):
            return False
        self.monitored_conversations.append(
            MonitoredConversation(id=conv_id, name=name, type=conv_type)
        )
        return True

    def remove_conversation(self, conv_id: str) -> bool:
        before = len(self.monitored_conversations)
        self.monitored_conversations = [
            c for c in self.monitored_conversations if c.id != conv_id
        ]
        return len(self.monitored_conversations) < before


@dataclass
class GlobalConfig:
    """Top-level config: global identity/connection + per-workspace settings."""
    identity: AuthorizedSender = field(default_factory=AuthorizedSender)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    workspaces: dict[str, WorkspaceConfig] = field(default_factory=dict)

    def get_workspace(self, workspace_dir: str | Path) -> WorkspaceConfig:
        """Get config for a workspace. Returns disabled default if not found."""
        key = _normalise_workspace_key(workspace_dir)
        return self.workspaces.get(key, WorkspaceConfig(enabled=False))

    def set_workspace(self, workspace_dir: str | Path, ws: WorkspaceConfig) -> None:
        key = _normalise_workspace_key(workspace_dir)
        self.workspaces[key] = ws

    def enabled_workspaces(self) -> dict[str, WorkspaceConfig]:
        """Return only workspaces with enabled=True."""
        return {k: v for k, v in self.workspaces.items() if v.enabled}


# ── Backward compatibility: MonitorConfig ────────────────────────────────────
# MessageHandler and service.py expect a MonitorConfig with all fields merged.
# This assembles one from GlobalConfig + a specific WorkspaceConfig.

@dataclass
class MonitorConfig:
    """Assembled config for a single workspace — used by MessageHandler."""
    enabled: bool = False
    keyword: str = "@agent"
    reply_prefix: str = "Agency Cowork: "
    authorized_sender: AuthorizedSender = field(default_factory=AuthorizedSender)
    monitored_conversations: list[MonitoredConversation] = field(default_factory=list)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
    connection: ConnectionConfig = field(default_factory=ConnectionConfig)
    workspace_dir: str = ""  # which workspace this config is for

    def __post_init__(self):
        if not self.monitored_conversations:
            self.monitored_conversations = [
                MonitoredConversation(
                    id="48:notes", name="Self (Notes)", type="Self",
                )
            ]
        if not self.dispatch.persistent_session_id:
            self.dispatch.persistent_session_id = str(uuid.uuid4())

    @property
    def monitored_ids(self) -> set[str]:
        return {c.id for c in self.monitored_conversations}

    def is_monitored(self, conversation_id: str) -> bool:
        return "*" in self.monitored_ids or conversation_id in self.monitored_ids

    def add_conversation(self, conv_id: str, name: str, conv_type: str) -> bool:
        if self.is_monitored(conv_id):
            return False
        self.monitored_conversations.append(
            MonitoredConversation(id=conv_id, name=name, type=conv_type)
        )
        return True

    def remove_conversation(self, conv_id: str) -> bool:
        before = len(self.monitored_conversations)
        self.monitored_conversations = [
            c for c in self.monitored_conversations if c.id != conv_id
        ]
        return len(self.monitored_conversations) < before


def assemble_monitor_config(
    global_cfg: GlobalConfig, workspace_dir: str | Path
) -> MonitorConfig:
    """Assemble a MonitorConfig for one workspace from the global config."""
    ws = global_cfg.get_workspace(workspace_dir)

    # Validate working_directory -- fall back to workspace_dir if missing or nonexistent
    wd = ws.dispatch.working_directory
    if wd and not Path(wd).is_dir():
        logger.warning(
            "dispatch.working_directory '%s' does not exist -- falling back to workspace dir '%s'",
            wd, workspace_dir,
        )
        ws.dispatch.working_directory = str(Path(workspace_dir).resolve())

    # Ensure command is compatible with PTY mode (no -p flag when PTY is enabled)
    if ws.dispatch.use_persistent_pty and " -p" in ws.dispatch.command:
        logger.warning(
            "dispatch.command contains '-p' (piped mode) but use_persistent_pty is true -- removing '-p'"
        )
        ws.dispatch.command = ws.dispatch.command.replace(" -p", "")

    return MonitorConfig(
        enabled=ws.enabled,
        keyword=ws.keyword,
        reply_prefix=ws.reply_prefix,
        authorized_sender=global_cfg.identity,
        monitored_conversations=ws.monitored_conversations,
        dispatch=ws.dispatch,
        connection=global_cfg.connection,
        workspace_dir=str(Path(workspace_dir).resolve()),
    )


# ── Serialisation helpers ────────────────────────────────────────────────────

def _ws_to_dict(ws: WorkspaceConfig) -> dict:
    d = asdict(ws)
    return d


def _ws_from_dict(data: dict) -> WorkspaceConfig:
    ws = WorkspaceConfig(
        enabled=data.get("enabled", False),
        keyword=data.get("keyword", "@agent"),
        reply_prefix=data.get("reply_prefix", "Agency Cowork: "),
    )
    if "monitored_conversations" in data:
        ws.monitored_conversations = [
            MonitoredConversation(
                id=c["id"], name=c.get("name", ""), type=c.get("type", "Unknown"),
                added=c.get("added", ""),
            )
            for c in data["monitored_conversations"]
        ]
    if "dispatch" in data:
        d = data["dispatch"]
        ws.dispatch = DispatchConfig(
            command=d.get("command", ws.dispatch.command),
            working_directory=d.get("working_directory", ws.dispatch.working_directory),
            timeout_minutes=d.get("timeout_minutes", ws.dispatch.timeout_minutes),
            send_receipt=d.get("send_receipt", ws.dispatch.send_receipt),
            send_result_summary=d.get("send_result_summary", ws.dispatch.send_result_summary),
            response_conversation=d.get("response_conversation", ws.dispatch.response_conversation),
            persistent_session_id=d.get("persistent_session_id", ""),
            use_persistent_pty=d.get("use_persistent_pty", ws.dispatch.use_persistent_pty),
            pty_warmup_conversations=d.get("pty_warmup_conversations", ws.dispatch.pty_warmup_conversations),
            pty_queue_max=d.get("pty_queue_max", ws.dispatch.pty_queue_max),
            pty_idle_timeout_minutes=d.get("pty_idle_timeout_minutes", ws.dispatch.pty_idle_timeout_minutes),
            pty_max_sessions=d.get("pty_max_sessions", ws.dispatch.pty_max_sessions),
            pty_stale_dispatch_timeout_minutes=d.get("pty_stale_dispatch_timeout_minutes", ws.dispatch.pty_stale_dispatch_timeout_minutes),
        )
    return ws


def _global_to_dict(cfg: GlobalConfig) -> dict:
    return {
        "identity": asdict(cfg.identity),
        "connection": asdict(cfg.connection),
        "workspaces": {k: _ws_to_dict(v) for k, v in cfg.workspaces.items()},
    }


def _global_from_dict(data: dict) -> GlobalConfig:
    cfg = GlobalConfig()
    if "identity" in data:
        s = data["identity"]
        cfg.identity = AuthorizedSender(
            mri=s.get("mri", cfg.identity.mri),
            displayName=s.get("displayName", cfg.identity.displayName),
            upn=s.get("upn", cfg.identity.upn),
        )
    if "connection" in data:
        c = data["connection"]
        cfg.connection = ConnectionConfig(
            trouter_gateway=c.get("trouter_gateway", cfg.connection.trouter_gateway),
            registrar_url=c.get("registrar_url", cfg.connection.registrar_url),
            app_id=c.get("app_id", cfg.connection.app_id),
            reconnect_delay_seconds=c.get("reconnect_delay_seconds", cfg.connection.reconnect_delay_seconds),
            max_reconnect_delay_seconds=c.get("max_reconnect_delay_seconds", cfg.connection.max_reconnect_delay_seconds),
            token_refresh_minutes=c.get("token_refresh_minutes", cfg.connection.token_refresh_minutes),
            heartbeat_interval_seconds=c.get("heartbeat_interval_seconds", cfg.connection.heartbeat_interval_seconds),
            chatsvc_region=c.get("chatsvc_region", cfg.connection.chatsvc_region),
        )
    if "workspaces" in data:
        for key, ws_data in data["workspaces"].items():
            cfg.workspaces[key] = _ws_from_dict(ws_data)
    return cfg


# ── Legacy format conversion ────────────────────────────────────────────────

def _legacy_to_global(data: dict, workspace_dir: str | Path) -> GlobalConfig:
    """Convert a legacy per-repo monitor-config.json into a GlobalConfig."""
    cfg = GlobalConfig()

    # Identity from authorized_sender
    if "authorized_sender" in data:
        s = data["authorized_sender"]
        cfg.identity = AuthorizedSender(
            mri=s.get("mri", cfg.identity.mri),
            displayName=s.get("displayName", cfg.identity.displayName),
            upn=s.get("upn", cfg.identity.upn),
        )

    # Connection
    if "connection" in data:
        c = data["connection"]
        cfg.connection = ConnectionConfig(
            trouter_gateway=c.get("trouter_gateway", cfg.connection.trouter_gateway),
            registrar_url=c.get("registrar_url", cfg.connection.registrar_url),
            app_id=c.get("app_id", cfg.connection.app_id),
            reconnect_delay_seconds=c.get("reconnect_delay_seconds", cfg.connection.reconnect_delay_seconds),
            max_reconnect_delay_seconds=c.get("max_reconnect_delay_seconds", cfg.connection.max_reconnect_delay_seconds),
            token_refresh_minutes=c.get("token_refresh_minutes", cfg.connection.token_refresh_minutes),
            heartbeat_interval_seconds=c.get("heartbeat_interval_seconds", cfg.connection.heartbeat_interval_seconds),
            chatsvc_region=c.get("chatsvc_region", cfg.connection.chatsvc_region),
        )

    # Workspace entry from per-repo fields
    ws = WorkspaceConfig(
        enabled=data.get("enabled", False),
        keyword=data.get("keyword", "@agent"),
        reply_prefix=data.get("reply_prefix", "Agency Cowork: "),
    )
    if "monitored_conversations" in data:
        ws.monitored_conversations = [
            MonitoredConversation(
                id=c["id"], name=c.get("name", ""), type=c.get("type", "Unknown"),
                added=c.get("added", ""),
            )
            for c in data["monitored_conversations"]
        ]
    if "dispatch" in data:
        d = data["dispatch"]
        ws.dispatch = DispatchConfig(
            command=d.get("command", ws.dispatch.command),
            working_directory=d.get("working_directory", ws.dispatch.working_directory),
            timeout_minutes=d.get("timeout_minutes", ws.dispatch.timeout_minutes),
            send_receipt=d.get("send_receipt", ws.dispatch.send_receipt),
            send_result_summary=d.get("send_result_summary", ws.dispatch.send_result_summary),
            response_conversation=d.get("response_conversation", ws.dispatch.response_conversation),
            persistent_session_id=d.get("persistent_session_id", ""),
            use_persistent_pty=d.get("use_persistent_pty", ws.dispatch.use_persistent_pty),
            pty_warmup_conversations=d.get("pty_warmup_conversations", ws.dispatch.pty_warmup_conversations),
            pty_queue_max=d.get("pty_queue_max", ws.dispatch.pty_queue_max),
            pty_idle_timeout_minutes=d.get("pty_idle_timeout_minutes", ws.dispatch.pty_idle_timeout_minutes),
            pty_max_sessions=d.get("pty_max_sessions", ws.dispatch.pty_max_sessions),
            pty_stale_dispatch_timeout_minutes=d.get("pty_stale_dispatch_timeout_minutes", ws.dispatch.pty_stale_dispatch_timeout_minutes),
        )

    key = _normalise_workspace_key(workspace_dir)
    cfg.workspaces[key] = ws
    return cfg


# ── Public API ───────────────────────────────────────────────────────────────

def load_global_config() -> GlobalConfig:
    """Load the global config from ~/.agency-cowork/monitor-config.json.

    If the file does not exist, attempts to migrate a legacy per-repo config.
    If no legacy config exists either, returns a default (all disabled).
    """
    if _GLOBAL_CONFIG.exists():
        try:
            with open(_GLOBAL_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = _global_from_dict(data)
        except (json.JSONDecodeError, OSError):
            cfg = GlobalConfig()
    else:
        # Try migrating legacy per-repo config
        cfg = _migrate_legacy_config()

    # Backward compat: apply overrides from agentconfig.json if present
    _apply_agent_config_overrides(cfg)

    return cfg


def save_global_config(cfg: GlobalConfig) -> Path:
    """Save global config to ~/.agency-cowork/monitor-config.json."""
    _GLOBAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(_GLOBAL_CONFIG, "w", encoding="utf-8") as f:
        json.dump(_global_to_dict(cfg), f, indent=2)
    return _GLOBAL_CONFIG


def load_config(workspace_dir: Optional[str | Path] = None) -> MonitorConfig:
    """Load an assembled MonitorConfig for a specific workspace.

    This is the backward-compatible entry point used by service.py and
    message_handler.py.  If workspace_dir is None, uses the repo root
    derived from this file's location (legacy behaviour).
    """
    global_cfg = load_global_config()
    if workspace_dir is None:
        # Legacy: derive from script location → repo root
        workspace_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    return assemble_monitor_config(global_cfg, workspace_dir)


def save_config(config: MonitorConfig, workspace_dir: Optional[str | Path] = None) -> Path:
    """Save a MonitorConfig back to the global file under its workspace key.

    Updates only the workspace entry and global identity/connection.
    """
    global_cfg = load_global_config()

    # Update global identity + connection from the assembled config
    global_cfg.identity = config.authorized_sender
    global_cfg.connection = config.connection

    # Update workspace entry
    ws_dir = workspace_dir or config.workspace_dir
    if not ws_dir:
        ws_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    ws = WorkspaceConfig(
        enabled=config.enabled,
        keyword=config.keyword,
        reply_prefix=config.reply_prefix,
        monitored_conversations=config.monitored_conversations,
        dispatch=config.dispatch,
    )
    global_cfg.set_workspace(ws_dir, ws)

    return save_global_config(global_cfg)


def set_enabled(enabled: bool, workspace_dir: Optional[str | Path] = None) -> None:
    """Set the enabled state for a workspace."""
    global_cfg = load_global_config()
    if workspace_dir is None:
        workspace_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    key = _normalise_workspace_key(workspace_dir)
    ws = global_cfg.workspaces.get(key, WorkspaceConfig())
    ws.enabled = enabled
    global_cfg.workspaces[key] = ws
    save_global_config(global_cfg)

    # Also update legacy agentconfig.json for backward compat
    try:
        _write_agent_config_field("enabled", enabled)
    except Exception:
        pass


# ── Legacy migration ─────────────────────────────────────────────────────────

def _migrate_legacy_config() -> GlobalConfig:
    """Migrate a legacy per-repo monitor-config.json to global config."""
    if _LEGACY_CONFIG_FILE.exists():
        try:
            with open(_LEGACY_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Derive workspace dir from legacy file location
            workspace_dir = _LEGACY_CONFIG_FILE.parent.parent.parent.parent
            cfg = _legacy_to_global(data, workspace_dir)

            # Save to global location
            save_global_config(cfg)

            # Rename legacy file so it's not re-migrated
            backup = _LEGACY_CONFIG_FILE.with_suffix(".json.migrated")
            _LEGACY_CONFIG_FILE.rename(backup)

            return cfg
        except (json.JSONDecodeError, OSError):
            pass

    return GlobalConfig()


def migrate_workspace_config(
    legacy_path: Path, workspace_dir: str | Path
) -> bool:
    """Migrate a legacy per-repo config from an arbitrary path.

    Called by Electron main.js (via subprocess) or setup scripts for
    workspaces that aren't the one this script lives in.
    Returns True if migration happened.
    """
    if not legacy_path.exists():
        return False
    try:
        with open(legacy_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    global_cfg = load_global_config()
    legacy_global = _legacy_to_global(data, workspace_dir)

    # Merge: update identity/connection if current is placeholder
    if global_cfg.identity.mri.endswith("00000000-0000-0000-0000-000000000000"):
        global_cfg.identity = legacy_global.identity
    # Always take connection from legacy if it has non-default values
    if legacy_global.connection.chatsvc_region:
        global_cfg.connection = legacy_global.connection

    # Merge workspace entry (don't overwrite if already exists and enabled)
    key = _normalise_workspace_key(workspace_dir)
    if key not in global_cfg.workspaces or not global_cfg.workspaces[key].enabled:
        for k, v in legacy_global.workspaces.items():
            global_cfg.workspaces[k] = v

    save_global_config(global_cfg)

    # Rename legacy file
    backup = legacy_path.with_suffix(".json.migrated")
    try:
        legacy_path.rename(backup)
    except OSError:
        pass

    return True


# ── Legacy agentconfig.json helpers ──────────────────────────────────────────

def _read_agent_config() -> dict:
    """Read the monitor section from agentconfig.json (repo root)."""
    try:
        if _AGENT_CONFIG.exists():
            with open(_AGENT_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("monitor", {})
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_agent_config_field(field: str, value) -> None:
    """Write a single field into agentconfig.json → monitor section."""
    try:
        data = {}
        if _AGENT_CONFIG.exists():
            with open(_AGENT_CONFIG, "r", encoding="utf-8") as f:
                data = json.load(f)
        data.setdefault("monitor", {})[field] = value
        with open(_AGENT_CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(f"Failed to update agentconfig.json: {e}")


def _apply_agent_config_overrides(cfg: GlobalConfig) -> None:
    """Apply backward-compat overrides from agentconfig.json.

    Only used during migration period — once all workspaces are in global
    config, agentconfig.json monitor section can be removed.
    """
    agent_monitor = _read_agent_config()
    if not agent_monitor:
        return

    workspace_dir = Path(__file__).resolve().parent.parent.parent.parent.parent
    key = _normalise_workspace_key(workspace_dir)

    # Global config is the source of truth once a workspace entry exists.
    # agentconfig.json only backfills a workspace during migration, instead of
    # overriding a newer global setting and silently disabling the service.
    if key not in cfg.workspaces:
        ws = WorkspaceConfig()
        if "enabled" in agent_monitor:
            ws.enabled = bool(agent_monitor["enabled"])
        if "keyword" in agent_monitor:
            ws.keyword = agent_monitor["keyword"]
        if "replyPrefix" in agent_monitor:
            ws.reply_prefix = agent_monitor["replyPrefix"]
        cfg.workspaces[key] = ws


# ── Utility: global config path (for external callers) ──────────────────────

def global_config_path() -> Path:
    """Return the path to the global config file."""
    return _GLOBAL_CONFIG


def global_config_dir() -> Path:
    """Return the path to the global config directory."""
    return _GLOBAL_DIR
