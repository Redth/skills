#!/usr/bin/env bash
#
# validate.sh — repo-wide validation for skill-reflect.
#
# Runs, from the repo root:
#   1. python3 -m py_compile on every *.py
#   2. unittest discovery on every scripts/ dir that has test_*.py
#   3. node --check on every *.mjs / *.js (if node is available)
#   4. JSON parse on every *.json (skipping .jsonc)
#   5. bash -n / sh -n on every *.sh
#   6. a light "dangling reference" scan: markdown links to repo-relative
#      paths that don't exist on disk
#
# Exit code is non-zero if any check fails. No network, no writes.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
note() { printf '%s\n' "$*"; }
section() { printf '\n=== %s ===\n' "$*"; }

# Directories we never scan
PRUNE=(-name .git -o -name node_modules -o -name .venv -o -name __pycache__)

section "1. python compile"
while IFS= read -r f; do
  if python3 -m py_compile "$f" 2>/tmp/_v_err; then
    note "OK   $f"
  else
    note "FAIL $f"; cat /tmp/_v_err; fail=1
  fi
done < <(find . \( "${PRUNE[@]}" \) -prune -o -name '*.py' -print | sort)

section "2. python unittest discovery"
# Find dirs containing test_*.py and run discovery in each once.
while IFS= read -r d; do
  note "-- discover in $d"
  if ( cd "$d" && python3 -m unittest discover -s . -p 'test_*.py' ) 2>/tmp/_v_err; then
    tail -2 /tmp/_v_err 2>/dev/null || true
    note "OK   tests in $d"
  else
    cat /tmp/_v_err; note "FAIL tests in $d"; fail=1
  fi
done < <(find . \( "${PRUNE[@]}" \) -prune -o -name 'test_*.py' -print \
          | xargs -n1 dirname 2>/dev/null | sort -u)

section "3. node --check (*.mjs, *.js)"
if command -v node >/dev/null 2>&1; then
  while IFS= read -r f; do
    if node --check "$f" 2>/tmp/_v_err; then
      note "OK   $f"
    else
      note "FAIL $f"; cat /tmp/_v_err; fail=1
    fi
  done < <(find . \( "${PRUNE[@]}" \) -prune -o \( -name '*.mjs' -o -name '*.js' \) -print | sort)
else
  note "SKIP node not available"
fi

section "4. JSON parse (*.json, not *.jsonc)"
while IFS= read -r f; do
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>/tmp/_v_err; then
    note "OK   $f"
  else
    note "FAIL $f"; cat /tmp/_v_err; fail=1
  fi
done < <(find . \( "${PRUNE[@]}" \) -prune -o -name '*.json' -print | sort)

section "5. shell syntax (*.sh)"
# Check each script with the interpreter its shebang declares. A bash script
# that uses bash-only constructs (e.g. process substitution) is not valid
# POSIX sh, so linting it with `sh -n` would be a false positive; conversely a
# script that declares #!/bin/sh is verified against POSIX to confirm portability.
while IFS= read -r f; do
  ok=1
  shebang="$(head -n1 "$f")"
  case "$shebang" in
    *bash*) bash -n "$f" 2>/tmp/_v_err || { ok=0; cat /tmp/_v_err; } ;;
    *)      sh   -n "$f" 2>/tmp/_v_err || { ok=0; cat /tmp/_v_err; } ;;
  esac
  if [ "$ok" = 1 ]; then note "OK   $f"; else note "FAIL $f"; fail=1; fi
done < <(find . \( "${PRUNE[@]}" \) -prune -o -name '*.sh' -print | sort)

section "6. dangling markdown references (best-effort)"
# Look for inline links/backticks to repo-relative paths and check existence.
# Purely advisory: reference misses print a WARN and do NOT fail the build,
# because many docs reference example/placeholder paths intentionally.
python3 - "$ROOT" <<'PY'
import os, re, sys
root = sys.argv[1]
link_re = re.compile(r'\]\(([^)]+)\)')
warn = 0
for dp, dn, fn in os.walk(root):
    if any(seg in dp for seg in ('/.git', '/node_modules', '/__pycache__')):
        continue
    for name in fn:
        if not name.endswith('.md'):
            continue
        p = os.path.join(dp, name)
        try:
            text = open(p, encoding='utf-8').read()
        except Exception:
            continue
        for m in link_re.finditer(text):
            tgt = m.group(1).split('#')[0].strip()
            if not tgt or tgt.startswith(('http://', 'https://', 'mailto:', '<')):
                continue
            if tgt.startswith('/'):
                cand = os.path.join(root, tgt.lstrip('/'))
            else:
                cand = os.path.normpath(os.path.join(dp, tgt))
            if not os.path.exists(cand):
                rel = os.path.relpath(p, root)
                print(f"WARN {rel} -> {tgt}")
                warn += 1
print(f"(dangling-ref warnings: {warn})")
PY

section "RESULT"
if [ "$fail" = 0 ]; then
  note "ALL HARD CHECKS PASSED"
else
  note "SOME CHECKS FAILED"
fi
exit "$fail"
