#!/usr/bin/env python3
"""Demo drift report — how far has the live demo fallen behind the panel?

Compares the panel pinned into the marketing site's demo against the one the
integration ships today, and reports:

  * whether the pinned panel is byte-identical to the current one
  * WebSocket commands added/removed since the pin (the strongest drift signal:
    a new command is a read/write the shim has never heard of)
  * how many commits have touched the frontend since the demo was last pinned
  * the fixture set's age (informational only — the shim rebases timestamps at
    load, so age alone never breaks the demo)

Exit codes: 0 = in sync, 1 = drifted. Used locally and by the demo-drift and
demo-refresh GitHub workflows (--markdown writes the issue/PR body).

Usage:
    python3 site/tools/demo-drift.py [--markdown out.md]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))

CURRENT_PANEL = os.path.join(_ROOT, "custom_components", "openreef", "frontend", "openreef-panel.js")
PINNED_PANEL = os.path.join(_ROOT, "site", "public", "demo", "openreef-panel.js")
FIXTURES = os.path.join(_ROOT, "site", "public", "demo", "fixtures.json")

WS_RE = re.compile(r'"(openreef/[a-z_/]+)"')


def ws_commands(path: str) -> set[str]:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return set(WS_RE.findall(fh.read()))


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markdown", help="also write a markdown report here")
    args = ap.parse_args()

    for path in (CURRENT_PANEL, PINNED_PANEL, FIXTURES):
        if not os.path.exists(path):
            print(f"missing: {path}")
            return 1

    cur_size = os.path.getsize(CURRENT_PANEL)
    pin_size = os.path.getsize(PINNED_PANEL)
    identical = (
        cur_size == pin_size
        and open(CURRENT_PANEL, "rb").read() == open(PINNED_PANEL, "rb").read()
    )

    added = sorted(ws_commands(CURRENT_PANEL) - ws_commands(PINNED_PANEL))
    removed = sorted(ws_commands(PINNED_PANEL) - ws_commands(CURRENT_PANEL))

    # Commits touching the frontend since the demo was last pinned. In a
    # shallow clone this can't be answered; report "unknown" rather than 0.
    pin_commit = git("log", "-1", "--format=%H", "--", "site/public/demo/openreef-panel.js")
    commits_behind: int | None = None
    if pin_commit:
        log = git("log", "--oneline", f"{pin_commit}..HEAD", "--",
                  "custom_components/openreef/frontend/")
        commits_behind = len(log.splitlines()) if log else 0

    fixture_days: float | None = None
    generated_at = ""
    try:
        with open(FIXTURES, encoding="utf-8") as fh:
            generated_at = json.load(fh).get("generatedAt", "")
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        fixture_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except (ValueError, OSError, json.JSONDecodeError):
        pass

    drifted = not identical or bool(added) or bool(removed)

    lines = ["# Demo drift report", ""]
    if identical:
        lines.append("✅ **Pinned panel is byte-identical to the shipping panel.**")
    else:
        lines.append(
            f"⚠️ **Pinned panel differs from the shipping panel** "
            f"({pin_size / 1024:.0f} KB pinned vs {cur_size / 1024:.0f} KB current)."
        )
    if commits_behind is not None:
        lines.append(f"- Frontend commits since the demo was pinned: **{commits_behind}**")
    if added:
        lines.append(f"- WS commands the demo has never heard of: **{', '.join(added)}**")
    if removed:
        lines.append(f"- WS commands that no longer exist: **{', '.join(removed)}**")
    if fixture_days is not None:
        lines.append(
            f"- Fixtures generated {fixture_days:.0f} days ago ({generated_at}) — "
            "informational; the shim rebases timestamps at load."
        )
    lines.append("")
    lines.append(
        "**Fix:** run `pnpm demo:refresh` in `site/` (regenerates fixtures via the "
        "fake-HA harness, re-pins the panel, and smoke-tests every tab), then commit "
        "`site/public/demo/` — or let the monthly demo-refresh workflow open the PR."
        if drifted
        else "Nothing to do — the showroom matches the shipping panel."
    )

    report = "\n".join(lines)
    print(report)
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as fh:
            fh.write(report + "\n")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
