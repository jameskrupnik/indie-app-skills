# play-release reference

Detail behind [SKILL.md](SKILL.md). Read the section you need.

## How the console fails

The Play Console is flaky in specific, recognisable ways. None of these is
your mistake.

- **Form state desyncs from what is shown.** A checkbox can look ticked while
  the page's form model never registered it: the section counter stays `0/N`,
  Next stays dead, everything *looks* right. Automation that sets values
  directly causes this, and so can a real click during a page stall. **Read
  the counters and summary text, never the checkboxes.** Fix by toggling the
  control off and on with real clicks. A red *"Confirm all declarations"*
  appearing afterwards is the model catching up, not a new error.
- **Long hangs.** The page can stop responding for a minute or more, then
  recover on its own. Wait rather than retrying into it.
- **Deep links bounce to the app list.** Open the app from the list and use
  the left nav.
- **Wizards lose progress** when a step fails to advance. Re-enter from a
  fresh page load rather than fighting a stuck step.
- **Native `<select>` dropdowns mis-select.** Options render at a different
  size once open, so a click can land one row off — one such miss put
  *Casino* as the category of a children's game. Confirm the selected value
  (screenshot or zoom) **before** saving.

## Uploading through browser automation

This applies when an agent drives the console through a browser-automation
tool that can place local files into `<input type=file>` elements (Claude in
Chrome's `file_upload` is one). With a service account, use `fastlane supply`
instead and skip this section.

**Listing images can be uploaded this way; the `.aab` usually cannot.**

- On first load the store listing page has no file input at all. Clicking an
  **Add assets** button opens an **asset-library side panel** that mounts a
  real `<input type=file>`. Find it, fill it with the local image paths, then
  click the panel's **Add** to place the selection into the slot.
- **Never click the panel's "Upload" button** — it opens the OS file picker,
  which automation cannot drive.
- **Files land in upload-completion order**, not selection order. Upload a
  screenshot set one file at a time, a few seconds apart, or drag to reorder
  afterwards (dragging works).
- **Listing text needs real keystrokes to register.** Setting `.value` from
  script leaves "Add a short description" errors. Set it, then click into the
  field and press `End`, `Space`, `Backspace`.
- **Save** is refused until every required image is present. **Save as
  draft** keeps the text meanwhile.
- **The bundle upload is over the size cap.** Claude in Chrome's
  `file_upload` refuses files over 10 MB; a Flutter release bundle is
  typically 30-80 MB. Hand that one step to a human (`handoff.sh` reveals the
  file and opens the page).

## EEA consent in detail

### Checking the code

```bash
grep -rl "requestConsentInfoUpdate" --include="*.dart" lib   # gathering
grep -rl "showPrivacyOptionsForm"   --include="*.dart" lib   # revocation
```

Gathering is usually present (most AdMob setup guides include it). The
revocation entry point usually is not. `preflight.sh` fails on either.

### Building the revocation entry point

It is small: a settings row that calls `ConsentForm.showPrivacyOptionsForm`,
shown only when `ConsentInformation.instance.getPrivacyOptionsRequirementStatus()`
returns `required`. Wrapping the UMP calls behind your own interface keeps
it testable. Two things to get right:

- **Wait for the consent update before asking.** Until
  `requestConsentInfoUpdate` has completed, the status reads `unknown`, which
  is indistinguishable from "not in the EEA" and silently hides the row.
- **Hide the row, never disable it.** Outside the EEA, UK and Switzerland
  there is nothing to withdraw, and a permanently dead control reads as a bug.

### Publishing the message

Two settings block **Publish** in AdMob and neither is obvious:

- **A privacy policy URL for the app.** Publish stays greyed out without one.
  Never invent a URL.
- **"Do not consent"**, which is off by default. Turning it on is the
  user-respecting choice, and costs nothing for an app that already serves
  only non-personalised ads.

Allow up to an hour for a published message to reach devices.

### Why it is also a revenue hole

`canRequestAds()` should gate every ad request. With no message configured,
the consent form fails to load (*"no form(s) configured for the input app
ID"*), so in the EEA the app plausibly serves no ads at all — a loss that
shows up nowhere either store would mention.

### Testing from outside the EEA

Neither the consent form nor the privacy options row appears on a device
outside the EEA, which is how a published message comes to promise a link
nobody built. Pass `ConsentDebugSettings` into the consent request from
debug-only `--dart-define`s, for example:

```bash
flutter run \
  --dart-define=UMP_TEST_DEVICE=<hashed id the SDK logs> \
  --dart-define=UMP_DEBUG_GEOGRAPHY=eea \
  --dart-define=UMP_RESET=true
```

(The define names are yours to choose; add your own flavor flags.) The hook
**must be inert in release builds, unconditionally** — a hard-coded geography
reaching production would classify real users by something other than where
they are. Gate it on `kReleaseMode`, not on a define.

## Content rating examples

For a cartoon game where something is struck and falls over (a pie thrown at
a duck, a bird knocked off a perch), the honest answers are *yes* to
violence, *yes* to violence against non-humans, and *yes* to real-world
animals if the targets are real species. Characterised accurately alongside
them — **fantastical setting, childlike style, unrealistic reactions,
distant perspective, no blood** — the result is still the lowest band: ESRB
Everyone, PEGI 3, USK 6, IARC 3+, with a descriptor like *Mild Fantasy
Violence*. That was observed on a real submission; your answers decide
yours.

## Capturing tablet screenshots

- **Use a real tablet emulator (AVD)**, not an upscaled phone shot. A Flutter
  layout that responds to width renders a genuinely different screen on a
  tablet, which is the point of the slot.
- **Match emulators by AVD name, not serial.** With a phone and a tablet both
  running, `emulator-5554` is whichever booted first. Ask each one:
  `adb -s <serial> emu avd name`.
- **Do not resize a phone to fake a tablet.** `adb shell wm size 1080x1920`
  can leave the Flutter surface black. Boot a tablet AVD.
- Copy results into `fastlane/metadata/android/<locale>/images/sevenInchScreenshots/`
  and `tenInchScreenshots/`. Remember the 10-inch slot's minimum side is
  1080 px.
