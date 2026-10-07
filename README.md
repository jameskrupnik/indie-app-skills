# indie-app-skills

Claude Code skills for one developer shipping many small Flutter, React Native
or Expo apps. Each one covers a failure that a green test suite and a clean
analyzer never mention: a store rejection, a Play release that stalls, a frame budget
spent on work that only needed doing once.

Every skill came out of shipping real apps to the App Store and Google Play.
Each rule in them exists because a measurement reversed something that had
seemed obviously true.

## The skills

| Skill | What it does | Script |
|---|---|---|
| `app-similarity` | Measures how much a Flutter, React Native or Expo app shares with its sibling apps (of either stack) across source, store metadata, screenshots and bundled assets, before Apple's guideline 4.3 (spam) does. | `check_similarity.py` |
| `listing-accuracy` | Checks that the store listing (fastlane, or Expo's `store.config.json`) and App Review notes describe the Flutter, React Native or Expo app that actually exists (guideline 2.3). | `check_listing.py` |
| `play-release` | Gets a Flutter, React Native or Expo app onto Google Play: the order the declarations must be done in, a preflight of the signed `.aab` and store listing, the EEA consent gap, and which steps a human has to do. | `preflight.sh`, `handoff.sh` |
| `perf` | Finds work repeated every frame in `render`, `paint` and `update` methods, and benchmarks a fix without being fooled by thermal throttling. | `check_perf.py`, `paired_bench.py`, `frame_probe.dart` |
| `polish` | Finds the layout, accessibility and Reduce Motion faults that make an app feel unfinished. | `check_polish.py` |
| `niche-scout` | Measures an app idea against the free iTunes Search API and kills the dead ones before any code is written. App Store only. | `sweep.py` |
| `claude-md-trim` | Brings CLAUDE.md, AGENTS.md and their imports back under Claude Code's size warning by moving evidence into `docs/` without losing a rule, then checks every link still resolves. | `check_size.py` |
| `human-voice` | Catches the tells that make a Reddit reply, cold email, cover letter, pin or store listing read as machine-written (dashes, "it's not X, it's Y", hype words, even paragraphs, templated batches), with a register for each surface. | `check_voice.py` |

The scripts need only Python 3.9+ and bash; no packages to install. Every one
answers `--help`, and those that check a project take `--json` for hooks and CI.
The store skills (`app-similarity`, `listing-accuracy`, `play-release`) work on
a Flutter project (`pubspec.yaml`) or a React Native / Expo one (`package.json`
naming `react-native`, with or without `ios/` and `android/`), and assume the
listing lives under `fastlane/metadata` (the per-platform `ios/fastlane` and
`android/fastlane` layouts are found too; Expo's `store.config.json` is read
for App Store copy). `claude-md-trim`, `human-voice` and `niche-scout` work for any project.

## The paid skills

The release pipeline these checks were built for is sold separately on
[Agensi](https://www.agensi.io/creators/james-krupnik), $15 each or
[$39 for all four](https://www.agensi.io/bundles/flutter-indie-release-pipeline):

| Skill | What it does |
|---|---|
| [New App from a Fork](https://www.agensi.io/skills/flutter-new-app-from-a-fork) | Starts a new Flutter app from one of yours without carrying over the parent's Firebase project, ad ids or bundle ids, then takes it to TestFlight. |
| [Bug Hunt](https://www.agensi.io/skills/flutter-bug-hunt) | Finds the bugs that pass `flutter analyze` and your whole test suite, and fixes each one with a test that fails first. |
| [TestFlight and App Store Review](https://www.agensi.io/skills/flutter-to-testflight-and-app-store-review) | Ships a fresh fork to a build in App Store review, in the order Apple enforces, with a fix written down for each known error. |
| [Release Cadence for Many Apps](https://www.agensi.io/skills/flutter-release-cadence-for-many-apps) | For one account with several apps: picks which app goes to review today, runs the pre-release checks, and paces submissions. |

The skills in this repo stay free and MIT-licensed, and none of them needs the
paid ones.

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
- Two scripts touch the network: `niche-scout` queries Apple's public search
  API and `play-release` checks that your privacy policy URL loads. Nothing
  else leaves your machine. See [PRIVACY.md](PRIVACY.md).
- Everything the scripts print is a finding to check, not a verdict. Each
  SKILL.md says what its script cannot see.
- The checks do not help you hide similarity from a reviewer.
  `app-similarity` refuses to rename or restructure code only to lower its
  number. It says to fix the app instead.

## License

MIT
