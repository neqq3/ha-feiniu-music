# Verification — complete experience candidate 0.2.0

## Current candidate checks (2026-09-28, local only)

Environment: isolated official HA Core 2026.9.4 container, Python 3.14.6,
pytest-homeassistant-custom-component 0.13.367; no dependency upgrade. Tests run in a
separate candidate directory, without real NAS credentials or speaker control.

| Check | Actual result |
| --- | --- |
| `python -m pytest tests -o addopts=--strict-markers -q --timeout=30` | 275 passed |
| `ruff check custom_components tests` | Passed |
| `ruff format --check custom_components tests` | 40 files already formatted |
| `MYPYPATH=/usr/src/homeassistant mypy custom_components/feiniu_music` | 22 source files, no issues |
| `node --test frontend/card.test.js` | 4 passed |
| `node frontend/build.mjs` | Bundled file generated, no runtime imports |
| `node frontend/browser-check.mjs` | Passed; two cards, queue/actions, safe text, lyrics race, hidden page, 360/390/430/1100 px, light/dark |

The browser harness uses Playwright 1.62.1 and installed Edge (`CARD_BROWSER_CHANNEL=msedge`).
It serves only a temporary loopback page with synthetic HA messages and closes its browser/server.
It does not inspect a user's browser profile. Install the listed dev dependency or reuse an existing
Playwright runtime; screenshots under `artifacts/card-preview` are intentionally untracked.

New HA-fixture tests exercise platform setup/options, standard services, state events, real
HA Store and authenticated WebSocket handlers. They cover independent fixed outputs, registry
renames/offline retention, incremental options, old unique-ID migration, permission checks,
reload without autoplay, queue revision/occurrence editing, cross-account leases, cancellation,
conservative startup/end evidence, sparse anchors, seek confirmation and late lyrics.
Loopback HTTP tests check simultaneous streams and stopping just one, HEAD/Range/206/416,
revocation, bounded authentication, JSON/HTML errors and response release. They use synthetic
bytes and do not claim codec decoding. DLNA's cached-PLAYING early return is reproduced in
an isolated reference test, not patched in HA core.

A real test-HA check exposed an enqueue bug: adding a track selected from a list appended its
entire browse context. The new regression requires only the chosen occurrence for `add`/`next`,
while play/replace retains list context. The first simulated-end probe also failed because its
research-only output timer was not marked as an HA callback; a second probe stopped waiting
as soon as the queue ID changed, before the next load completed. These failed attempts are
retained in local research; neither is reported as a successful playback check.

## Current isolated HA deployment

The candidate was installed into the already-authorized standalone HA, after a private backup
of the old integration, configuration, relevant config-entry/entity-registry/Lovelace storage and
existing FeiNiu queue files. Thirty deployed integration files match the candidate hashes. All
three original account data dictionaries (including saved credentials and device IDs) and the
three old entity IDs/unique IDs were retained; entries migrated to version 2. The account with
an explicit saved output retained that binding. Accounts without one were not assigned a real
speaker automatically; their old unused entities may remain unavailable until the user manages
those registry entries. Two new silent simulated outputs were explicitly selected only for the
test music account. No real speaker command was sent.

Through real HA WebSocket/REST APIs and the official music service:

- Browse returned 164 visible tracks for this test account. It has zero playlists; populated
  playlist tests remain offline and the earlier separate account's live record remains historical.
- Adding three individual browsed songs produced three queue occurrences per output and no
  play commands. Explicit Play created separate rounds with first-byte and matching HA-state evidence.
- Pause/resume, seek feedback, shuffle/repeat controls, manual next/previous and independent
  session state worked. The simulated transport's natural end advanced exactly once.
- Reloading this account preserved both three-item queues/current occurrences, without any new
  output command or ownership claim. Explicit resume created a new round.
- Lyrics returned 668 text characters and 47 synchronized lines. The real HA page rendered cover,
  metadata, queue rows and lyrics. Browsing and playback controls on other real outputs were untouched.
- Each simulated playback round fetched only 4 KiB into memory. Its reported position/end is a
  simulated transport clock using track duration, not decoding, physical sound or listening evidence.

Real HA masonry revealed a card lifecycle bug that the initial flat harness missed: detach/reinsert
while the first request was pending could leave Loading visible. The card now invalidates and
reissues that read on reconnect; a browser regression reproduces this timing, and the deployed
page was rechecked with both queues visible. Metadata-derived button names are text-only and
now match their visible row labels. Recent filtered FeiNiu/WebSocket error-header count was zero.

The simulator and live probes are local research tools and are excluded from the integration,
commit and installation package. The test HA has a dedicated dashboard; original dashboards
were not overwritten. Actual device startup quirks remain unverified on this complete candidate.

## Reproduction commands

```sh
python -m pytest tests -o addopts=--strict-markers -q --timeout=30
ruff check custom_components tests
ruff format --check custom_components tests
MYPYPATH=/path/to/homeassistant/source mypy custom_components/feiniu_music
node frontend/build.mjs
node --test frontend/card.test.js
# Requires Playwright and an installed supported browser:
CARD_BROWSER_CHANNEL=msedge node frontend/browser-check.mjs
git diff --check
```

Only the integration suite is claimed, not the entire Home Assistant or MA test suite.
The optional card is original local code with self-contained SVG controls and no CDN dependency.
No production HA/MA, NAS permissions or music files were changed. Physical playback and listening
were not repeated for 0.2.0; previous device observations below remain historical evidence only.

## Earlier versions: preserved evidence

The following entries describe prior revisions. Their old selectable-output/in-memory-queue
limitations are superseded by 0.2.0; their live playback results were not repeated on this candidate.

### Initial verification — 2026-09-27

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

## Initial browse/artwork cache update

The cache candidate was checked in a separate directory using the existing HA 2026.9.4
test environment. The targeted runtime/HTTP/cache tests passed (58 tests); the entire
integration suite passed (162 tests). Ruff check/format and mypy passed (12 source files).

Regression coverage includes per-entry byte/result caches, TTL and size bounds, complete
filtered pagination with duplicate positions, failed refresh propagation, exact owner checks
ahead of cached images/304 responses, conditional HTTP responses, one-consumer cancellation,
unload cleanup, and separate signed URLs for different HA browser sessions. No live permission
changes, playback controls, or NAS modifications were needed for these offline checks.

After user-approved deployment/restart of the independent test HA, the same 150-entry
playlist and first eight cover URLs (four concurrent requests) were measured read-only:

| Operation | Before | After |
| --- | --- | --- |
| First playlist browse | 507.7 ms | 511.2 ms |
| Repeated playlist browse | 265.6 / 265.0 ms | 6.6 / 5.9 ms |
| First batch of eight covers | 4003.0 ms | 3517.1 ms |
| Repeated same eight URLs | 2006.4 ms | 3.0 ms |
| Conditional cover revalidation | Not implemented | 2.2 ms; all eight HTTP 304 |

All 150 tracks and their order were retained; repeated thumbnail URLs were stable.
All eight image content hashes matched the earlier measurement. These are HTTP/WebSocket
request timings, not browser paint or speaker latency, and repeated reads occurred within
the cache lifetime. Cold requests and owner checks after the 30-second detail cache expires
still contact the NAS. No playback was started by the benchmark. The authorized restart
cleared the in-memory queue; no normal MA or NAS settings were changed.

## Complete browse-path update

The initial cache update missed the root folders. The final implementation also caches
track/album/artist/playlist collections, their relationships, and searches for 30 seconds.
It reuses those fresh account-filtered rows for exact artwork ownership, without using
them as playback authorization. Queue selection still refreshes its native list.

The final candidate passed 59 targeted tests and all 186 integration tests in the existing
HA 2026.9.4 environment, plus Ruff check/format (24 Python files), mypy (12 source files),
and `git diff --check`. New coverage includes all browse paths, a 164-image grid with
128 KiB synthetic covers, failed/incomplete pagination, non-extending access TTLs, earlier
browse data superseded by a new detail refusal, exact owner binding, image concurrency,
and real HTTP-disconnect cancellation. Shared downloads remain alive while another
consumer needs them. These tests do not require a NAS or credentials.

The first whole-grid measurement exposed a capacity failure that the earlier eight-image
sample missed: 164 responses contained 20,812,764 bytes. The 16 MiB cache caused repeated
eviction and the second pass took 65,707.4 ms. That failed measurement is retained. With a
32 MiB / 512-image per-entry cap, the repeated grid took 52.0 ms; all 164 conditional
requests returned 304 in 39.2 ms. The content hashes matched between passes. The grid has
139 unique images totaling 17,962,396 bytes. This is bounded source-image memory, not a
disk cache or an unlimited full-library cache.

Read-only WebSocket/HTTP measurements after deployment:

| Browse path | Entries | First request | Immediate repeat |
| --- | --- | --- | --- |
| Tracks | 164 | 266.6 ms | 4.3 ms |
| Playlists | 2 | 245.1 ms | 0.7 ms |
| Album tracks | 3 | 238.4 ms | 1.0 ms |
| Artist tracks | 14 | 250.4 ms | 0.8 ms |
| Artist albums | 1 | 249.3 ms | 0.8 ms |
| Playlist tracks | 150 | 509.2 ms | 5.0 ms |
| Search | 1 | 243.3 ms | 0.9 ms |

The 139-album and 128-artist root folders also retained their counts/order, with warm
requests around 3 ms. Their first reads were already primed by the navigation probe,
so these are not cold-load measurements. All repeated relationship lists kept their order.
While images were loading, album navigation completed in 1,437.8 ms; the probe cancelled
its own 12 remaining HTTP consumers, then artist navigation completed in 497.7 ms.
No player-control service was called.

The entire initial grid download after the small probes still took 42,384.1 ms. Native
request throttling remains unchanged, and access checks resume when the 30-second owner
window expires. This does not claim instant cold loading, nor browser rendering timing.
A prior 31-second expiry check of the same browse/ownership logic refreshed the 164-track
list in 508.1 ms and reused eight cover bodies in 3.2 ms; the two playlist covers reused
in 2.4 ms. That check preceded only the capacity adjustment from 16 to 32 MiB.

After the complete grid pass, the probe waited five minutes. HA closed its idle WebSocket
before the next command, so that attempt did not exercise the expired cache. Reconnecting
357.9 seconds after the last complete pass, the final version returned 164 tracks in
265.2 ms (repeat 4.3 ms); eight expired covers took 1,487.8 ms and their immediate repeat
took 2.0 ms, all HTTP 200. The probe failure and the resumed measurement are both retained.
The deployed 12 Python source files matched the tested candidate. The independent HA
was restarted for deployment; no production MA/NAS settings or music files were changed.

## Evidence and limits

Sanitized live summaries and deployment probes are retained outside this repository under
the original workspace's `research/ha-integration`. Credentials and temporary HA signed
URLs stay in ignored private material, never in these tests or the distributable source.
No music or cover downloads are retained by the probes.

Large libraries, other FeiNiu/HA releases, all codecs, long-term natural expiry and
cross-process concurrent login have not been validated. The detail cache permits a
30-second stale window; already delivered metadata/images cannot be revoked from clients.
No synthetic result is presented as a live NAS or listening test.
