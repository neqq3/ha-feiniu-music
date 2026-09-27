# FeiNiu Music for Home Assistant

Experimental, unofficial, read-only integration for the official fnOS music service.
It connects directly with a regular **music account and password**. Music Assistant,
fn-music-bridge, NAS administrator access and an external database are not required.

## What it provides

- Multiple account entries, each with its own session, device ID and detail cache.
- HA media browser: tracks, albums, artists and playlists, with complete native pagination.
- Artist → **Tracks** and Artist → Albums, using the verified native relationships.
- Native search within an account or media category; owner-bound artwork.
- One queue player per account, using an existing HA media player as its output.
- Album, playlist, artist and library track queues; previous/next and automatic advance.
- Shuffle, repeat off/one/all, append/play-next enqueue actions and queue clearing.
- Original audio through HA's existing HTTP server, including byte Range requests.
- Song title, artists, album and artwork through the DIDL metadata extension consumed
  by HA's built-in DLNA player. Other players may use only the standard URL/MIME result.
- Read-only `feiniu_music.get_lyrics` action returning text and timestamped lines.

The integration reads complete collections when browsed; it does not create a second
persistent music database. Its account player manages queue order and metadata, while
the selected output entity handles the speaker protocol and decoding.

## Install and configure

Developed and tested with **Home Assistant Core 2026.9.4 / Python 3.14** and
**FeiNiu Music 1.0.1 (0.8.41)**. Compatibility with older/newer releases is unverified.

1. Copy `custom_components/feiniu_music` into your HA configuration's
   `custom_components` directory and restart the **test** HA instance.
2. Settings → Devices & services → Add integration → **FeiNiu Music**.
3. Enter the official music service URL (`http(s)://HOST:PORT/music/`), music username
   and password. The root URL is also accepted. HTTPS certificates are validated.
4. Open the **FeiNiu Music — account** player, then select your independently configured
   speaker under **Source**. Selecting a speaker does not start playback.
5. Use that account player's **Browse media** button. Select a track in an album,
   playlist, artist track list or the library; playback starts there and continues
   through that list. Albums/playlists can also be played as a whole.
6. Use the FeiNiu player's previous/next buttons. Its expanded dialog also exposes
   shuffle and repeat controls, plus volume and the output's available pause/seek controls.

The original media source remains usable directly with a browser or physical player.
Direct playback on that output resolves one track; choose the **FeiNiu player** to use
its queue, shuffle and automatic advance. A search result or an explicit single-track
ID starts a one-track queue; it does not invent neighbouring search results.

Queue order is held in memory and is cleared by an integration reload or HA restart.
Output selection persists. Shuffle keeps the current song and shuffles the remaining
positions; disabling it restores original list order. Repeat-one applies to natural
completion; manual Next still moves forward. Standard `media_player.play_media` enqueue
modes `add`, `next`, `play` and `replace` are supported.

Automatic advance uses the output's actual state, media identity, duration and position.
It needs a confirmed playing state followed by idle near the track end. Early stop,
unavailability or another controller taking over disarms the queue. A device-side stop
within the final two seconds can be indistinguishable from natural completion; Stop
on the FeiNiu player explicitly disarms advance. Outputs without usable identity/end
information can still use manual Next but are not guaranteed automatic advance.
DLNA pause/seek buttons follow the device's current capabilities and may briefly be
unavailable during transport transitions. Permission or playback errors stop the queue
rather than silently skipping denied tracks or repeatedly retrying.

HA installs the declared `python-didl-lite==1.5.1` dependency. The vendored native
client uses HA's existing aiohttp installation. No rendering tool is a runtime dependency.

Use HA's **Reconfigure** action to update the existing account's password. A blank password
keeps the saved value; forms never prefill it. Changing the URL or username requires removing
the source and adding it again. Device ID stays stable during ordinary reconfiguration.
HA stores the configured credentials in its normal private configuration storage: protect
that directory and its backups.

For DLNA discovery, HA and the speaker need suitable LAN multicast connectivity. Container
host networking is useful for this deployment; a Docker bridge with only the web port
published may prevent SSDP discovery and event callbacks. DLNA is a separate HA integration,
not part of the music account or a setting copied from MA.

## Lyrics action

Call `feiniu_music.get_lyrics` with `entry_id` and `track_id`, requesting a service response.
The identifiers come from the browsed item's
`media-source://feiniu_music/ENTRY/track/TRACK` ID. The result contains `text` and
`synced_lines` (`time_ms`, `text`). HA's stock player UI does not display these lyrics
automatically; an automation or custom card can consume the action response.

## Access and playback boundaries

- Track metadata must contain the explicit integer `accessStatus == 0`. Playlist rows
  use the same strict allow condition. On the tested music version, album/artist
  relationships filter inaccessible children server-side and omit that field.
- A cover must belong to its accessible owner, including the owner's returned album/artist
  associations. Runtime checks do not scan the full music library.
- Detail cache lifetime is 30 seconds, maximum 128 entries per account. Playback rechecks
  track metadata. Already delivered metadata or artwork cannot be recalled from clients.
- Native service URLs and music cookies remain server-side. Audio uses a path-bound
  HA signed URL (two hours); browser thumbnails use signed paths (thirty minutes).
  DLNA artwork uses a short, random, two-hour grant bound to one owner and cover because
  the tested MA3 truncates long artwork URLs at 256 characters. Each entry retains at most
  128 such grants; normal owner/access checks still apply on fetch. Treat these URLs as
  temporary access grants. Removing/reloading the entry invalidates its old paths/grants.
- Music account separation is not per-HA-user access control: users allowed to use HA's
  media source can browse its configured accounts. Use a restricted music account when
  HA users should share only a subset of the NAS library.
- HTTP 200 JSON/HTML errors are rejected before audio delivery; redirects are not followed.
  Authentication is retried once before delivery, with coordinated login per server.
  Invalid credentials start HA reauthentication. An error after delivery stops the stream;
  it does not silently restart from the beginning. Update credentials/reload the integration
  if required, then select the track again.
- Audio stays in bounded streaming buffers; no music files are downloaded to disk.
  There is no transcoder. The selected browser/speaker must support the original format;
  forwarding byte ranges does not guarantee accurate time seeking on every player/codec.

FN ID, NAS OAuth, CUE split tracks, arbitrary reverse-proxy path prefixes, playlist editing,
favourites/metadata writes, MA queueing and multi-room synchronization are outside this version.
Large libraries, all formats/devices, natural long-term session expiry and cross-process
concurrent login remain unverified.

## Development

Use an isolated Linux environment with Python 3.14 and the pinned HA version. Do not point
tests at a production HA config directory.

```sh
python -m pip install -r requirements-test.txt
python -m pytest tests
ruff check .
ruff format --check .
mypy custom_components/feiniu_music
git diff --check
```

Tests use synthetic data and loopback HTTP servers. They need no NAS or real credentials.
If using HA's container image, its editable source directory may need
`MYPYPATH=/usr/src/homeassistant` for mypy. See `TESTING.md` for executed results and limits.

The client/protocol and relevant regression tests derive from the MA FeiNiu Provider;
see `NOTICE` and the included Apache-2.0 `LICENSE`. Local brand PNGs were rendered from the
existing user-reviewed SVG, not redesigned. Public redistribution permission for the brand
artwork has not been independently established; no official endorsement is claimed.
