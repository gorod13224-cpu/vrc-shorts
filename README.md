# VRCShorts

The existing `/shorts` redirect endpoint is retained for older worlds. It now
selects a video from the local committed catalog instead of searching YouTube.
History and video sharing use the committed, append-only registry in `clips.json`.
Its initial videos come from `gorod13224-cpu/vr-shorts-data/shorts_urls.txt`.

- `GET /catalog.json` returns `{"version":1,"count":N,"topics":[{"id":"q0","name":"рекомендации","clips":[0,5]}]}`. Slots are contiguous from `0` through `N-1`.
- `GET /clip/0` redirects to the same YouTube video on every request. No video is downloaded or proxied by this route.
- Missing, negative and out-of-range slots return `404`. Request parameters cannot select an arbitrary redirect target.
- Both endpoints and the legacy random redirect use `Cache-Control: no-store`.

The registry and topic definitions load once per server process. None of these
routes searches YouTube, calls GitHub, or makes an external request for each player.
An empty legacy catalog returns `503` rather than an unrelated fallback video.

Topic IDs `q0` through `q26` identify the existing 27 queries. Every topic appears
in the response, even with `clips:[]`; an empty topic has no ready videos and must
not silently fall back to all videos. An unclassified clip remains in the global
feed only. Old clients can keep reading `version` and `count` and ignore `topics`.
The registry stores optional `clip_topics` associations by YouTube ID, so growing
the catalog never renumbers a shared clip or its topic membership. Normal URL-file
imports preserve these associations and other registry metadata.

## Adding videos

After updating the data repository, import its URL file from this repository:

```sh
python import_clips.py ../data/shorts_urls.txt
```

Commit and deploy the updated `clips.json`. The import only appends previously
unseen YouTube IDs: removing, reordering or duplicating input lines does not change
an existing slot. An invalid link or a capacity overflow leaves the registry file
unchanged. Never manually reorder, remove or replace registry entries; already
shared videos and players' history refer to their numeric slot.

The stable-feed protocol allows up to 8192 reserved client URLs, so the importer
rejects a larger registry. The world must reserve matching URLs and clamp the
catalog count to its own baked capacity. New entries within that capacity only
need a backend deployment; existing history and shares retain their original IDs.

## Automatic refresh

`.github/workflows/refresh-catalog.yml` runs every 30 minutes at minutes 23 and 53 (UTC) and supports
manual **Run workflow**. It runs tests, discovers Shorts, appends at most 1000 new
IDs, and commits only `clips.json` when entries or topic memberships change. The connected Vercel
Git integration then deploys the committed registry. Actions needs to be enabled
and allowed to write repository contents; it uses its built-in, repository-scoped
`GITHUB_TOKEN`. No YouTube API key, personal access token or runtime write secret
is required. Verify the first bot commit produces a Vercel deployment for the
project's Git/plan settings.

The editable `feed_sources.json` contains the existing 27 search topics, queries per
run (up to 100), maximum additions (up to 1000), and the curated-source switch. Queries
rotate every 30 minutes. Results from successful searches are interleaved to avoid filling
the whole update with the first topic. `#shorts` is added when a query omits it.
Each topic has an explicit stable `id`, display `name` (the existing query without
the common `#shorts` prefix), and `query`. Do not renumber or reuse IDs when editing
the file. These are discovery topics, not invented categories or a free-form query
transport from the phone. Each successful search also records memberships for
matching already-registered clips. A metadata-only refresh can therefore commit
topic classifications without adding or moving any clip slots.
The owner's `vr-shorts-data/shorts_urls.txt` is also imported as a trusted curated
list, without removing or reordering old entries.

YouTube discovery accepts explicit `shortsLockupViewModel` or legacy
`reelItemRenderer` entries with validated reel-watch endpoints. A `videoRenderer`
also requires an explicit `SHORTS` overlay and a reel endpoint matching its ID.
Ordinary search IDs, a `#shorts` title and short duration alone are insufficient.
Known ad/promoted subtrees (`adSlotRenderer`, `adPlacements`, `playerAds`,
`promotedVideoRenderer` and related layouts) are excluded even when they contain
Shorts renderers. This concerns YouTube's marked platform ads; creator integrations
inside an otherwise organic clip are not removed or skipped.
The HTML structure is undocumented and may change or be blocked by YouTube. At
least one valid Shorts search response is required before writing anything;
failures are reported, malformed curated input is discarded as a whole, and an
all-failed/empty discovery run leaves the registry unchanged. No video files are
downloaded. This is ongoing discovery, not a guarantee of newest-first ordering
or availability of every video in every region.

Try a read-only refresh before publishing:

```sh
python refresh_catalog.py --dry-run
```

For initial topic population, run **Run workflow → full_scan = true**, or:

```sh
python refresh_catalog.py --full-scan --max-additions 1000
```

This explicit manual mode scans all 27 topics and caps new clips at 200. Without
that mode a refresh still scans at most 8 queries and appends at most 20 clips.
Classifications and new IDs are written atomically in the same registry document.

Without `--dry-run` the command appends validated new IDs using an atomic file
replacement. Existing slots are never recycled, including unavailable videos.
At 8192 entries it cannot add more clips, but may continue classifying existing
ones. A full catalog with no new associations reports `capacity_reached`; raising
the slot limit requires a matching client URL pool. Concurrent refresh
runs are serialized. A competing Git push causes a normal push rejection rather
than rebasing/remapping IDs or force-pushing; the next run starts from current main.
GitHub schedules are best effort, so an exact 30-minute start time is not guaranteed.
Run results and source errors are visible in the Actions job summary.

## Deployment

Vercel uses its native Flask integration and detects the `app` in `main.py`.
Flask handles the original request paths. Do not add a catch-all rewrite to
`main.py`: it replaces the path and makes the application routes return 404.

## Local verification

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests use Flask's test client and mocked YouTube search responses. They do not
download videos, make external network requests, or contact the production service.

Topic definitions may include a Russian `category` label. Edit `feed_sources.json` to organize phone categories; keep topic IDs stable. The phone supports selecting multiple tags or a whole category and combines their clips.

Production refreshes scan all configured topics every 30 minutes and append up to 1000 unique new clips per run. Discovery can return fewer fresh matches; existing slots and saved/shared IDs are preserved.

## Recommendation settings

The phone searches both categories and hashtag labels; search is local to settings. Labels retain their original spelling. Stable topic IDs are preserved when aliases are updated, and new topics append new IDs. The current config has 149 topics and the client supports 252.

`weight` (1–20, default 1) controls weighted query selection without replacement and result interleaving under the per-run cap. The five configured MGE story tags have weight 6, the twelve cat tags have weight 4. `allow_long` defaults to false and is enabled only for the five story tags: those queries omit the forced Shorts filter and accept organic watch-endpoint video renderers as well as Shorts. Promoted results remain excluded. No AI tool/tutorial hashtags were added.
