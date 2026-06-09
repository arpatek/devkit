#!/usr/bin/env python3
"""ipa.py - FreeIPA module for devkit
========================================================================================

User, group, host, and HBAC visibility via the FreeIPA JSON-RPC API.
Authenticates with admin credentials over HTTPS — no SSH, no Kerberos setup needed
on the local machine.

Author: Juan Garcia (arpatek)

Usage:
------
  ./modules/ipa.py                  # user list (default)
  ./modules/ipa.py --groups         # group list with member counts
  ./modules/ipa.py --hosts          # enrolled hosts
  ./modules/ipa.py --hbac           # HBAC rules
  ./modules/ipa.py --user-ops       # interactive: enable/disable/reset password
"""

__version__ = "1.0.0"

# ──[ venv bootstrap ]─────────────────────────────────────────────────────────────────
import os, sys
from pathlib import Path as _P
_venv = _P(os.environ.get("DEVKIT_ROOT") or _P(__file__).resolve().parent.parent) / ".venv"
if _venv.exists() and sys.prefix != str(_venv):
    os.execv(str(_venv / "bin/python3"), [str(_venv / "bin/python3")] + sys.argv)
del _venv

# ──[ Imports ]─────────────────────────────────────────────────────────────────────────
import argparse
import os
import sys
from pathlib import Path

DEVKIT_ROOT = Path(os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(DEVKIT_ROOT / "lib"))

try:
    from rich.console import Console
    from rich.prompt import Confirm, Prompt
    from rich.table import Table
except ImportError:
    print("Missing dependency: rich  →  pip install --user rich", file=sys.stderr)
    sys.exit(2)

import secrets
from api import APIError, IPAClient, IPAError

# ──[ Config ]──────────────────────────────────────────────────────────────────────────

console = Console()
err     = Console(stderr=True)


# ──[ Helpers ]─────────────────────────────────────────────────────────────────────────


def _val(obj: dict, key: str, default: str = "—") -> str:
    """Extract first value from an IPA attribute (which may be a list or scalar)."""
    v = obj.get(key, default)
    if isinstance(v, list):
        return str(v[0]) if v else default
    return str(v) if v is not None else default


def _flag(obj: dict, key: str) -> bool:
    v = obj.get(key)
    if isinstance(v, list):
        v = v[0] if v else False
    return bool(v)


# ──[ Views ]───────────────────────────────────────────────────────────────────────────


def render_users(ipa: IPAClient) -> list:
    result = ipa.call("user_find", options={"all": True, "sizelimit": 200})
    users = result.get("result", [])

    table = Table(title="IPA · Users", header_style="bold cyan", show_lines=False)
    table.add_column("UID", style="cyan", no_wrap=True)
    table.add_column("Full Name", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Groups", style="dim")

    for u in sorted(users, key=lambda x: _val(x, "uid")):
        uid = _val(u, "uid")
        name = f"{_val(u, 'givenname', '')} {_val(u, 'sn', '')}".strip() or "—"
        locked = _flag(u, "nsaccountlock")
        status = "[red]disabled[/red]" if locked else "[green]active[/green]"
        groups = ", ".join(u.get("memberof_group", [])) or "—"
        table.add_row(uid, name, status, groups)

    console.print(table)
    return users


def render_groups(ipa: IPAClient) -> None:
    result = ipa.call("group_find", options={"all": True, "sizelimit": 200})
    groups = result.get("result", [])

    table = Table(title="IPA · Groups", header_style="bold cyan", show_lines=False)
    table.add_column("Group", style="cyan", no_wrap=True)
    table.add_column("Description", style="dim")
    table.add_column("Members", justify="right", no_wrap=True)

    for g in sorted(groups, key=lambda x: _val(x, "cn")):
        cn = _val(g, "cn")
        desc = _val(g, "description", "")
        members = g.get("member_user", [])
        table.add_row(cn, desc, str(len(members)))

    console.print(table)


def render_hosts(ipa: IPAClient) -> None:
    result = ipa.call("host_find", options={"all": True, "sizelimit": 200})
    hosts = result.get("result", [])

    table = Table(title="IPA · Enrolled Hosts", header_style="bold cyan", show_lines=False)
    table.add_column("FQDN", style="cyan", no_wrap=True)
    table.add_column("OS", style="dim", no_wrap=True)
    table.add_column("Enrolled", style="dim", no_wrap=True)

    for h in sorted(hosts, key=lambda x: _val(x, "fqdn")):
        fqdn = _val(h, "fqdn")
        os_name = _val(h, "nsosversion", _val(h, "nshostos", "—"))
        enrolled = _val(h, "enrolledby", "—")
        table.add_row(fqdn, os_name, enrolled)

    console.print(table)


def render_hbac(ipa: IPAClient) -> None:
    result = ipa.call("hbacrule_find", options={"all": True, "sizelimit": 200})
    rules = result.get("result", [])

    table = Table(title="IPA · HBAC Rules", header_style="bold cyan", show_lines=False)
    table.add_column("Rule", style="cyan", no_wrap=True)
    table.add_column("Enabled", justify="center", no_wrap=True)
    table.add_column("Users / Groups", style="dim")
    table.add_column("Hosts / Groups", style="dim")
    table.add_column("Services", style="dim")

    for r in sorted(rules, key=lambda x: _val(x, "cn")):
        cn = _val(r, "cn")
        enabled = not _flag(r, "ipaenabledflag") is False
        # ipaenabledflag is True when enabled
        raw_flag = r.get("ipaenabledflag")
        if isinstance(raw_flag, list):
            raw_flag = raw_flag[0] if raw_flag else True
        enabled_str = "[green]✓[/green]" if raw_flag is not False else "[red]✗[/red]"

        users = ", ".join(r.get("memberuser_user", []) + r.get("memberuser_group", [])) or "any"
        hosts = ", ".join(r.get("memberhost_host", []) + r.get("memberhost_hostgroup", [])) or "any"
        svcs  = ", ".join(r.get("memberservice_hbacsvc", [])) or "any"

        table.add_row(cn, enabled_str, users, hosts, svcs)

    console.print(table)


def render_user_ops(ipa: IPAClient) -> None:
    if not sys.stdin.isatty():
        err.print("[red]![/red] --user-ops requires a TTY.")
        sys.exit(1)

    users = render_users(ipa)
    if not users:
        return

    uid = Prompt.ask("\nEnter UID")
    matched = [u for u in users if _val(u, "uid") == uid]
    if not matched:
        err.print(f"[red]![/red] User '{uid}' not found.")
        sys.exit(1)

    u = matched[0]
    locked = _flag(u, "nsaccountlock")
    current = "[red]disabled[/red]" if locked else "[green]active[/green]"
    console.print(f"  {uid} is currently {current}")

    action = Prompt.ask("Action", choices=["enable", "disable", "reset-password"])

    if action == "enable":
        if Confirm.ask(f"Enable user [cyan]{uid}[/cyan]?"):
            ipa.call("user_enable", args=[uid])
            console.print(f"[green]✓[/green] {uid} enabled")

    elif action == "disable":
        if Confirm.ask(f"[red]Disable[/red] user [cyan]{uid}[/cyan]?"):
            ipa.call("user_disable", args=[uid])
            console.print(f"[green]✓[/green] {uid} disabled")

    elif action == "reset-password":
        new_pw = Prompt.ask(f"New password for [cyan]{uid}[/cyan]", password=True)
        confirm_pw = Prompt.ask("Confirm password", password=True)
        if new_pw != confirm_pw:
            err.print("[red]![/red] Passwords do not match.")
            sys.exit(1)
        if Confirm.ask(f"Reset password for [cyan]{uid}[/cyan]?"):
            ipa.call("passwd", args=[uid, new_pw])
            console.print(f"[green]✓[/green] Password reset for {uid}")


# ──[ CLI ]─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ipa.py", description="FreeIPA homelab module")
    p.add_argument("--groups", action="store_true", help="List groups")
    p.add_argument("--hosts", action="store_true", help="List enrolled hosts")
    p.add_argument("--hbac", action="store_true", help="List HBAC rules")
    p.add_argument("--user-ops", action="store_true", help="Interactive user operations")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        secrets.load()
        host     = secrets.require("IPA_HOST")
        user     = secrets.require("IPA_USER")
        password = secrets.require("IPA_PASSWORD")
    except RuntimeError as e:
        err.print(f"[red]![/red] {e}")
        sys.exit(1)

    try:
        ipa = IPAClient(host, user, password)
    except RuntimeError as e:
        err.print(f"[red]![/red] {e}")
        sys.exit(1)
    except (APIError, OSError) as e:
        err.print(f"[red]![/red] Cannot reach IPA at {host}: {e}")
        sys.exit(1)

    try:
        if args.groups:
            render_groups(ipa)
        elif args.hosts:
            render_hosts(ipa)
        elif args.hbac:
            render_hbac(ipa)
        elif args.user_ops:
            render_user_ops(ipa)
        else:
            render_users(ipa)
    except IPAError as e:
        err.print(f"[red]![/red] IPA error {e.code}: {e.message}")
        sys.exit(1)
    except (APIError, OSError) as e:
        err.print(f"[red]![/red] IPA API error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
