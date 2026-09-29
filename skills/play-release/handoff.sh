#!/usr/bin/env bash
# Open everything needed for the manual half of a Play release: Finder at the
# files to upload, and Chrome at the pages to upload them to.
#
# The AAB and the store images cannot be uploaded by automation (see SKILL.md),
# so this makes the handoff as short as possible instead of pretending
# otherwise. It runs preflight.sh first and refuses to open anything if the
# artefact is not fit to upload — handing over a debug-signed or over-length
# release is worse than handing over nothing.
#
# Usage:
#   handoff.sh                      # ids from .play-release, env, or fall back
#   handoff.sh --app-id 123 --dev-id 456
#   handoff.sh --force              # open even if preflight fails
#   handoff.sh --aab path/to.aab
#
# Ids: take them from any Play Console URL —
#   /developers/<DEV_ID>/app/<APP_ID>/...
# Set them once per repo in a `.play-release` file:
#   PLAY_DEV_ID=<developer id>
#   PLAY_APP_ID=<app id>

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
META="fastlane/metadata/android/en-US"
AAB="build/app/outputs/bundle/release/app-release.aab"
FORCE=0

case "${1:-}" in -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; esac

# ids: file < env < args
[ -f .play-release ] && . ./.play-release
DEV_ID="${PLAY_DEV_ID:-}"
APP_ID="${PLAY_APP_ID:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --app-id) APP_ID="$2"; shift 2;;
    --dev-id) DEV_ID="$2"; shift 2;;
    --aab)    AAB="$2";    shift 2;;
    --force)  FORCE=1;     shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

bold() { printf '\033[1m%s\033[0m\n' "$1"; }

# --- refuse to hand over something broken -------------------------------------
bold "Checking the artefact first"
if "$HERE/preflight.sh" "$AAB" >/tmp/play-preflight.$$ 2>&1; then
  echo "  preflight passed"
else
  cat /tmp/play-preflight.$$
  rm -f /tmp/play-preflight.$$
  if [ "$FORCE" -eq 0 ]; then
    echo
    bold "Not opening anything — fix the failures above, or re-run with --force."
    exit 1
  fi
  echo
  echo "  --force given, continuing anyway"
fi
rm -f /tmp/play-preflight.$$

# --- Finder -------------------------------------------------------------------
bold "Opening Finder"
if [ -d "$META/images" ]; then
  open "$META/images" && echo "  images        $META/images"
else
  echo "  (no $META/images to open)"
fi
if [ -f "$AAB" ]; then
  # -R reveals and selects the file rather than just opening its folder.
  open -R "$AAB" && echo "  app bundle    $AAB"
fi

# --- Chrome -------------------------------------------------------------------
# Opened in the normal browser, not the automation tab group, so the existing
# signed-in session is used and the tabs stay put after this script exits.
bold "Opening Play Console"
BROWSER="Google Chrome"
open_tab() { open -a "$BROWSER" "$1" 2>/dev/null && echo "  $2"; }

if [ -n "$DEV_ID" ] && [ -n "$APP_ID" ]; then
  BASE="https://play.google.com/console/u/0/developers/$DEV_ID/app/$APP_ID"
  open_tab "$BASE/main-store-listing" "store listing (icon, feature graphic, screenshots)"
  sleep 1
  open_tab "$BASE/tracks/production"  "production track (upload the .aab)"
  sleep 1
  open_tab "$BASE/publishing"         "publishing overview (send for review)"
else
  open_tab "https://play.google.com/console" "Play Console (set PLAY_DEV_ID / PLAY_APP_ID for deep links)"
fi

# --- what to actually do ------------------------------------------------------
cat <<'EOF'

What to do, in order
  1. Store listing tab → the "Add assets" buttons:
       icon             images/icon.png                  (512x512)
       feature graphic  images/featureGraphic.png        (1024x500)
       phone            images/phoneScreenshots/*
       10-inch tablet   images/tenInchScreenshots/*      (scroll down for it)
       7-inch tablet    images/sevenInchScreenshots/*    (if present)
     Save.
     Tablet slots sit further down the same page than you expect — filling
     only the phone slot loses tablet placement.
  2. Production tab → Create new release → drop in the .aab Finder selected.
     Add release notes, Save, then Review release.
  3. Publishing overview → Send app for review.

Notes
  - Saving only stages a change. Nothing reaches Google until step 3.
  - A deep link sometimes bounces to the app list; if so, pick the app and use
    the left nav rather than retrying the URL.
EOF
