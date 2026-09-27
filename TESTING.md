# Local verification — 2026-09-27

This is an experimental local candidate. It has not been published, submitted to HACS,
reviewed by Home Assistant, or tested against the entire HA test suite.

## Offline checks actually executed

Environment: official HA Core container 2026.9.4, Python 3.14.6, separate test venv;
`pytest-homeassistant-custom-component==0.13.367`.

| Check | Result |
|---|---|
| `python -m pytest tests` | 149 passed |
| `mypy custom_components/feiniu_music` against installed HA source | 12 source files, no issues |
| `ruff check custom_components tests` | Passed |
| `ruff format --check custom_components tests` | 22 files already formatted |

Coverage includes actual HA config flows and models, corrected initial-login input,
password updates without echoing, fixed account identity, complete multi-page relations,
playlist filtering after counting raw rows, duplicate positions, denied metadata before
caching, independent caches, exact cover binding, bounded coordinated reauthentication,
stream error envelopes, real malformed HTTP parsing, signed/unsigned/expired HA URLs,
single/suffix/nonzero/tiny Range requests, redirect refusal, early response release,
unload cancellation, lyrics, and DIDL title/artist/album/artwork serialization.
The artwork regression follows the DIDL round trip and 256-character URI limit through
HA's real player image proxy, asserting returned image bytes. Short-grant tests cover
expiry, bounds, instance isolation, reload/unload, denied owners and incorrect covers.

Loopback HTTP tests use synthetic bytes. Their successful responses do not establish
audio decoding; the separate real-player observations below provide playback evidence.

## Real, read-only integration checks

An independent HA instance was configured with two existing test music accounts against
FeiNiu Music **1.0.1 (0.8.41)**. No NAS permissions/files, existing MA instance or production
HA configuration were changed.

- Normal account: 164 tracks, 139 albums, 128 artists. Restricted account: 2 tracks,
  2 albums, 1 artist. Both configured successfully and survive the test HA restart.
- Native Artist → Tracks returned 14 tracks in the normal account; the browser showed
  only the restricted account's two tracks under its artist. Artist → Albums and
  Album → Tracks also returned real results.
- Search returned the selected known title; resolving a known outside-scope track through
  the restricted entry failed before playback.
- Both accounts' legitimate artwork returned images. Owner mismatch is covered offline;
  no new live permission toggling or image-leak experiment was performed.
- FLAC, MP3 and OGG samples each returned HTTP 206 for `bytes=0-65535` and
  `bytes=1000000-1065535`, with matching Content-Range and exactly 65,536 bytes. Nonzero
  ranges differed from the beginning. Unsigned audio URLs returned HTTP 401.
- The read-only lyric action returned 668 text characters and 47 synchronized lines
  for one existing sample.
- Both selected accounts currently have zero playlists. Empty playlist browsing was
  checked live; populated playlist pagination/filtering/order are verified with synthetic
  offline fixtures, not claimed as this HA candidate's live 150-entry playlist test.

## HA → DLNA player

The independent container was changed to host networking at the user's request.
HA's built-in DLNA integration then discovered the existing EDIFIER MA3. Its configuration
is separate from the MA music integration and did not come from the existing MA container.

A user's active FeiNiu playback was observed, without interruption, progressing from
121 to 126 seconds through the new HA endpoint. After the metadata fix, a separate MP3
check started from idle and progressed from 2 to 7 seconds. The actual DLNA entity reported
the exact selected track title, artist, album and an artwork field. That initial check
did not fetch the artwork and therefore missed the failure described below. It stopped the speaker
and restored its original volume. This is a short device-state playback check, not a
listening assessment or complete-song test. FLAC/OGG playback on this speaker and
cross-device format compatibility are not claimed. Queue tests were added later, below.

The user's subsequent screenshot exposed a broken cover. Read-only UPnP inspection found
that MA3 returned only 256 characters of the long artwork URI; its HA signature was
incomplete and the image request returned 401. A fresh, complete 602-character thumbnail
URL returned the image successfully. The HA player image proxy consequently returned 404.
After deploying the short artwork grant, MA3 returned the complete 115-character URL.
The real player image proxy returned HTTP 200,
`image/webp`, 82,116 bytes, and the browser visibly rendered the cover with title/artist.
This validates image delivery, not just the presence of an artwork field.

The muted deployment check attempted to restore the previously paused track, but HA
returned 500 (`ServiceNotSupported`) for the pause service. Automatic
restoration of the original playback position/volume was not confirmed. Subsequent
read-only observation showed the same track paused at 109 seconds, volume 0.08; no further
playback control was attempted after that observation. The image fix's successful result
is separate from this unsuccessful state-restoration step.

HA's own brands API returned the local 256 px / 512 px icons byte-for-byte. The logo
request successfully used HA's standard icon fallback. PNG sizes: 11,910 / 27,611 bytes.

## Queue player update

The account player delegates real device control to an existing HA output. Offline
queue tests use HA's actual entity services and state events with a synthetic output
that has no next/previous support. They cover list context, order and duplicates,
playlist access filtering, shuffle and restoring order, repeat-one/all, enqueue modes,
pause/resume, end detection, explicit stop near the end, early stops, foreign playback,
permission failure on advance, account isolation, serialized Next operations, output
selection, dynamic transport capabilities and platform unload.

The real EDIFIER MA3 check was muted and used two existing MP3 tracks. Manual next and
previous, shuffle on/off, repeat one/all/off selection, pause/resume, and automatic
advance after seeking near the first track's end succeeded. The account player's
actual image proxy returned HTTP 200 (`image/jpeg`, 151,798 bytes). This was not a
complete-song or listening test. Actual repeat wrap/one and randomized queue order
are covered offline; the live check verified their control settings, not full repeat cycles.

The first queue attempt returned `ServiceNotSupported` for Pause because DLNA's
playing state preceded its available transport actions. The live probe now waits
for the output's advertised capability; it does not bypass HA's capability checks.
That attempt's failure record is retained separately. A regression verifies these
dynamic capability changes through HA service calls. The subsequent live check passed.
Both queue attempts confirmed restoration of the original paused track, its exact
615-second position and volume 0.08. The final controller retains the full 164-track
context, so previous/next can be used after resuming the restored track.

The browser displayed the new player with artwork, title/artist, previous/next,
shuffle, repeat and output selection. Queues do not survive reload/restart; output
choice does. Natural completion requires usable device state/identity/position;
this behavior has been exercised on this MA3 only.

## Evidence and limits

Sanitized live summaries and deployment probes are retained outside this repository under
the original workspace's `research/ha-integration`. Credentials and temporary HA signed
URLs stay in ignored private material, never in these tests or the distributable source.
No music or cover downloads are retained by the probes.

Large libraries, other FeiNiu/HA releases, all codecs, long-term natural expiry and
cross-process concurrent login have not been validated. The detail cache permits a
30-second stale window; already delivered metadata/images cannot be revoked from clients.
No synthetic result is presented as a live NAS or listening test.
