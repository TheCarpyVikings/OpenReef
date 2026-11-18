#!/usr/bin/env bash
# Start the disposable demo Home Assistant for this worktree, seed it, print the URLs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
export DEMO_PORT; DEMO_PORT="$(pick_port)"
echo "worktree: $SLUG   port: $DEMO_PORT"
compose up -d --wait --wait-timeout 300 >/dev/null
node "$DEMO_DIR/seed.mjs"
echo
echo "Demo HA:  http://127.0.0.1:$DEMO_PORT/openreef   (login $DEMO_USER / $DEMO_PASS)"
echo "Preview:  $(bash "$HOME/.claude/skills/proof/preview.sh" up "$DEMO_PORT")/openreef"
echo "Screenshots: $DEMO_DIR/auth-state  then  node ~/.claude/skills/proof/shoot.mjs --storage <json> openreef=http://127.0.0.1:$DEMO_PORT/openreef"
