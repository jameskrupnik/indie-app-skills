#!/usr/bin/env bash
# Pre-upload checks for a Flutter app bundle going to Google Play.
#
# Checks what is silently wrong at upload time and that no test suite covers:
#
#   - signed with a real upload key, not the debug key Gradle falls back to
#   - targetSdkVersion against Play's current minimum (needs bundletool)
#   - the AD_ID permission, which must agree with the Advertising ID declaration
#   - assets bundled from dependencies under flutter_assets/packages/
#   - store text within Play's limits, in every locale (counted in characters)
#   - icon, feature graphic and screenshots within Play's size rules
#   - the privacy policy URL actually resolving
#   - EEA consent: gathering AND the in-app revocation entry point
#
# It cannot tell which build configuration (flavor, --dart-define) produced
# the bundle. See SKILL.md.
#
# Run from the Flutter project root. Expected layout:
#   pubspec.yaml
#   build/app/outputs/bundle/release/app-release.aab   (default bundle path)
#   fastlane/metadata/android/<locale>/{title,short_description,full_description}.txt
#   fastlane/metadata/android/<locale>/images/{icon.png,featureGraphic.png,
#       phoneScreenshots/,sevenInchScreenshots/,tenInchScreenshots/}
#
# Usage:
#   preflight.sh [--metadata DIR] [--offline] [--quiet] [path/to/app.aab]
#
#   --metadata DIR  metadata root (default fastlane/metadata/android)
#   --offline       skip the privacy policy URL request
#   -q, --quiet     print only failures and warnings
#
# Environment:
#   PLAY_MIN_TARGET_SDK   minimum targetSdkVersion (default 36, Play's rule
#                         for new apps and updates from 2026-08-31)
#   PLAY_ASSET_ALLOW      extended regex of package asset paths not to report
#
# Needs: unzip, a JDK's jarsigner. Optional: bundletool, curl, sips (macOS).
# Exit: 0 no failures (warnings allowed), 1 at least one failure, 2 bad usage.

set -uo pipefail

usage() { sed -n '2,38p' "$0" | sed 's/^# \{0,1\}//'; }

AAB="build/app/outputs/bundle/release/app-release.aab"
META_ROOT="fastlane/metadata/android"
OFFLINE=0
QUIET=0
MIN_TARGET="${PLAY_MIN_TARGET_SDK:-36}"

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --metadata)
      [ $# -ge 2 ] || { echo "--metadata needs a directory" >&2; exit 2; }
      META_ROOT="$2"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
    -q|--quiet) QUIET=1; shift ;;
    -*) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    *) AAB="$1"; shift ;;
  esac
done

FAIL=0
if [ -t 1 ]; then G=$'\033[32m' R=$'\033[31m' Y=$'\033[33m' B=$'\033[1m' N=$'\033[0m'
else G='' R='' Y='' B='' N=''; fi
pass() { [ "$QUIET" -eq 1 ] || printf '  %sok%s    %s\n' "$G" "$N" "$1"; }
fail() { printf '  %sFAIL%s  %s\n' "$R" "$N" "$1"; FAIL=1; }
warn() { printf '  %swarn%s  %s\n' "$Y" "$N" "$1"; }
note() { printf '        %s\n' "$1"; }
head2() { printf '\n%s%s%s\n' "$B" "$1" "$N"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Characters, not bytes: Play's limits are in characters, and `wc -c` counts
# an accented letter as 2 and a CJK one as 3. Counting bytes that are not
# UTF-8 continuation bytes gives code points in any locale, on BSD and GNU.
# Trailing newlines are dropped (command substitution strips them).
charcount() {
  local s; s=$(cat "$1")
  printf '%s' "$s" | LC_ALL=C tr -d '\200-\277' | wc -c | tr -d ' '
}

# Width and height of an image, "W H", or nothing. PNG is read from its
# header, so it works everywhere; anything else needs sips (macOS) or file(1).
imgsize() {
  local sig
  sig=$(od -An -tx1 -N8 "$1" 2>/dev/null | tr -d ' \n')
  if [ "$sig" = "89504e470d0a1a0a" ]; then
    od -An -tu1 -j16 -N8 "$1" | awk '{
      for (i = 1; i <= NF; i++) b[n++] = $i }
      END { printf "%d %d\n", ((b[0]*256+b[1])*256+b[2])*256+b[3],
                              ((b[4]*256+b[5])*256+b[6])*256+b[7] }'
  elif have sips; then
    sips -g pixelWidth -g pixelHeight "$1" 2>/dev/null \
      | awk '/pixelWidth/{w=$2} /pixelHeight/{h=$2} END{if(w&&h)print w, h}'
  else
    file "$1" 2>/dev/null | grep -oE '[0-9]+ ?x ?[0-9]+' | tail -1 | tr -d ' ' | tr x ' '
  fi
}

filesize() { wc -c < "$1" | tr -d ' '; }

[ -f pubspec.yaml ] || warn "no pubspec.yaml here — run this from the Flutter project root"

# --- bundle ------------------------------------------------------------------
head2 "Bundle"
if [ ! -f "$AAB" ]; then
  fail "no bundle at $AAB — build one first (flutter build appbundle)"
  echo
  echo "Nothing else can be checked without it."
  exit 1
fi
if ! have unzip; then
  fail "unzip not found — install it; the bundle cannot be inspected without it"
  exit 1
fi
pass "$AAB ($(du -h "$AAB" | cut -f1 | tr -d ' '))"

# --- signing -----------------------------------------------------------------
# The Flutter template's build.gradle(.kts) signs release with the debug key
# when key.properties is absent or incomplete, and says nothing. jarsigner
# still reports "jar verified" for a debug-signed bundle, so read the signer's
# identity, not the verdict.
head2 "Signing"
JARSIGNER=""
for c in jarsigner "${JAVA_HOME:-/nonexistent}/bin/jarsigner" \
         "/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/jarsigner" \
         "/opt/android-studio/jbr/bin/jarsigner"; do
  if have "$c" || [ -x "$c" ]; then JARSIGNER="$c"; break; fi
done
if [ -z "$JARSIGNER" ]; then
  fail "jarsigner not found — cannot tell a debug-signed bundle from a real one"
  note "It ships with every JDK. Put one on PATH or set JAVA_HOME"
  note "(Android Studio bundles one under its jbr/ directory)."
else
  SIGNER=$("$JARSIGNER" -verify -verbose:summary -certs "$AAB" 2>/dev/null \
           | LC_ALL=C grep -m1 '^- Signed by' | sed 's/^- Signed by //; s/"//g')
  if [ -z "$SIGNER" ]; then
    case "$AAB" in
      *.apk) fail "no v1/JAR signature readable — for an APK use: apksigner verify --print-certs" ;;
      *)     fail "bundle carries no readable signature — is signingConfig set for release?" ;;
    esac
  elif printf '%s' "$SIGNER" | LC_ALL=C grep -qiE 'CN=Android Debug|O=Android'; then
    fail "signed with the DEBUG key: $SIGNER"
    note "android/key.properties missing or unreadable — Gradle fell back silently"
  else
    pass "signed by $SIGNER"
  fi
fi

# --- manifest ----------------------------------------------------------------
# The bundle manifest is protobuf, but permission names sit in it as plain
# UTF-8, so a binary-safe grep reads them without bundletool.
MANIFEST_OK=1
if ! unzip -l "$AAB" base/manifest/AndroidManifest.xml >/dev/null 2>&1; then
  MANIFEST_OK=0
fi
has_in_manifest() {
  unzip -p "$AAB" base/manifest/AndroidManifest.xml 2>/dev/null \
    | LC_ALL=C grep -aq "$1"
}

head2 "Target SDK"
if have bundletool; then
  TSDK=$(bundletool dump manifest --bundle "$AAB" \
           --xpath /manifest/uses-sdk/@android:targetSdkVersion 2>/dev/null | tr -d '[:space:]')
  VCODE=$(bundletool dump manifest --bundle "$AAB" \
           --xpath /manifest/@android:versionCode 2>/dev/null | tr -d '[:space:]')
  [ -n "$VCODE" ] && pass "versionCode $VCODE — must be higher than any code already uploaded"
  case "$TSDK" in
    ''|*[!0-9]*) warn "could not read targetSdkVersion" ;;
    *) if [ "$TSDK" -lt "$MIN_TARGET" ]; then
         fail "targetSdkVersion $TSDK — Play rejects new apps and updates below $MIN_TARGET"
       else pass "targetSdkVersion $TSDK (minimum $MIN_TARGET)"; fi ;;
  esac
else
  warn "bundletool not installed — targetSdkVersion and versionCode not checked"
  note "Play rejects updates below its current minimum (API $MIN_TARGET)."
fi

# --- advertising id ----------------------------------------------------------
# The Google Mobile Ads SDK declares AD_ID in its own library manifest and it
# merges in whether or not the app lists it. Play's Advertising ID declaration
# has to match what is actually in the bundle.
#
# Match the full name. android.permission.ACCESS_ADSERVICES_AD_ID (the Privacy
# Sandbox permission that play-services-measurement adds) also contains
# "AD_ID"; a bare substring match reports the advertising id as present in a
# bundle that removed it with tools:node="remove" — the wrong answer for an
# app that removed it in order to declare an under-13 audience.
head2 "Advertising ID"
if [ "$MANIFEST_OK" -eq 0 ]; then
  fail "could not read base/manifest/AndroidManifest.xml — AD_ID state unknown"
elif has_in_manifest 'com\.google\.android\.gms\.permission\.AD_ID'; then
  pass "com.google.android.gms.permission.AD_ID present"
  warn "Play 'Advertising ID' declaration must therefore say YES"
else
  pass "com.google.android.gms.permission.AD_ID absent"
  warn "Play 'Advertising ID' declaration must therefore say NO"
  if has_in_manifest 'android\.permission\.ACCESS_ADSERVICES_AD_ID'; then
    note "android.permission.ACCESS_ADSERVICES_AD_ID is present — that is the"
    note "Privacy Sandbox permission, not the advertising id."
  fi
fi

# --- bundled package assets --------------------------------------------------
# A dependency ships its declared assets whether or not your code uses them.
# Usually harmless (cupertino_icons, your own local packages); sometimes it is
# another app's artwork riding in through a shared package, which a reviewer
# can read as a repackaged app. Listed for a human to judge, not failed.
head2 "Bundled package assets"
ALLOW="${PLAY_ASSET_ALLOW:-/packages/(cupertino_icons|wakelock_plus|flutter_local_notifications_web)/}"
PKGS=$(unzip -Z1 "$AAB" 2>/dev/null \
  | LC_ALL=C grep '^base/assets/flutter_assets/packages/[^/]*/.*[^/]$' \
  | LC_ALL=C grep -vE "$ALLOW" \
  | cut -d/ -f5 | sort | uniq -c | awk '{printf "%s (%s)\n", $2, $1}')
if [ -n "$PKGS" ]; then
  warn "dependencies ship assets in this bundle — confirm each belongs here:"
  printf '%s\n' "$PKGS" | sed 's/^/          /'
else
  pass "no unexpected package assets"
fi

# --- store text --------------------------------------------------------------
head2 "Store text"
LOCALES=""
if [ -d "$META_ROOT" ]; then
  for d in "$META_ROOT"/*/; do
    [ -d "$d" ] || continue
    loc=$(basename "$d")
    LOCALES="$LOCALES $loc"
    for spec in title.txt:30:title short_description.txt:80:short \
                full_description.txt:4000:full; do
      f="${spec%%:*}"; rest="${spec#*:}"; lim="${rest%%:*}"; lab="${rest#*:}"
      if [ -f "$d$f" ]; then
        n=$(charcount "$d$f")
        if [ "$n" -gt "$lim" ]; then fail "$loc $lab: $n chars (limit $lim)"
        elif [ "$n" -eq 0 ]; then fail "$loc $lab: empty"
        else pass "$loc $lab: $n/$lim"; fi
      elif [ "$f" != full_description.txt ] || [ "$loc" = en-US ]; then
        warn "$loc: $f not found"
      fi
    done
    # Release notes: fastlane reads changelogs/<versionCode>.txt or default.txt.
    if [ -d "${d}changelogs" ]; then
      for c in "${d}"changelogs/*.txt; do
        [ -f "$c" ] || continue
        n=$(charcount "$c")
        [ "$n" -gt 500 ] && fail "$loc release notes $(basename "$c"): $n chars (limit 500)"
      done
    fi
  done
fi
[ -z "$LOCALES" ] && warn "no locales under $META_ROOT — store text not checked"

# --- images ------------------------------------------------------------------
# Play's rules: icon 512x512 32-bit PNG <= 1 MB; feature graphic 1024x500.
# Screenshots: 2-8 per type, each side 320-3840 px (tablets 1080-7680), the
# long side at most twice the short. Promotion in large-format
# layouts wants 4+ screenshots at 16:9 or 9:16 and >= 1080 px — a shortfall
# costs featuring, not acceptance, so it is a warning.
check_image() { # file, W, H, maxBytes (0 = no limit), label
  if [ ! -f "$1" ]; then fail "$5 missing ($1)"; return; fi
  local wh; wh=$(imgsize "$1")
  if [ "$wh" != "$2 $3" ]; then fail "$5 is $(printf '%s' "${wh:-unreadable}" | tr ' ' x) — must be $2x$3"
  elif [ "$4" -gt 0 ] && [ "$(filesize "$1")" -gt "$4" ]; then fail "$5 over $(( $4 / 1024 )) KB"
  else pass "$5 ${2}x${3}"; fi
}

check_shots() { # dir, label, required(1|0), minSide, maxSide
  local n=0 bad=0 promo=0 offaspect=0 f wh w h lo hi r ratios=""
  for f in "$1"/*; do
    case "$f" in *.png|*.PNG|*.jpg|*.jpeg|*.JPG|*.JPEG) ;; *) continue ;; esac
    n=$((n+1))
    wh=$(imgsize "$f")
    if [ -z "$wh" ]; then warn "$2: $(basename "$f") dimensions unreadable"; continue; fi
    w=${wh% *}; h=${wh#* }
    lo=$w; hi=$h; [ "$w" -gt "$h" ] && { lo=$h; hi=$w; }
    if [ "$lo" -lt "$4" ] || [ "$hi" -gt "$5" ]; then
      fail "$2: $(basename "$f") ${w}x${h} — each side must be $4-$5 px"; bad=1
    elif [ "$hi" -gt $((lo * 2)) ]; then
      fail "$2: $(basename "$f") ${w}x${h} — long side more than twice the short"; bad=1
    fi
    r=$((hi * 100 / lo))    # 16:9 = 177; allow slack for real device captures
    if [ "$r" -ge 170 ] && [ "$r" -le 186 ]; then
      [ "$lo" -ge 1080 ] && promo=$((promo+1))
    else
      offaspect=$((offaspect+1))
      ratios="$ratios $(awk -v r="$r" 'BEGIN{printf "%.2f", r/100}')"
    fi
  done
  if [ "$n" -eq 0 ]; then
    if [ "$3" = 1 ]; then fail "$2: none — Play requires at least 2"
    else warn "$2: none — an empty tablet slot costs tablet placement"; fi
    return
  fi
  [ "$n" -gt 8 ] && fail "$2: $n — Play takes at most 8"
  [ "$3" = 1 ] && [ "$n" -lt 2 ] && fail "$2: only $n — Play requires at least 2"
  [ "$bad" -eq 0 ] && pass "$2: $n, within $4-$5 px"
  if [ "$promo" -lt 4 ]; then
    msg="$2: $promo of $n qualify for promotion (wants 4 at 16:9/9:16, >=1080 px)"
    if [ "$offaspect" -gt 0 ]; then
      ratios=$(printf '%s\n' $ratios | sort -u | tr '\n' ' ')
      msg="$msg; off-aspect ratios: ${ratios% }"
    fi
    warn "$msg"
  fi
}

IMG_LOCALES=""
SAME_AS=""
for loc in $LOCALES; do [ -d "$META_ROOT/$loc/images" ] && IMG_LOCALES="$IMG_LOCALES $loc"; done
if [ -z "$IMG_LOCALES" ]; then
  head2 "Images"
  warn "no $META_ROOT/<locale>/images — images not checked"
fi
SEEN=""   # "fingerprint=locale" pairs, so identical image sets are checked once
for loc in $IMG_LOCALES; do
  I="$META_ROOT/$loc/images"
  fp=$(cd "$I" && find . -type f -exec cksum {} + 2>/dev/null | sort | cksum | tr -d ' ')
  same=$(printf '%s\n' $SEEN | awk -F= -v f="$fp" '$1==f{print $2; exit}')
  if [ -n "$same" ]; then SAME_AS="$SAME_AS $loc"; continue; fi
  SEEN="$SEEN $fp=$loc"
  head2 "Images ($loc)"
  check_image "$I/icon.png" 512 512 1048576 "icon.png"
  if [ -f "$I/featureGraphic.jpg" ]; then FG="$I/featureGraphic.jpg"; else FG="$I/featureGraphic.png"; fi
  check_image "$FG" 1024 500 0 "$(basename "$FG")"
  check_shots "$I/phoneScreenshots"     "phone"    1  320 3840
  check_shots "$I/sevenInchScreenshots" "7-inch"   0  320 3840
  check_shots "$I/tenInchScreenshots"   "10-inch"  0 1080 7680
done
[ -n "${SAME_AS:-}" ] && note "identical image sets, not repeated:$SAME_AS"

# --- privacy policy ----------------------------------------------------------
# Play follows this URL. A shared policy that names a different app, or claims
# data this app does not collect, contradicts the Data safety form.
head2 "Privacy policy"
PURL=""
for loc in $LOCALES; do
  [ -f "$META_ROOT/$loc/privacy_url.txt" ] && { PURL=$(tr -d '[:space:]' < "$META_ROOT/$loc/privacy_url.txt"); break; }
done
if [ -z "$PURL" ]; then
  warn "no privacy_url.txt in any locale — Play requires a policy URL; check it by hand"
elif [ "$OFFLINE" -eq 1 ]; then
  warn "$PURL not requested (--offline) — confirm it resolves"
elif ! have curl; then
  warn "$PURL not requested (curl not installed) — confirm it resolves"
else
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 20 "$PURL" 2>/dev/null)
  case "$CODE" in
    200) pass "$PURL -> 200" ;;
    ''|000) fail "$PURL -> no response" ;;
    *) fail "$PURL -> HTTP $CODE" ;;
  esac
  note "confirm the policy text describes THIS app and what it collects"
fi

# --- EEA consent -------------------------------------------------------------
# An ad-supported app distributed in the EEA needs a published consent message
# in AdMob (console config) AND an in-app way to reopen it (code). The message
# itself tells users to look for that control in the app, so shipping the
# message without it describes a control that does not exist. Neither store
# flags the gap. Details: reference.md.
head2 "EEA consent (google_mobile_ads)"
SRC_EXCLUDES="--exclude-dir=build --exclude-dir=.dart_tool --exclude-dir=.git --exclude-dir=Pods --exclude-dir=node_modules"
# shellcheck disable=SC2086
if grep -rqsE --include=pubspec.yaml $SRC_EXCLUDES '^[[:space:]]+google_mobile_ads:' .; then
  # shellcheck disable=SC2086
  if grep -rqs --include='*.dart' $SRC_EXCLUDES 'requestConsentInfoUpdate' .; then
    pass "consent gathering present (requestConsentInfoUpdate)"
  else
    fail "no requestConsentInfoUpdate — the UMP consent SDK is never asked"
  fi
  # shellcheck disable=SC2086
  if grep -rqs --include='*.dart' $SRC_EXCLUDES 'showPrivacyOptionsForm' .; then
    pass "privacy options entry point present (the revocation link)"
  else
    fail "no ConsentForm.showPrivacyOptionsForm call — users cannot withdraw consent"
    note "Add a settings entry that calls it BEFORE publishing an EEA message."
  fi
  warn "confirm AdMob has a PUBLISHED European regulations message for this app"
  note "(Privacy & messaging > European regulations; publishing needs a privacy"
  note "policy URL and the 'Do not consent' option, which is off by default)."
else
  pass "google_mobile_ads not a dependency — nothing to check"
fi

# --- the one it cannot check -------------------------------------------------
head2 "Build configuration — not checkable"
note "Nothing in a bundle reliably says which flavor or --dart-define produced"
note "it. If both production and test ids are compiled in as constants, both"
note "appear as strings either way. If unsure, rebuild with the production"
note "flags stated explicitly."

head2 "Result"
if [ "$FAIL" -eq 0 ]; then
  printf '  %sready to upload%s — the .aab upload is still a manual step unless you use a service account\n\n' "$G" "$N"
else
  printf '  %snot ready%s — fix the failures above\n\n' "$R" "$N"
fi
exit "$FAIL"
