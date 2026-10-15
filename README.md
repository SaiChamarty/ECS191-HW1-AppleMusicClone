# Sound-alike

An iPhone app that finds songs that **sound like** a song you pick, in any genre, language or region.

- **Search** the whole iTunes catalog for your country, with real artwork and 30-second previews.
- **Find Similar Songs**: get 10 songs that sound alike, ranked by how they actually sound (tempo, energy, timbre), plus catalog data.
- **Playlists**: save any song to your own playlists, Apple Music style.

The project has two parts:

```
ECS191-HW1-AppleMusicClone/
├── MyApp/                       iOS app — Swift/SwiftUI, iOS 17+
├── SoundAlike.xcodeproj   open this in Xcode
├── similarity-service/          Python server that analyzes audio and ranks similar songs
├── README.md                    this file
└── proposal.md                  the original project proposal
```

The app talks to a **hosted similarity server at <https://soundalike.junebase.com>**, so you don't need to run anything yourself. If the server can't be reached, the app falls back to a basic offline ranking.

---

## 1. Build and run (no setup needed)

**Requirements:** a Mac with **Xcode 27** and an internet connection. No accounts, keys or extra installs are needed.

1. Clone the repo:
   ```bash
   git clone https://github.com/SaiChamarty/ECS191-HW1-AppleMusicClone.git
   ```
2. Open **`SoundAlike.xcodeproj`** in Xcode.
3. In the toolbar, choose the **MyApp** scheme and an **iPhone simulator** (e.g. iPhone 18 Pro).
4. Press **Run** (▶).

Signing isn't needed for the simulator. To run on a real iPhone, select your own team under the **MyApp** target → **Signing & Capabilities**.

**To confirm it's using the server:** the gray line under each similar-song result reads like `74% match · sound 63% · 144 BPM · chill`. If it ends in "— shared feel" instead, the server wasn't reachable and you're seeing the offline fallback. Server status: <https://soundalike.junebase.com/health>.

### Try the main features

1. **Home tab:** the Popular list shows today's top songs for your region. Tap **▶** on any row to hear its 30-second preview.
2. **Search:** type any song or artist (any language). Results show artwork, **▶**, and **•••**.
3. **Find similar songs:** tap a song → **Find 10 similar songs**, or use **•••** → **Find Similar Songs**. If the song is new to the server, the first answer takes a few seconds. The list may then update itself while the footer says *"Analyzing more songs like this…"*.
4. **Playlists:** on any song, **•••** → **Add to Playlist** → **New Playlist…**, then name it. Open the **Playlists** tab to see it. Inside a playlist you can play songs, find similar songs, swipe to remove, or rename/delete it from the top-right **•••**.
5. **Long-press** any song row for the same actions.

---

## 1b. Running your own server (optional, for development)

You only need this to change the server or run it yourself. The app ships pointing at the hosted server.

### One-time setup

```bash
brew install ffmpeg uv                      # ffmpeg decodes the AAC previews
cd similarity-service
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m similarity.index --seeds seeds.csv --charts us,gb,in,br,mx,jp,ng,za,fr,de,eg,tr,id,au --discard-audio
```

The last command builds the song index: about 1,100 songs, roughly 10 minutes the first time. The virtualenv, index and caches are git-ignored.

### Start it

```bash
cd similarity-service
.venv/bin/uvicorn similarity.api:app --host 127.0.0.1 --port 8765
```

Wait for `Application startup complete`, then leave it running (**Ctrl+C** stops it). Check it with <http://127.0.0.1:8765/health>.

### Point the app at your local server

In Xcode: **Product → Scheme → Edit Scheme… → Run → Arguments → Environment Variables**, add
`SIMILARITY_SERVICE_URL` = `http://127.0.0.1:8765`. Remove it to go back to the hosted server; `Info.plist` doesn't need to change.

For a real iPhone on the same Wi-Fi, start the server with `--host 0.0.0.0` and use your Mac's local IP instead (e.g. `http://192.168.1.20:8765`).

### How the hosted server is run

`soundalike.junebase.com` runs this same service behind a **Cloudflare Tunnel**:
- uvicorn listens only on `127.0.0.1:8765` on the host.
- `cloudflared` forwards `https://soundalike.junebase.com` to it, so there are no open ports and HTTPS is provided by Cloudflare.

### Optional: Claude tags

Set `ANTHROPIC_API_KEY` before starting the server or the indexer. Songs then get a listening-context tag (e.g. `chill`, `workout`, `devotional`), and the tag score counts toward ranking. Without a key everything still works, but tags stay `unknown` and score 0.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# Rerun the same seeds + charts as the original build (one Claude call per 20 songs):
.venv/bin/python -m similarity.index --seeds seeds.csv --charts us,gb,in,br,mx,jp,ng,za,fr,de,eg,tr,id,au --discard-audio
```

Always pass the same `--seeds`/`--charts` as before. The index is rebuilt from what you pass, plus songs added by searches, so leaving `--charts` off drops the chart songs.

---

## 2. How it works

### What the user sees

| Screen | What it does |
|---|---|
| **Home** tab | Search field plus **Popular searches** (the live iTunes top-songs chart for the device's country). Each row has artwork, a ▶ preview button, and **•••** |
| Search dropdown | Live iTunes results as you type (debounced 300 ms), with suggestions, artwork, ▶ and ••• |
| **•••** menu (every song) | **Find Similar Songs** · **Add to Playlist** (New Playlist… or an existing one) · inside a playlist also **Remove from Playlist**. Long-press shows the same menu |
| Song sheet | Tap a song → "Find 10 similar songs" → ranked results, each with a "why" line, ▶ and •••. While the server is still analyzing more candidates, the footer says *"Analyzing more songs like this…"* and the list updates in place |
| **Playlists** tab | "New Playlist…" plus your playlists. Open one to play, find similar, remove (swipe), rename or delete |

The tab bar is a standard SwiftUI `TabView`, so it gets the floating Liquid Glass look automatically on iOS 26+.

### What happens when you tap "Find Similar Songs"

```
 iPhone app                                   similarity-service (Python)
 ──────────                                   ───────────────────────────
 Song from iTunes search                      POST /v1/similar
 (trackId, title, artist, country) ─────────▶  1. Find the song in the index
                                                  └ not there? download its 30 s preview,
                                                    analyze it (≈3–10 s) and add it
                                               2. Compare its sound vector with every
                                                  indexed song (≈1–3 ms)
                                               3. Score the 100 closest, return the top 10
 Show results  ◀───────────────────────────── 4. Reply right away with "expanding": true
                                               5. In the background: analyze up to 80 more
                                                  candidates (same artist, genre chart in
                                                  your country, more songs in that genre)
 Re-ask every 4 s while expanding ─────────▶   6. Rank again over the bigger index
 Update the list in place  ◀─────────────────
```

So the pool of songs grows wherever people search. The more the app is used, the better the results get.

### How "sounds alike" is measured

For every song, the server turns its 30-second preview into **78 numbers** with [librosa](https://librosa.org) (`similarity/features.py`):

| Group | What it captures |
|---|---|
| Rhythm (4) | Tempo (BPM and log₂ BPM, so half/double time count as related), beat strength, notes per second |
| Energy (12) | Loudness (average and variation) and how it rises and falls over the clip (10 points) |
| Spectral (10) | Brightness, rolloff, bandwidth, noisiness, zero-crossing rate |
| Timbre (40) | 20 MFCCs (mean and spread): the "colour" of the sound, i.e. instruments, voice, production |
| Harmony (12) | Which of the 12 pitch classes are prominent |

The numbers are standardized across the whole index, each group is weighted so the big groups don't drown out the small ones, and the vector is scaled to length 1. The audio itself is then deleted; only the numbers are kept, about 300 bytes per song.

The final score for each candidate is a weighted mix (weights live in `similarity/settings.toml`):

| Component | Weight | Meaning |
|---|---|---|
| **Sound** | 50% | Cosine similarity of the two 78-number vectors |
| **Tags** | 25% | Same Claude listening context and overlapping mood tags, scaled by Claude's confidence (0 without an API key) |
| **Metadata** | 15% | Same artist, same genre, released within ±3 years |
| **Tempo** | 10% | Close BPM, with half/double time counting as a match |

The query song itself and other versions of it (remasters, live, edits) are excluded.

### Fallbacks (the app never shows an error for this)

1. **Similarity server** (`https://soundalike.junebase.com`): the normal path.
2. **In-app Claude call**: only if a key is configured in `Secrets.xcconfig`. Development only.
3. **Offline ranking**: the 26 bundled songs, ranked by shared tags and release year.

Search falls back the same way: iTunes first, then the bundled list when offline. If a country has no iTunes chart (e.g. Korea), Popular uses the US chart.

---

## 3. Where things are

### iOS app (`MyApp/`)

| File | Role |
|---|---|
| `SoundAlikeApp.swift` | App entry point → `RootView` |
| `RootView.swift` | Tab bar (Home, Playlists) and app-wide UI: the song sheet, the "New Playlist" prompt, "Added to…" toasts, haptics |
| `ContentView.swift` | Home tab: header, search field, search dropdown, Popular list |
| `SongSheet.swift` | Bottom sheet: confirm mode ("Find 10 similar songs") and results mode |
| `PlaylistsView.swift` | Playlists tab and playlist detail screen |
| `SongActionsMenu.swift` | The **•••** menu / long-press menu used by every song row |
| `SearchViewModel.swift` | `@Observable` state for search, the sheet and loading results (MVVM) |
| `PlaylistStore.swift` | Playlists model, saved as JSON in Application Support |
| `Catalog.swift` | Song sources: `ITunesCatalog` (search and charts) and the bundled 26-song `Catalog` |
| `SimilarSongsService.swift` | Similarity providers: the server client (with live updates), the in-app Claude fallback, the offline ranking |
| `PreviewPlayer.swift` | 30-second preview playback (AVPlayer) and the shared ▶ button |
| `Song.swift` | The song model used everywhere |
| `ArtworkTile.swift` | Album art (real artwork, or a coloured letter tile as a placeholder) |
| `Theme.swift` | Colours, Archivo fonts, small shared views |
| `Info.plist` | `SimilarityServiceURL` (the hosted server), local-network permission for development, fonts |

### Similarity service (`similarity-service/`)

| Path | Role |
|---|---|
| `similarity/api.py` | HTTP API (FastAPI) — see the API section below |
| `similarity/service.py` | Query path: find or analyze the song, rank, kick off expansion |
| `similarity/expansion.py` | Background worker that grows the index around each query |
| `similarity/pipeline.py` | Shared analysis: download preview → features → tags → index |
| `similarity/features.py` | Audio features (librosa) and normalization |
| `similarity/scoring.py` | Candidate search and the weighted score |
| `similarity/tagging.py` | Claude tagging (metadata only, batches of 20, cached) |
| `similarity/rerank.py` | Optional "explain" mode: one Claude call that re-orders and explains |
| `similarity/itunes.py` | iTunes Search/Lookup/charts client: throttled, retried, cached |
| `similarity/store.py` | Index storage: SQLite (songs and tags) plus `vectors.npy` (audio numbers) |
| `similarity/index.py` | Command-line indexer (seeds and charts) |
| `similarity/query.py` | Command-line query, the same path as the API |
| `similarity/evaluate.py` | Measures ranking quality against `pairs.csv` |
| `similarity/settings.toml` | **All tunables**: score weights, tag taxonomy, expansion limits, throttling |
| `seeds.csv` / `pairs.csv` | Seed songs to index / song pairs you consider similar (for evaluation) |
| `tests/` | pytest suite (features, scoring, parsing, expansion) |
| `cache/` *(git-ignored)* | iTunes responses, features, tags, and temporary previews |
| `data/` *(git-ignored)* | The index: `index.sqlite`, `vectors.npy`, `norm_stats.json` |

---

## 4. Everyday commands

Run these from `similarity-service/`.

```bash
.venv/bin/uvicorn similarity.api:app --host 127.0.0.1 --port 8765   # run the server
.venv/bin/python -m similarity.query "Myth" "Beach House"            # try a query in Terminal
.venv/bin/python -m similarity.query "Clocks" "Coldplay" --json      # unindexed → analyzed on demand
.venv/bin/python -m similarity.index --charts us,in,jp --discard-audio  # add more songs
.venv/bin/python -m similarity.evaluate pairs.csv                    # how good is the ranking?
.venv/bin/python -m pytest                                           # run the tests
```

Indexer notes:
- **Resumable:** every stage caches per song, so reruns only do new work.
- **Rebuilds keep songs added by queries.**
- **`--discard-audio`** deletes previews once their numbers are saved.
- **First runs are slow:** the iTunes rate limit (about 20 requests/minute) dominates, at roughly 6 minutes per 100 seed songs. Charts are fast because they use one request per 150 songs.

Environment variables (all optional):

| Variable | Default | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Tagging and explain mode |
| `TAGGING_MODEL` | `claude-haiku-4-5` | Tagging (20 songs per call) |
| `RERANK_MODEL` | `claude-sonnet-5` | Explain mode (one call per query) |
| `SIMILARITY_CACHE_DIR` | `similarity-service/cache` | Cache location |
| `SIMILARITY_DATA_DIR` | `similarity-service/data` | Index location |

---

## 5. API

Base URL: `https://soundalike.junebase.com` (hosted), or `http://127.0.0.1:8765` when running locally. JSON fields use snake_case.

### `POST /v1/similar`

```json
{ "track_id": 509665325, "title": "Myth", "artist": "Beach House", "country": "us", "limit": 10, "explain": false }
```

- Send `track_id` **or** `title` (+ `artist`). An ID wins.
- `country` is the two-letter iTunes storefront.
- `limit` is 1–25.
- `explain: true` makes one Claude call that re-orders the top 15 and adds a one-line `reason` to each result.

Response:

```json
{
  "query":   { ...Track },
  "results": [
    { "track": { ...Track }, "score": 0.5247,
      "breakdown": { "audio": 0.5495, "tags": 0.0, "metadata": 1.0, "tempo": 1.0, "total": 0.5247 },
      "reason": null }
  ],
  "weights": { "audio": 0.5, "tags": 0.25, "metadata": 0.15, "tempo": 0.1 },
  "indexed_on_demand": false,
  "expanding": true,
  "index_size": 1482,
  "explained": false,
  "explain_error": null,
  "took_ms": 1.4
}
```

A `Track` has these fields: `track_id`, `title`, `artist`, `album`, `genre`, `release_date`, `year`, `duration_ms`, `preview_url`, `artwork_url`, `bpm`, `context`, `mood_tags`, `tag_confidence`.

- **`expanding: true`:** more candidates are being analyzed in the background. Ask again in a few seconds; the app does this automatically, every 4 s, up to 8 times.
- **Errors:** `422` if neither `track_id` nor `title` is given; `404` if the song isn't on iTunes or has no preview.

### Other endpoints

- `GET /health` → `{"status": "ok", "tracks": N}`
- `GET /v1/tracks/{track_id}` → `Track` or `404`

---

## 6. Known limitations

- **Results come from the index, not the whole catalog.** Comparing against ~100 million songs per query isn't possible. The index (about 1,500 songs today) grows around every search and with `--charts`, but a song nobody has searched near won't be a candidate yet.
- **Ranking quality is moderate.** On the example `pairs.csv`, the expected partner lands in the top 10 for about a third of pairs. Claude tags (once you add a key) and a bigger index are the biggest improvements available.
- **Previews are 30-second excerpts**, often the chorus, so the features describe that excerpt only.
- **Tempo detection** struggles with ambient, classical and free-tempo music.
- **Harmony features depend on key**, so two similar songs in different keys look less alike.
- **Catalog gaps:** some originals aren't sold on iTunes in a given country (e.g. Bad Bunny's "Tití Me Preguntó" in the US). Search then shows only covers.
- **iTunes rate limits** (~20 requests/min per IP) will matter at real traffic. Production should use the Apple Music API, which needs a developer token.
- **Preview terms:** Apple provides previews to promote music. Check the iTunes/Apple Music terms before shipping audio analysis of previews.
- **Playlists are stored on the device only**: no iCloud sync yet.
- **Accessibility:** the song sheet's header and "Done" button aren't exposed to VoiceOver yet.
- **No Swift unit tests**: the project has no test target. The app is verified by building and simulator runs; the server has 47 pytest tests.

---

## 7. Going to production

**Current deployment:** the service runs on a home server behind a Cloudflare Tunnel at `https://soundalike.junebase.com`, and the app points there by default. That's enough for a demo and for grading.

For a real release:

1. **Host the server somewhere reliable.** Any container host with `ffmpeg` works, still behind HTTPS. Build the index offline and ship or mount `data/`.
2. **Tighten the app's settings.** Keep `SimilarityServiceURL` on the HTTPS URL, and remove `NSAllowsLocalNetworking` from `Info.plist`; it's only for local development.
3. **Protect it.** The API is public and has no login. Add authentication, or at least a Cloudflare rate-limiting rule, because each new song costs a download and an analysis. Don't put a Cloudflare challenge (Bot Fight Mode / Under Attack) in front of it, since the app can't solve challenge pages.
4. **Keep keys server-side.** Don't ship the in-app Claude fallback's key (`Secrets.xcconfig`) in a release build.
5. **Scale up.** Numpy search is fine to ~100k songs. Beyond that, add FAISS in `scoring.rank`.

---

## 8. Design decisions (summary)

| Decision | Why |
|---|---|
| Separate Python server for audio analysis | librosa can't run on iOS, and a shared index has to live somewhere |
| iTunes Search API as the catalog | Free, no key, includes previews and artwork; the app had no catalog before |
| SQLite + a numpy matrix, held in memory | No extra services; queries take ~1–3 ms |
| No API calls on the default query path | Keeps indexed queries well under 1 second |
| The index grows around queries instead of scanning everything | Comparing against the whole catalog per query isn't feasible |
| Claude gets metadata only (never lyrics or audio) | Privacy, cost and copyright; the taxonomy is configurable |
| Model defaults `claude-haiku-4-5` / `claude-sonnet-5` | The originally requested IDs (`…-5-5`) aren't known models; both are overridable by env var |
| Port 8765 | Port 8000 was taken by another app on the dev machine |
| Standard `TabView` for the tab bar | Gets the Liquid Glass look automatically and stays compatible with iOS 17 |
