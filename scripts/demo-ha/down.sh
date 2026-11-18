#!/usr/bin/env bash
# Remove this worktree's demo containers, network and volumes, and stop the tailnet share.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
PORT="$(running_port)"
export DEMO_PORT="${PORT:-8300}"
compose down -v --remove-orphans
[ -z "$PORT" ] || bash "$HOME/.claude/skills/proof/preview.sh" down "$PORT" || true
echo "demo down ($COMPOSE_PROJECT_NAME)"
