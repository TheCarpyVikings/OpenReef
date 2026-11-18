#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

DATE_STAMP="${OPENREEF_CONTEXT_DATE:-$(date +%F)}"
OUTPUT_FILE="${1:-openreef_context_${DATE_STAMP}.md}"
FILES_TMP="$(mktemp)"
BUNDLE_TMP="$(mktemp)"
SCAN_TMP="$(mktemp)"
trap 'rm -f "$FILES_TMP" "$BUNDLE_TMP" "$SCAN_TMP"' EXIT

DISALLOWED_PATH_REGEX='(^|/)(\.env[^/]*|\.google-tokens\.json|\.reef-settings\.json|openreef-settings\.json|.*\.pem)$'
EXCLUDED_PATH_REGEX='(^|/)(\.git|\.agents|\.next|node_modules|\.venv|coverage|out|build|dist)(/|$)|(^|/)codebase_bundle.*\.md$|(^|/)openreef_context_.*\.md$|(^|/)openreef_context_for_gravityclaw\.md$|(^|/)openreef_notebooklm_bundle\.md$|(^|/)gather_reef_context\.sh$|(^|/)pnpm-lock\.yaml$|(^|/)package-lock\.json$|(^|/)yarn\.lock$|(^|/)tsconfig\.tsbuildinfo$|(^|/)next-env\.d\.ts$|(^|/)\.DS_Store$|.*\.(png|jpe?g|webp|gif|ico|pdf|zip|tar|gz|tgz|mp4|mov|mp3|wav|woff2?|ttf|eot)$'

fence_lang() {
    local file="$1"
    case "$file" in
        *.ts|*.tsx) echo "tsx" ;;
        *.js|*.jsx|*.mjs|*.cjs) echo "js" ;;
        *.css) echo "css" ;;
        *.json) echo "json" ;;
        *.yaml|*.yml) echo "yaml" ;;
        *.md) echo "md" ;;
        *.html) echo "html" ;;
        *.sh) echo "bash" ;;
        *.py) echo "python" ;;
        Dockerfile|*/Dockerfile) echo "dockerfile" ;;
        *.svg) echo "svg" ;;
        *) echo "" ;;
    esac
}

is_text_file() {
    local file="$1"

    case "$file" in
        *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.css|*.json|*.yaml|*.yml|*.md|*.html|*.sh|*.py|*.svg|*.toml|*.txt|Dockerfile|*/Dockerfile)
            return 0
            ;;
    esac

    if command -v file >/dev/null 2>&1; then
        local mime_type
        mime_type="$(file --mime-type -b "$file" 2>/dev/null || true)"
        [[ "$mime_type" == text/* ]]
        return
    fi

    return 1
}

collect_files() {
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git ls-files --cached --others --exclude-standard
    else
        find . -type f -print | sed 's#^\./##'
    fi
}

while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    [[ "$file" =~ $DISALLOWED_PATH_REGEX ]] && continue
    [[ "$file" =~ $EXCLUDED_PATH_REGEX ]] && continue
    [[ -f "$file" ]] || continue
    is_text_file "$file" || continue
    printf '%s\n' "$file"
done < <(collect_files) | LC_ALL=C sort -u > "$FILES_TMP"

if [[ ! -s "$FILES_TMP" ]]; then
    echo "No safe text files found to bundle." >&2
    exit 1
fi

if grep -Eq "$DISALLOWED_PATH_REGEX" "$FILES_TMP"; then
    echo "Refusing to bundle: a disallowed secret/config path was selected." >&2
    grep -En "$DISALLOWED_PATH_REGEX" "$FILES_TMP" >&2 || true
    exit 1
fi

COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")"
STATUS_COUNT="$(git status --short 2>/dev/null | wc -l | tr -d ' ')"
FILE_COUNT="$(wc -l < "$FILES_TMP" | tr -d ' ')"

{
    echo "# OpenReef ChatGPT Context Bundle"
    echo
    echo "- Generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
    echo "- Repository: OpenReef"
    echo "- Commit: $COMMIT_SHA"
    echo "- Working tree entries changed/untracked: $STATUS_COUNT"
    echo "- Included safe text files: $FILE_COUNT"
    echo
    echo "## How To Use This Bundle"
    echo
    echo "Upload this file to the ChatGPT Project named \`OpenReef\` alongside \`docs/chatgpt_project_brief.md\` and the lightweight docs you want ChatGPT to reference."
    echo
    echo "Treat this bundle as a read-only snapshot. Make code changes in the repository through Codex or your editor, then regenerate this file when the repo meaningfully changes."
    echo
    echo "## Safety Exclusions"
    echo
    echo "This bundle intentionally excludes local secrets/config, generated build output, dependencies, old context bundles, lockfiles, and raster/media assets."
    echo
    echo "Excluded secret/config examples: \`.env*\`, \`*.pem\`, \`.google-tokens.json\`, \`.reef-settings.json\`, and \`openreef-settings.json\`."
    echo
    echo "## Included Files"
    echo
    sed 's/^/- `/' "$FILES_TMP" | sed 's/$/`/'
    echo
    echo "## File Contents"
    echo

    while IFS= read -r file; do
        lang="$(fence_lang "$file")"
        echo "<file path=\"$file\">"
        echo "\`\`\`\`$lang"
        cat "$file"
        echo
        echo "\`\`\`\`"
        echo "</file>"
        echo
    done < "$FILES_TMP"
} > "$BUNDLE_TMP"

if grep -Eq '(<file path="(\.env|\.google-tokens\.json|\.reef-settings\.json|openreef-settings\.json)|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})' "$BUNDLE_TMP"; then
    echo "Refusing to write bundle: the safety scan found a likely secret or disallowed file marker." >&2
    grep -En '(<file path="(\.env|\.google-tokens\.json|\.reef-settings\.json|openreef-settings\.json)|-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})' "$BUNDLE_TMP" > "$SCAN_TMP" || true
    sed -n '1,20p' "$SCAN_TMP" >&2
    exit 1
fi

mv "$BUNDLE_TMP" "$OUTPUT_FILE"

echo "Generated $OUTPUT_FILE"
echo "Included $FILE_COUNT safe text files."
echo "Upload with docs/chatgpt_project_brief.md to your OpenReef ChatGPT Project."
