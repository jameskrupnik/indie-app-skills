# indie-app-skills

Claude Code skills for one developer shipping many small Flutter apps. Each
one covers a failure that a green test suite and a clean `flutter analyze`
never mention: a store rejection, a Play release that stalls, a frame budget
spent on work that only needed doing once.

Every skill came out of shipping real apps to the App Store and Google Play.
Each rule in them exists because a measurement reversed something that had
seemed obviously true.

## The skills

| Skill | What it does | Script |
|---|---|---|
| `app-similarity` | Measures how much an app shares with its sibling apps across source, store metadata, screenshots and bundled assets, before Apple's guideline 4.3 (spam) does. | `check_similarity.py` |
| `listing-accuracy` | Checks that the store listing and App Review notes describe the app that actually exists (guideline 2.3). | `check_listing.py` |
| `play-release` | Gets a Flutter app onto Google Play: the order the declarations must be done in, a preflight of the signed `.aab` and store listing, the EEA consent gap, and which steps a human has to do. | `preflight.sh`, `handoff.sh` |
| `perf` | Finds work repeated every frame in `render`, `paint` and `update` methods, and benchmarks a fix without being fooled by thermal throttling. | `check_perf.py`, `paired_bench.py`, `frame_probe.dart` |
| `polish` | Finds the layout, accessibility and Reduce Motion faults that make an app feel unfinished. | `check_polish.py` |
| `niche-scout` | Measures an app idea against the free iTunes Search API and kills the dead ones before any code is written. App Store only. | `sweep.py` |
| `claude-md-trim` | Brings CLAUDE.md, AGENTS.md and their imports back under Claude Code's size warning by moving evidence into `docs/` without losing a rule, then checks every link still resolves. | `check_size.py` |

The scripts need only Python 3.9+ and bash; no packages to install. Every one
answers `--help`, and those that check a project take `--json` for hooks and CI.
The store skills assume a Flutter project that keeps its listing under
`fastlane/metadata` (the per-platform `ios/fastlane` and `android/fastlane`
layouts are found too). `claude-md-trim` and `niche-scout` work for any project.

## Install

As a Claude Code plugin:

```
/plugin marketplace add jameskrupnik/indie-app-skills
/plugin install indie-app-skills@indie-app-skills
```

Or copy the skills you want into `~/.claude/skills/`:

```bash
git clone https://github.com/jameskrupnik/indie-app-skills
cp -r indie-app-skills/skills/perf ~/.claude/skills/
```

Claude loads a skill when your request matches its description. You can also
run any script directly, for example
`python3 skills/app-similarity/check_similarity.py --help`.

## Notes

- `play-release/handoff.sh` is macOS-only. It opens Finder and your browser;
  `--dry-run` prints what it would open.
- Everything the scripts print is a finding to check, not a verdict. Each
  SKILL.md says what its script cannot see.
- The checks do not help you hide similarity from a reviewer.
  `app-similarity` refuses to rename or restructure code only to lower its
  number. It says to fix the app instead.

## License

MIT
