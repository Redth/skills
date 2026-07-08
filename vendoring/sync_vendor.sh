#!/bin/sh
# sync_vendor.sh — copies skill-reflect/ (and optionally skill-reflect-auto/) from a
# skill-reflect repository checkout into a host plugin directory.
#
# Never overwrites an existing skill-reflect.config.json in the target.
# Pure copy tool — no network calls, no git operations, no AI.
#
# Usage:
#   sync_vendor.sh --from <skill-reflect-repo> --to <host-plugin-dir> [--with-auto]
#
# Options:
#   --from <path>    Path to a local skill-reflect repository checkout (must contain
#                    skill-reflect/SKILL.md)
#   --to   <path>    Path to the host plugin directory to sync into
#   --with-auto      Also copy skill-reflect-auto/ (Copilot CLI automation extension)
#
# Requirements: rsync (preferred) or cp (fallback). Neither git nor a network
#               connection is required.

set -eu

SCRIPT_NAME="$(basename "$0")"

usage() {
    printf 'Usage: %s --from <skill-reflect-repo> --to <host-plugin-dir> [--with-auto]\n' "$SCRIPT_NAME" >&2
    printf '\n' >&2
    printf '  --from <path>    Path to a skill-reflect repository checkout\n' >&2
    printf '  --to   <path>    Path to the host plugin directory to sync into\n' >&2
    printf '  --with-auto      Also copy skill-reflect-auto/ (optional automation extension)\n' >&2
    printf '  -h, --help       Show this message\n' >&2
    exit 1
}

FROM=""
TO=""
WITH_AUTO=0

while [ $# -gt 0 ]; do
    case "$1" in
        --from)
            if [ $# -lt 2 ]; then
                printf 'ERROR: --from requires an argument.\n' >&2
                usage
            fi
            shift
            FROM="$1"
            ;;
        --to)
            if [ $# -lt 2 ]; then
                printf 'ERROR: --to requires an argument.\n' >&2
                usage
            fi
            shift
            TO="$1"
            ;;
        --with-auto)
            WITH_AUTO=1
            ;;
        -h|--help)
            usage
            ;;
        *)
            printf 'ERROR: Unknown option: %s\n' "$1" >&2
            usage
            ;;
    esac
    shift
done

# Validate required arguments
if [ -z "$FROM" ]; then
    printf 'ERROR: --from is required.\n' >&2
    usage
fi
if [ -z "$TO" ]; then
    printf 'ERROR: --to is required.\n' >&2
    usage
fi

# Refuse if source does not look like a skill-reflect repository
if [ ! -f "$FROM/skill-reflect/SKILL.md" ]; then
    printf 'ERROR: "%s/skill-reflect/SKILL.md" not found.\n' "$FROM" >&2
    printf '       Is --from pointing to a skill-reflect repository checkout?\n' >&2
    exit 1
fi

# Determine copy method (prefer rsync for incremental updates)
if command -v rsync >/dev/null 2>&1; then
    COPY_METHOD="rsync"
else
    COPY_METHOD="cp"
fi

printf 'skill-reflect vendor sync\n'
printf '  source : %s\n' "$FROM"
printf '  target : %s\n' "$TO"
printf '  method : %s\n' "$COPY_METHOD"
printf '\n'

# Create target directory if it does not exist
mkdir -p "$TO"

# ---------------------------------------------------------------------------
# Copy skill-reflect/
# ---------------------------------------------------------------------------
DEST_SR="$TO/skill-reflect"
mkdir -p "$DEST_SR"

if [ "$COPY_METHOD" = "rsync" ]; then
    rsync -a --delete "$FROM/skill-reflect/" "$DEST_SR/"
else
    rm -rf "$DEST_SR"
    cp -R "$FROM/skill-reflect" "$DEST_SR"
fi
printf 'Copied:  %s/skill-reflect/  ->  %s/\n' "$FROM" "$DEST_SR"

# ---------------------------------------------------------------------------
# Optionally copy skill-reflect-auto/
# ---------------------------------------------------------------------------
if [ "$WITH_AUTO" = "1" ]; then
    if [ ! -d "$FROM/skill-reflect-auto" ]; then
        printf 'WARNING: --with-auto specified but "%s/skill-reflect-auto/" not found. Skipping.\n' "$FROM" >&2
    else
        DEST_AUTO="$TO/skill-reflect-auto"
        mkdir -p "$DEST_AUTO"
        if [ "$COPY_METHOD" = "rsync" ]; then
            rsync -a --delete "$FROM/skill-reflect-auto/" "$DEST_AUTO/"
        else
            rm -rf "$DEST_AUTO"
            cp -R "$FROM/skill-reflect-auto" "$DEST_AUTO"
        fi
        printf 'Copied:  %s/skill-reflect-auto/  ->  %s/\n' "$FROM" "$DEST_AUTO"
    fi
fi

# ---------------------------------------------------------------------------
# Preserve an existing skill-reflect.config.json — never overwrite it
# ---------------------------------------------------------------------------
CONFIG="$TO/skill-reflect.config.json"
printf '\n'
if [ -f "$CONFIG" ]; then
    printf 'NOTE: Existing config preserved: %s\n' "$CONFIG"
    printf '      Review it to confirm it is still compatible with the updated skill version.\n'
    printf '      Schema reference: %s/skill-reflect.config.schema.json\n' "$FROM"
else
    printf 'NOTE: No skill-reflect.config.json found at %s/\n' "$TO"
    printf '      Create one from the vendored template:\n'
    printf '        %s/vendoring/skill-reflect.config.vendored.example.json\n' "$FROM"
fi

printf '\nDone.\n'
