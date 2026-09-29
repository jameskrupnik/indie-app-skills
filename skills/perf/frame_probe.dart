// A frame-cost harness. Copy to `tool/tuning/perf_probe.dart` and adapt the
// marked lines.
//
// Throwaway measurement, not a test of anything. It plays a real round and
// times the three things a frame costs:
//
//   update   the simulation tick
//   record   building the frame — `endRecording` does no GPU work, so this
//            isolates the Dart-side cost, which runs on the UI thread, which
//            is the thread jank comes from. **This is the number to watch.**
//   raster   Skia's *software* path, not Impeller. Comparable between runs on
//            this machine; NOT comparable to a device, and it prices blurs and
//            mipmaps quite differently from a GPU. Read it for direction only.
//
// It lives in `tool/` so `flutter test` does not run it: it asserts nothing
// and its output is a table a human reads.
//
// Run with:  flutter test tool/tuning/perf_probe.dart
//
// **Keep `update` in the table even when you are only changing render code.**
// It is the control: if a change that cannot touch it appears to move it, the
// machine drifted and the whole run is noise. See paired_bench.py.
import 'dart:math';
import 'dart:ui' as ui;

import 'package:flame/components.dart';
import 'package:flame_test/flame_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// ADAPT: the game, and whatever picks a difficulty for it.
import 'package:my_app_ui/screens/game/game/my_game.dart';

/// ADAPT: the levels worth timing. Include the busiest one the game can
/// produce — most spawns, most hazards, most effects. That is the one that
/// decides whether a mid-range phone holds 60fps, and it is rarely level 1.
const _levels = [1, 25, 50];

/// A competent player, so the round lasts long enough to be worth timing and
/// the field stays as full as it would really be. A stationary basket measures
/// an empty screen.
const _reactionFrames = 6;

/// Frames played at the start of each level and not counted.
///
/// **The first frames are the compiler, not the game.** Counted in, the first
/// level measured reported a 33ms max and a p95 three times its later self, on
/// a game whose honest worst frame was 1.5ms — a hitch no player ever sees,
/// reading exactly like one they do.
const _warmupFrames = 120;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final rows = <String>[];

  // **The first level is played twice and the first pass thrown away.**
  // `_warmupFrames` alone was not enough: whichever level went first still
  // read about 1.5x its later self. Every level after the first runs in an
  // isolate the JIT has already seen, so only the first needs this.
  final passes = [(_levels.first, true), for (final l in _levels) (l, false)];
  for (final (levelId, discard) in passes) {
    testWithGame<MyGame>(
      discard ? 'warm-up (not counted)' : 'level $levelId',
      // ADAPT. Seed the generator: an unseeded round makes two runs
      // incomparable, which is the whole point of the exercise.
      () => MyGame(random: Random(7)),
      (game) async {
        // A real phone surface, so the world size and the item count are what
        // a player actually gets rather than the 800x600 test default.
        game
          ..onGameResize(Vector2(393, 852))
          ..applyLevel(levelId) // ADAPT
          ..beginRound(); // ADAPT

        final rng = Random(11);
        const frame = 1 / 60;

        final updateUs = <int>[];
        final recordUs = <int>[];
        final rasterUs = <int>[];
        var peak = 0;

        for (var i = 0; i < 60 * 60 && game.isPlaying; i++) {
          if (i % _reactionFrames == 0) {
            _steer(game, rng); // ADAPT
          }

          final updateWatch = Stopwatch()..start();
          game.update(frame);
          updateWatch.stop();
          // Drains Flame's lifecycle queue, so components added *during* that
          // update actually mount. Without it the screen stays empty and every
          // number below is the cost of drawing nothing.
          await game.ready();

          final recorder = ui.PictureRecorder();
          final canvas = Canvas(recorder);
          final recordWatch = Stopwatch()..start();
          game.renderTree(canvas);
          final picture = recorder.endRecording();
          recordWatch.stop();

          final warm = i >= _warmupFrames;
          if (warm) {
            updateUs.add(updateWatch.elapsedMicroseconds);
            recordUs.add(recordWatch.elapsedMicroseconds);
          }

          // Rasterizing every frame would dominate the wall clock and tell you
          // nothing extra, so it is sampled.
          if (warm && i % 20 == 0) {
            final rasterWatch = Stopwatch()..start();
            picture.toImageSync(393, 852).dispose();
            rasterWatch.stop();
            rasterUs.add(rasterWatch.elapsedMicroseconds);
          }
          picture.dispose();

          final onScreen = game.world.children.length;
          if (onScreen > peak) peak = onScreen;
        }

        if (discard) return;
        rows.add(
          'L${levelId.toString().padLeft(2)} '
          'frames=${updateUs.length.toString().padLeft(4)}  '
          'update ${_stat(updateUs)}  '
          'record ${_stat(recordUs)}  '
          'raster ${_stat(rasterUs)}  '
          'peak=$peak',
        );
      },
    );
  }

  tearDownAll(() {
    // ignore: avoid_print — this file is a measurement tool.
    print('\n=== per-frame cost, microseconds (p50 / p95 / max) ===');
    for (final row in rows) {
      // ignore: avoid_print — this file is a measurement tool.
      print(row);
    }
    // ignore: avoid_print — this file is a measurement tool.
    print('\n16,667us is one frame at 60fps.\n');
  });
}

String _stat(List<int> samples) {
  if (samples.isEmpty) return '   -/   -/   -';
  final sorted = [...samples]..sort();
  String at(double q) =>
      sorted[(sorted.length * q).clamp(0, sorted.length - 1).floor()]
          .toString()
          .padLeft(4);
  return '${at(0.5)}/${at(0.95)}/${sorted.last.toString().padLeft(5)}';
}

/// ADAPT: a stand-in player good enough to keep the round alive.
///
/// If the app already has a tuning probe, reuse its player rather than writing
/// a second one — two stand-ins that disagree make two tables that cannot be
/// compared.
void _steer(MyGame game, Random rng) {}
