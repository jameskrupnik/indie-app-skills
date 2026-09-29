---
name: play-release
description: Get an Android app onto Google Play, and know in advance which parts a human has to do. Use when releasing, submitting, publishing or shipping an app to Google Play or the Play Console; when building an .aab or app bundle, creating a production or internal track release, or uploading a build; when filling Play declarations — data safety, content rating, target audience, advertising ID, ads, health, financial or government apps; when "Send app for review" is greyed out or the setup checklist will not complete; when an under-13 age group is locked or an ESRB rating looks wrong; or when asked what still blocks a Play release.
---

# Releasing to Google Play

**Most of the time lost here is spent discovering two things this file already
tells you: the order the declarations have to be done in, and which steps a
human has to do.** Neither is discoverable from the console, and one of the
error messages actively misleads.

Read [What a human has to do](#what-a-human-has-to-do) before promising anyone a
release is automatable.

## What a human has to do

**The AAB has to be uploaded by hand. The store images do not** — an earlier
version of this file said they did, and a real listing upload disproved it.

On first load the store-listing page has no file input at all
(`document.querySelectorAll('input[type=file]').length` is 0), which is what
the old claim measured. But clicking an **"Add assets"** button does not open
the OS picker; it opens an **asset-library side panel** that mounts a real
`<input type=file>`. `find` it, fill it with the browser tool's `file_upload`
(the repo's `fastlane/metadata/android/en-US/images/` paths are accepted),
then click the panel's **Add** to place the selection into the slot. **Never
click the panel's "Upload" button** — that one does open the OS picker.

- **Files land in upload-completion order**, not selection order. Upload a
  screenshot set one file at a time, a few seconds apart, or drag to reorder
  afterwards (drag works).
- The listing text needs real keystrokes to register: setting `.value` from
  JS leaves "Add a short description" errors. Set it, then click in and press
  `End space BackSpace`.
- "Save" is refused until every required image is present; **Save as draft**
  keeps the text meanwhile.

The AAB is still a hand job: the release page's bundle upload is over
`file_upload`'s 10 MB cap (a Flutter AAB is 60-80 MB).

The other route is the Play Developer API (`fastlane supply`), which needs a
**service account** in a Google Cloud project linked to the developer account.
If the project already has one, use it. If it does not, creating one is the
developer's decision, not a convenience to reach for mid-release: it is a
long-lived credential with publish rights, and on a machine where `gcloud` is
signed in to a different organisation it is easy to create it in the wrong
one. Ask; do not assume.

So **every Play release has a manual leg.** Plan the handoff from the start:
do all the declarations, build and verify the artefact, then hand over a short
list of files and clicks. Do not spend a session trying to automate the upload.

## The order, which is not optional

The setup checklist presents the declarations as a flat list. They are not.

```
Content rating  →  Target audience  →  Data safety
```

**With no content rating submitted, Play treats the app as ESRB "Teen or
higher" and greys out every under-13 age group.** The message it shows says the
rating "is set as 'teen' or higher", which reads as *a wrong rating exists* and
sends you looking for one to correct. There is no rating at all. Complete the
IARC questionnaire and the age groups unlock.

Target audience then gates Data safety: the Data safety preview refuses to
submit with *"you must let us know the target age group of your app"*, and the
Save button stays draft-only until it has one.

Everything else — privacy policy, sign-in details, ads, financial, government,
health, advertising ID — is independent and can be done in any order.

## Answer the content rating honestly; it still comes out low

There is a temptation to under-declare to protect the age groups. Don't:
under-declaring content is the thing rating boards actually penalise, and Play
warns it "may reject your app or app update for misrepresentation".

For a cartoon game where something is struck and falls over — a pie thrown at a
duck, a bird knocked off a perch — the honest answers are *yes* to violence,
*yes* to violence against non-humans, and *yes* to real-world animals if the
targets are real species. Characterised accurately alongside them (**fantastical
setting, childlike style, unrealistic reactions, distant perspective, no
blood**) that still returns the lowest band everywhere: **ESRB Everyone, PEGI 3,
USK 6, IARC 3+**, with a descriptor like *Mild Fantasy Violence*.

Two questions are narrower than they look and are usually **no**: *Crude humor*
means bodily functions specifically, not slapstick; *Digital purchases* means
real purchases, cash-convertible rewards and NFTs, not cosmetic unlocks earned
in play.

**Completing the questionnaire accepts IARC's Terms of Service in the
developer's name.** That is a third-party agreement — get an explicit yes in
chat first.

## The Families decision is cheaper than it looks

If the app already applies child-directed treatment to every user —
`tagForChildDirectedTreatment.yes`, `maxAdContentRating.g`,
`nonPersonalizedAds: true` — then **it has already forfeited personalised-ad
revenue for everyone.** Declaring an under-13 target audience therefore costs
almost nothing extra, and removes the risk of a visibly child-appealing app
having claimed 13+.

Verify that the flag is actually wired to the SDK before relying on it. A
`childDirectedAds`-style constant that nothing passes to
`updateRequestConfiguration` is a promise the binary does not keep.

Two follow-ons:

- **Ads step**: "are all ads suitable for children and from certified
  networks?" — AdMob is certified, so **yes** when the above holds.
- **`AD_ID` permission**: the Google Mobile Ads SDK declares it in its own
  library manifest and it merges into your app whether or not you list it.
  Under a **mixed** audience (children *and* adults) it may stay, provided it is
  not used for children. Children-only is stricter. Either way the Advertising
  ID declaration must match what is actually in the bundle — check, don't
  assume.

## An ad-supported app going to the EEA needs both halves of consent

**This is a release step for every ad-supported Android app, and it is the one
nothing on either store will ever tell you about.** Play's policy status reads
*No issues found* and App content reads *You're all caught up* while an app
serves 27 EU member states with no consent message at all. The gap is visible
only in AdMob → **Privacy & messaging → European regulations**.

There are **two** halves and they ship together:

1. **A published European regulations message.** Pure console config — no
   rebuild, provided the app already calls the UMP SDK.
2. **An in-app link to reopen it.** Code, and therefore a build.

**Publishing the message and shipping the link are one change, not two.** The
message says in its own body text to *"look for a link or button in the app
menu to manage or withdraw consent in privacy and cookie settings"*, and
AdMob's publish dialog asks for it by name. Ship half of it and the app's own
consent form describes a control that does not exist.

Three apps in one portfolio made exactly that mistake in sequence — two fixed
it after the fact, and the third repeated it because the console work was
correctly described as needing "no rebuild". That was true of consent
*gathering* and false of this.

### What to check, in order

```bash
# Does the app already gather consent? (nearly always yes — it is in the template)
grep -rl "requestConsentInfoUpdate" --include="*.dart" .

# Does it have the revocation link? (nearly always no)
grep -rl "showPrivacyOptions" --include="*.dart" .
```

`preflight.sh` fails the run on the second one, so this fires rather than
relying on anyone reading this section.

The fix is small: a domain port (`AdConsent`), an implementation over the UMP
SDK (`AdConsentService`), and a settings row (`AdPrivacyTile`) that calls
`ConsentForm.showPrivacyOptionsForm` — about 130 lines plus a test. Two things
to get right:

- **Await the ads layer before asking.** Until `requestConsentInfoUpdate` has
  run, the SDK answers `unknown`, which is indistinguishable from "not in the
  EEA" and silently hides the row.
- **Hide the row, never disable it.** Outside the EEA, the UK and Switzerland
  there is nothing to withdraw, and a permanently dead control reads as a bug.

### Publishing the message

Two settings block **Publish** until answered, and neither is obvious:

- **A privacy policy URL per app** — the button stays greyed out without one,
  and a URL must never be invented.
- **Do not consent**, which is unset by default. On for all 33 EEA/UK/Swiss
  countries is the user-respecting choice, and it is free for any app already
  serving only non-personalised ads.

Allow up to an hour for a published message to reach devices.

### Why it is a revenue hole as well as a compliance one

`canRequestAds()` gates every request. With no message configured the form load
fails — the *"no form(s) configured for the input app ID"* error — so in the
EEA this plausibly means **no ads serve at all**. A gap that costs money and
shows up nowhere either store would mention it.

### Seeing any of this from outside the EEA

Neither the consent form nor the privacy options row can be reached from a US
device, which is how a published message comes to promise a link nobody built.
Add a small debug hook that passes `ConsentDebugSettings` to the UMP request
from `--dart-define`s (called `UmpDebug` below), and run:

```bash
fvm flutter run --dart-define=APP_FLAVOR=dev \
  --dart-define=UMP_TEST_DEVICE=<hash the SDK printed> \
  --dart-define=UMP_DEBUG_GEOGRAPHY=eea \
  --dart-define=UMP_RESET=true
```

It must be inert in a release build unconditionally — a hardcoded geography
reaching production would classify real EEA users by something other than where
they are.

## Verify the artefact, not the invocation

Run the preflight before handing anything over:

```bash
${CLAUDE_SKILL_DIR}/preflight.sh [path/to/app.aab]
```

It checks the four things that are silently wrong at upload time: the signing
certificate (the Gradle config **falls back to the debug key without saying so**
when `key.properties` is missing), the `AD_ID` permission against your
declaration, sibling assets leaking in under `assets/packages`, and the store
metadata field limits.

**One thing it deliberately cannot check is the build flavor**, and that is
worth knowing rather than guessing: in a Flutter release build *both* the
production and the Google-sample ad unit ids appear as strings in the bundle,
because the `AdUnits` objects are const-constructed and retained whichever
flavor is compiled. Measured, not assumed. So:

> **A staging build is indistinguishable from a production build by
> inspection.** The only defence is to control the invocation — pass the
> production flag explicitly and rebuild if you are unsure which you have.

This matters if your release scripts **default to staging**: a staging build
on a public track serves Google's *test* ad units, so it earns nothing and shows
test creatives to real players.

## How the console fails

It is flaky in specific, recognisable ways. None of these is your mistake.

- **The form model desyncs from the DOM.** `form_input` ticks a checkbox
  visually while the framework never registers it — the section counter stays
  `0/N`, Next stays dead, and everything *looks* right. A real click during a
  page stall does the same. **Read the counters and the summary text, never the
  checkboxes.** Fix by toggling the control off and on with real clicks; a red
  *"Confirm all declarations"* appearing is the model catching up, not a new
  error.
- **Long hangs.** Script injection times out for a minute or more, then
  recovers on its own. Wait it out rather than retrying into it.
- **Deep links bounce to the app list.** Navigate to the app dashboard and click
  through the UI instead.
- **Wizards lose progress** if a step fails to advance. Re-enter from a fresh
  page load rather than fighting a stuck step.
- **Native `<select>` dropdowns mis-click.** A one-row miss put **Casino** on a
  children's game. Options render at a different size once open — screenshot or
  zoom to confirm the selected value *before* saving.

## Saving is not submitting

Every Save shows *"changes will be saved in Publishing overview, ready for you
to send for review"*. Nothing reaches Google until **Publishing overview → Send
app for review**, which stays locked until the dashboard checklist is complete.

This is the Play version of a rule the App Store side already has: uploading is
not distributing, and a green exit code is not a fact. Verify state in the
console, not from the absence of an error.

## The handoff

Do not hand over a list of paths for someone to go and find. Run:

```bash
${CLAUDE_SKILL_DIR}/handoff.sh
```

It runs the preflight, and **only if that passes** opens Finder at the images
folder, Finder with the `.aab` revealed and selected, and three Chrome tabs —
store listing, production track, publishing overview — then prints the three
steps in order. Handing over a debug-signed or over-length release is worse
than handing over nothing, so a failed preflight opens nothing (`--force`
overrides).

The tabs open in the **normal** browser rather than an automation tab group, so
the existing signed-in session is used and they survive the script exiting.

Deep links need the console ids. Put them in a `.play-release` file at the repo
root once, and every future release picks them up:

```sh
PLAY_DEV_ID=<developer id>   # from /developers/<id>/app/...
PLAY_APP_ID=<app id>         # from .../app/<id>/...
```

Without them it falls back to opening the Play Console home, which still works
but costs a few clicks.

Then the human does:

1. **The build** → Create release → upload the `.aab`.
2. **Publishing overview → Send app for review.**

The images are no longer on this list — upload them yourself first; see
[What a human has to do](#what-a-human-has-to-do).

## Tablet screenshots are not optional if the app ships to tablets

Play has **separate phone, 7-inch and 10-inch slots**. Filling only the phone
slot is what gets an app flagged as not designed for tablets and drops it out
of tablet placement — a silent loss of installs, which for an ad-supported app
is a silent loss of impressions.

Capture them from a real tablet AVD, not by upscaling a phone shot. A Flutter
app whose layout responds to width renders a genuinely different screen on a
tablet, and that is the whole value of the slot.

Then copy the output into the slot fastlane and the console both expect:

```
fastlane/metadata/android/en-US/images/
  phoneScreenshots/        icon.png  featureGraphic.png
  sevenInchScreenshots/
  tenInchScreenshots/
```

Two things that will bite:

- **Match the emulator by AVD name, never by serial.** With a phone and a
  tablet both up, `emulator-5554` is whichever booted first, and the capture
  silently goes to the wrong device. Ask each one: `adb -s <serial> emu avd
  name`.
- **Do not resize the device to fake a tablet.** `adb shell wm size 1080x1920`
  renders a black Flutter surface. Boot the tablet AVD.

Play's per-slot rules — each side 320–3840px, longest side ≤ 2× shortest — are
checked by `preflight.sh` for all three slots.

Say plainly that the bundle upload cannot be automated and why (the 10 MB
`file_upload` cap), so it does not read as something you failed to finish.

## Also worth a decision, not a default

**Teacher Approved** is offered inside the Target audience wizard for
child-targeted apps. It is an optional programme opt-in rather than a
declaration — opting in submits the app to third-party reviewers — so it is the
developer's call. It is also free distribution: the badge and Kids-tab
featuring are worth real installs for a family game, which is the honest way to
raise ad revenue when eCPM is already capped by child-directed serving.

## Before you start, check the privacy policy actually applies

Play requires a privacy policy URL and follows it. Two failures are common in a
portfolio that shares one policy across apps:

- **The URL 404s.** Confirm it resolves before pasting it in:
  `curl -o /dev/null -w '%{http_code}' -L <url>`. Do not invent a per-app path.
- **The policy describes a different app.** A shared policy that names one
  sibling by name, or claims data types this app does not collect, contradicts
  the Data safety form you are about to submit. Both stores check applicability.
