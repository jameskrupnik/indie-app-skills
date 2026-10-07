# Before and after: a real Reddit comment

This was rewritten after it was posted, because the first version read as generated. Same
facts, both times.

**Before:**

> I ship both — audioplayers (and flame_audio, which sits on it) across several apps,
> SoLoud in a puzzle game that fires a sound on every swipe.
>
> For your case SoLoud is the right move, and the reason is architectural rather than
> "it's faster". It's a game audio engine, not a media player: it mixes its own voices
> internally, so ten overlapping sounds need no pool of players and no AVPlayer per
> effect. That's exactly where audioplayers struggles in quick succession.
>
> **It decodes through miniaudio: WAV, MP3, OGG and FLAC — not AAC.** An .m4a is found and
> then fails with `SoLoudFileLoadFailedException: File found, but could not be loaded`,
> which reads like a corrupt file rather than an unsupported container.

Five em dashes. A bold header on each of four paragraphs. "the reason is architectural
rather than", "That's exactly where". Every paragraph the same length.

**After:**

> I've used both. audioplayers and flame_audio in a bunch of apps, soloud in a puzzle game
> that plays a sound on basically every swipe.
>
> For overlapping SFX soloud is the better fit. It's a game audio engine rather than a
> media player, so it mixes the voices itself and you're not managing a pool of players or
> an AVPlayer per effect. That's the part audioplayers isn't really built for.
>
> Stuff I wish I'd known going in:
>
> It won't decode AAC. It's miniaudio underneath, so WAV/MP3/OGG/FLAC only. Hand it an
> .m4a and it finds the file and then throws `SoLoudFileLoadFailedException: File found,
> but could not be loaded`, which really sounds like the file is corrupt. Took me way too
> long.

Nothing technical was removed. "Stuff I wish I'd known going in" replaced a bolded header
and does the same work. "Took me way too long" is the line that makes it a person.
