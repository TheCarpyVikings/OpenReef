#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

STRATON_FILES=(
  "README.md"
  "custom_components/openreef/const.py"
  "custom_components/openreef/__init__.py"
  "custom_components/openreef/diagnostics.py"
  "custom_components/openreef/frontend/openreef-panel.js"
  "docs/straton-beta-test-guide.md"
  "docs/straton-controller-integration.md"
  "docs/straton-push-checklist.md"
  "scripts/check_straton_beta.sh"
)

usage() {
  cat <<'EOF'
Usage: scripts/check_straton_beta.sh [--files|--help]

Runs the focused OpenReef Straton beta pre-push checks without staging,
committing, pushing, or changing repo state.

Options:
  --files   Print the exact Straton files that belong in the narrow commit.
  --help    Show this help text.
EOF
}

print_files() {
  printf '%s\n' "${STRATON_FILES[@]}"
}

case "${1:-}" in
  "")
    ;;
  --files)
    print_files
    exit 0
    ;;
  --help|-h)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

run() {
  printf '\n==> %s\n' "$*"
  "$@"
}

printf 'OpenReef Straton beta pre-push check\n'
printf 'Repo: %s\n' "$ROOT"

printf '\n==> expected Straton files\n'
print_files

printf '\n==> file existence check\n'
for file in "${STRATON_FILES[@]}"; do
  if [[ ! -e "$file" ]]; then
    printf 'Missing expected Straton file: %s\n' "$file" >&2
    exit 1
  fi
done
printf 'All expected Straton files exist.\n'

printf '\n==> push checklist drift check\n'
for file in "${STRATON_FILES[@]}"; do
  if ! grep -Fq "\`$file\`" docs/straton-push-checklist.md; then
    printf 'Push checklist does not mention expected Straton file: %s\n' "$file" >&2
    exit 1
  fi
done
printf 'Push checklist mentions every expected Straton file.\n'

run node --check custom_components/openreef/frontend/openreef-panel.js
run python3 -m py_compile \
  custom_components/openreef/const.py \
  custom_components/openreef/__init__.py \
  custom_components/openreef/diagnostics.py
run pnpm exec tsc --noEmit
run pnpm lint

printf '\n==> whitespace check for Straton files\n'
perl -ne 'print "$ARGV:$.: trailing whitespace\n" if /[ \t]$/; close ARGV if eof' "${STRATON_FILES[@]}"

printf '\n==> conflict-marker scan for Straton files\n'
if command -v rg >/dev/null 2>&1; then
  if rg -n '^(<<<<<<<|=======|>>>>>>>)' "${STRATON_FILES[@]}"; then
    printf 'Conflict marker scan found matches.\n' >&2
    exit 1
  fi
else
  if grep -nE '^(<<<<<<<|=======|>>>>>>>)' "${STRATON_FILES[@]}"; then
    printf 'Conflict marker scan found matches.\n' >&2
    exit 1
  fi
fi

printf '\n==> git diff --check for tracked Straton files\n'
git diff --check -- \
  README.md \
  custom_components/openreef/const.py \
  custom_components/openreef/__init__.py \
  custom_components/openreef/diagnostics.py \
  custom_components/openreef/frontend/openreef-panel.js

printf '\n==> Straton file status\n'
git status --short -- "${STRATON_FILES[@]}" || true

printf '\n==> staged-file guard\n'
mapfile -t STAGED_FILES < <(git diff --cached --name-only)
if ((${#STAGED_FILES[@]})); then
  for file in "${STAGED_FILES[@]}"; do
    allowed=0
    for straton_file in "${STRATON_FILES[@]}"; do
      if [[ "$file" == "$straton_file" ]]; then
        allowed=1
        break
      fi
    done
    if ((allowed == 0)); then
      printf 'Unrelated staged file: %s\n' "$file" >&2
      printf 'Unstage it before committing the Straton beta work.\n' >&2
      exit 1
    fi
  done
  printf 'Only Straton files are staged.\n'
else
  printf 'No files are staged yet.\n'
fi

printf '\n==> unrelated dirty-file reminder\n'
git status --short | while IFS= read -r line; do
  path="${line:3}"
  keep=0
  for straton_file in "${STRATON_FILES[@]}"; do
    if [[ "$path" == "$straton_file" ]]; then
      keep=1
      break
    fi
  done
  if ((keep == 0)); then
    printf '%s\n' "$line"
  fi
done

printf '\nStraton beta checks finished. Keep the commit narrow and do not stage unrelated files.\n'
