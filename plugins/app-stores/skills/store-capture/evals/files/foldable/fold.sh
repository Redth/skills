#!/bin/sh
# Opens or closes the foldable before launch, run as a script step on each foldable device.
# Usage: fold.sh unfolded|folded [WxH]
MODE="${1:-unfolded}"
SIZE="${2:-}"
if [ -n "${APPSTORES_UDID:-}" ]; then
  maui devflow device fold set "$MODE" --udid "$APPSTORES_UDID" --experimental --timeout 60
elif [ -n "${ANDROID_SERIAL:-}" ]; then
  if [ "$MODE" = unfolded ]; then adb -s "$ANDROID_SERIAL" emu unfold; else adb -s "$ANDROID_SERIAL" emu fold; fi
  sleep 3
  if [ -n "$SIZE" ]; then adb -s "$ANDROID_SERIAL" shell wm size "$SIZE"; fi
fi
