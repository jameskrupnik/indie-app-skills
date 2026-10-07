// A frame-interval probe for a React Native / Expo app using Reanimated 4.
// A TEMPLATE: copy it into your app (e.g. `src/dev/frame_probe.ts`), call
// the hook from the screen you want to measure, read the log, delete the call.
//
//   useFrameProbe('L01');            // in the game screen, dev builds only
//
// Every `windowFrames` frames it logs one line per thread, in milliseconds
// between frames (p50 / p95 / max):
//
//   L01  ui 16.7/17.4/33.5  (n=240)
//   L01  js 16.7/18.9/50.1  (n=240)
//
//   ui  intervals seen by Reanimated's useFrameCallback, which runs on the
//       UI thread: Reanimated worklets, Skia pictures, gestures.
//   js  intervals between requestAnimationFrame callbacks on the JS thread:
//       React renders, state updates, runOnJS / scheduleOnRN handlers.
//
// The p95 is the number to watch: a per-frame cost moves it, a single GC
// pause only moves the max. The first window is discarded (warm-up). The
// line shape is the one paired_bench.py parses, if you pipe device logs
// through a command (`adb logcat -d -s ReactNativeJS`, or Metro's output).
//
// Measure a release-like build: a dev build runs the JS thread with extra
// checks and is not comparable to what ships. On Reanimated 3, replace
// `scheduleOnRN(report, ...)` with `runOnJS(report)(...)` from
// react-native-reanimated.

import { useEffect } from 'react';
import { useFrameCallback, useSharedValue } from 'react-native-reanimated';
import { scheduleOnRN } from 'react-native-worklets';

function summary(samples: number[]): string {
  const s = samples.slice().sort((a, b) => a - b);
  const at = (q: number) => s[Math.min(s.length - 1, Math.floor(q * s.length))];
  return `${at(0.5).toFixed(1)}/${at(0.95).toFixed(1)}/${s[s.length - 1].toFixed(1)}`;
}

export function useFrameProbe(label: string, windowFrames = 240, enabled = true): void {
  const ui = useSharedValue<number[]>([]);
  const windows = useSharedValue(0);

  const report = (thread: 'ui' | 'js', samples: number[]) => {
    console.log(`${label}  ${thread} ${summary(samples)}  (n=${samples.length})`);
  };

  // UI thread. The buffer lives in a shared value and is appended to in
  // place with `modify`, so a frame allocates nothing until a window fills.
  useFrameCallback((frame) => {
    'worklet';
    const dt = frame.timeSincePreviousFrame;
    if (dt === null) return;
    ui.modify((buf) => {
      'worklet';
      buf.push(dt);
      return buf;
    });
    if (ui.value.length >= windowFrames) {
      const full = ui.value.slice();
      ui.value = [];
      windows.value += 1;
      if (windows.value > 1) scheduleOnRN(report, 'ui', full);
    }
  }, enabled);

  // JS thread.
  useEffect(() => {
    if (!enabled) return;
    let id = 0;
    let last = 0;
    let seen = 0;
    let buf: number[] = [];
    const tick = (now: number) => {
      if (last !== 0) {
        buf.push(now - last);
        if (buf.length >= windowFrames) {
          seen += 1;
          if (seen > 1) report('js', buf);
          buf = [];
        }
      }
      last = now;
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [enabled, windowFrames, label]);
}
