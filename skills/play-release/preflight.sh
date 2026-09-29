#!/usr/bin/env bash
# Pre-upload checks for a Google Play app bundle.
#
# Checks the things that are silently wrong at upload time and that no test
# suite covers, because none of them is a compile error:
#
#   - signed with the real upload key, not the debug key Gradle falls back to
#   - the AD_ID permission, which must agree with the Advertising ID declaration
#   - sibling assets leaking in under assets/packages/
#   - store metadata within Play's field limits
#   - the privacy policy URL actually resolving
#
# It deliberately does NOT try to detect the build flavor. See --help.
#
# Usage:
#   preflight.sh [path/to/app.aab]      # defaults to the standard Flutter path
#
# Exit code is 1 if anything failed, 0 otherwise. Warnings do not fail the run.

set -uo pipefail

AAB="${1:-build/app/outputs/bundle/release/app-release.aab}"
META="fastlane/metadata/android/en-US"

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

FAIL=0
pass() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=1; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
# Neither good nor bad — something true that changes a later decision.
note() { printf '        %s\n' "$1"; }
head2() { printf '\n\033[1m%s\033[0m\n' "$1"; }

head2 "Bundle"
if [ ! -f "$AAB" ]; then
  fail "no bundle at $AAB — build one first"
  echo
  echo "Nothing else can be checked without it."
  exit 1
fi
pass "$AAB ($(du -h "$AAB" | cut -f1))"

# --- signing -----------------------------------------------------------------
# build.gradle.kts falls back to the debug key in silence when key.properties is
# absent, and `jarsigner -verify` still says "jar verified" for a debug-signed
# bundle. The identity is the thing to look at, not the verdict.
head2 "Signing"
SIGNER=$(jarsigner -verify -verbose:summary -certs "$AAB" 2>/dev/null \
         | LC_ALL=C grep -m1 '^- Signed by' | sed 's/^- Signed by //; s/"//g')
if [ -z "$SIGNER" ]; then
  # jarsigner only reads v1/JAR signatures. An .aab is v1-signed so this is a
  # real failure for the intended input; an .apk may be v2/v3-only and simply
  # unreadable this way. Say which, rather than asserting it is unsigned.
  case "$AAB" in
    *.apk) fail "no v1/JAR signature readable — for an APK use: apksigner verify --print-certs" ;;
    *)     fail "bundle carries no readable signature" ;;
  esac
elif printf '%s' "$SIGNER" | LC_ALL=C grep -qi 'CN=Android Debug\|O=Android'; then
  fail "signed with the DEBUG key: $SIGNER"
  warn "key.properties missing or unreadable — Gradle fell back silently"
else
  pass "signed by $SIGNER"
fi

# --- advertising id ----------------------------------------------------------
# The Google Mobile Ads SDK declares AD_ID in its own library manifest and it
# merges in whether or not the app lists it. Play's Advertising ID declaration
# has to match whatever is actually here.
#
# **Two different permissions contain the substring AD_ID, and only one of them
# is the advertising id.** Grepping for `AD_ID` alone matched
# `android.permission.ACCESS_ADSERVICES_AD_ID` — the Android 13 Privacy Sandbox
# permission that play-services-measurement contributes — and reported the
# advertising id as present in a bundle that had just had it removed with
# `tools:node="remove"`. That is the wrong answer in the expensive direction: it
# tells you to declare YES on an app whose whole reason for removing the
# permission was to declare an under-13 audience. Found on a real release,
# against a merged manifest that was checked by hand.
head2 "Advertising ID"
MANIFEST=$(unzip -p "$AAB" base/manifest/AndroidManifest.xml 2>/dev/null \
           | LC_ALL=C strings)
AD_ID=$(printf '%s\n' "$MANIFEST" | LC_ALL=C grep -c 'gms\.permission\.AD_ID')
SANDBOX=$(printf '%s\n' "$MANIFEST" | LC_ALL=C grep -c 'ACCESS_ADSERVICES_AD_ID')
if [ "${AD_ID:-0}" -gt 0 ]; then
  pass "com.google.android.gms.permission.AD_ID present"
  warn "Play 'Advertising ID' declaration must therefore say YES"
else
  pass "com.google.android.gms.permission.AD_ID absent"
  warn "Play 'Advertising ID' declaration must therefore say NO"
  if [ "${SANDBOX:-0}" -gt 0 ]; then
    # Left in deliberately rather than reported as a failure: it is a normal
    # permission from the measurement SDK, it is not the advertising id, and
    # removing it is a separate decision from the one this check is about.
    note "android.permission.ACCESS_ADSERVICES_AD_ID is still present"
    note "  (Privacy Sandbox, not the advertising id — different declaration)"
  fi
fi

# --- sibling asset leak ------------------------------------------------------
# A dependency can add assets to the binary without a line of your code
# importing it. Shipping a sibling's promo art is a 4.3 spam signal.
head2 "Bundled assets"
# Plugin assets that are known and harmless, matched exactly. Each is a
# plugin's own platform helper, not app content: it identifies no sibling and
# cannot be excluded, because Flutter bundles every asset a dependency
# declares. Add to this only with the file named and the reason given.
#   wakelock_plus/assets/no_sleep.js — the plugin's web implementation, a 3 KB
#     script declared for every platform.
BENIGN='assets/flutter_assets/packages/wakelock_plus/assets/no_sleep.js$'
LEAKS=$(unzip -l "$AAB" 2>/dev/null | LC_ALL=C grep 'assets/flutter_assets/packages/' \
  | LC_ALL=C grep -vE "$BENIGN")
LEAK=$(printf '%s' "$LEAKS" | grep -c . )
if [ "${LEAK:-0}" -gt 0 ]; then
  fail "$LEAK file(s) under assets/packages — a dependency's assets are shipping"
  printf '%s\n' "$LEAKS" | awk '{print "        " $4}' | sort -u | head -10
else
  pass "no third-party package assets bundled"
fi

# --- store metadata ----------------------------------------------------------
head2 "Store metadata"
check_len() { # file, limit, label
  if [ -f "$META/$1" ]; then
    n=$(LC_ALL=C wc -c < "$META/$1" | tr -d ' ')
    if [ "$n" -gt "$2" ]; then fail "$3: $n chars (limit $2)"
    else pass "$3: $n/$2 chars"; fi
  else
    warn "$3: $META/$1 not found"
  fi
}
check_len title.txt 30 "title"
check_len short_description.txt 80 "short description"
check_len full_description.txt 4000 "full description"

# --- images ------------------------------------------------------------------
head2 "Images (uploaded by hand — see SKILL.md)"
if [ -d "$META/images" ]; then
  for f in icon.png featureGraphic.png; do
    if [ -f "$META/images/$f" ]; then
      dim=$(sips -g pixelWidth -g pixelHeight "$META/images/$f" 2>/dev/null \
            | awk '/pixel/{printf "%sx", $2}' | sed 's/x$//')
      pass "$f  ${dim:-?}"
    else
      fail "$f missing"
    fi
  done
  # Play's rules are PER SLOT and the console states them under each one.
  # Phone and 7-inch: each side 320-3840px. 10-inch: each side 1080-7680px.
  # All slots want 16:9 or 9:16.
  #
  # The aspect rule is not enforced at upload — a 3:4 tablet capture is
  # accepted — but the console says promotion eligibility needs "at least 4
  # screenshots, with at least 3 in 16:9 or 9:16 and at least 1080 px". So an
  # off-aspect set costs featuring, not acceptance. Warn, do not fail.
  check_shots() { # dir, label, required(1|0), minSide, maxSide
    local dir="$META/images/$1" n bad=0 offaspect=0 promo=0
    n=$(find "$dir" -type f -name '*.png' 2>/dev/null | wc -l | tr -d ' ')
    if [ "${n:-0}" -eq 0 ]; then
      if [ "$3" = "1" ]; then fail "$2: none — Play requires at least 2"
      else warn "$2: none — an empty tablet slot means no tablet placement"; fi
      return
    fi
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      read -r w h <<EOF
$(sips -g pixelWidth -g pixelHeight "$f" 2>/dev/null | awk '/pixel/{printf "%s ", $2}')
EOF
      [ -z "${w:-}" ] && continue
      lo=$w; hi=$h; [ "$w" -gt "$h" ] && { lo=$h; hi=$w; }
      if [ "$lo" -lt "$4" ] || [ "$hi" -gt "$5" ]; then
        fail "$2: $(basename "$f") ${w}x${h} — sides must be $4-$5 px"; bad=1
      fi
      # 16:9 is 1.777…; allow a little slack for real device captures.
      if ! python3 -c "import sys;r=$hi/$lo;sys.exit(0 if 1.70<=r<=1.86 else 1)" 2>/dev/null; then
        offaspect=$((offaspect+1))
      elif [ "$lo" -ge 1080 ]; then
        promo=$((promo+1))
      fi
    done <<EOF
$(find "$dir" -type f -name '*.png' 2>/dev/null | sort)
EOF
    [ "$bad" -eq 0 ] && pass "$2: $n, sides within $4-$5 px"
    if [ "$offaspect" -gt 0 ]; then
      # Show what they actually are — "not 16:9" is not actionable on its own,
      # and 1.86 (a tall phone) is a different problem from 1.33 (a tablet).
      ratios=$(find "$dir" -type f -name '*.png' 2>/dev/null | while IFS= read -r f; do
        sips -g pixelWidth -g pixelHeight "$f" 2>/dev/null \
          | awk '/pixel/{printf "%s ", $2}' \
          | awk '{lo=$1;hi=$2;if(lo>hi){t=lo;lo=hi;hi=t}printf "%.2f\n", hi/lo}'
      done | sort -u | tr '\n' ' ')
      warn "$2: $offaspect of $n off 16:9/9:16 (ratios: ${ratios%% })— fine to ship, but no promo credit"
    fi
    if [ "${n:-0}" -ge 4 ] && [ "$promo" -lt 3 ]; then
      warn "$2: $promo/3 qualify for promotion (needs 16:9 or 9:16 at >=1080px)"
    fi
    if [ "$3" = "1" ] && [ "${n:-0}" -lt 2 ]; then
      fail "$2: only $n — Play requires at least 2"
    fi
  }
  check_shots phoneScreenshots     "phone screenshots"   1  320 3840
  check_shots sevenInchScreenshots "7-inch screenshots"  0  320 3840
  check_shots tenInchScreenshots   "10-inch screenshots" 0 1080 7680
else
  warn "$META/images not found"
fi

# --- privacy policy ----------------------------------------------------------
# Play follows this URL. An invented per-app path 404s; a shared policy that
# names a different app contradicts the Data safety form.
head2 "Privacy policy"
if [ -f "$META/privacy_url.txt" ]; then
  URL=$(tr -d '[:space:]' < "$META/privacy_url.txt")
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -L --max-time 20 "$URL" 2>/dev/null)
  if [ "$CODE" = "200" ]; then pass "$URL → 200"
  else fail "$URL → ${CODE:-no response}"; fi
  warn "confirm the policy text actually describes THIS app, not a sibling"
else
  warn "$META/privacy_url.txt not found"
fi

# --- EEA consent: both halves, or neither ------------------------------------
# An ad-supported app distributed in the EEA needs TWO things, and the console
# will happily give you one of them:
#
#   1. a published European regulations message in AdMob (console config), and
#   2. an in-app link to reopen it (code, and therefore a build).
#
# The published message says, in its own body text, "look for a link or button
# in the app menu to manage or withdraw consent in privacy and cookie
# settings". Ship the message without the link and the app's own consent form
# describes a control that does not exist.
#
# Three apps in one portfolio made exactly that mistake in sequence — two fixed
# it after the fact, and the third repeated it because the console work was
# correctly described as needing "no rebuild", which was true only of consent
# GATHERING.
#
# Neither store flags any of this. Play's policy status reads "No issues found"
# throughout; the gap is visible only in AdMob, and only if you go looking.
head2 "EEA consent"
if grep -rqs "google_mobile_ads" --include=pubspec.yaml .; then
  if grep -rqs "showPrivacyOptions" --include="*.dart" .; then
    pass "privacy options entry point present (the revocation link)"
  else
    fail "google_mobile_ads is in the build with NO showPrivacyOptions call"
    note "The published AdMob message promises a link in the app menu."
    note "Add a settings row that calls ConsentForm.showPrivacyOptionsForm"
    note "BEFORE publishing a European regulations message for this app."
  fi

  if grep -rqs "requestConsentInfoUpdate" --include="*.dart" .; then
    pass "consent gathering present (requestConsentInfoUpdate)"
  else
    fail "no requestConsentInfoUpdate — the UMP SDK is not being asked at all"
  fi

  warn "confirm in AdMob > Privacy & messaging > European regulations that a"
  note "message is PUBLISHED for this app. Publishing needs a privacy policy"
  note "URL per app, and 'Do not consent', which is unset by default."
else
  pass "no google_mobile_ads — nothing to consent to"
fi

# --- the one it cannot check -------------------------------------------------
head2 "Build flavor — NOT CHECKABLE"
cat <<'EOF'
  Both the production and the Google-sample ad unit ids appear as strings in a
  release bundle whichever flavor was compiled, because the AdUnits objects are
  const-constructed and retained. A staging build is therefore
  indistinguishable from a production build by inspection.

  The release scripts here DEFAULT TO STAGING, and a staging build on a public
  track serves Google's test ad units: no revenue, test creatives to real
  players.

  If you are not certain this bundle was built with the production flag,
  rebuild it. That is cheaper than finding out from the store.
EOF

head2 "Result"
if [ "$FAIL" -eq 0 ]; then
  printf '  \033[32mready to upload\033[0m — remember the AAB and images are a manual step\n\n'
else
  printf '  \033[31mnot ready\033[0m — fix the failures above\n\n'
fi
exit "$FAIL"
