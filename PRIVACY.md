# Privacy

These skills run on your machine. They collect no personal data, have no
server of their own, and keep nothing about you or your projects anywhere
but your own disk.

Three things leave your machine, and only when you run them:

- `niche-scout/sweep.py` sends the search terms you give it to Apple's public
  iTunes Search API (`https://itunes.apple.com/search`) and reads back the
  results. No account, key or identifier is sent. Apple's own privacy policy
  covers that request.
- `play-release/preflight.sh` requests the privacy policy URL found in your
  store listing, to check that it loads. It reads only the HTTP status code.
- `play-release/handoff.sh` opens Google Play Console pages in your browser.
  It does not send anything itself.

No other script makes a network request. The scripts read files in the
project you point them at and print findings; the few that write (such as
`claude-md-trim` moving text into `docs/`) write only inside that project.

Questions: open an issue at
https://github.com/jameskrupnik/indie-app-skills/issues
