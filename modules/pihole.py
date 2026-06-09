#!/usr/bin/env python3
"""pihole.py - Pi-hole module for devkit
========================================================================================

Stats dashboard, top blocked domains, blocking toggle, and DHCP lease viewer.
Connects to the Pi-hole v6 REST API with session-based password auth.

Author: Juan Garcia (arpatek)

Usage:
------
  ./modules/pihole.py                   # stats dashboard (default)
  ./modules/pihole.py --top-blocked     # top blocked domains
  ./modules/pihole.py --toggle          # enable/disable blocking (with confirmation)
  ./modules/pihole.py --leases          # DHCP lease table
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
from datetime import datetime, timezone
from pathlib import Path

DEVKIT_ROOT = Path(os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(DEVKIT_ROOT / "lib"))

try:
    from rich.columns import Columns
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm
    from rich.table import Table
except ImportError:
    print("Missing dependency: rich  →  pip install --user rich", file=sys.stderr)
    sys.exit(2)

import secrets
from api import APIError, Session

# ──[ Config ]──────────────────────────────────────────────────────────────────────────

console = Console()
err     = Console(stderr=True)

# ──[ Auth ]────────────────────────────────────────────────────────────────────────────


class _PiholeSession(Session):
    """Session subclass that appends ?sid=<value> to every request URL.

    Pi-hole v6 FTL requires the session SID as a URL query parameter — not as a
    Bearer token (that path is for app passwords only) and not as a Cookie header
    (stdlib CookieJar domain/path matching is unreliable with self-signed certs).
    """

    def __init__(self, sid: str) -> None:
        super().__init__(verify_ssl=False)
        self._sid = sid

    def _sid_url(self, url: str) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}sid={self._sid}"

    def get(self, url: str, timeout: float = 10.0) -> Any:
        return super().get(self._sid_url(url), timeout)

    def post(self, url: str, data: Any, timeout: float = 10.0) -> Any:
        return super().post(self._sid_url(url), data, timeout)


def _auth(host: str, password: str) -> _PiholeSession:
    """Authenticate with Pi-hole v6 API. Returns an authorised session."""
    bootstrap = Session(verify_ssl=False)
    try:
        resp = bootstrap.post(f"https://{host}/api/auth", {"password": password})
    except APIError as e:
        if e.status in (401, 403):
            raise RuntimeError("Pi-hole authentication failed — check PIHOLE_PASSWORD") from e
        raise

    sid = resp.get("session", {}).get("sid")
    if not sid:
        raise RuntimeError(f"Pi-hole auth response missing SID: {resp}")

    return _PiholeSession(sid)


def _delete_session(session: _PiholeSession, host: str) -> None:
    """Logout — best-effort, ignore errors."""
    import urllib.request
    try:
        url = session._sid_url(f"https://{host}/api/auth")
        req = urllib.request.Request(url, method="DELETE")
        session._opener.open(req, timeout=5)  # type: ignore[attr-defined]
    except Exception:
        pass


# ──[ Views ]───────────────────────────────────────────────────────────────────────────


def render_stats(session: _PiholeSession, host: str) -> None:
    data = session.get(f"https://{host}/api/stats/summary")

    queries    = data.get("queries", {})
    clients    = data.get("clients", {})
    gravity    = data.get("gravity", {})

    total      = queries.get("total", 0)
    blocked    = queries.get("blocked", 0)
    pct        = queries.get("percent_blocked", 0.0)
    unique_dom = queries.get("unique_domains", 0)
    active_cl  = clients.get("active", 0)
    total_cl   = clients.get("total", 0)
    gravity_ct = gravity.get("domains_being_blocked", 0)

    bar_filled = int(pct / 100 * 30)
    bar_color  = "green" if pct < 20 else "yellow" if pct < 50 else "red"
    bar        = f"[{bar_color}]{'█' * bar_filled}{'░' * (30 - bar_filled)}[/{bar_color}]"

    lines = [
        f"  [cyan]Queries today [/cyan]  {total:>10,}",
        f"  [cyan]Blocked       [/cyan]  {blocked:>10,}  {bar}  {pct:.1f}%",
        f"  [cyan]Unique domains[/cyan]  {unique_dom:>10,}",
        f"  [cyan]Active clients[/cyan]  {active_cl:>10,}  (total: {total_cl})",
        f"  [cyan]Gravity list  [/cyan]  {gravity_ct:>10,} domains",
    ]
    console.print(Panel("\n".join(lines), title="[bold]Pi-hole · Stats[/bold]"))


def render_top_blocked(session: _PiholeSession, host: str, count: int = 15) -> None:
    data = session.get(f"https://{host}/api/stats/top_domains?blocked=true&count={count}")
    domains = data.get("domains", [])

    if not domains:
        console.print("[dim]No blocked domains yet.[/dim]")
        return

    table = Table(title=f"Pi-hole · Top {count} Blocked Domains", header_style="bold cyan")
    table.add_column("Hits", justify="right", style="red", no_wrap=True)
    table.add_column("Domain", style="cyan")

    for entry in domains:
        table.add_row(f"{entry.get('count', 0):,}", entry.get("domain", "—"))

    console.print(table)


def render_toggle(session: _PiholeSession, host: str) -> None:
    state = session.get(f"https://{host}/api/dns/blocking")
    blocking = state.get("blocking", False)
    current  = "[green]ENABLED[/green]" if blocking else "[red]DISABLED[/red]"
    action   = "disable" if blocking else "enable"
    color    = "red" if blocking else "green"

    console.print(f"  Blocking is currently {current}")
    if not Confirm.ask(f"[{color}]{action.upper()}[/{color}] blocking?"):
        console.print("[dim]Cancelled.[/dim]")
        return

    session.post(f"https://{host}/api/dns/blocking", {"blocking": not blocking})
    new_state = "[red]DISABLED[/red]" if blocking else "[green]ENABLED[/green]"
    console.print(f"  Blocking is now {new_state}")


def render_leases(session: _PiholeSession, host: str) -> None:
    data = session.get(f"https://{host}/api/dhcp/leases")
    leases = data if isinstance(data, list) else data.get("leases", [])

    if not leases:
        console.print("[dim]No active DHCP leases.[/dim]")
        return

    table = Table(title="Pi-hole · DHCP Leases", header_style="bold cyan")
    table.add_column("Hostname", style="cyan", no_wrap=True)
    table.add_column("IP", no_wrap=True)
    table.add_column("MAC", style="dim", no_wrap=True)
    table.add_column("Expires", style="dim", no_wrap=True)

    now = datetime.now(timezone.utc).timestamp()
    for lease in sorted(leases, key=lambda l: l.get("ip", "")):
        exp = lease.get("expires", 0)
        if exp == 0:
            exp_str = "static"
        elif isinstance(exp, (int, float)) and exp > 0:
            remaining = int(exp - now)
            if remaining <= 0:
                exp_str = "expired"
            elif remaining < 3600:
                exp_str = f"{remaining // 60}m"
            elif remaining < 86400:
                exp_str = f"{remaining // 3600}h"
            else:
                exp_str = f"{remaining // 86400}d"
        else:
            exp_str = lease.get("expiry_str", "—") or "static"
        table.add_row(
            lease.get("name") or "[dim]—[/dim]",
            lease.get("ip", "—"),
            lease.get("hwaddr", "—"),
            exp_str,
        )

    console.print(table)


# ──[ CLI ]─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pihole.py", description="Pi-hole homelab module")
    p.add_argument("--top-blocked", action="store_true", help="Top blocked domains")
    p.add_argument("--toggle", action="store_true", help="Toggle blocking on/off")
    p.add_argument("--leases", action="store_true", help="DHCP lease table")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    try:
        secrets.load()
        host     = secrets.require("PIHOLE_HOST")
        password = secrets.require("PIHOLE_PASSWORD")
    except RuntimeError as e:
        err.print(f"[red]![/red] {e}")
        sys.exit(1)

    try:
        session = _auth(host, password)
    except RuntimeError as e:
        err.print(f"[red]![/red] {e}")
        sys.exit(1)
    except (APIError, OSError) as e:
        err.print(f"[red]![/red] Cannot reach Pi-hole at {host}: {e}")
        sys.exit(1)

    try:
        if args.top_blocked:
            render_top_blocked(session, host)
        elif args.toggle:
            render_toggle(session, host)
        elif args.leases:
            render_leases(session, host)
        else:
            render_stats(session, host)
    except (APIError, OSError) as e:
        err.print(f"[red]![/red] Pi-hole API error: {e}")
        sys.exit(1)
    finally:
        _delete_session(session, host)


if __name__ == "__main__":
    main()
