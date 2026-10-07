---
name: perf
description: Find and fix work that repeats every frame in a Flutter, React Native or Expo app or game (Flame, CustomPainter, react-native-skia, Reanimated worklets, requestAnimationFrame loops) and work redone on every React re-render — the cost a green suite and a clean analyze or tsc never mention — and measure the fix honestly. Use when asked to profile or improve performance, make an app or game faster or smoother, or reduce jank, stutter, dropped frames, battery drain or heat; when something "feels laggy" or "chugs" on an older phone; when reviewing a render, paint, update, frame-callback or component render method; before shipping a game that draws its own canvas; or when asked whether an optimization actually helped, or to benchmark two versions of anything.
---

# Frame cost

**A frame has 16.6ms, and no test measures how much of it you are using.**
Everything here ships in apps that are green, clean, and not visibly dropping
frames, because none of it is a bug. It is work repeated sixty times a second
that only needed doing once.

The shape is always the same: **an allocation or computation whose scope is
wrong.** A `Paint`, a shader, a text layout, a blur is unremarkable in a
`build` that runs when state changes, and a per-frame cost in a
`render(Canvas)`. The code reads identically in both places.

## Quick start

```bash
python3 ${CLAUDE_SKILL_DIR}/check_perf.py --app .
```

`--quiet` hides NOTEs, `--json` for a hook, `--strict` exits 1 on any
finding, `--help` lists the checks. The stack is detected (Dart under `lib/`,
or a `package.json` depending on `react-native` or `expo`); `--stack
flutter|rn` forces one. **React Native or Expo: read
[React Native and Expo](#react-native-and-expo) below; the Flutter detail
in between still explains the reasoning.**

It finds per-frame methods first (`render(Canvas)`, `update(double)`,
`paint(Canvas, Size)`) and reports only what is inside them, following
private helpers in the same file two levels down, because the blur is usually
in the `_drawGlow` that `render` calls. It recognises the memo idiom
(`??=`, `putIfAbsent`, a null-check-then-store) so it does not report the fix
back to you as the fault.

A `CustomPainter` only runs per frame while something repaints it. One wired
to an animation (`super(repaint: ...)`) counts as per-frame; any other
painter's findings are reported one level lower and tagged `repaint`.

**Everything it prints is a hypothesis.** Measure before believing it.

### Measure, and measure honestly

```bash
cp ${CLAUDE_SKILL_DIR}/frame_probe.dart tool/perf_probe.dart  # edit the ADAPT lines
flutter test tool/perf_probe.dart
```

The probe times `update`, **recording** a frame, and rasterizing one.
Recording is the number to watch: `endRecording` does no GPU work, so it
isolates the Dart-side cost on the UI thread, which is where jank comes from.
The raster column is Skia's software path: comparable between runs on one
machine, **not** comparable to a device, and it prices blurs and mipmaps
differently from a GPU.

**Throw away the first level, and the first frames of every level.** The
first thing measured is the JIT, not the game. Counted in, it read a 33ms max
and a p95 three times the steady state on a game whose honest worst frame was
1.5ms. A 120-frame skip alone was not enough: whichever level ran first still
read about 1.5x. The bundled probe does both; check any existing probe for
this before trusting its max column.

**The max is one frame, and a GC pause lands there.** A warm probe read one
level's worst frame as 2.2ms, then 49ms on the next run with nothing changed,
while p50 and p95 held within noise. Believe a max only when it repeats. A
per-frame cost moves the p95; a GC pause does not.

### Never compare N runs of A against N runs of B

A laptop throttles under sustained benchmarking, so whichever arm runs second
loses, often by more than the optimization wins. Run that way, one change
appeared to double every metric, including `update`, which it did not touch.
The conclusion was exactly backwards.

Alternate the arms and take the median of the **per-pair** ratio:

```bash
python3 ${CLAUDE_SKILL_DIR}/paired_bench.py \
  --probe 'flutter test tool/perf_probe.dart' \
  --swap  './bench_swap.sh {arm}' \
  --pairs 4 --control update
```

`bench_swap.sh` copies the saved `before` or `after` version of each changed
file into place. The order flips every pair, so a steady drift cancels.

**Always keep a control**: a metric the change cannot affect. Read it first.
If it is not near 1.00x the machine drifted and the raw column is noise; the
`corrected` column divides by the control. **Run it once with both arms
identical** to see your noise floor: on a small probe, identical code read
anywhere from 0.7x to 1.4x per metric. A range that straddles 1.00x is not an
effect.

For CI, [frame_baseline](https://github.com/jameskrupnik/frame_baseline)
turns frame timings into committed baselines that fail a test on regression.

## The catalogue

Each was found in a shipping app, and apps cut from the same template all had
it.

| Fault | Why it hides | The fix |
|---|---|---|
| **Text laid out every frame** | `TextPainter.layout` shapes and line-breaks on the UI thread. A "+50" fading over 40 frames pays 40 times to draw four characters; one cost 1.2ms a frame, more than the rest of the scene. Flame's `TextPaint.render(canvas, 'text', ...)` does the same | Lay out once. If only opacity varies, quantise it and cache one paragraph per step: 16 steps over 0.7s is imperceptible. In Flame, a `TextComponent` |
| **A blur per object per frame** | `MaskFilter.blur` cannot fold into its pass: it needs its own render target and two passes. Drop shadows are the worst, one per shape | A `RadialGradient` reaching the same distance is one fill |
| **A shader rebuilt every frame** | `createShader(rect)` allocates and defeats caching underneath | Cache it **keyed on the rect it was built for**. Unkeyed, a rotation stretches the old gradient across the new screen |
| **`Paint()` per draw call** | The cheapest and most numerous | Hoist when the colour is constant; mutate one reusable `Paint` when not |
| **`.toList()` in a per-frame sweep** | Sixty throwaway lists a second, usually finding nothing | A reused scratch list, or iterate a const list instead of a map's keys |
| **Decoding inside a frame** | An image or SVG decoded in `render` stalls that frame | Rasterize once at load into a `ui.Image` and draw it |
| **`saveLayer` per frame** | An offscreen buffer and a pass switch | Usually avoidable by baking the alpha into the colour |

## Things that look like wins and are not

- **A blur is not a gradient.** Compare them side by side on the real
  background. A linear ramp does not fall off like a gaussian, so a two-stop
  gradient matched to the blur's reach comes out bigger and woollier. A middle
  stop and a smaller radius fix it, and the wrong version looked fine alone.
- **`FilterQuality.medium` on image draws.** The software rasterizer prices it
  at 6x `low` because it rebuilds mipmaps every pass; Impeller keeps them per
  texture. Dropping to `low` aliases a downscaled icon on a 2x display. Do not
  trade image quality for a saving no device has confirmed.
- **A full-screen gradient fill.** Looks expensive; is one of the cheapest
  things a GPU does. Cache the shader object; do not contort the scene.
- **Anything a profiler has not agreed with.** Static findings are where to
  point the probe, not a work list.

## What a script cannot check

- **Widget rebuilds.** A `ValueListenableBuilder` around a whole HUD rebuilds
  all of it to change one number; one per readout rebuilds one `Text`.
  `ValueNotifier<Map>` compares by identity, so a fresh map per frame
  rebuilds every listener to show the same value.
- **State in the wrong layer.** Anything changing every frame does not belong
  in a bloc or provider: an emit per frame rebuilds the widget holding the
  game surface while the player is dragging across it.
- **Whether the work is needed at all.** The fastest render is for the object
  that was removed two seconds ago.
- **What the device does.** All of this is a headless approximation.
  `flutter run --profile` with the performance overlay, on the oldest phone
  you support, is the only real answer.

## The test gap this always uncovers

A game's suite drives `update` and **never calls `render`**. A shader built
from an empty rect, a paragraph laid out to the wrong width, gradient stops
that do not ascend: none is a compile error, and all sail past a green suite.
The symptom is an invisible object (`render-untested` in the script).

Rasterize each component across its life and assert ink landed:

```dart
final recorder = ui.PictureRecorder();
final canvas = Canvas(recorder)..drawRect(bounds, background);
component.render(canvas);
final data = await (await recorder.endRecording().toImage(w, h)).toByteData();
// count pixels that differ from the background colour
```

**Include a negative control**: drawing nothing must ink zero pixels. Without
it, an off-by-one in the pixel comparison passes every component, including
ones that render an empty box.

## Order of work

1. Run the script. Treat each finding as a hypothesis.
2. Stand up the probe if there is none. Record a baseline.
3. Fix FAILs first: text layout and decoding land on the UI thread, which is
   what janks.
4. Re-measure **paired, with a control**. Keep only what the numbers support,
   and say plainly which effects you could not demonstrate.
5. Look at anything visual you changed next to what it replaced.
6. Add a render test if there is none.
7. Leave the probe in `tool/` with a note to re-run it.

## React Native and Expo

Same idea, two threads. Reanimated worklets, gestures and Skia pictures run
on the **UI thread**; React renders, state and `runOnJS`/`scheduleOnRN`
handlers on the **JS thread**. A frame drops when either misses it.

The script treats as per-frame: `useFrameCallback`, `requestAnimationFrame`
loops and any function taking an `SkCanvas` (certain); `useDerivedValue`,
`useAnimatedStyle`, `useAnimatedProps`, `useAnimatedReaction` and
`createPicture` (per frame only while a value they read animates, reported
one level lower and tagged). It follows calls three levels, across files
through relative and `tsconfig` alias imports, and skips
`node_modules`, `build`, `.expo`, `Pods` and the native folders.

| Fault | Check | The fix |
|---|---|---|
| **Skia objects built per frame** | `paint-per-frame`, `shader-per-frame`, `blur-per-frame`, `path-per-frame`, `color-parse-per-frame`, `text-layout-per-frame`, `decode-per-frame`, `save-layer-per-frame` | Build once (module scope, `useMemo`, or `cache ??= ...`) and mutate or transform it. A shader for a moving object can keep one gradient and move it with a local matrix |
| **A JS hop every frame** | `js-roundtrip-per-frame` | `runOnJS`/`scheduleOnRN` only when something changed (the script accepts it behind an `if`); keep per-frame consumers on shared values |
| **Logging in a hot path** | `console-per-frame` | Remove it. React Native's performance guide calls `console.*` "a big bottleneck" on the JS thread and recommends `babel-plugin-transform-remove-console` for production |
| **State set in a rAF loop** | `setstate-per-frame` | A ref, an Animated/shared value, or `useFrameCallback`; render React state at most when the visible value changes |
| **Garbage per frame** | `allocation-per-frame` | `.map`/`.filter`/spreads/`Object.keys` in a frame callback: reuse a scratch array, mutate in place (`sharedValue.modify`) |
| **Memo defeated** | `inline-prop-to-memo` | An inline `{}`, `[]` or arrow passed to a `memo()` child is new every render; hoist it or `useMemo`/`useCallback` |
| **Per-render work** | `stylesheet-in-render`, `heavy-in-render` | `StyleSheet.create` at module scope; sort/reduce/JSON in `useMemo` |
| **Lists** | `list-in-scrollview`, `inline-render-item`, `index-key` | `FlatList` (or FlashList) for lists that grow; `renderItem` in `useCallback`; a stable key. `getItemLayout` when rows have a fixed height (both from React Native's list guide) |

Not checked, and worth a look by hand: reading `sharedValue.value` on the JS
thread (Reanimated's docs: it blocks until the UI thread answers), whole
screens re-rendering from one context or store subscription, and images
decoded at full resolution into small views.

**Measure.** Static findings are where to point a measurement, not a work
list, and the same rules apply: warm up, read the p95, believe a max only
when it repeats, alternate the arms.

- **Perf Monitor** (Dev Menu → *Show Perf Monitor*) shows the JS and UI
  frame rates live. Quick, but a dev build: direction only.
- **frame_probe.ts** logs frame intervals for both threads (UI via
  `useFrameCallback`, JS via `requestAnimationFrame`), p50/p95/max per
  window, first window discarded. Copy it into the app, call
  `useFrameProbe('L01')` from the screen under test, and measure a release
  build (`npx expo run:android --variant release`, `npx expo run:ios
  --configuration Release`, or the bare-RN equivalent from Gradle/Xcode). Reanimated 4; on Reanimated 3 swap `scheduleOnRN` for
  `runOnJS` as its header says.
- **Flashlight** (Android) scores a real device run from the command line:
  `flashlight measure` with the app open, or `flashlight test --bundleId
  <id> --testCommand '<e2e command>' --resultsFilePath results.json` for
  repeated runs, then `flashlight report results.json`.
- **Platform profilers** for the why: React Native's profiling guide points
  to the Android Studio Profiler (System Activities trace, exportable to
  Perfetto) and Xcode Instruments. The standalone `systrace` tool has been
  removed from Android platform-tools.

`paired_bench.py` is stack-neutral: any `--probe` command that prints lines
like `L01  ui 16.7/17.4/33.5` works, for example one that launches the
release build, waits, and dumps the probe lines from `adb logcat -d -s
ReactNativeJS`. The `--swap` script and the control metric are as above.

For layout, text scale, tablets and Reduce Motion, use the `polish` skill;
its faults hide from a green suite the same way.
On React Native that skill covers Pressable labels and sizes, font scaling,
safe areas and Reduce Motion the same way.

## Across several apps

These faults travel with the template an app was cut from: in eight sibling
games, six had the same per-frame popup layout and six never called `render`
in a test. Fix the template too, or it comes back with the next app.
