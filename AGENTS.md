# OpenReef: instructions for coding agents

OpenReef is an open-source reef-aquarium controller built on Home Assistant. **This repository is
public**, and beta testers install the integration from it through the Home Assistant Marketplace (formerly HACS).

| Path | What it is |
|---|---|
| `custom_components/openreef/` | The Home Assistant integration: Python backend plus the panel (`frontend/openreef-panel.js`). This is the product. |
| `portal/` | Beta-tester portal (Next.js + Supabase), deployed on Vercel. |
| `site/` | Marketing site (Next.js, 3D homepage), deployed on Vercel. |
| `src/` | Old standalone dashboard (Next.js). **Dormant: never deploy it.** |
| `esphome/`, `docs/manual/*.yaml` | ESPHome firmware references for the reef nodes. |
| `tests/` | Python and panel regression suites (`tests/test_*.py`, `tests/test_*.mjs`). |

## Safety: hard rules
This code runs a live aquarium. A wrong pump or heater action can kill livestock.
- **Never touch real hardware.** Don't flash or OTA-upload firmware, don't call Home Assistant
  services or webhooks, don't publish MQTT messages, and don't toggle equipment. Write code and
  tests only. Validate firmware with `esphome config` / `esphome compile` at most.
- **Never deploy.** Supabase migrations, Vercel deploys, GitHub releases and Home Assistant Marketplace (formerly HACS) publishing are
  done by Reece.
- **Public repo:** never commit secrets, `.env` contents, hostnames or IPs of Reece's network,
  security audit write-ups, or details of unpatched vulnerabilities.

`.claude/guard-rules.json` blocks the obvious commands for these. Treat the rules above as
binding even where the guard can't see a command.

## Workflow
- Work on a branch (`feat/…`, `fix/…`, `chore/…`), never on `main`. `main` is protected, so
  changes go in only through PRs, with CI's `checks` job passing. Don't merge your own PR.
- Every PR description includes:
  - what changed and why, in plain English
  - the commands you ran and their results
  - **proof**: screenshots of the panel or site for UI changes
- **Integration changes** bump `INTEGRATION_VERSION` in `custom_components/openreef/const.py`
  and `"version"` in `manifest.json` together, as the next patch version.
- Node ≥ 22.23.4. Use `corepack pnpm@9.15.9` at the repo root and `corepack pnpm@10.34.9` in
  `portal/` and `site/`.

## Verify before opening a PR
```bash
python3 -m py_compile custom_components/openreef/*.py
node --check custom_components/openreef/frontend/openreef-panel.js
for s in tests/test_*.py; do python3 "$s" || echo "FAIL $s"; done
for s in tests/test_*.mjs; do node "$s" || echo "FAIL $s"; done
```
Also run the following, depending on what you touched:
- **`portal/`, `site/` or `src/`:** in that directory, `pnpm install --frozen-lockfile`,
  `pnpm exec tsc --noEmit`, then `pnpm build`. Add `--webpack` to the build for the root and
  `portal/`.
- **Portal security suites:**
  - `node --test portal/tests/security.test.cjs`
  - `python3 portal/tests/test_security_sql.py`, which needs Docker

Tests use fakes (`tests/_fake_ha.py`). Never point them at a real Home Assistant.

## Demo Home Assistant (panel screenshots)
`scripts/demo-ha/` runs a disposable Home Assistant 2026.10.4 in Docker with **your worktree's**
`custom_components/openreef` mounted read-only and fake "Demo" reef data (sensors, switches backed
by input helpers). It is the **only Home Assistant agents may call**.
```bash
scripts/demo-ha/up.sh                      # start, seed, print the local URL (and tailnet URL for Reece)
scripts/demo-ha/auth-state /tmp/demo.json  # Playwright storage state, logged in to the demo
node ~/.claude/skills/proof/shoot.mjs --storage /tmp/demo.json openreef=http://127.0.0.1:<port>/openreef
scripts/demo-ha/down.sh                    # remove containers, network, volume and the tailnet share
```
- Port is 8300-8399, derived from the worktree name; `up.sh` prints it. Login is `demo` /
  `demo-reef-only` (fixed, local-only).
- The code is mounted live, but HA loads Python at startup: after backend changes, run `down.sh`
  then `up.sh`. Panel-only (JS) changes need just a hard browser reload.
- **Isolation:** HA is on a Docker `internal: true` network with no route to the host, LAN, libvirt,
  MQTT or internet. It is reached only through a socat proxy published on `127.0.0.1`. No mqtt or
  esphome is configured. `scripts/demo-ha/isolation-probe.sh` proves it.
- Its scripts refuse any target other than `127.0.0.1:<demo port>`. Never point agents, tests or
  scripts at any other Home Assistant. Buttons in the demo only flip fake helpers.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues (`gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human` and
`wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root, created lazily. See
`docs/agents/domain.md`.
