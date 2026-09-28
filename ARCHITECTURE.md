# Architecture

- `runtime.py`, `client.py`, `media*.py`: one account's bounded content caches, authentication,
  pagination and current-access checks. Shared by that account's outputs.
- The client limits metadata and artwork to four concurrent responses per lane, with separate
  audio-start pacing. Login/token replacement remains coordinated; a response read never holds
  the shared request-start lock.
- `artwork.py`: entry/account-specific bounded memory and atomic disk source/thumbnail resources,
  using HA's existing Pillow off the event loop. Thirty-second owner evidence is indexed separately
  from one-hour image resources. Both HTTP image routes authorize the exact owner before cache access;
  browser private max-age is capped by evidence and link expiry. No speculative background prefetch.
- `queue.py`: pure occurrence IDs, history/current/pending, ordering, repeat and revision-safe edits.
- `output.py`: stable registry binding, public HA actions/events and integration-local output lease.
- `session.py`: intent and cancellable generation, current-round identity/evidence, bounded start
  confirmation, conservative end detection. No network wait inside a queue/control lock.
- `timeline.py`: paired native anchors, monotonic display estimates and seek confirmation. It never
  decides playback or advances a queue; estimated progress is not device evidence.
- `players.py`, `storage.py`: incremental output selection, legacy identity migration and per-account
  HA Store. Deselection preserves records; account deletion removes only its own records.
- `media_player.py`: thin entity facade, just-in-time track resolution, standard services.
- `streaming.py`, `http.py`: per-output playback rounds on HA's HTTP server. Revocation cancels only
  that round's HTTP tasks. HEAD/GET/first-byte/EOF are separate observations, not acoustic claims.
- `selection.py`: native media-browser context and complete fresh queue selection.
- `websocket.py`: authenticated paged queue/edit/lyrics/preferences commands. Entity/output permission
  checks, occurrence IDs and revisions; no full queue or lyrics in Recorder/state attributes.
- `frontend.py`: registers the bundled card once in Lovelace resource storage after frontend setup.
  The bundle hash updates its cache key in place. YAML-managed resources remain user-managed.
- `frontend/feiniu-music-card.js`: dependency-free web component. HA-native browse/search/actions,
  backend-authoritative queues and local display-only timeline/lyrics animation. Built file under `www`.
  Queue occurrence IDs retain row/image nodes across refresh; browse thumbnails use the same HA route.

Compatibility is explicit and per output. A single optional Play after load does not reload a song,
uses public HA services and is cancelled by newer user intent. Weak end-state policies are opt-in.
Old events, HTTP EOF and timers do not independently confirm start/end. No core monkey-patch, vendor
SOAP, new transcoder, external service, MA dependency or native NAS write operation is introduced.
