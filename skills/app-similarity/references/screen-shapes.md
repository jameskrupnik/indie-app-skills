# Screen shapes: what to look for on the screens sheet

`screens_sheet.py` draws this app's screens above its closest siblings'. The
sheet is read by a person (or an agent with the Read tool). This file says what
to read it for.

**Why it exists.** An app can pass every other surface (different source,
listing, icon, palette, sounds) and still look like its sibling within one
glance at the screenshots, because the *shapes* of the screens are the same.
Measured on a real app: its palette, icon, copy and art were all
its own, and four screen shapes were still shared with three siblings. A
reviewer reads shape before colour.

## The shapes that give a template away

Check every row of the sheet for each of these. One shared shape is worth
noting; three or more shared with one sibling is the same app in a new colour.

| Shape | What it looks like | Why it is a tell |
|---|---|---|
| **Title over stacked buttons** | logo or wordmark, centred title, two or three full-width pill buttons | the screen you can build without knowing what the app is |
| **Primary button over a nav grid** | one wide accent "Play" / "Start" button, then a 2x2 or 2x3 grid of small icon tiles | every menu cut from one template has it |
| **Bar on every inner screen** | back arrow, title, coloured band across the top | the most-copied chrome there is; identical across forks even when the band changes colour |
| **Rounded coloured list rows** | a column of rounded rectangles, icon left, label, chevron or number right | the template's list, whatever it lists |
| **Number-over-label tiles** | a grid of cards, each a big number with a small caption under it | the template's stats screen |
| **Badge grid** | a grid of medallions or trophies with a caption each | the template's achievements screen |
| **Level map trail** | numbered nodes on a winding path | every casual game's map |
| **Bottom nav bar** | three to five icons along the bottom edge | stock navigation |
| **HUD chips** | score, timer and lives in rounded pills along the top of a game | the catcher/shooter HUD |
| **Same order** | the store set tells the same story in the same order (home, play, levels, stats, badges) | a reviewer compares sets side by side |

None of these is wrong on its own: a bar on an inner screen is a fine pattern.
They are tells only when a **sibling on the same account** has the same one.

## What counts as a fix

**Replace the shape with an object from the app's own world**, so the screen
could not be lifted into the sibling without a redesign:

- a nav grid becomes things on a surface the app is about (tags on a rail,
  drawers in a cabinet, pages in a book, tools on a bench);
- the back-arrow bar becomes something that belongs to the screen (a tag, a
  tab, a torn edge, a hand-lettered title with no band);
- coloured list rows become the medium the content lives in (ledger lines
  with dotted leaders, index cards, ticket stubs);
- number tiles become one composed figure (a meter, a tally, a chart drawn in
  the app's art).

Keep the **interaction** conventional: a tap target still looks tappable, a
back control still sits top-start, a screen reader still hears "Back, button".
Distinct means a different *picture*, not a different *grammar*. Usability
skills that recommend "use the platform's standard pattern" are about the
grammar, and they are right about it.

## What does not count

- **A new colour on the same shape.** Two apps with one header shape and one
  list rhythm read as one template in two palettes.
- **Renaming or moving code so the source surface stops matching.** That is
  the evasion the main SKILL.md refuses; it changes nothing a reviewer sees.
- **Reordering the store screenshots only.** If the screens are the same
  shapes, the order is not the problem.

## How to record it

Write the app's layout idea and the shapes it deliberately avoids in its
CLAUDE.md (or equivalent), so the next app cut from it knows what is taken.
If the workspace keeps a shared "taken" list, add this app's row there.
