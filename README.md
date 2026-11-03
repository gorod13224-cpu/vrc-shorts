# VRCShorts

The existing `/shorts` random-search endpoint is retained for older worlds.
History and video sharing use the committed, append-only registry in `clips.json`.
Its initial videos come from `gorod13224-cpu/vr-shorts-data/shorts_urls.txt`.

- `GET /catalog.json` returns `{"version":1,"count":N}`. Slots are contiguous from `0` through `N-1`.
- `GET /clip/0` redirects to the same YouTube video on every request. No video is downloaded or proxied by this route.
- Missing, negative and out-of-range slots return `404`. Request parameters cannot select an arbitrary redirect target.
- Both endpoints and the legacy random redirect use `Cache-Control: no-store`.

The registry loads once per server process. These new routes do not search YouTube,
call GitHub, or make another external request for each player.

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

The stable-feed protocol allows up to 1024 reserved client URLs, so the importer
rejects a larger registry. The current Unity integration still uses the legacy
random feed; reserving stable URLs and adding history/sharing are separate client
changes. Once a world reserves the full pool, new entries within that capacity
only need a backend deployment. Importing a data-file edit is intentional; the
server does not silently remap slots from a mutable remote text file.

## Local verification

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The tests use Flask's test client and mocked YouTube search responses. They do not
download videos, make external network requests, or contact the production service.
