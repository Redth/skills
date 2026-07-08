#!/bin/sh
# sync_vendor.sh — minimal/basic copy path for vendoring skill-reflect.
#
# For versioned adopt/update/doctor with drift detection, .skill-reflect-vendor.json,
# hooks.json merging, scoped nudge stamping, and manual author-approved updates, use
# the skill-reflect-maintainer skill's engine instead:
#   skills/skill-reflect-maintainer/scripts/adopt.py
# See AUTHORS.md for the canonical author guide.
#
# This helper only copies the current checkout layout into a host plugin directory.
# It never overwrites an existing skill-reflect.config.json, never performs network
# calls, never runs git, and does not blindly overwrite an existing hooks/hooks.json.
#
# Usage:
#   sync_vendor.sh --from <redth-skills-repo> --to <host-plugin-dir> [--with-auto]
#
# Options:
#   --from <path>    Path to a local Redth/skills checkout (must contain
#                    skills/skill-reflect/SKILL.md)
#   --to   <path>    Path to the host plugin directory to sync into
#   --with-auto      Also copy the Copilot CLI automation extension to
#                    extensions/skill-reflect-auto/
#
# Requirements: rsync (preferred) or cp (fallback). POSIX sh + stdlib tools only.

set -eu

SCRIPT_NAME="$(basename "$0")"

usage() {
    printf 'Usage: %s --from <redth-skills-repo> --to <host-plugin-dir> [--with-auto]\n' "$SCRIPT_NAME" >&2
    printf '\n' >&2
    printf '  --from <path>    Path to a Redth/skills repository checkout\n' >&2
    printf '  --to   <path>    Path to the host plugin directory to sync into\n' >&2
    printf '  --with-auto      Also copy extensions/skill-reflect-auto/\n' >&2
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

if [ -z "$FROM" ]; then
    printf 'ERROR: --from is required.\n' >&2
    usage
fi
if [ -z "$TO" ]; then
    printf 'ERROR: --to is required.\n' >&2
    usage
fi

if [ ! -f "$FROM/skills/skill-reflect/SKILL.md" ]; then
    printf 'ERROR: "%s/skills/skill-reflect/SKILL.md" not found.\n' "$FROM" >&2
    printf '       Is --from pointing to a Redth/skills repository checkout?\n' >&2
    exit 1
fi

if command -v rsync >/dev/null 2>&1; then
    COPY_METHOD="rsync"
else
    COPY_METHOD="cp"
fi

printf 'skill-reflect vendor sync (minimal/basic)\n'
printf '  source : %s\n' "$FROM"
printf '  target : %s\n' "$TO"
printf '  method : %s\n' "$COPY_METHOD"
printf '\n'

mkdir -p "$TO"

# ---------------------------------------------------------------------------
# Copy skills/skill-reflect/
# ---------------------------------------------------------------------------
DEST_SKILLS="$TO/skills"
DEST_SR="$DEST_SKILLS/skill-reflect"
mkdir -p "$DEST_SKILLS"

if [ "$COPY_METHOD" = "rsync" ]; then
    mkdir -p "$DEST_SR"
    rsync -a --delete "$FROM/skills/skill-reflect/" "$DEST_SR/"
else
    rm -rf "$DEST_SR"
    cp -R "$FROM/skills/skill-reflect" "$DEST_SKILLS/"
fi
printf 'Copied:  %s/skills/skill-reflect/  ->  %s/\n' "$FROM" "$DEST_SR"

# ---------------------------------------------------------------------------
# Copy Claude Code hook scripts; do not clobber an existing hooks.json.
# ---------------------------------------------------------------------------
DEST_HOOKS="$TO/hooks"
mkdir -p "$DEST_HOOKS"
cp "$FROM/hooks/stage_pending.py" "$FROM/hooks/nudge_start.py" "$DEST_HOOKS/"
printf 'Copied:  %s/hooks/stage_pending.py  ->  %s/\n' "$FROM" "$DEST_HOOKS"
printf 'Copied:  %s/hooks/nudge_start.py    ->  %s/\n' "$FROM" "$DEST_HOOKS"

if [ -f "$TO/hooks/hooks.json" ]; then
    printf 'NOTE: Existing hooks.json preserved: %s/hooks/hooks.json\n' "$TO"
    printf '      Merge the SessionStart/SessionEnd command entries from:\n'
    printf '        %s/hooks/hooks.json\n' "$FROM"
else
    cp "$FROM/hooks/hooks.json" "$DEST_HOOKS/hooks.json"
    printf 'Copied:  %s/hooks/hooks.json       ->  %s/hooks.json\n' "$FROM" "$DEST_HOOKS"
fi

# ---------------------------------------------------------------------------
# Optionally copy integrations/copilot-cli/skill-reflect-auto/
# ---------------------------------------------------------------------------
if [ "$WITH_AUTO" = "1" ]; then
    SRC_AUTO="$FROM/integrations/copilot-cli/skill-reflect-auto"
    if [ ! -d "$SRC_AUTO" ]; then
        printf 'WARNING: --with-auto specified but "%s/" not found. Skipping.\n' "$SRC_AUTO" >&2
    else
        DEST_EXTENSIONS="$TO/extensions"
        DEST_AUTO="$DEST_EXTENSIONS/skill-reflect-auto"
        mkdir -p "$DEST_EXTENSIONS"
        if [ "$COPY_METHOD" = "rsync" ]; then
            mkdir -p "$DEST_AUTO"
            rsync -a --delete "$SRC_AUTO/" "$DEST_AUTO/"
        else
            rm -rf "$DEST_AUTO"
            cp -R "$SRC_AUTO" "$DEST_EXTENSIONS/"
        fi
        printf 'Copied:  %s/  ->  %s/\n' "$SRC_AUTO" "$DEST_AUTO"
    fi
fi

# ---------------------------------------------------------------------------
# Preserve an existing skill-reflect.config.json — never overwrite it.
# ---------------------------------------------------------------------------
CONFIG="$TO/skill-reflect.config.json"
printf '\n'
if [ -f "$CONFIG" ]; then
    printf 'NOTE: Existing config preserved: %s\n' "$CONFIG"
    printf '      Review it against schema: %s/skill-reflect.config.schema.json\n' "$FROM"
else
    printf 'NOTE: No skill-reflect.config.json found at %s/\n' "$TO"
    printf '      Create one from the vendored template:\n'
    printf '        %s/vendoring/skill-reflect.config.vendored.example.json\n' "$FROM"
fi

printf '\nFor versioned maintenance, run the skill-reflect-maintainer skill (AUTHORS.md).\n'
printf 'Done.\n'
