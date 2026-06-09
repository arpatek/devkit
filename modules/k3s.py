#!/usr/bin/env python3
"""k3s.py - Kubernetes / k3s module for devkit
========================================================================================

Node status, pod views across namespaces, and log tailing.
Runs kubectl locally — requires kubeconfig at ~/.kube/config pointing to the k3s
cluster API server. No SSH required.

Author: Juan Garcia (arpatek)

Setup (one-time):
-----------------
  mkdir -p ~/.kube
  ssh arpatek@erebus.home.arpa "sudo cat /etc/rancher/k3s/k3s.yaml" \\
    | sed 's/127.0.0.1/erebus.home.arpa/' > ~/.kube/config
  chmod 600 ~/.kube/config

Usage:
------
  ./modules/k3s.py                              # node status + pod counts (default)
  ./modules/k3s.py --namespace default          # pods in a specific namespace
  ./modules/k3s.py --namespace kube-system      # pods in kube-system
  ./modules/k3s.py --all-namespaces             # all pods across all namespaces
  ./modules/k3s.py --logs --pod <name> --namespace <ns>  # tail pod logs
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
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEVKIT_ROOT = Path(os.environ.get("DEVKIT_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(DEVKIT_ROOT / "lib"))

try:
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("Missing dependency: rich  →  pip install --user rich", file=sys.stderr)
    sys.exit(2)

# ──[ Config ]──────────────────────────────────────────────────────────────────────────

console = Console()
err     = Console(stderr=True)

STATUS_COLORS = {
    "Running":            "green",
    "Completed":          "dim",
    "Pending":            "yellow",
    "Failed":             "red",
    "CrashLoopBackOff":   "red",
    "OOMKilled":          "red",
    "Error":              "red",
    "ImagePullBackOff":   "red",
    "ErrImagePull":       "red",
    "Terminating":        "yellow",
    "Unknown":            "dim",
}

# ──[ kubectl runner ]──────────────────────────────────────────────────────────────────


def _kubectl(*args: str, timeout: int = 15) -> dict:
    """Run kubectl with -o json output and return parsed result."""
    cmd = ["kubectl", *args, "-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        err.print("[red]![/red] kubectl not found on PATH.")
        err.print("    Install kubectl and ensure ~/.kube/config points to the cluster.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        err.print(f"[red]![/red] kubectl timed out after {timeout}s.")
        sys.exit(1)

    if proc.returncode != 0:
        msg = proc.stderr.strip()
        if "no such file" in msg.lower() or "does not exist" in msg.lower():
            err.print("[red]![/red] kubeconfig not found — run the setup steps in the module docstring.")
        elif "connection refused" in msg.lower() or "unable to connect" in msg.lower():
            err.print(f"[red]![/red] Cannot reach cluster API: {msg}")
        else:
            err.print(f"[red]![/red] kubectl error: {msg}")
        sys.exit(1)

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        err.print(f"[red]![/red] kubectl returned non-JSON output: {proc.stdout[:200]}")
        sys.exit(1)


def _kubectl_logs(pod: str, namespace: str, tail: int = 50) -> str:
    cmd = ["kubectl", "logs", pod, "-n", namespace, f"--tail={tail}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return "kubectl not found"
    except subprocess.TimeoutExpired:
        return "timed out"
    return proc.stdout or proc.stderr or "(no output)"


# ──[ Helpers ]─────────────────────────────────────────────────────────────────────────


def _age(timestamp: str) -> str:
    if not timestamp:
        return "—"
    try:
        created = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - created
        d, s = delta.days, delta.seconds
        if d > 0:
            return f"{d}d{s // 3600}h"
        if s >= 3600:
            return f"{s // 3600}h{(s % 3600) // 60}m"
        return f"{s // 60}m"
    except ValueError:
        return "—"


def _pod_display(pod: dict) -> tuple:
    """Return (status_str, ready_str, restarts, color) for a pod."""
    phase = pod.get("status", {}).get("phase", "Unknown")
    cs_list = pod.get("status", {}).get("containerStatuses", [])
    init_cs = pod.get("status", {}).get("initContainerStatuses", [])

    # Surface the most meaningful waiting reason if any container is not ready
    for cs in cs_list:
        waiting = cs.get("state", {}).get("waiting", {})
        if waiting:
            reason = waiting.get("reason", "Waiting")
            color = STATUS_COLORS.get(reason, "red")
            ready = f"{sum(c.get('ready', False) for c in cs_list)}/{len(cs_list)}"
            restarts = sum(c.get("restartCount", 0) for c in cs_list)
            return reason, ready, restarts, color

    ready_count = sum(c.get("ready", False) for c in cs_list)
    total = len(cs_list) or 1
    restarts = sum(c.get("restartCount", 0) for c in cs_list + init_cs)
    color = STATUS_COLORS.get(phase, "white")
    return phase, f"{ready_count}/{total}", restarts, color


# ──[ Views ]───────────────────────────────────────────────────────────────────────────


def render_nodes() -> None:
    data = _kubectl("get", "nodes")
    items = data.get("items", [])

    table = Table(title="k3s · Nodes", header_style="bold cyan", show_lines=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Role", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Version", style="dim", no_wrap=True)
    table.add_column("Age", justify="right", no_wrap=True)

    for node in items:
        name = node["metadata"]["name"].split(".")[0]  # strip domain

        labels = node["metadata"].get("labels", {})
        roles = [
            k.split("/")[-1]
            for k in labels
            if k.startswith("node-role.kubernetes.io/")
        ]
        role_str = ",".join(roles) if roles else "worker"

        ready = next(
            (c["status"] == "True" for c in node["status"].get("conditions", []) if c["type"] == "Ready"),
            False,
        )
        status_str = "[green]Ready[/green]" if ready else "[red]NotReady[/red]"
        version = node["status"].get("nodeInfo", {}).get("kubeletVersion", "—")
        age = _age(node["metadata"].get("creationTimestamp", ""))

        table.add_row(name, role_str, status_str, version, age)

    console.print(table)


def render_pod_summary() -> None:
    """Pod counts by namespace."""
    data = _kubectl("get", "pods", "--all-namespaces")
    items = data.get("items", [])

    counts: dict = {}
    for pod in items:
        ns = pod["metadata"].get("namespace", "default")
        phase = pod.get("status", {}).get("phase", "Unknown")
        counts.setdefault(ns, {"Running": 0, "Other": 0})
        if phase == "Running":
            counts[ns]["Running"] += 1
        else:
            counts[ns]["Other"] += 1

    table = Table(title="k3s · Pod Summary", header_style="bold cyan", show_lines=False)
    table.add_column("Namespace", style="cyan", no_wrap=True)
    table.add_column("Running", justify="right", no_wrap=True)
    table.add_column("Other", justify="right", no_wrap=True)
    table.add_column("Total", justify="right", no_wrap=True)

    for ns in sorted(counts):
        r = counts[ns]["Running"]
        o = counts[ns]["Other"]
        other_str = f"[yellow]{o}[/yellow]" if o > 0 else str(o)
        table.add_row(ns, f"[green]{r}[/green]", other_str, str(r + o))

    console.print(table)


def render_pods(namespace: str = None, all_namespaces: bool = False) -> None:
    if all_namespaces:
        data = _kubectl("get", "pods", "--all-namespaces")
        title = "k3s · All Pods"
    else:
        ns = namespace or "default"
        data = _kubectl("get", "pods", "-n", ns)
        title = f"k3s · Pods — {ns}"

    items = data.get("items", [])
    if not items:
        console.print(f"[dim]No pods found{' in ' + namespace if namespace else ''}.[/dim]")
        return

    show_ns = all_namespaces or not namespace

    table = Table(title=title, header_style="bold cyan", show_lines=False)
    if show_ns:
        table.add_column("Namespace", style="dim", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Ready", justify="center", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Restarts", justify="right", no_wrap=True)
    table.add_column("Age", justify="right", no_wrap=True)

    for pod in sorted(items, key=lambda p: (p["metadata"].get("namespace", ""), p["metadata"]["name"])):
        ns = pod["metadata"].get("namespace", "—")
        name = pod["metadata"]["name"]
        age = _age(pod["metadata"].get("creationTimestamp", ""))
        status, ready, restarts, color = _pod_display(pod)

        restart_str = f"[red]{restarts}[/red]" if restarts > 5 else str(restarts)
        row = [name, ready, f"[{color}]{status}[/{color}]", restart_str, age]
        if show_ns:
            row = [ns] + row
        table.add_row(*row)

    console.print(table)


def render_logs(pod: str, namespace: str) -> None:
    console.print(f"[dim]─── logs: {pod} ({namespace}) — last 50 lines ───[/dim]")
    console.print(_kubectl_logs(pod, namespace))


# ──[ CLI ]─────────────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="k3s.py", description="k3s / Kubernetes homelab module")
    p.add_argument("--namespace", "-n", help="Show pods in this namespace")
    p.add_argument("--all-namespaces", "-A", action="store_true", help="Show pods in all namespaces")
    p.add_argument("--logs", action="store_true", help="Tail pod logs (requires --pod and --namespace)")
    p.add_argument("--pod", help="Pod name for --logs")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.logs:
        if not args.pod or not args.namespace:
            err.print("[red]![/red] --logs requires --pod and --namespace.")
            sys.exit(1)
        render_logs(args.pod, args.namespace)
    elif args.namespace:
        render_pods(namespace=args.namespace)
    elif args.all_namespaces:
        render_pods(all_namespaces=True)
    else:
        render_nodes()
        render_pod_summary()


if __name__ == "__main__":
    main()
