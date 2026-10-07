---
name: polish
description: Find and fix the last 10% of a Flutter, React Native or Expo app or game — the faults that make it feel unfinished while analyze or tsc is clean and every test passes. Use when asked to polish an app, do final touches, make something feel complete or "next level", or before a first store submission; when something "feels off" or "looks unfinished" but nothing is broken; when adding tablet or iPad support or checking a layout on a larger screen; for an accessibility pass (Reduce Motion, Dynamic Type, large text, font scaling, VoiceOver, TalkBack, screen-reader labels, tap targets, safe areas); or when a layout is stretched, cramped, clipped or overflowing on some devices but not others.
---

# Polish

**The last 10% is invisible from inside the code.** None of these faults is a
crash, a type error or a failed assertion. They share one shape: a number
chosen against one device, one text size or one orientation, applied
unchanged to another, producing a layout that *works* and is wrong.

That is what "feels unfinished" means: a stretched card, text crammed into
the top of a tile, a starfield that will not stop moving, a setting that
silences nothing. Users cannot name any of it and all of them feel it.

## Quick start

```bash
python3 ${CLAUDE_SKILL_DIR}/check_polish.py --app .
```

`--json` for a hook, `--strict` exits 1 on any finding, `--quiet` hides NOTEs,
`--help` lists the checks. Everything is advisory: it flags shapes, and a
shape can be deliberate.

The stack is detected (Dart under `lib/`, or a `package.json` depending on
`react-native` or `expo`); `--stack flutter|rn` forces one. On React Native
or Expo, the catalogue below still holds; the
[React Native and Expo](#react-native-and-expo) section maps it to RN's
APIs and lists the RN checks.

Then do what the script cannot: **look at it** on the largest and smallest
device you support, at large text. Most of what matters is only visible there.

## The catalogue

| Fault | How it hides |
|---|---|
| **A content cap wider than the device** | `maxWidth: 1100` looks like tablet support. No iPad is wider than 1024pt in portrait, and the smallest is 744, so it never engages and every list runs edge to edge while the code reads as handled |
| **A fixed `childAspectRatio`** | Ties cell height to width. Text wrapping does the opposite: wider means fewer lines and less height. Cavernous tiles on a tablet, clipped text on a phone, and neither end throws |
| **A fixed height around text** | Fine at 1.0x. iOS Dynamic Type reaches about 3.1x, and layouts break at **1.35x**, one notch up the slider and not an accessibility setting at all |
| **Ambient animation** | A looping controller runs until the user leaves the screen. Reduce Motion exists for this, and honouring it in one place out of three is worse than none, because it looks done |
| **A dead touch band** | Where a game letterboxes, the margin is on screen and usually not touchable. It is where a thumb rests when someone holds the device by its edge |
| **A setting that silences nothing** | The switch, the stored value and the effect are joined by convention, not by a type. Test at the bottom (the platform call, the audio player), not at the flag |
| **Icon-only controls** | No tooltip means no accessible name and no long-press hint. Cheap, mechanical |
| **The one widget with no words** | Progress dots, pips, bars. Everything around them reads itself out; they announce nothing |

Haptics are a special case: Flutter's `HapticFeedback` already obeys the
system setting on both platforms, so an in-app switch is a courtesy. A
vibration plugin bypasses it and needs one.

## Three moves that find more than reading the code

**1. Capture it on real devices.** Not the emulator you develop on: the
biggest and smallest you ship to. One pass turned up a stretched title
screen, a badge grid two-thirds empty, a preview squashed to a 22:1 sliver,
and score popups rendering **upside down**. The popups had been "fixed" with
the sign backwards. A half-turn error stays horizontal and the right size, so
it reads as fine in motion; only a still frame gives it away.

**2. Render at the settings nobody uses.** Largest text, smallest screen,
widest screen, Reduce Motion, both orientations. A suite that only renders at
1.0x on one phone shape is silent about all of them.

**3. Measure instead of tabulating.** When a layout number depends on width
*and* text scale *and* wording, a table of constants is right for one setting
of the others. Ask the question the layout is about to ask (a `TextPainter`,
an unbounded layout pass) and the answer is right everywhere. A band table of
badge heights was right at 1.0x and broke at 1.35x; measuring fixed it and
deleted the table.

## Do not sniff for overflows

The obvious test is a fixed-height box and a check that nothing overflowed.
**It under-reports: Flutter suppresses repeat layout errors within one
test**, so a loop over ten widgets finds the first and goes quiet. It said
122pt was enough at a width where 220 was needed, and sent two rounds of
tuning the wrong way.

Lay the widget out **unbounded**, read its real height, and compare it to what
the container gives. Nothing to suppress, and it fails on a reworded string
rather than when someone happens to look at a small phone.

## What a script cannot check

- **Whether empty, loading and error states were designed**, or left as a
  spinner and a grey sentence. Most apps have art for one of the three.
- **Whether feedback is proportionate.** Every meaningful action gets an
  acknowledgement; nothing that happens several times a second does. A device
  that buzzes on every tap just hums.
- **Whether the first run makes sense** with no data, no history, nothing
  unlocked. It is what every reviewer sees and what developers never look at.
- **Whether copy is consistent.** "Play Together" here and "2 Player" there
  is only found by reading the whole app aloud.
- **Whether it is smooth.** Jank and per-frame waste are the `perf` skill.

## Order of work

1. Run the script; fix what is mechanical and true.
2. Capture the biggest and smallest devices you ship to. Fix what the
   pictures show, not what you expect them to show.
3. Add a test at the extremes: one tablet width, one text scale of at least
   1.35x. Those two regress silently.
4. Walk the system settings: Reduce Motion, large text, a screen reader on
   the menus.
5. Re-capture. The store screenshots are also the proof.

## React Native and Expo

The same faults, in React Native's vocabulary. The script skips
`node_modules`, `build`, `.expo`, `Pods` and the native folders.

| Check | What it flags | Why |
|---|---|---|
| `icon-label` | A `Pressable`/`Touchable*` with no `accessibilityLabel` and no `Text` inside | Touchables are accessible by default and build their label from `Text` children; an icon alone gives nothing to read |
| `a11y-role` | No `accessibilityRole`/`role` | The screen reader does not say "button" |
| `tap-target` | A pressable whose style is under 44pt on a side, with no `hitSlop` | Apple asks for 44pt, Material for 48dp; `hitSlop` grows the touch area without growing the box |
| `font-scaling` | `allowFontScaling={false}`, or `maxFontSizeMultiplier` between 1 and 1.5 | Text then ignores the system size. `0` means no cap, a value `>= 1` caps it |
| `fixed-height-text` | A literal `height` on a `View`/`Text`/pressable that holds `Text` | The fixed-height-around-text fault. `minHeight` or padding |
| `reduce-motion` | `Animated.loop`, `ReduceMotion.Never`, or a `useFrameCallback`/`useClock` (NOTE) in a file that never asks about Reduce Motion | Reanimated animations default to `ReduceMotion.System` and honour the setting; core `Animated` and frame-driven motion do not. Use `useReducedMotion()` or `AccessibilityInfo.isReduceMotionEnabled()` |
| `haptics-switch` | `Vibration.vibrate` or expo-haptics `impactAsync`/`notificationAsync` with no in-app switch | iOS skips expo-haptics when system haptics are off; on Android those two are simulated with the `Vibrator` API |
| `safe-area` | No safe-area handling anywhere, or `SafeAreaView` imported from `react-native` | RN's own `SafeAreaView` is deprecated and iOS-only; use react-native-safe-area-context |
| `dimensions-at-load` | `Dimensions.get` at module scope | Read once at load, stale after rotation, split view or a fold. `useWindowDimensions()` |
| `image-alt` | An `Image` with no `alt`/`accessibilityLabel` (NOTE) | Images are not accessible by default; fine if decorative |
| `content-cap` | A `maxWidth` no iPad reaches in portrait | As above |
| `tablet-layout` | Expo `ios.supportsTablet: true` and nothing reads the window size at render time | Every iPad gets the stretched phone layout |

To render at the settings nobody uses: raise the system text size (iOS
Larger Text, Android Font size) and turn on Reduce Motion on the simulator
or emulator, then look. There is no `untested-scale` check on React Native;
Jest rarely renders at a font scale, so the screenshot is the test.

## Across several apps

These faults travel with the template an app was cut from: three sibling apps
had the same `childAspectRatio: 1.15` badge grid, and two ignored Reduce
Motion. Fix the template too, or it comes back with the next app.
