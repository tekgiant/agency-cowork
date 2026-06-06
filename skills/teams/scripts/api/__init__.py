"""Direct Teams API client — bypasses MCP for speed and reliability.

Key modules:
- client: TeamsApiClient (Playwright browser auth for reads, direct HTTP for writes)
- sync_cache: Populate cache files directly from API or stdin JSON
- chats / messages / teams_channels: High-level API wrappers
- models: Chat, Message, Member, Team, Channel dataclasses
"""
