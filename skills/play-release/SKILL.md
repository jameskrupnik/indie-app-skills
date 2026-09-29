---
name: play-release
description: Get a Flutter app onto Google Play, and know in advance which steps a human has to do. Covers the order of Play Console declarations, pre-upload checks on the .aab (signing key, target SDK, advertising ID permission, store text and image limits, privacy policy, EEA ad consent), and the upload handoff. Use when releasing, submitting, publishing or shipping an Android app to Google Play or the Play Console; when building an .aab or app bundle, creating a production or internal testing release, or uploading a build; when filling Play declarations such as data safety, content rating (IARC), target audience, advertising ID, ads, health, financial or government apps; when "Send app for review" is greyed out or the setup checklist will not complete; when under-13 age groups are locked or the app is shown as rated "Teen"; when a bundle might be signed with the debug key; or when asked what still blocks a Play release.
---

# Releasing to Google Play

**Most time lost on a Play release goes on two things this file tells you up
front: the order the declarations must be done in, and which steps a human
has to do.** The console shows neither, and one of its messages misleads.

**Assumed layout** (run the scripts from the Flutter project root):

```
pubspec.yaml
android/key.properties                       # upload key config, not committed
build/app/outputs/bundle/release/app-release.aab
fastlane/metadata/android/<locale>/          # fastlane supply layout
  title.txt  short_description.txt  full_description.txt  privacy_url.txt
  changelogs/<versionCode>.txt | default.txt
  images/icon.png  images/featureGraphic.png
  images/phoneScreenshots/  sevenInchScreenshots/  tenInchScreenshots/
```

The metadata tree is worth keeping even without fastlane: it versions the
listing and lets the preflight check it. Deeper material (console failure
modes, browser-automation uploads, EEA consent implementation, rating
examples, tablet capture) is in [reference.md](reference.md).

## Quick path

1. **Declarations, in this order:** Content rating → Target audience → Data
   safety. Everything else (privacy policy, app access, ads, advertising ID,
   government, financial, health) in any order. [Why](#the-order-is-not-optional)
2. **Build** with the production configuration stated explicitly:
   `flutter build appbundle --release` plus whatever `--flavor` /
   `--dart-define` your production build needs.
   [Why explicit](#the-build-configuration-cannot-be-checked-afterwards)
3. **Preflight:** `${CLAUDE_SKILL_DIR}/preflight.sh` — fix every FAIL, read
   every warn. [What it checks](#preflight)
4. **Upload** the listing assets and the `.aab`:
   - with a Play service account: `fastlane supply` does it all;
   - otherwise (macOS): `${CLAUDE_SKILL_DIR}/handoff.sh` opens the files and the
     console pages for a human. [The manual leg](#what-a-human-has-to-do)
5. **Publishing overview → Send app for review.** Saving is not submitting.
   [Details](#saving-is-not-submitting)

## What a human has to do

**Plan for a manual leg from the start.** Do the declarations, build and
verify, then hand over a short list of files and clicks. Do not spend a
session trying to automate the last step.

Which steps are manual depends on what you have:

- **A service account with Play Console access** (Google Cloud project linked
  to the developer account): `fastlane supply` uploads the bundle, listing text
  and images through the Play Developer API. Still manual: creating the app,
  its first bundle upload (the API cannot create an app, so supply needs one
  build already in the console — an internal testing track will do), and the
  declarations. If the project already has a service account, use it.
- **No service account.** Creating one is the developer's decision, not a
  convenience to reach for mid-release: it is a long-lived credential with
  publish rights, and it is easy to create in the wrong Google Cloud
  organisation. Ask; do not assume.
- **Driving the console with a browser-automation tool** (e.g. Claude in
  Chrome): the listing text and images can be done this way, but **the `.aab`
  cannot** if the tool's file upload is size-capped — Claude in Chrome's
  `file_upload` caps at 10 MB and a Flutter bundle is typically 30-80 MB. That
  upload is a human's. Technique in [reference.md](reference.md#uploading-through-browser-automation).

**Human-only regardless of tooling:** accepting third-party terms (the IARC
questionnaire, below), and **Send app for review** unless the developer has
said to press it. Say plainly which step is manual and why, so it does not
read as something you failed to finish.

## The order is not optional

The setup checklist looks like a flat list. It is not:

```
Content rating  →  Target audience  →  Data safety
```

**With no content rating submitted, Play treats the app as "Teen or higher"
and greys out every under-13 age group.** The message says the rating "is set
as 'teen' or higher", which reads as *a wrong rating exists*. There is no
rating at all. Complete the IARC questionnaire and the age groups unlock.

**Target audience then gates Data safety:** Data safety refuses to submit
with *"you must let us know the target age group of your app"* and stays
draft-only until it has one.

## Content rating: answer honestly

Under-declaring is what rating boards penalise, and Play warns it "may reject
your app or app update for misrepresentation". Honest answers for cartoon
content, described accurately (fantasy setting, no blood, unrealistic
reactions), still come out in the lowest band. Worked example in
[reference.md](reference.md#content-rating-examples).

Two questions are narrower than they look and are usually **no**: *Crude
humor* means bodily functions, not slapstick; *Digital purchases* means real
purchases, cash-convertible rewards and NFTs, not unlocks earned in play.

**Completing the questionnaire accepts IARC's Terms of Service in the
developer's name.** That is a third-party agreement — get an explicit yes
from the developer first.

## Target audience and ads

If the app already applies child-directed ad treatment to every user
(`TagForChildDirectedTreatment.yes`, `MaxAdContentRating.g`, non-personalised
ads), **it has already given up personalised-ad revenue.** Declaring an
under-13 audience then costs little and removes the risk of a visibly
child-appealing app claiming 13+.

**Verify the flag reaches the SDK.** A constant that nothing passes to
`MobileAds.instance.updateRequestConfiguration` is a promise the binary does
not keep.

- **Ads step:** "are all ads suitable for children and from certified
  networks?" AdMob is on Google's Families self-certified ads SDK list, so
  **yes** when the above holds and AdMob is the only network.
- **Advertising ID:** the Google Mobile Ads SDK declares
  `com.google.android.gms.permission.AD_ID` in its own manifest, and it merges
  into your app whether or not you list it. The Play declaration must match
  what is actually in the bundle — preflight reports which. Under the Families
  policy, apps aimed only at children must not transmit it (remove the
  permission with `tools:node="remove"`); mixed-audience apps must not
  transmit it from children or users of unknown age.
- **Teacher Approved** is offered inside the Target audience wizard. It is an
  opt-in programme that submits the app to outside reviewers — the
  developer's call, not a default.

## EEA consent needs both halves

**An ad-supported app distributed in the EEA needs a published consent
message in AdMob *and* an in-app way to reopen it. Neither store will tell you
if either is missing** — Play's policy status reads "No issues found"
throughout.

1. **A published European regulations message** — AdMob → Privacy &
   messaging → European regulations. Console config, no rebuild, provided the
   app already calls the UMP SDK (`ConsentInformation.requestConsentInfoUpdate`).
2. **An in-app entry point** that calls `ConsentForm.showPrivacyOptionsForm` —
   code, and therefore a build.

**Ship them together.** The published message tells users to look for a
link in the app to manage or withdraw consent; ship the message without the
link and the consent form describes a control that does not exist.

`preflight.sh` fails when `google_mobile_ads` is a dependency and either call
is missing from the Dart sources. Implementation notes, the two settings that
block **Publish**, and how to test from outside the EEA are in
[reference.md](reference.md#eea-consent-in-detail).

## Preflight

```bash
${CLAUDE_SKILL_DIR}/preflight.sh [--offline] [--quiet] [path/to/app.aab]
```

It checks what is silently wrong at upload time and no test catches:

| Check | Why |
|---|---|
| Signer identity | The Flutter template **falls back to the debug key without a word** when `key.properties` is missing, and `jarsigner -verify` still says "jar verified". |
| `targetSdkVersion` (needs bundletool) | Play rejects new apps and updates below the current minimum (API 36 from 2026-08-31; override with `PLAY_MIN_TARGET_SDK`). |
| `AD_ID` permission | Tells you what the Advertising ID declaration must say. Matches the full name, so `ACCESS_ADSERVICES_AD_ID` (Privacy Sandbox) is not mistaken for it. |
| Package assets | Lists assets dependencies ship under `flutter_assets/packages/`, so another app's artwork riding in through a shared package gets seen. |
| Store text, every locale | Title 30, short 80, full 4000, release notes 500 — counted in characters, not bytes. |
| Images | Icon 512x512, feature graphic 1024x500, screenshot counts, sizes and aspect (below). |
| Privacy policy | `privacy_url.txt` must return 200. |
| EEA consent | Both halves, as above. |

Needs `unzip` and a JDK's `jarsigner` (Android Studio's bundled JBR is found
automatically). `bundletool` and `curl` are optional. Exit 1 on any failure.

### The build configuration cannot be checked afterwards

**A staging build and a production build can be indistinguishable by
inspection.** If your app picks ad unit ids, API hosts or keys at build time
and both sets are compiled in as constants, both appear as strings in the
bundle whichever was selected. A staging build on a public track serves test
ads (no revenue) or talks to the wrong backend. The only defence is to control
the invocation: pass the production flags explicitly, and rebuild if unsure.

## Store listing images

Play's rules (Play Console Help, "Add preview assets"):

- **Icon:** 512x512, 32-bit PNG with alpha, ≤ 1 MB.
- **Feature graphic:** 1024x500, JPEG or 24-bit PNG (no alpha).
- **Screenshots:** 2-8 per device type; each side 320-3840 px (tablets
  1080-7680); the long side at most twice the short.
- **Promotion** in large-format layouts wants at least 4 screenshots at 16:9
  or 9:16 and ≥ 1080 px. Other ratios are accepted but earn no promotion
  credit, so preflight warns rather than fails.

**Fill the tablet slots if the app runs on tablets.** Phone, 7-inch and
10-inch are separate slots, further down the listing page than you expect.
Leaving tablets empty loses tablet placement. Capture them on a real tablet
emulator, not by upscaling phone shots — see
[reference.md](reference.md#capturing-tablet-screenshots).

## Privacy policy

Play requires a policy URL and follows it. Two failures are common when one
policy is shared across apps:

- **The URL 404s.** Preflight checks it. Never invent a per-app path.
- **The policy describes a different app**, or claims data this app does not
  collect, and so contradicts the Data safety form. Read it.

## Saving is not submitting

Every Save says changes are *"ready for you to send for review"*. **Nothing
reaches Google until Publishing overview → Send app for review**, which stays
locked until the dashboard checklist is complete. Verify state in the console,
not from the absence of an error.

The console is flaky in recognisable ways (form state desyncing from what is
shown, deep links bouncing, native dropdowns mis-selecting). Read the
section counters and summaries, not the checkboxes. See
[reference.md](reference.md#how-the-console-fails).

## The handoff (macOS)

```bash
${CLAUDE_SKILL_DIR}/handoff.sh [--dry-run] [--force] [--aab PATH]
```

Runs the preflight and, **only if it passes**, opens Finder at the images
folder, reveals the `.aab`, and opens three console tabs — store listing,
production track, publishing overview — then prints the steps in order.
`--dry-run` prints instead of opening and works on any OS. `--force` opens
despite failures.

Tabs open in the normal browser profile (Chrome, or `PLAY_BROWSER`, else the
default browser) so the signed-in session is used. Deep links need the
console ids; save them once in `.play-release` at the project root:

```sh
PLAY_DEV_ID=<developer id>   # from /developers/<id>/app/...
PLAY_APP_ID=<app id>         # from .../app/<id>/...
```

Without them it opens the Play Console home page. Keep `.play-release` out
of a public repo if you consider the ids private.
