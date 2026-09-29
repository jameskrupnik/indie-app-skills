#!/usr/bin/env bash
# Open everything a human needs for the manual half of a Play release: Finder
# at the files to upload, and the browser at the Play Console pages to upload
# them to. macOS only (uses `open`); elsewhere, use --dry-run to print the
# paths and URLs instead.
#
# It runs preflight.sh first and opens nothing if the bundle is not fit to
# upload — handing over a debug-signed or over-length release is worse than
# handing over nothing.
#
# Run from the Flutter project root.
#
# Usage:
#   handoff.sh [options]
#
#   --app-id ID    Play Console app id        (or PLAY_APP_ID)
#   --dev-id ID    Play Console developer id  (or PLAY_DEV_ID)
#   --aab PATH     bundle to check and reveal
#                  (default build/app/outputs/bundle/release/app-release.aab)
#   --dry-run      print what would be opened; open nothing (works anywhere)
#   --force        open even if preflight fails
#   -h, --help     this text
#
# Ids come from any Play Console URL: /developers/<DEV_ID>/app/<APP_ID>/...
# Save them once in a `.play-release` file at the project root (it is sourced
# as shell, so keep it to these two lines):
#   PLAY_DEV_ID=<developer id>
#   PLAY_APP_ID=<app id>
# Without them the Play Console home page opens instead of deep links.
#
# Environment: PLAY_BROWSER  macOS app to open the console in
#                            (default "Google Chrome", else the default browser)
#
# Exit: 0 handed off, 1 preflight failed, 2 bad usage or unsupported OS.

set -uo pipefail

usage() { sed -n '2,34p' "$0" | sed 's/^# \{0,1\}//'; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META="fastlane/metadata/android/en-US"
AAB="build/app/outputs/bundle/release/app-release.aab"
FORCE=0
DRY=0

# ids: file < env < args
if [ -f .play-release ]; then
  # shellcheck disable=SC1091
  . ./.play-release
fi
DEV_ID="${PLAY_DEV_ID:-}"
APP_ID="${PLAY_APP_ID:-}"

need_arg() { [ "$2" -ge 2 ] || { echo "$1 needs a value (see --help)" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --app-id)  need_arg "$1" $#; APP_ID="$2"; shift 2 ;;
    --dev-id)  need_arg "$1" $#; DEV_ID="$2"; shift 2 ;;
    --aab)     need_arg "$1" $#; AAB="$2";    shift 2 ;;
    --force)   FORCE=1; shift ;;
    --dry-run) DRY=1;   shift ;;
    *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

if [ "$DRY" -eq 0 ] && [ "$(uname -s)" != Darwin ]; then
  echo "handoff.sh opens Finder and a browser with macOS 'open'; this is $(uname -s)." >&2
  echo "Run it with --dry-run to print the files and URLs instead." >&2
  exit 2
fi

bold() { if [ -t 1 ]; then printf '\033[1m%s\033[0m\n' "$1"; else printf '%s\n' "$1"; fi; }

# --- refuse to hand over something broken -------------------------------------
bold "Checking the bundle first"
LOG=$(mktemp "${TMPDIR:-/tmp}/play-preflight.XXXXXX")
trap 'rm -f "$LOG"' EXIT
if bash "$HERE/preflight.sh" --quiet "$AAB" >"$LOG" 2>&1; then
  echo "  preflight passed (warnings, if any, below)"
  grep -E 'warn' "$LOG" | sed 's/^ */  /' || true
else
  cat "$LOG"
  if [ "$FORCE" -eq 0 ]; then
    echo
    bold "Not opening anything — fix the failures above, or re-run with --force."
    exit 1
  fi
  echo
  echo "  --force given, continuing anyway"
fi

# open_path <label> <open args...>: open, or just print under --dry-run.
run_open() {
  local label="$1"; shift
  if [ "$DRY" -eq 1 ]; then printf '  would open  %-28s %s\n' "$label" "${*: -1}"
  else open "$@" && printf '  %-28s %s\n' "$label" "${*: -1}"; fi
}

# --- files --------------------------------------------------------------------
bold "Files"
if [ -d "$META/images" ]; then
  run_open "images folder" "$META/images"
else
  echo "  (no $META/images)"
fi
# -R reveals and selects the file rather than just opening its folder.
[ -f "$AAB" ] && run_open "app bundle (selected)" -R "$AAB"

# --- console ------------------------------------------------------------------
# Opened in the normal browser profile, not an automation tab group, so the
# existing signed-in session is used and the tabs outlive this script.
bold "Play Console"
BROWSER="${PLAY_BROWSER:-Google Chrome}"
open_url() {
  if [ "$DRY" -eq 0 ] && ! open -Ra "$BROWSER" 2>/dev/null; then
    run_open "$2" "$1"                     # default browser
  else
    run_open "$2" -a "$BROWSER" "$1"
  fi
}
if [ -n "$DEV_ID" ] && [ -n "$APP_ID" ]; then
  BASE="https://play.google.com/console/u/0/developers/$DEV_ID/app/$APP_ID"
  open_url "$BASE/main-store-listing" "store listing"
  [ "$DRY" -eq 1 ] || sleep 1
  open_url "$BASE/tracks/production"  "production track"
  [ "$DRY" -eq 1 ] || sleep 1
  open_url "$BASE/publishing"         "publishing overview"
else
  open_url "https://play.google.com/console" "Play Console home"
  echo "  (set PLAY_DEV_ID and PLAY_APP_ID for deep links — see --help)"
fi

cat <<'EOF'

What to do, in order
  1. Store listing -> each "Add assets" button:
       icon             images/icon.png                  (512x512)
       feature graphic  images/featureGraphic.png        (1024x500)
       phone            images/phoneScreenshots/*
       7-inch tablet    images/sevenInchScreenshots/*    (further down the page)
       10-inch tablet   images/tenInchScreenshots/*      (further down the page)
     Save.
  2. Production track -> Create new release -> drop in the selected .aab.
     Add release notes, Save, then Review release.
  3. Publishing overview -> Send app for review.

Saving only stages a change; nothing reaches Google until step 3.
If a deep link bounces to the app list, pick the app and use the left nav.
EOF
