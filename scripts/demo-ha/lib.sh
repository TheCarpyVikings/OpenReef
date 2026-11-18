# Shared helpers for up.sh / down.sh / auth-state. Source this; do not run it.
DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$DEMO_DIR" rev-parse --show-toplevel)"
SLUG="$(basename "$REPO_ROOT" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9]\+/-/g; s/^-//; s/-$//' | cut -c1-40)"
export COMPOSE_PROJECT_NAME="ordemo-$SLUG"
export OPENREEF_SRC="$REPO_ROOT/custom_components/openreef"
# Fixed, local-only demo credentials (documented in AGENTS.md).
export DEMO_USER="demo" DEMO_PASS="demo-reef-only"

compose() { docker compose -f "$DEMO_DIR/docker-compose.yml" "$@"; }

# Port of the running proxy for this worktree, or empty.
running_port() {
  docker port "${COMPOSE_PROJECT_NAME}-proxy-1" 8123/tcp 2>/dev/null | sed -n 's/^127\.0\.0\.1:\([0-9]*\)$/\1/p' | head -1
}

# Deterministic port in 8300-8399 from the worktree slug; probe forward if it is taken.
pick_port() {
  local p; p="$(running_port)"
  if [ -n "$p" ]; then echo "$p"; return; fi
  local start=$(( $(printf '%s' "$SLUG" | cksum | cut -d' ' -f1) % 100 )) i cand
  for i in $(seq 0 99); do
    cand=$(( 8300 + (start + i) % 100 ))
    if ! ss -ltnH "( sport = :$cand )" | grep -q .; then echo "$cand"; return; fi
  done
  echo "no free port in 8300-8399" >&2; return 1
}
