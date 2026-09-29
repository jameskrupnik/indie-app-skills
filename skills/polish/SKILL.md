---
name: polish
description: Find and fix the last 10% of an app — the faults that make it feel unfinished while every test passes. Use when asked to polish an app or game, to do final touches, to make something feel complete or "next level", or before a first submission; when something "feels off" or "looks unfinished" but nothing is broken; when adding tablet or iPad support, or checking a layout on a larger screen; for an accessibility pass, Reduce Motion, Dynamic Type, large text, VoiceOver or screen-reader labels; or when a layout is stretched, cramped, clipped, or overflowing on some devices but not others.
---

# Polish

**The last 10% is invisible from inside the code.** Every fault in this file
ships in an app whose `flutter analyze` is clean and whose suite is green,
because none of them is a crash, a type error, or an assertion. They are all
the same shape: a number chosen against one device, one text size or one
orientation, applied unchanged to a second one, producing a layout that *works*
and is wrong.

That is what "feels unfinished" is. Not bugs — a stretched card, a tile with
its text crammed into the top quarter, a starfield that will not stop moving,
a preference that silences nothing. Users cannot name any of it and all of them
feel it.

## Run it

```bash
python3 ${CLAUDE_SKILL_DIR}/check_polish.py
```

`--app DIR` to check elsewhere, `--json` for a hook, `--strict` to exit
non-zero. Everything is advisory: it flags shapes, and a shape can be
deliberate.

Then do the part the script cannot: **look at it**, on the largest and smallest
device you support, at 2× text. Most of what matters is only visible there.

## The catalogue

Each of these was found on a real shipping app. The right-hand column is why it
survived.

| Fault | How it hides |
|---|---|
| **A content cap wider than the device** | `maxWidth: 1100` looks like tablet support. No iPad is 1100pt across in portrait — the largest is 1024 — so it never engages and every list runs edge to edge, while the code reads as handled |
| **A fixed `childAspectRatio`** | Ties cell height to width. Text wrapping does the *opposite*: wider means fewer lines and less height. Wrong at both ends — cavernous tiles on a tablet, clipped text on a phone — and neither end throws |
| **A fixed height around text** | Fine at 1.0× text. Dynamic Type reaches 3.1×, and things break at **1.35×**, which is one notch up the iOS slider and not an accessibility setting at all |
| **Ambient animation** | A looping controller runs from the moment its screen appears until the user leaves. Reduce Motion exists for exactly this, and honouring it in one place out of three is worse than none, because it looks done |
| **A dead touch band** | Wherever a game letterboxes, the margin is usually still on screen and usually not touchable. It is where a thumb rests when somebody holds the device by its edge |
| **A preference that silences nothing** | The switch, the stored value and the effect are joined by convention, not by a type. Assert at the bottom — the platform channel, the audio player — not at the flag |
| **Icon-only controls** | No tooltip means no accessible name and no long-press hint. Cheap to fix, and the check is mechanical |
| **The one widget with no words in it** | Progress pips, dots, bars. Everything around them is text that reads itself out; they announce nothing at all |

## Three moves that find more than reading the code

**1. Capture it on the real device.** Not the emulator you develop on — the
biggest and the smallest you ship to. In one session this turned up a stretched
title screen, a badge grid two-thirds empty, a theme preview squashed to a 22:1
sliver, and score popups rendering **upside down** in the store screenshot set.
The popups had been "fixed" in an earlier commit; the fix had the sign
backwards. A half-turn error stays horizontal and the right size, so it reads
as fine in motion and only a still frame gives it away.

**2. Render at the settings nobody uses.** Largest text, smallest screen,
widest screen, Reduce Motion, both orientations. A suite that only ever renders
at 1.0× on one phone shape is silent about every one of them.

**3. Measure instead of tabulating.** When a layout number depends on more than
one input — width *and* text scale *and* wording — a table of measured
constants can only ever be right for one setting of the others. Ask the same
question the layout is about to ask (a `TextPainter`, an unbounded layout pass)
and the answer is right at every combination, including the ones nobody thought
of. A band table for badge heights was correct at 1.0× and broke at 1.35×;
measuring made it correct everywhere and deleted the table.

## Do not sniff for overflows

The obvious accessibility test is a fixed-height box and a check that nothing
overflowed. **It under-reports.** Flutter suppresses repeat layout errors
within a single test, so a loop over ten widgets finds the first and goes quiet
about the rest. It reported that 122pt was enough at a width where 220 is, and
sent two rounds of tuning in the wrong direction.

Lay the widget out **unbounded**, read its real height, and compare that to
what the container will give it. No suppression to fool, and it fails on a
reworded string rather than on somebody happening to look at a small phone.

## What a script cannot check

- **Whether the empty state, the loading state and the error state were
  designed** or just left as a spinner and a grey sentence. Every list has all
  three and most apps have art for one.
- **Whether feedback is proportionate.** Something should acknowledge every
  meaningful action, and nothing should acknowledge the ones that happen
  several times a second. A device that buzzes on every tap just hums.
- **Whether the first run makes sense** with no data: no scores, no history,
  nothing unlocked. It is the state every reviewer sees and the one developers
  never look at.
- **Whether copy is consistent** — "Play Together" in one place and "2 Player"
  in another is the kind of thing only reading the whole app aloud finds.
- **Whether the thing is worth having at all.** Accurate, accessible and
  well-spaced is not the same as good.

## Order

1. Run the script; fix what is mechanical and true.
2. Capture the biggest and smallest device you ship to. Fix what the pictures
   show, not what you expect them to show.
3. Add a test at the extremes — one tablet width, one large text scale. These
   are the two that regress silently.
4. Walk the system settings: Reduce Motion, large text, screen reader on the
   menus.
5. Re-capture. The store screenshots are also the proof.

## Expect the same findings across a portfolio

These faults come from the template, so they are in **every app cut from it**.
Running this across three sibling apps found the same `childAspectRatio: 1.15`
badge grid in all three, two of them with ambient animation ignoring Reduce
Motion, and one that buzzed with no way to switch it off. Fix it in one app and
the fix is worth carrying to the others — and worth carrying back into the
template, which is the only way it stops recurring.
