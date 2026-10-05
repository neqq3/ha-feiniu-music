# Verification

## Running the compatibility checks

GitHub Actions runs the same integration suite against HA 2025.12.2 / Python 3.13
and HA 2026.9.4 / Python 3.14. Each job uses its matching pytest plugin and installs
component dependencies from that HA version's own manifests. Tests use synthetic
accounts and outputs; they do not need NAS credentials or access to a real HA instance.

For a local Linux environment, use Python 3.13 with `requirements-test-min.txt`,
or Python 3.14 with `requirements-test.txt`:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-test-min.txt
python scripts/install_test_dependencies.py
python -m pytest tests --timeout=30
ruff check custom_components tests scripts
ruff format --check custom_components tests scripts
mypy --python-version 3.13 custom_components/feiniu_music
```

Use `--python-version 3.14` for mypy when testing HA 2026.9.4, whose own source
requires Python 3.14. Ruff always checks our source against the Python 3.13 baseline.

The frontend job runs `npm test`, rebuilds and compares the bundled card, then runs
`npm run test:browser` with Playwright Chromium. Browser checks cover compact/full
layouts, touch controls, search, lyrics, and the visual editor using synthetic HA messages.
It also runs the browse lifecycle checks with `CARD_BROWSER_ENGINE=webkit`, using
touch/mobile emulation. This is not a physical iPhone or HA Companion WebView test.

## Persistent duration fallback

The compatibility continuation selector now also offers `duration_fallback`.
Standard/manual and `estimated_duration` retain their existing behavior. The new
choice is per output, takes effect next round, and keeps duration + 5-second
estimation after startup confirmation. No device-brand detection is used.

Controlled-clock regressions reproduce a continuously playing output whose raw
position wraps to the start and whose stream is fetched again. Only the new
opt-in advances the queue. They also cover pause/resume and buffering, early/late
confirmation, acknowledged forward/backward seeks, failed or pending controls,
same-turn timer/end/intent races, takeover, queue repeat/shuffle and stopping a
looping output at the end of a non-repeating queue when supported. Native position
wraps do not reset the fallback clock; external seeks without a FeiNiu request
cannot be reliably distinguished from device looping.

The local controlled suites (feedback compatibility/options/storage and timeline)
pass 293 tests on HA 2026.9.4 / Python 3.14. These run without the full HA pytest
plugin on Windows; they are not a substitute for the Linux integration matrix.
The card passes 9 unit tests, Chromium and WebKit checks, including bilingual
three-choice settings and reopening/saving the new choice. Native HA options and
WebSocket persistence cases are included in the existing CI suite. There is no
new real-speaker acceptance result for this strategy yet.

## Playback feedback compatibility — 2026-10-05

Implementation baseline: `6b8de85`. The reviewed production code is in `d1dae85`;
`09e4297` only corrects a delayed-failure test double so the exception is raised
inside the service coroutine instead of an unconsumed future.

The added controlled-clock suite uses real HA `State` objects, a synthetic output
adapter and controlled service/wait futures. It covers all 24 legacy profiles,
compatibility through late confirmation and pause/resume, exact duration + 5-second
continuation, cancellation races, stale identities, transport/error distinctions,
queue modes, seek gating and privacy. Migration transforms cover all 24 profiles,
offline/deselected records, account isolation, corruption and idempotence. Native HA
Store and options-flow tests are also added to the normal Linux suite.

Final-review regressions cover pending-resume timing, superseded service results,
buffering, short-track queue completion and concurrent options edits. The full
Linux checks passed for `09e4297` in
[Actions #37265917745](https://github.com/neqq3/ha-feiniu-music/actions/runs/37265917745):
HA 2025.12.2 / Python 3.13 and HA 2026.9.4 / Python 3.14 each passed **670 tests**,
Ruff, formatting and mypy. The card passed **9 unit tests**, build consistency,
Chromium and WebKit. No tests were skipped or dependency constraints relaxed.

`feedback-check.mjs` runs on both Chromium and WebKit, covering English/Chinese
settings, compatibility-only opt-in, runtime notices, disabled seek/lyric jumps
and late confirmation. Existing browse/artist regressions remain enabled.

### Limited device acceptance and remaining limits

The same `09e4297` integration was checked on HA 2025.12.2, with Xiaomi Miot 1.1.1
and HA's native `dlna_dmr`. These are software-state and transport observations;
audible playback was not independently confirmed.

- DLNA Standard completed three fixed-track Start/Seek/Next/Stop repetitions.
  Each seek to 60 seconds produced native reports of 60, 69, 79 and 89 seconds,
  with matching FeiNiu positions. Next confirmed in 1.33–1.45 seconds. The earlier
  position rollback and one startup timeout did not recur; no baseline A/B was needed.
- Miot Compatibility/manual retained an unconfirmed round, supported same-round
  pause/resume and late confirmation, and gated seeking while unconfirmed.
- Estimated continuation has live evidence for timer arming, pause/resume,
  resume-pending protection, late-confirm cancellation and Stop/Next cancellation.
  In the final three natural-wait attempts on a 45-second track, every round
  entered assumed but confirmed before its calculated deadline. Each timer was
  cancelled, with no estimated end or automatic queue advance.
- **Natural estimated expiry and its once-only automatic next remain unverified
  on real hardware.** Exact duration + 5-second timing, invalid/missing duration,
  missing first-byte delivery and stale-callback guards have deterministic tests
  in both HA CI jobs. They are not claims of acoustic or real-device expiry proof.
- Miot's unavailable Stop action remains a device/integration limitation. Cleanup
  used its existing Pause action; FeiNiu cannot guarantee physical audio silence.
  Both outputs were restored to Standard/manual and their original other settings,
  with debug logging restored and no retained lease or estimated timer.

Private diagnostics, device identifiers and raw acceptance artifacts are not
included in this repository. Results apply to these bounded checks, not all Miot
models or a guarantee against network, format, buffering or external-control issues.

## Paged browsing and lifecycle — 2026-10-04

Regression tests were committed before the implementation: both HA matrix jobs
reproduced 13 failures while the original 375 tests still passed. These establish
the old global-lock, whole-list and TTL mechanisms with a fake backend, not a
reproduction of a user's NAS or speaker problem.

The new suite covers page-level reads, full queue selection, single-flight cancellation,
bounded admission, access epochs, playlist status validation, Retry-After and diagnostic
privacy. Frontend checks defer main/sidebar/image replies, expire a request, simulate a
disconnect, switch entities during a pending reply, and close/reopen/detach the card.
The existing strict lyric-scroll assertion remains; its fixture now waits until a prior
smooth keyboard scroll has settled before testing subsequent position updates.

`tests/test_browse_benchmark.py` emits six synthetic measurements per HA version to
`artifacts/browse-*.json`. Actions uploads them as `browse-ha-<version>`. They contain
only fake library sizes, elapsed times, request counts and Python allocation peaks.
Both full enumeration and first-page reads use allocation tracing for comparable
instrumentation; no exact timing threshold determines pass/fail.

See [browse performance and cache boundaries](docs/BROWSE_PERFORMANCE.md) for the
verified run, measured values, call graph, upstream comparison and remaining limits.
Earlier live-service observations below belong to their dated changes, not this round.

## Artist relationship pagination — 2026-10-04

Review baseline: `ada2e06` on `dev/browse-performance-checks`, initially clean.
The new `frontend/artist-browse-check.mjs` runs the bundled, real custom element
against synthetic native-shaped HA replies and asserts its DOM. Before changing
the card, the 100-track control passed; opening the 201-track artist's first page
failed with title `歌曲`, hidden/empty relation tabs, no active tab and no artist
detail artwork. Expected: artist title, Songs/Albums tabs and the artist detail.

The fix recognizes only an explicitly typed artist item with its exact expandable,
non-playable `tracks` and `albums` directories. Pagination directories and titles
alone cannot establish context. Navigation frames retain the existing artist
context so Back can restore a previously visited artist's relationship view.

The same assertions cover second/last/previous song and album pages, albums and
tracks named `Tracks` / `Albums`, reordered/localized relation names, unrelated
directories, Back from album contents and another artist, and delayed replies from
both artist details and relationship contents. Page 2 still sends global position
100 plus its GUID; Play all still sends the canonical complete-list URI.

The existing Chromium suite and WebKit touch-emulation job both invoke this check.
The frontend unit tests, build comparison and both HA backend matrix jobs are
unchanged. This fix changes no backend code, cache, playback state machine or
queue behavior; no production HA or physical speaker is involved in these tests.

## Automatic card registration — 0.2.2

- HA 2026.9.4 regression suite: **316 passed**, including eight resource registration tests.
  Fresh HTTP delivery, content-based updates, repeat setup, multiple accounts/reload,
  YAML resource ownership and registration failure isolation are covered.
- Ruff lint/format passed; mypy passed for 24 source files. The frontend bundle is unchanged.
- Test HA recreated its removed card resource on restart and served the exact bundle.
  A fresh browser page rendered the card. Existing dashboards and other resources were unchanged.
  Playback changed during verification; its queue snapshot was not treated as a preservation check.
  The deployment/verification sent no audio service calls.

## Artwork and browse checks (2026-09-28)

Environment: the existing isolated HA Core 2026.9.4 container, Python 3.14.6,
Pillow 12.3.0 already supplied by HA, unchanged dependencies. The tests run in a
separate candidate directory without NAS credentials. The running test integration
was updated only after these checks passed.

| Check | Actual result |
| --- | --- |
| Targeted artwork, request-lane, HTTP, browse and client tests | 145 passed |
| `python -m pytest tests -o addopts=--strict-markers -q --timeout=30` | 296 passed in 5.51 s |
| `ruff check custom_components tests` | Passed |
| `ruff format --check custom_components tests` | 43 files already formatted |
| `MYPYPATH=/usr/src/homeassistant mypy custom_components/feiniu_music` | 23 source files, no issues |
| `npm test` | 4 passed |
| `node frontend/build.mjs` | Generated the bundled card |
| `node frontend/browser-check.mjs` | Passed, including keyed row/image reuse and browse thumbnails |
| `git diff --check` | Passed |

The loopback HTTP test holds four distinct image responses open while metadata and
audio startup finish, and verifies that a fifth image has not started. Another test
delivers an old authentication failure after a new token has been installed: four
requests recover with one login. The cache tests cover persistence, expiry, byte/file
bounds, corruption, negative caching, entry/account isolation, exact owner binding,
fresh access checks before disk reads, source age preservation, cancellation, entry
unload/removal and disk-I/O fallback. HTTP tests retain signed-path/session checks and
exercise ETag/304, fixed thumbnail sizes and cache lifetimes bounded by access evidence
and signed-link/player-grant expiry. The browser harness checks actual DOM identity,
unchanged image `src` and request count, duplicate queue occurrences and reordering.

### Actual service and HA timing

Normal music-account access to Music 1.0.1 (0.8.41), 164 tracks, 139 albums, 128 artists,
two playlists (150 and 13 entries). Counts and ordering matched across repeated reads.
The comparison baseline is `fc81992`; the same account, service and HA were used.
"Cold" means absent from the HA cache, not a cleared NAS/OS cache. Timings below are
HTTP/WebSocket elapsed time, not browser paint or speaker audibility.

| Operation | Before | After |
| --- | ---: | ---: |
| Tracks root, cold / immediate repeat | 266 / 4.55 ms | 65 / 2.79 ms |
| Albums root, cold / repeat | 492 / 3.05 ms | 95 / 3.75 ms |
| Artists root, cold / repeat | 496 / 3.23 ms | 95 / 3.67 ms |
| Playlists root, cold / repeat | 241 / 0.44 ms | 40 / 0.69 ms |
| 150-entry playlist, cold / repeat | 507 / 6.59 ms | 108 / 4.97 ms |
| Search, cold / repeat | 253 / 0.68 ms | 49 / 0.88 ms |
| First eight cold covers | 2,001 ms | 371 ms |
| Next 20 distinct cold covers | 5,009 ms | 1,045 ms |
| All 144 distinct cover IDs, segmented cold reads | 43.01 s | 7.63 s |
| Eight covers immediately repeated | 4.08 ms | 3.29 ms |
| Eight covers after more than five minutes | 2,005 ms | 3.97 ms |
| Eight persisted covers after HA restart | Not available | 7.95 ms |
| Eight persisted covers after integration reload | Not available | 5.97 ms |

Grid requests have at most four consumers, with a 50 ms scroll pause after each eight
items; they are not a 164-request fan-out. The 20-image timings include 100 ms of
intentional pauses. The full cold total is the sum of the 8, 20 and 116-image cohorts;
it includes 800 ms of intentional pauses. Whole-grid warm/304 passes were 1.070/1.068 s,
including 850 ms of deliberate scrolling. The 144 response bodies totaled 19,240,872
bytes before and 2,009,478 bytes after resizing. This measures HA-to-client image bodies,
not total network traffic. There are 144 distinct cover IDs, not a claim of 144 distinct
pixel contents; the earlier 139-image report used a different uniqueness criterion.

The later eight-image read was 347 seconds after the main after-run. Restart and reload
left all 424 existing resource files (14,232,019 bytes) unchanged in size and mtime. An
independent runtime with per-operation request counters fetched the first eight images
in 370 ms (eight native cover GETs); hot reads took 0.23 ms and a new runtime's disk reads
took 4.44 ms, both with zero cover GETs. It read 8,458,772 native image body bytes for the
144-ID cold pass; this is application response data, not a packet capture.

With 29–34 image requests still pending, actual HA Play/Next service calls to an
explicitly authorized silent simulated output took 102/99 ms and reached the expected
queue occurrences. Album/artist navigation took 18/51 ms and a cached lyric request
0.55 ms. An independent runtime's uncached lyrics took 49 ms; its 4 KiB audio startup
took 1.53 ms while images loaded. These are bounded in-memory delivery/state checks,
not decoding or listening tests. No real-speaker control command was sent. The original
output options were restored and verified; account credentials/device IDs were unchanged.

The final source is deployed to the standalone test HA. Restart was explicitly authorized;
integration reload was checked without autoplay. No production HA/MA, NAS permissions,
music files or playlists were changed. No new background image prefetch was introduced.

### Limits

Only this service/HA version and library size were exercised live. Large libraries,
long-running disk eviction under load and other service versions remain unverified.
The one-hour resource TTL is bounded, not permanent; a changed image with the same cover
ID can remain stale until expiry. Access evidence and browser max-age remain at most
30 seconds; bytes already delivered to a client cannot be recalled. Permission and
cross-account regression tests are offline; this run did not alter real account rights.
Read-only live diagnostics/counters and their outputs remain outside the repository.

## Preserved 0.2.0 verification

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
The optional card has a local component implementation and no runtime CDN dependency.
Navigation and transport SVG paths are hand-authored in `frontend/card-icons.js`.
The project owner retains the separate brand-reference redraw; its distinction from
the independent UI icons is documented in `frontend/REFERENCE_ASSETS.md`.
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

## Native per-output playback options (2026-09-28)

Integration options → Playback compatibility now edits the existing persisted profile for one
selected FeiNiu proxy. No custom card is required. Tests verify isolation, offline editing,
cancel/removal/unloaded handling, actual HA Store reload, administrator checks, native/card
round trips and no output commands or queue/session replacement when preferences are saved.

- Target HA tests: **43 passed**; full backend: **308 passed**.
- Ruff check/format: passed; mypy: 23 source files, no issues; `git diff --check`: passed.
- Frontend unit tests: **5 passed**; synthetic browser regression: passed, including external
  profile state updates and lyric-only/partial saves that preserve unedited playback preferences.
- The existing fullscreen-exit browser assertion now waits for the fullscreenchange-driven
  control state; the first run caught a timing race, not a playback-preference failure.
- Test HA native options saved a reversible profile change and the card API restored it.
  Queue revision/identity/length, playback round and lyrics offset remained unchanged.
  This settings round trip sent no audio service commands. Deployment required one test-HA
  restart; the original queue was retained and the authorized MA3 playback resumed.

Live evidence and screenshots remain outside the repository. No credentials or media payloads
were added. No commit or push was performed for this local candidate.

## Playback-page lyrics and layout (2026-09-28)

- Frontend unit tests: **6 passed**, including inverse display-offset seek calculation,
  track bounds and invalid timestamps.
- The existing synthetic browser suite passed, extended with real wheel events and an
  8-second inactivity deadline (subsequent scrolling restarts it), keyboard time-button
  activation, paused-track seek/resume, rejected seek, stale track response, unsupported
  seek, offset persistence requests/failure/bounds and untimed lyrics.
- The layout test reproduces HA 2026.9.4's observed `ha-card` default
  `transition: 0.3s ease-out` and samples 24 frames in each direction. The card now
  disables layout interpolation; reduced-motion and 390/1280px lyric controls are covered.
- Test HA serves the exact built JavaScript bytes and reports `transition-property: none`.
  Deployment only updates the static card and its existing resource URL: no HA restart,
  integration reload or audio commands. Live UI validation covered both untimed and synced
  lyrics, a reversible `0 → +0.5 → 0` offset save, wheel browsing, right-side time buttons
  and automatic recentering. Lyric seek behavior above is synthetic, not an assertion of
  real speaker seek accuracy; no live seek command was sent in this pass.
- `git diff --check`: passed. Backend Python is unchanged by this frontend task;
  the previous 308-test backend result was not rerun or relabeled as a new run.

### Lyrics visual interaction follow-up (2026-09-28)

- Frontend unit tests: **6 passed**; the existing synthetic browser suite passed again.
- Added text-click/keyboard centering with zero audio commands, progressive edge blur,
  hover clarity, symmetric portrait lyric gutters, centered portrait title/subtitle,
  and missing-lyrics layout without timed-line padding.
- The transition regression now samples **32 frames** each way: content opacity and
  vertical translation change while card bounds, grid, artwork and text dimensions
  stay stable within each view. Rapid reversal, closing during entry, animation cleanup
  and reduced motion are also covered. No playback service is called by navigation.
- Official frontend code and its rendered page were inspected as reference only;
  the existing custom element uses its own DOM, CSS and Web Animations implementation.
- This pass changes frontend only; backend tests are not represented as newly rerun.
- Follow-up regression covers disabled/paused time-button visibility in both desktop
  sizes and a separate real `hasTouch`/mobile browser context. Tapping lyric text reveals
  only its time button and sends no audio command. Offset controls fade on lyric-region
  hover, remain keyboard reachable, and appear during touch lyric interaction.
- A live resize check caught self-sized lyric padding retaining a former taller viewport.
  Padding now derives from the allocated parent panel; browser checks assert that the
  scroll viewport fits that panel after wide/portrait resize.

## Compact dashboard card and visual editor (2026-09-28)

- Frontend unit tests: **6 passed**. Full synthetic browser suite passed, including
  compact sizing at 320/390/700 px, two independent player targets, native modal focus
  return, stable dashboard space, fullscreen exit and reconfiguration cleanup.
- Collapsed compact cards do not request library, queue pages or lyrics. Opening lyrics
  does not fetch the library; expansion and closing send no playback command.
- Editor schema/events preserve unknown YAML fields and grid options, retain legacy
  full mode, filter FeiNiu entities and update the preview without playback commands.
- In real HA 2026.9.4, the native form loaded, compact mode/title/auto theme updated the
  preview and produced matching YAML. Its library modal opened and closed successfully.
  Preview edits were cancelled instead of replacing the user's existing dashboard.
- Navigation regression covers all four library categories at wide and portrait sizes:
  opening the queue removes category highlight/aria-current; returning to the library
  restores the remembered category. Portrait queue hides the library category strip.
  Live wide and 390x844 checks confirmed the same visibility/selection behavior.
- Frontend-only deployment served exactly the local build. No HA restart, integration
  reload or live audio command was needed. Backend tests were not rerun for this task.

### Compact lyrics and background presets (2026-09-28)

- Frontend unit tests: **6 passed**; the full synthetic browser suite passed with
  simple/lyrics/auto modes, synced/plain/missing/stale lyric results, paused/offline
  states, cached expansion, fixed stage height, two independent cards and 320/390/700 px
  compact layouts. Full-page lyric and editor regressions also passed.
- The established controls remain on one row with queue/volume at the right and the
  progress bar below. Rich modes insert the lyric/artwork stage above those controls.
- Background presets are independent of content mode: omitted settings preserve the
  original background/opacity; artwork enables cover crossfades and translucent glass.
  Tests cover dark/light themes, invalid/missing artwork and redundant image requests.
- Test HA 2026.9.4 served the exact `0.3.0-compact-lyrics-2` build. Its native editor
  preview verified both background choices, the title without a note icon, restored
  controls and live synchronized lyrics in auto mode. Preview edits were cancelled;
  the existing full-page dashboard was retained.
- This deployment updated only the card resource and static JavaScript. No HA restart,
  integration reload or live audio command was sent. Backend tests were not rerun.

## Stable snapshot and asset audit (2026-09-28)

- Full backend regression: **308 passed** in the existing isolated HA test environment;
  frontend unit tests: **6 passed**; the full synthetic Edge browser suite passed.
- Ruff lint and format pass for the integration/test Python files; mypy passes 23
  source modules. The OFL font notice remains in the source and built resource.
  Provider lineage identifies the integration author's own MA provider. The owner's
  reference-based brand redraw is retained as explicitly requested; navigation and
  transport icons use independent geometry.
- Candidate upload contains no captured media, vendor application bundle, HAR, runtime
  config or private research. A pattern scan found only the deliberate credential-URL
  rejection fixture at `test.invalid`; it is not a live credential.
- The retained brand adaptation also exists in early Git history. No history rewrite or
  repository visibility change is part of this snapshot. These checks do not constitute
  a legal guarantee about visual similarity or historical redistribution.
- Subsequent overlay/auto-mode behavior changes are separate from this stable snapshot.

### Compact mode behavior and same-height lyric layout (2026-09-28)

- Frontend unit tests: **6 passed**; the complete synthetic Edge browser suite passed.
  Auto collapses without lyrics (including pending requests); explicit lyrics mode
  retains its loading/empty message without a duplicate cover. Both overlay choices,
  paused timestamp visibility, status text and symmetric pagination are covered.
- The single-line title/output header and left offset rail retain the existing **386 px**
  rich card height. The rail no longer takes a separate row from the 136 px lyric region.
  Narrow 320/390 px layouts, wrapped long lyrics, timestamp hit targets and touch offset
  controls were checked. Offset controls do not seek or start audio; timestamp controls
  retain their separate seek/play behavior.
- Test HA served the exact `0.3.0-compact-layout-1` bundle. Its native editor preview
  confirmed the single-line header and 386 px card height at 470 px width. The current
  real track had no lyrics; left-rail interactions were verified with synthetic lyrics.
  Preview changes were cancelled; no playback service call, HA restart or integration
  reload was sent. Backend tests were not rerun for these frontend changes.

### Reclaim actual header space (2026-09-28)

- `0.3.0-compact-layout-1` combined header text but still reserved a 34 px button row.
  `0.3.0-compact-layout-2` gives the header a 20 px text row, while preserving the
  expand button's 34 x 34 px hit target outside that row's flow.
- Browser geometry checks confirm the padded header shrinks from 46 to 32 px and
  the lyric viewport grows from 136 to 150 px; the total remains **386 px**. The
  artwork and lyric region move up, leaving the transport and progress bar in place.
- The complete synthetic browser suite passed, including 320/390/700 px widths,
  long wrapped lyrics, isolated left/right controls and keyboard/touch interaction.
  The expand target clears both header labels and artwork at each checked width.
- Test HA serves byte-identical `0.3.0-compact-layout-2`. Deployment sent no playback
  command and required no restart or integration reload. No backend code changed.

### Five short lines at 400 px (2026-09-28)

- `0.3.0-compact-lyrics-400` makes the rich card 400 px tall, with a 164 px lyric
  viewport. Text remains 16 px; a 24 px line height and 8 px gap fit five full
  single-line paragraphs. The simple player keeps its previous dimensions.
- Browser checks at 320/420/700 px viewport widths verify all five paragraphs fit
  completely, with the current one centred. Edge paragraphs keep visible opacity;
  blur increases on each side of the centre. Hover restores clear, bright text,
  and a small scroll changes blur continuously rather than toggling visibility.
- Wrapped long lyrics, left offset controls, right timestamp hit targets, touch,
  full-page lyrics and both background overlays pass the complete browser suite.
  Frontend unit tests: **6 passed**. Screenshots include short and wrapped examples.
- Test HA serves byte-identical deployed JavaScript. No playback command, integration
  reload or HA restart was sent. Backend tests were not rerun for this frontend change.

### Restore lyric spacing at 425 px (2026-09-28)

- `0.3.0-compact-lyrics-425` increases only the lyric region by 25 px (164 to 189 px),
  bringing the rich card to 425 px. The 16 px font is unchanged; line height returns
  from 24 to 25.6 px and the gap between lyrics returns from 8 to 12 px.
- The full browser suite passed. At 320/420/700 px widths, five complete short lines
  fit using the restored spacing. Progressive blur, hover clarity, long lines and
  separate offset/seek controls remain covered. Simple player dimensions are unchanged.
- Test HA serves the exact new build. The update sent no playback command and needed
  no integration reload or HA restart. No backend code changed.

### Clear compact lyrics and publication audit (2026-09-28)

- `0.3.0-compact-lyrics-clear` removes compact lyric blur at every scroll position,
  retaining subtle fading, 425 px total height, 16 px text and the restored spacing.
  The CSS override also avoids residual blur when returning from the full-page view.
- Six frontend unit tests and the complete synthetic browser suite pass, including
  five complete short lines, long-line wrapping, hover, touch and independent seek
  and offset controls. Full-page lyric behavior remains covered by its existing tests.
- Test HA serves the exact new build; deployment sent no audio command and required
  no restart. No backend code changed.
- Before public publication, all fetched branches and reachable history were scanned
  for credential patterns and private configuration paths. No live secrets or private
  paths were found; credential URL matches are deliberate `test.invalid` fixtures.
  Candidate assets retain their existing notices; private research and runtime files
  are outside the repository. This is a pattern scan, not a blanket security guarantee.

### Readable untimed lyrics (2026-09-28)

- Untimed lyrics now use the same paragraph typography and spacing as timed lyrics:
  16 px text in the compact card, with the existing 425 px total height. Blank lines
  and wrapped text are preserved; plain lyrics have no invented timing controls.
- Six frontend unit tests and the complete synthetic browser suite pass. A 47-line
  fixture covers mouse-wheel scrolling, keyboard Home/End, a real browser touch
  gesture, preserved scroll position during progress updates, and reset on song change.
  Compact widths of 320/420/500 px and full-page landscape/portrait are checked.
- The reported track's source was inspected read-only: its only lyric candidate
  contains 47 plain-text lines and no timestamps. Automatic following and line seeking
  cannot be provided for that source. Its text was not copied into the test fixtures.
- Test HA serves the byte-identical new build. No playback command, HA restart or
  integration reload was sent. No backend code changed.
