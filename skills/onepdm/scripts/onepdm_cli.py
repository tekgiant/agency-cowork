#!/usr/bin/env python3
"""
OnePDM CLI — Search, browse, and download specifications from OnePDM PLM.

Usage:
    python onepdm_cli.py search <query>
    python onepdm_cli.py info <doc_number>
    python onepdm_cli.py list-files <doc_number>
    python onepdm_cli.py download <doc_number> [--dest <path>]
    python onepdm_cli.py list [--filter <term>] [--stale] [--program <name>]
    python onepdm_cli.py update [--all] [--stale] [<numbers>]
    python onepdm_cli.py import-sow <file>
    python onepdm_cli.py check-freshness
    python onepdm_cli.py test-auth
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from auth import get_browser

# Config paths
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent  # skills/onepdm/scripts -> project root
CONFIG_DIR = PROJECT_ROOT / "config"
SPEC_REGISTRY = CONFIG_DIR / "onepdm-specs.json"
PROGRAM_CONFIG = CONFIG_DIR / "onepdm-programs.json"
DEFAULT_DEST = PROJECT_ROOT / "memory" / "Knowledgebase" / "Specifications"


def load_registry() -> dict:
    """Load the spec retrieval registry."""
    if SPEC_REGISTRY.exists():
        with open(SPEC_REGISTRY, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_registry(registry: dict):
    """Save the spec retrieval registry."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(SPEC_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def load_program_config() -> dict:
    """Load program-specific configuration."""
    if PROGRAM_CONFIG.exists():
        with open(PROGRAM_CONFIG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def update_registry_entry(registry: dict, doc_number: str, **kwargs):
    """Update or create a registry entry for a document."""
    entry = registry.get(doc_number, {})
    entry.update(kwargs)
    entry["doc_number"] = doc_number
    registry[doc_number] = entry


# ── Commands ──

def cmd_test_auth(args):
    """Test authentication to OnePDM."""
    print("Testing OnePDM authentication...")
    browser = get_browser()
    if not browser.ensure_ready():
        print("  Authentication failed — could not establish browser session")
        print("  Run 'onepdm_cli.py setup' for first-time authentication.")
        sys.exit(1)
    info = browser.validate_user()
    if info.get("login_name"):
        print(f"  Authenticated as: {info['login_name']}")
        print(f"  Database: {info.get('database', 'N/A')}")
        print(f"  Auth type: {info.get('authentication_type', 'N/A')}")
    else:
        print("  Authentication failed — no valid session")
        sys.exit(1)


def cmd_setup(args):
    """First-time setup: launch Edge, walk user through Azure AD sign-in."""
    from auth import OnePDMBrowser, BROWSER_PROFILE_DIR

    print(
        "\n╔═══════════════════════════════════════════════════════════════╗\n"
        "║                  OnePDM First-Time Setup                     ║\n"
        "╠═══════════════════════════════════════════════════════════════╣\n"
        "║                                                               ║\n"
        "║  1. An Edge window will open and navigate to OnePDM.          ║\n"
        "║  2. Complete the Azure AD sign-in (email + MFA).              ║\n"
        "║  3. Wait until the OnePDM dashboard loads.                    ║\n"
        "║  4. The CLI will detect authentication automatically.         ║\n"
        "║                                                               ║\n"
        "║  This is only needed ONCE — credentials are cached in:        ║\n"
        "║    ~/.onepdm-agent/browser-profile/                           ║\n"
        "║                                                               ║\n"
        "║  You have up to 5 minutes to complete sign-in.                ║\n"
        "║                                                               ║\n"
        "╚═══════════════════════════════════════════════════════════════╝\n"
    )

    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    browser = OnePDMBrowser()

    # Override timeout to 5 minutes for first-time setup
    import auth as auth_mod
    original_timeout = auth_mod._HEADED_READY_TIMEOUT
    auth_mod._HEADED_READY_TIMEOUT = 300  # 5 minutes

    try:
        if browser.ensure_ready():
            info = browser.validate_user()
            login = info.get('login_name', info.get('user_id', '?'))
            print(f"\n  ✓ SUCCESS — Authenticated as: {login}")
            print(f"  ✓ Profile cached at: {BROWSER_PROFILE_DIR}")
            print("  ✓ Future runs will auto-authenticate.\n")
        else:
            print("\n  ✗ Setup failed — could not authenticate within 5 minutes.")
            print("    Try again: python onepdm_cli.py setup\n")
            sys.exit(1)
    finally:
        auth_mod._HEADED_READY_TIMEOUT = original_timeout
        browser.close()


def cmd_search(args):
    """Search OnePDM by document number or keyword."""
    browser = get_browser()
    browser.ensure_ready()
    results = browser.global_search(args.query)

    if not results:
        print(f"No results for '{args.query}'")
        return

    print(f"\n{'#':>3}  {'Type':<12} {'Number':<14} {'Rev':>3}  {'State':<12} {'Name'}")
    print("─" * 80)
    for i, r in enumerate(results, 1):
        print(f"{i:>3}  {r.get('_itemtype', ''):<12} {r.get('_itemnumber', ''):<14} "
              f"{r.get('_revision', ''):>3}  {r.get('_state', ''):<12} "
              f"{r.get('_name', '')[:40]}")


def cmd_info(args):
    """Show document metadata."""
    browser = get_browser()
    browser.ensure_ready()
    doc = browser.get_document_by_number(args.doc_number)

    if not doc:
        print(f"Document '{args.doc_number}' not found")
        sys.exit(1)

    print(f"\n{'Document':>16}: {doc.get('item_number', '')} — {doc.get('name', '')}")
    print(f"{'Revision':>16}: {doc.get('major_rev', '')}")
    print(f"{'State':>16}: {doc.get('state', '')}")
    print(f"{'Classification':>16}: {doc.get('classification', '')}")
    print(f"{'Sub-class':>16}: {doc.get('m_sub_class', '')}")
    print(f"{'Created by':>16}: {doc.get('created_by_id_name', '')}")
    print(f"{'Created on':>16}: {doc.get('created_on', '')}")
    print(f"{'Modified on':>16}: {doc.get('modified_on', '')}")
    print(f"{'Owned by':>16}: {doc.get('owned_by_id_name', '')}")
    print(f"{'OnePDM ID':>16}: {doc.get('id', '')}")

    # Also list files
    files = browser.list_document_files(doc.get("id", ""))
    if files:
        print(f"\n  Files ({len(files)}):")
        for f in files:
            size = f.get("file_size", "?")
            print(f"    {f.get('filename', 'unknown')} ({size} bytes)")


def cmd_list_files(args):
    """List all file attachments for a document."""
    browser = get_browser()
    browser.ensure_ready()
    doc = browser.get_document_by_number(args.doc_number)
    if not doc:
        print(f"Document '{args.doc_number}' not found")
        sys.exit(1)

    files = browser.list_document_files(doc.get("id", ""))
    if not files:
        print(f"No files attached to {args.doc_number}")
        return

    print(f"\nFiles for {args.doc_number} ({doc.get('name', '')}):")
    print(f"{'#':>3}  {'Filename':<50} {'Size':>10}  {'Modified'}")
    print("─" * 80)
    for i, f in enumerate(files, 1):
        print(f"{i:>3}  {f.get('filename', ''):<50} {f.get('file_size', ''):>10}  "
              f"{f.get('modified_on', '')}")


def cmd_download(args):
    """Download a specification by document number."""
    browser = get_browser()
    browser.ensure_ready()
    dest = args.dest or str(DEFAULT_DEST)

    print(f"Searching for {args.doc_number}...")
    path = browser.download_by_doc_number(args.doc_number, dest)
    if path:
        print(f"Downloaded: {path}")
        # Update registry
        registry = load_registry()
        doc = browser.get_document_by_number(args.doc_number)
        update_registry_entry(registry, args.doc_number,
                              onepdm_id=doc.get("id", "") if doc else "",
                              name=doc.get("name", "") if doc else "",
                              revision=doc.get("major_rev", "") if doc else "",
                              state=doc.get("state", "") if doc else "",
                              last_retrieved=datetime.now(timezone.utc).isoformat(),
                              local_path=path,
                              onepdm_modified=doc.get("modified_on", "") if doc else "")
        save_registry(registry)
        print(f"Registry updated: {args.doc_number}")
    else:
        print(f"Failed to download {args.doc_number}")
        sys.exit(1)


def cmd_list(args):
    """Show numbered list of tracked specifications."""
    registry = load_registry()
    if not registry:
        print("No specifications tracked. Use 'import-sow' or 'download' first.")
        return

    # Apply filters
    items = list(registry.items())

    if args.filter:
        term = args.filter.lower()
        items = [(k, v) for k, v in items
                 if term in k.lower() or term in v.get("name", "").lower()
                 or term in v.get("classification", "").lower()]

    if args.program:
        pc = load_program_config()
        prog = pc.get("programs", {}).get(args.program, {})
        spec_list = prog.get("sow_exhibits", [])
        if spec_list:
            items = [(k, v) for k, v in items if k in spec_list]

    if args.stale:
        items = [(k, v) for k, v in items if not v.get("last_retrieved")]

    if not items:
        print("No matching specifications.")
        return

    print(f"\n{'#':>3}  {'Doc Number':<14} {'Rev':>3}  {'State':<10} {'Retrieved':<20} {'Name'}")
    print("─" * 95)
    for i, (doc_num, entry) in enumerate(items, 1):
        retrieved = entry.get("last_retrieved", "—never—")
        if retrieved and retrieved != "—never—":
            retrieved = retrieved[:19].replace("T", " ")
        print(f"{i:>3}  {doc_num:<14} {entry.get('revision', '?'):>3}  "
              f"{entry.get('state', '?'):<10} {retrieved:<20} "
              f"{entry.get('name', '')[:35]}")

    print(f"\n{len(items)} specification(s). Use 'update <numbers>' to re-download.")


def cmd_update(args):
    """Update (re-download) selected specifications."""
    registry = load_registry()
    items = list(registry.keys())

    if not items:
        print("No specifications tracked.")
        return

    if args.stale:
        targets = [k for k in items if not registry[k].get("last_retrieved")]
    elif args.all:
        targets = items
    elif args.numbers:
        # Parse number selections (e.g., "1,3,5" or "1-5")
        targets = []
        for part in args.numbers.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                for n in range(int(start), int(end) + 1):
                    if 1 <= n <= len(items):
                        targets.append(items[n - 1])
            else:
                n = int(part)
                if 1 <= n <= len(items):
                    targets.append(items[n - 1])
    else:
        print("Specify --all, --stale, or number selection (e.g., 1,3,5 or 1-5)")
        return

    if not targets:
        print("No specifications to update.")
        return

    print(f"Updating {len(targets)} specification(s)...")
    browser = get_browser()
    browser.ensure_ready()

    for doc_num in targets:
        try:
            dest = registry[doc_num].get("local_path", str(DEFAULT_DEST))
            dest_dir = str(Path(dest).parent) if os.path.isfile(dest) else dest
            print(f"  {doc_num}...", end=" ", flush=True)
            path = browser.download_by_doc_number(doc_num, dest_dir)
            if path:
                doc = browser.get_document_by_number(doc_num)
                update_registry_entry(registry, doc_num,
                                      last_retrieved=datetime.now(timezone.utc).isoformat(),
                                      local_path=path,
                                      revision=doc.get("major_rev", "") if doc else "",
                                      onepdm_modified=doc.get("modified_on", "") if doc else "")
                print(f"OK ({path})")
            else:
                print("FAILED (not found)")
        except Exception as e:
            print(f"ERROR ({e})")

    save_registry(registry)
    print("Registry updated.")


def cmd_import_sow(args):
    """Import document numbers from SOW/PRD exhibits file into registry."""
    import re as _re

    filepath = Path(args.file)
    if not filepath.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)

    # Read file and extract M-numbers (e.g., M1345662)
    text = filepath.read_text(encoding="utf-8", errors="replace")
    doc_numbers = sorted(set(_re.findall(r"\bM\d{7}\b", text)))

    if not doc_numbers:
        print("No document numbers (M#######) found in file.")
        return

    registry = load_registry()
    added = 0
    for doc_num in doc_numbers:
        if doc_num not in registry:
            registry[doc_num] = {"doc_number": doc_num, "name": "", "revision": "",
                                 "state": "", "last_retrieved": None}
            added += 1

    save_registry(registry)
    print(f"Found {len(doc_numbers)} document numbers. Added {added} new to registry "
          f"({len(registry)} total tracked).")
    print("Use 'list' to see all tracked specs, 'update --all' to download them.")


def cmd_check_freshness(args):
    """Check which tracked specs have newer versions on OnePDM."""
    registry = load_registry()
    if not registry:
        print("No specifications tracked.")
        return

    browser = get_browser()
    browser.ensure_ready()

    stale = []
    never = []
    current = []

    print(f"Checking {len(registry)} specifications...")
    for doc_num, entry in registry.items():
        if not entry.get("last_retrieved"):
            never.append(doc_num)
            continue

        try:
            doc = browser.get_document_by_number(doc_num)
            if not doc:
                continue
            remote_modified = doc.get("modified_on", "")
            local_modified = entry.get("onepdm_modified", "")
            if remote_modified and remote_modified != local_modified:
                stale.append((doc_num, local_modified, remote_modified))
            else:
                current.append(doc_num)
        except Exception as e:
            print(f"  {doc_num}: error checking ({e})")

    print(f"\n  Current: {len(current)}")
    print(f"  Never retrieved: {len(never)}")
    print(f"  Stale (newer on OnePDM): {len(stale)}")

    if stale:
        print(f"\n  Stale specifications:")
        for doc_num, local, remote in stale:
            print(f"    {doc_num}: local={local}, remote={remote}")
    if never:
        print(f"\n  Never retrieved: {', '.join(never[:20])}")
        if len(never) > 20:
            print(f"    ... and {len(never) - 20} more")


def main():
    parser = argparse.ArgumentParser(description="OnePDM Specification Manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("test-auth", help="Test OnePDM authentication")
    sub.add_parser("setup", help="First-time setup: interactive Azure AD sign-in")

    p_search = sub.add_parser("search", help="Search OnePDM")
    p_search.add_argument("query", help="Search query (doc number or keyword)")

    p_info = sub.add_parser("info", help="Show document metadata")
    p_info.add_argument("doc_number", help="Document number (e.g., M1345662)")

    p_files = sub.add_parser("list-files", help="List file attachments")
    p_files.add_argument("doc_number", help="Document number")

    p_dl = sub.add_parser("download", help="Download a specification")
    p_dl.add_argument("doc_number", help="Document number")
    p_dl.add_argument("--dest", help="Destination directory or file path")

    p_list = sub.add_parser("list", help="List tracked specifications")
    p_list.add_argument("--filter", help="Filter by keyword")
    p_list.add_argument("--stale", action="store_true", help="Show only never-retrieved specs")
    p_list.add_argument("--program", help="Filter by program name")

    p_upd = sub.add_parser("update", help="Update (re-download) specifications")
    p_upd.add_argument("numbers", nargs="?", help="Spec numbers from list (e.g., 1,3,5 or 1-5)")
    p_upd.add_argument("--all", action="store_true", help="Update all tracked specs")
    p_upd.add_argument("--stale", action="store_true", help="Update only never-retrieved specs")

    p_sow = sub.add_parser("import-sow", help="Import doc numbers from SOW/PRD file")
    p_sow.add_argument("file", help="Path to SOW exhibits file (xlsx, md, or txt)")

    sub.add_parser("check-freshness", help="Check for newer versions on OnePDM")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "test-auth": cmd_test_auth,
        "setup": cmd_setup,
        "search": cmd_search,
        "info": cmd_info,
        "list-files": cmd_list_files,
        "download": cmd_download,
        "list": cmd_list,
        "update": cmd_update,
        "import-sow": cmd_import_sow,
        "check-freshness": cmd_check_freshness,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
