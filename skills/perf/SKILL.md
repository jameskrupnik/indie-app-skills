---
name: perf
description: Find and fix work that repeats every frame — the cost that a green suite and a clean analyze never mention. Use when asked to profile or improve performance, to make an app or game faster or smoother, to reduce jank, stutter, dropped frames, battery drain or heat; when something "feels laggy" or "chugs" on an older phone; when reviewing a render, paint or update method; or before shipping a game that draws its own canvas. Also use when asked whether an optimization actually helped, or to benchmark two versions of anything.
---

# Frame cost

**A frame has 16.6ms and no test measures how much of it you are using.**
Everything in this file ships in an app that is green, clean, and not visibly
dropping frames — because none of it is a bug. It is work repeated sixty times
a second that only needed doing once.

That is the shape: **an allocation or a computation whose scope is wrong.** A
`Paint`, a shader, a text layout, a blur — each unremarkable in a `build` that
runs when state changes, each a per-frame cost in a `render(Canvas)`. The code
reads identically in both places.

## Run it

```bash
python3 ${CLAUDE_SKILL_DIR}/check_perf.py --app DIR
```

`--quiet` hides notes, `--json` for a hook, `--strict` to exit non-zero. It
finds the per-frame methods first and only reports what is inside them,
following private helpers one and two levels down — because the blur is
usually not in `render`, it is in the `_drawGlow` that `render` calls.

It understands the memo idiom (`_field ??= …`, a null-check-then-store, a
`putIfAbsent`), so it will not report the fix back to you as a fault.

Everything it prints is a **hypothesis**. Measure before believing it.

## Measure, and measure honestly

Two harnesses, both bundled:

```bash
cp ${CLAUDE_SKILL_DIR}/frame_probe.dart tool/tuning/perf_probe.dart   # adapt the marked lines
flutter test tool/tuning/perf_probe.dart
```

It times `update`, **recording** a frame, and rasterizing one. Recording is the
number to watch: `endRecording` does no GPU work, so it isolates the Dart-side
cost, which runs on the UI thread, which is where jank comes from. The raster
column runs Skia's *software* path — comparable between runs on your machine,
**not** comparable to a device, and it prices blurs and mipmaps quite
differently from a GPU.

### The first level measured is the compiler

**Throw away the first level, and the first frames of every level.** The
bundled probe does both. Without it, the first level reads a 33ms max and a
p95 three times its later self — on a game whose honest worst frame was
1.5ms — and the max column reports a hitch no player ever sees. A 120-frame
skip alone was not enough; whichever level went first still read about 1.5x.
**Check any existing probe for this before trusting its max column.**

**And even after warm-up, the max is one frame, and a garbage-collection
pause lands there.** One game's warm probe read a rung's worst frame as
2.2ms, then 49ms on the very next run with nothing changed, while p50 and p95
held to within noise. Believe a max only when it repeats across runs; a
per-frame cost moves the p95, and a GC pause does not.

### The trap that costs an afternoon

**Never compare five runs of one arm against five of the other.** A laptop
throttles under sustained benchmarking, so whichever arm goes second loses —
and by more than most optimizations win. On a real run this reported every
metric doubling, `update` included, against a change that touched no
simulation code at all. The conclusion was exactly backwards.

Alternate the arms and take the median of the **per-pair** ratio:

```bash
python3 ${CLAUDE_SKILL_DIR}/paired_bench.py \
  --probe 'flutter test tool/tuning/perf_probe.dart' \
  --swap  './bench_swap.sh {arm}' \
  --pairs 4 --control update
```

**Always keep a control** — a metric the change cannot possibly affect. Read it
first. If it does not come back near 1.00x the machine drifted, and every other
number in the table is noise wearing a decimal point. Correcting by the control
recovers a usable estimate; the tool prints that column for you.

`bench_swap.sh` is three lines: copy the two versions of each changed file out
to `/tmp` once, then `cp` the right one back per arm.

## The catalogue

Each of these was found on a shipping app, and most were in its siblings too —
they came from the same template, so they propagate.

| Fault | Why it hides | The fix |
|---|---|---|
| **Text laid out every frame** | `TextPainter.layout` shapes and line-breaks the string. A "+50" that fades over 40 frames pays 40 times to draw four characters — on the UI thread | Build the paragraph once. If only opacity varies, quantise it and cache one paragraph per step; 16 steps over 0.7s is imperceptible |
| **A blur per object per frame** | `MaskFilter.blur` cannot fold into the pass it sits in — it needs its own render target and two passes. Drop shadows are the worst offender: one per shape | A `RadialGradient` reaching the same distance is a single fill |
| **A shader rebuilt every frame** | `LinearGradient(...).createShader(rect)` allocates and defeats caching underneath | Cache it **against the rect it was built for**. Unkeyed, a rotation stretches yesterday's gradient across today's screen |
| **`Paint()` per draw call** | The cheapest and the most numerous | Hoist when the colour is constant; mutate one reusable `Paint` when it is not |
| **`.toList()` in a per-frame sweep** | Sixty throwaway lists a second, finding nothing on almost all of them | A reused scratch list; or iterate a const enum instead of a map's keys |
| **Decoding inside a frame** | An SVG or image decoded in `render` stalls that frame | Rasterize once at load into a `ui.Image` and blit |
| **`saveLayer` per frame** | An offscreen buffer and a pass switch | Usually avoidable by baking the alpha into the colour |

## Things that look like wins and are not

- **A blur is not a gradient.** Swapping one for the other has to be looked at,
  side by side, on a real background. A linear ramp does not fall off like a
  gaussian, so matching the blur's reach with a two-stop gradient comes out
  visibly bigger and woollier. A middle stop and a smaller radius fixes it —
  and the wrong version looked perfectly fine in isolation.
- **`FilterQuality.medium` on image blits.** A software rasterizer prices it at
  6x `low`, which looks damning until you notice it rebuilds the mipmap chain
  per raster pass while Impeller keeps one per texture for the life of the app.
  Dropping to bilinear aliases a downscaled icon on a 2x display. Do not trade
  real image quality for a saving no device has confirmed.
- **A full-screen gradient fill.** It looks expensive and is one of the
  cheapest things a GPU does. Cache the *shader object*; do not contort the
  scene to avoid the fill.
- **Anything a profiler has not agreed with.** Static findings are where to
  point the probe, not a work list.

## What a script cannot check

- **Whether the widget layer is rebuilding more than it needs to.** A
  `ValueListenableBuilder` around a whole HUD rebuilds all of it to change one
  number; one per readout rebuilds one `Text`. `ValueNotifier<Map>` compares by
  identity, so assigning a fresh map per frame rebuilds every listener to show
  the same value.
- **Whether live state is going through the wrong layer.** Anything changing
  every frame does not belong in a bloc: an emit per frame rebuilds the widget
  holding the game surface while the player is dragging across it.
- **Whether the work is needed at all.** The fastest render is the one for an
  object that should have been removed two seconds ago.
- **Startup cost.** Decode-at-load is right, but a launch that awaits forty
  images is a different complaint from the same user.
- **What the device actually does.** Everything here is a headless
  approximation. `flutter run --profile` with the performance overlay, on the
  oldest phone you support, is the only thing that answers the real question.

## Order

1. Run the script. Treat every finding as a hypothesis.
2. Stand up the probe if there is not one. Record a baseline.
3. Fix the FAILs first — text layout and per-frame decoding are the two that
   land on the UI thread, and the UI thread is what janks.
4. Re-measure **paired**, with a control. Keep only what the numbers support,
   and say plainly which effects you could not demonstrate.
5. Look at anything visual you changed, next to what it replaced.
6. Add a render test if there is not one — see below.
7. Leave the probe in `tool/` and a note saying to re-run it.

## The test gap this always uncovers

A game's suite drives `update` and **never calls `render`**. So a shader built
from an empty rect, a paragraph laid out to the wrong constraints, or a
gradient whose stops do not ascend all sail past a green suite — and none of
them is a compile error. The symptom is an invisible object falling through the
sky.

Rasterize every component across its life and assert ink landed:

```dart
final recorder = ui.PictureRecorder();
final canvas = Canvas(recorder)..drawRect(bounds, background);
component.render(canvas);
final data = await (await recorder.endRecording().toImage(w, h)).toByteData();
// count pixels that are not the background colour
```

**Include a no-op negative control** — assert that drawing *nothing* inks zero
pixels. Without it, an off-by-one in the pixel comparison makes the whole file
pass against components that render an empty box.

## Expect the same findings across a portfolio

These come from the template, so they are in every app cut from it. One sweep
across eight sibling games found the identical `TextPainter`-per-frame score
popup in **six of them**, fifteen blurred drop shadows per frame in one, and
six of the eight with no test that ever called `render`. Fix it in one app,
carry it to the others, and carry it back into the template — which is the only
way it stops recurring.
