// A frame-cost harness for a Flame game. A TEMPLATE: copy it into your app
// (e.g. `tool/perf_probe.dart`) and change every line marked `ADAPT`:
//
//   ADAPT 1  the import of your game class
//   ADAPT 2  the levels (or modes, or seeds) worth timing
//   ADAPT 3  constructing the game, seeded
//   ADAPT 4  starting a round at a given level
//   ADAPT 5  "is the round still running"
//   ADAPT 6  a stand-in player
//
// Not using Flame? Keep the loop and replace `game.update` / `game.renderTree`
// with your own tick and `painter.paint(canvas, size)`.
//
// It times three things per frame, in microseconds (p50 / p95 / max):
//
//   update   the simulation tick. Keep it in the table even when you only
//            change render code: it is the control. If a change that cannot
//            touch it appears to move it, the machine drifted.
//   record   building the frame into a Picture. `endRecording` does no GPU
//            work, so this isolates the Dart-side cost on the UI thread, which
//            is where jank comes from. THE NUMBER TO WATCH.
//   raster   Skia's software rasterizer, not Impeller. Comparable between runs
//            on one machine; NOT comparable to a device. Direction only.
//
// Run:  flutter test tool/perf_probe.dart
// It lives outside test/ so the normal suite does not run it: it asserts
// nothing and prints a table for a human. Compare two versions with
// paired_bench.py, never with back-to-back batches.
//
// ignore_for_file: avoid_print
import 'dart:math';
import 'dart:ui' as ui;

import 'package:flame/components.dart';
import 'package:flame_test/flame_test.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

// ADAPT 1: your game class.
import 'package:my_app/game/my_game.dart';

/// ADAPT 2: what to time. Include the busiest state the game can produce
/// (most spawns, most effects); that decides whether a mid-range phone holds
/// 60fps, and it is rarely level 1.
const _levels = [1, 25, 50];

/// A real phone surface (logical pixels), not the 800x600 test default, so
/// world size and object count are what a player gets.
const _surface = (width: 393.0, height: 852.0);

/// Frames per level, at 60fps.
const _frames = 60 * 60;

/// The stand-in player acts every this many frames: roughly human reaction.
const _reactionFrames = 6;

/// Frames at the start of each level that are played but not counted.
///
/// The first frames measure the JIT, not the game. Counted in, they produced
/// a 33ms max and a p95 three times the steady state on a game whose honest
/// worst frame was 1.5ms.
const _warmupFrames = 120;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final rows = <String>[];

  // The first level is played twice and the first pass thrown away. The
  // per-level warm-up alone was not enough: whichever level ran first still
  // read about 1.5x its later self.
  final passes = [(_levels.first, true), for (final l in _levels) (l, false)];
  for (final (level, discard) in passes) {
    testWithGame<MyGame>(
      discard ? 'warm-up (not counted)' : 'level $level',
      // ADAPT 3: seed every source of randomness. An unseeded round makes two
      // runs incomparable, which defeats the exercise.
      () => MyGame(random: Random(7)),
      (game) async {
        game.onGameResize(Vector2(_surface.width, _surface.height));
        game.startLevel(level); // ADAPT 4
        await game.ready();

        final rng = Random(11);
        const dt = 1 / 60;
        final updateUs = <int>[];
        final recordUs = <int>[];
        final rasterUs = <int>[];
        var peak = 0;

        // ADAPT 5: stop when the round ends, or the tail measures a menu.
        for (var i = 0; i < _frames && game.isPlaying; i++) {
          if (i % _reactionFrames == 0) _steer(game, rng);

          final updateWatch = Stopwatch()..start();
          game.update(dt);
          updateWatch.stop();
          // Mounts components added during that update. Without it nothing
          // spawned ever appears, and every number is the cost of drawing
          // an empty screen.
          await game.ready();

          final recorder = ui.PictureRecorder();
          final canvas = Canvas(recorder);
          final recordWatch = Stopwatch()..start();
          game.renderTree(canvas);
          final picture = recorder.endRecording();
          recordWatch.stop();

          final counted = i >= _warmupFrames;
          if (counted) {
            updateUs.add(updateWatch.elapsedMicroseconds);
            recordUs.add(recordWatch.elapsedMicroseconds);
          }
          // Rasterizing every frame would dominate the wall clock, so sample.
          if (counted && i % 20 == 0) {
            final rasterWatch = Stopwatch()..start();
            picture
                .toImageSync(_surface.width.round(), _surface.height.round())
                .dispose();
            rasterWatch.stop();
            rasterUs.add(rasterWatch.elapsedMicroseconds);
          }
          picture.dispose();

          peak = max(peak, game.world.children.length);
        }

        if (discard) return;
        // `L01`, not `L 1`: paired_bench.py labels a row by its first token.
        rows.add(
          'L${level.toString().padLeft(2, '0')} '
          'frames=${updateUs.length}  '
          'update ${_stat(updateUs)}  '
          'record ${_stat(recordUs)}  '
          'raster ${_stat(rasterUs)}  '
          'peak=$peak',
        );
      },
    );
  }

  tearDownAll(() {
    print('\n=== per-frame cost, microseconds (p50 / p95 / max) ===');
    rows.forEach(print);
    print(
      '\n16667us is one frame at 60fps. A max that does not repeat across '
      'runs is usually a GC pause; trust p50 and p95.\n',
    );
  });
}

String _stat(List<int> samples) {
  if (samples.isEmpty) return '-/-/-';
  final sorted = [...samples]..sort();
  int at(double q) => sorted[(sorted.length * q).floor().clamp(
        0,
        sorted.length - 1,
      )];
  return '${at(0.5)}/${at(0.95)}/${sorted.last}';
}

/// ADAPT 6: a stand-in player good enough to keep the round alive and the
/// screen as full as it really gets. A player who does nothing measures an
/// empty screen. If the app already has a bot for tuning, reuse it: two
/// stand-ins that disagree produce tables that cannot be compared.
void _steer(MyGame game, Random rng) {}
