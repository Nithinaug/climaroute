# ClimaRoute: Project Brief

Context for anyone (human or AI assistant) working on this project. The
**Interfaces** section at the end is the source of truth for data formats,
function signatures and the API.

## What we're building

A web app that finds the **safest route on foot or by two-wheeler**
(scooter/motorbike) between two points for current conditions:

- **Summer mode:** prefers streets shaded by buildings, using the sun's
  position at the departure time. Shows drinking-water points.
- **Monsoon mode:** avoids low-lying streets likely to waterlog, scaled by
  current rainfall.

It always returns two routes, the safe one and the direct (shortest) one, with
a comparison, e.g. *"6 min longer, 65% shaded vs 20%"* or *"avoids 2
flood-risk streets"*.

## Hackathon context

- Online AWS environmental hackathon, track **"Heat and Water"**: *"Too much
  water, too little of it, and the heat in between."*
- 3 days, 4 people. Submission: demo video, README, write-up, architecture
  diagram, live link. No live pitch.
- **Judges may open the live link days later with nobody around.** The app
  must work standalone: preset demo trips, a built-in heavy-rain scenario,
  and clear messages for anything outside the covered area.

## Scope (deliberately small)

- **Two transport options: walking and two-wheeler.** Pedestrians and
  two-wheeler riders are the most exposed to heat and street flooding
  (a scooter stalls in ~30 cm of water). Cars and public transport are
  future scope.
- **One area: Koramangala, Bengaluru**, about 2 × 2 km around 4th to 6th Block,
  Sony World Signal and Ejipura. Chosen because:
  - it's a well-known waterlogging area, so our terrain model can be checked
    against real flood reports;
  - it mixes narrow built-up lanes and wide open roads, so shaded routes
    differ from direct ones;
  - OSM building coverage is excellent (~19k buildings traced in the wider
    area).
- **Web only** (React, mobile-friendly layout). No native app.
- Points outside the area get a "not covered yet" message. Scaling to more
  areas is future scope (the pipeline is tile-based, so it repeats per area).

## How it works

Everything heavy is **precomputed** for the area. Nothing calls OSM or does
geometry work when a user searches. The precompute has three stages:

```
1. PREPARE (laptop script)
   OSM streets + buildings, Open Buildings heights, sun positions
     -> split area into tiles -> tiles/<id>/input.json + base graphs   -> S3
   Copernicus DEM -> terrain risk per edge                             -> S3

2. SHADE (AWS Step Functions, Distributed Map)
   one Lambda per tile, all in parallel -> tiles/<id>/shade.json       -> S3

3. MERGE (Lambda)
   base graphs + all shade.json + terrain risk -> walk.pkl, two_wheeler.pkl -> S3

ONLINE (per request)
user -> frontend -> POST /route -> Lambda (loads both graphs once) -> A* -> 2 routes + stats
                                     └─ Open-Meteo rainfall (cached 30 min)
```

Step 2 is the expensive part (every building's shadow × every time slot), so
it fans out across tiles. A whole city takes about as long as one tile, which
is how the project scales: adding an area = re-running the pipeline over more
tiles. The same shade function also runs in a plain local loop over the
tiles, which is the fallback if the AWS pipeline isn't ready.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Streets, buildings, trees, drinking water | OpenStreetMap via OSMnx | Two street networks: `network_type="walk"` and `network_type="drive"` (two-wheelers follow road rules, incl. one-ways). Projected to local UTM (`estimate_utm_crs`) |
| Building heights | Google Open Buildings 2.5D Temporal, 2023 height band (4 m raster) | Free; download only the tile/clip covering the area |
| Elevation | Copernicus GLO-30 DEM (AWS Open Data) | One tile covers the area |
| Rainfall | Open-Meteo API | Live mm/hour; heavy-rain demo scenario = 50 mm/hour |
| Known flood spots, extra trees, water points | Hand-marked GeoJSON | OSM has <50 trees and few water points here |

**Building height priority:** OSM `height` → OSM `building:levels` × 3 m →
Open Buildings median height inside the footprint → default by building type
(e.g. house 9 m, apartments/commercial 12-15 m, garage/shed 3 m). Under 1% of
OSM buildings here have height or levels, so most come from Open Buildings.
Sanity-check a few known buildings before trusting it.

## Algorithms

**Shade (offline):**
- pvlib sun elevation and azimuth for each 15-minute slot over daylight hours,
  for one chosen date.
- Each building's shadow = convex hull of its footprint and the footprint
  translated away from the sun by `height / tan(elevation)`.
- Union all shadows, intersect with each street segment → fraction of each
  edge shaded, per slot.
- Slots where the sun is below 10° count as fully shaded (no meaningful heat,
  and shadows would be near-infinite).
- Work is split into square tiles. Each edge belongs to the tile containing its
  midpoint; each tile also gets the buildings in a buffer around it, because
  shadows cross tile edges (see Interfaces section 3).
- Shade and terrain risk are computed per edge geometry, so the same code
  runs on both graphs (walk and two-wheeler).

**Monsoon (offline + request time):**
- Fill depressions in the DEM with pysheds. Fill depth marks low spots.
- `terrain_risk` (0-1) per edge from fill depth; hand-marked known
  waterlogging spots are set to 1.0.
- At request time: `flood_risk = terrain_risk × rain_factor(mm/hour)`.

**Routing (request time):**
- A* with straight-line distance heuristic. This is admissible because every
  edge cost ≥ its length, so **penalties must never be negative**.
- Summer: `cost = length × (1 + ALPHA × heat_factor × (1 − shade[slot]))`
- Monsoon: `cost = length × (1 + BETA × flood_risk)`; edges above a
  threshold are blocked.
- ALPHA, BETA and the block threshold are **per transport**: two-wheelers
  get a lower ALPHA (less time exposed to sun) and a lower block threshold
  (they stall in water a pedestrian can wade through).
- Tune them so safe routes stay within ~30% of the shortest distance.
- Also return the direct route (shortest by length) for comparison.
- Nearest-node lookup with a scipy KD-tree.

## Architecture

| Layer | Tech |
|---|---|
| Frontend | React + Vite + MapLibre GL JS; Amazon Location Service for map tiles and place search; hosted on AWS Amplify |
| API | FastAPI on AWS Lambda (container image, Mangum adapter), behind API Gateway HTTP API |
| Precompute pipeline | AWS Step Functions (Distributed Map over tiles) + Lambda |
| Infrastructure as code | Terraform (S3 state backend) for all AWS resources, plus a few one-time console steps. No SAM, CDK or SDK-based deploy tooling |
| Storage | S3 for raw data, tiles and the two graph files |
| Region | ap-south-1 (Mumbai) |

All AWS work, deployment and integration are owned by one person (Nithin). No
one else writes AWS code.

Key decisions:
- The routing Lambda loads both graph files from S3 **once at cold start** and
  keeps them in memory. No database reads during routing.
- **Shade and merge code are plain Python functions** with no AWS code. Nithin
  wraps them in Lambdas and the Step Functions workflow. The same functions
  run locally in a loop, so the pipeline can be developed and tested without
  AWS.
- The tile-shade Lambda only needs shapely + numpy: sun positions are computed
  in the prepare step and passed in, so pvlib/pandas stay on the laptop.
- The Lambda image stays small: networkx, shapely, numpy, scipy only. **No
  GDAL, rasterio, osmnx, geopandas or pandas** in `routing/` or `api/`. These
  are fine in offline scripts (`shade/`, `monsoon/`).
- Files are read and written only through `shared.storage.read_bytes` /
  `write_bytes`, which uses local `data/` in development and S3 when deployed
  (switched by the `DATA_BUCKET` env var).

## Rules for working on this repo

- **This brief is the source of truth.** Match the Interfaces section's
  names, types, units and shapes exactly.
- **Keep the brief current.** Any change to an interface, dependency, file,
  env var or decision goes into this brief in the same PR as the code, so
  everyone (and every AI assistant) works from the latest version.
- **Stay in your own folder.** Don't edit other people's folders,
  `shared/`, `api/` or `infra/`.
- **No AWS code:** no `boto3`, no `s3://` paths.
- **New dependencies:** add them to the right pinned requirements file and
  note them in the brief. Keep heavy libraries out of the Lambda (see Key
  decisions).
- **Upstream not ready? Mock it.** Build against small fake inputs that match
  the contract (e.g. a 10-node test graph). Don't wait, don't invent a
  different format.
- **Simple over clever:** small plain functions, no frameworks or classes
  where a function works, no hardcoded secrets or config (env vars).
- **Tests:** pytest (Python), Vitest (frontend). Every non-trivial function
  gets at least one test.
- **Lint/format:** `ruff check . && ruff format .` before committing.
- **Small, frequent PRs**, one feature or fix each.
- Don't commit data files; `data/` is git-ignored except small test fixtures.

## Known simplifications (state these honestly in the write-up)

- Building heights are estimated (satellite-derived or by building type), not
  surveyed.
- Shade is computed for one representative date.
- Tree shade comes only from mapped and hand-marked trees.
- Flood risk is a terrain model plus known spots, not a hydrological
  simulation.
- Travel times use constant speeds; no traffic or signal delays.

## Before the hackathon (prep)

Only non-code prep unless the rules say pre-built code is allowed.

- [ ] Read the rules: pre-built code, AI-tool use and disclosure, submission
      format, repo visibility, deadlines (with timezone).
- [ ] Everyone: Python 3.12, Node 20+, Git, GitHub access, an editor. The
      prepare/ person also needs QGIS (for eyeballing data).
- [ ] Download and keep locally (public servers can be down on the day):
  - OSM extract for the area (or note the exact OSMnx query to rerun)
  - Open Buildings 2.5D heights clipped to the area (2023 band)
  - Copernicus GLO-30 DEM tile covering Koramangala
- [ ] Collect known waterlogging spots in the area from news reports (location,
      date, source link). These become `known_flood_spots.geojson` and
      evidence for the write-up.
- [ ] Sanity-check heights for 3-4 buildings someone knows.
- [ ] Pick 3-4 candidate demo trips (see Demo plan).
- [ ] Nithin: AWS account ready (done), Terraform installed (1.10+), state
      bucket created, practice deploy of FastAPI on Lambda with Terraform,
      Amazon Location API key test, Amplify test.

## Timeline and checkpoints

**Day 1 — skeleton and mocks**
- Hour 1: create repo, push this brief, agree open items, assign folders.
- Morning: Nithin deploys mock `POST /route` (returns the example JSON) and
  `GET /area`; Amplify serves the frontend shell. Everyone else builds
  against mocks and small fake inputs.
- Afternoon: Step Functions workflow deployed with a dummy tile function;
  prepare/ produces real tiles and base graphs for the area.
- **Checkpoint (evening):** frontend on the live URL calls the mock API and
  draws two lines. Tiles exist in S3.

**Day 2 — real data end to end**
- Real `compute_tile_shade` and terrain risk; pipeline (or local runner)
  produces real `walk.pkl` / `two_wheeler.pkl`.
- Real `find_routes` replaces the mock in the API.
- Validation (see Testing and validation).
- **Checkpoint (evening):** one full real trip in each mode and transport on
  the live URL. If not, freeze features and spend Day 3 fixing.

**Day 3 — polish and submit**
- Morning: preset trips, heavy-rain scenario, out-of-area and error
  messages, loading states, mobile layout check, warm-up ping.
- **Feature freeze at midday.** After that, only bug fixes.
- Afternoon: record demo video, write README and write-up, draw the
  architecture diagram, final test of the live link from a phone and a
  fresh browser, submit with time to spare.

## Development setup

- Python 3.12 virtual env per person. Three pinned requirement files at the
  repo root:
  - `requirements.txt` — runtime (Lambda): fastapi, networkx, shapely,
    numpy, scipy, httpx
  - `requirements-prepare.txt` — laptop only: `-r requirements.txt` plus
    osmnx, geopandas, rasterio, pvlib, pysheds
  - `requirements-dev.txt` — pytest, ruff
- Frontend: `cd frontend && npm install && npm run dev`.
- Local API: `uvicorn api.main:app --reload` with `DATA_BUCKET` unset (reads
  `./data/`).
- Shared test fixture: a tiny graph (~10 nodes) in `data/fixtures/` that
  matches the graph schema, so routing and API can be tested without the
  real pipeline.

## Configuration (environment variables)

| Variable | Where | Purpose |
|---|---|---|
| `DATA_BUCKET` | api, pipeline Lambdas | S3 bucket; unset = local `./data/` |
| `ALLOWED_ORIGINS` | api | CORS: Amplify URL + `http://localhost:5173` |
| `LOG_LEVEL` | api, pipeline | default `INFO` |
| `VITE_API_URL` | frontend | API base URL |
| `VITE_LOCATION_API_KEY` | frontend | Amazon Location API key (restricted, see below) |
| `VITE_AWS_REGION` | frontend | `ap-south-1` |

No secrets in the repo. The Location API key is public by nature (it ships in
the browser), so it is locked down by allowed referrers and allowed actions
instead.

## Git workflow

- `main` is protected and always deployable. Amplify auto-deploys `main`.
- Branch per change: `<name>/<short-topic>`. PR into `main`, small and often.
- PRs that change behaviour, interfaces or setup also update this brief.
- CI (GitHub Actions): `ruff check`, `pytest`, `npm test` on every PR.
- Backend deploys (after merging API, pipeline or infra changes):
  `infra/push_image.sh` (docker build + push to ECR, new image tag), then
  `terraform apply` in `infra/` with that tag.

## Frontend features

Must have:
- Full-screen MapLibre map of the area (Amazon Location map style), with the
  covered area outlined.
- Set origin and destination by place search (Amazon Location Places, biased
  to the area), tapping the map, or "use my location" (browser geolocation).
- Toggles: mode (summer / monsoon), transport (walk / two-wheeler).
- Departure time picker (default now). Rain scenario: live / heavy rain.
- Draw both routes: safe route prominent, direct route faded/dashed.
- Comparison card: e.g. "6 min longer · 65% shaded vs 20%" or "avoids 2
  flood-risk streets".
- Summer: drinking-water points layer. Monsoon: known flood spots layer.
- Preset demo trips (one tap each).
- Clear states: loading, out-of-area (show the area and offer a preset trip),
  no route, API error, rain unavailable (offer heavy-rain scenario).
- Mobile-first layout; works on a phone browser.
- Accessibility basics: keyboard reachable controls, labels, colour is never
  the only signal (route legend + text).

Nice to have: shade/flood heat-map layer on streets, street popups on tap,
PWA install.

## AWS setup (Nithin)

- **API:** FastAPI Lambda (container image, Mangum adapter, 2 GB
  memory) behind API Gateway HTTP API. CORS from `ALLOWED_ORIGINS`.
  Throttling on the stage (e.g. 20 req/s, burst 40).
- **Pipeline:** tile-shade Lambda + merge Lambda + Step Functions workflow
  (Distributed Map, `MaxConcurrency` 50). The state machine definition lives
  in `infra/pipeline.asl.json`, loaded by Terraform with `templatefile`.
- **One container image, three Lambdas:** API, tile-shade and merge share
  the image in ECR; each Lambda sets its own handler via `image_config`.
- **Terraform manages:** S3 data bucket, ECR repo, IAM roles, the three
  Lambdas, API Gateway HTTP API (CORS, throttling), Step Functions state
  machine, EventBridge warm-up schedule, CloudWatch log groups and alarm.
  State in an S3 backend with `use_lockfile = true` (Terraform 1.10+).
- **Console (one-time):** Terraform state bucket, Amplify ↔ GitHub
  connection, Amazon Location API key, budget, service quotas.
- **Script:** `infra/push_image.sh` builds the image and pushes it to ECR
  (`aws ecr get-login-password | docker login`, `docker push`). Terraform
  doesn't build images.
- **Only SDK use:** `shared/storage.py` uses boto3 (preinstalled in the
  Lambda base image) to read and write S3 at runtime. No other AWS SDK code.
- **Storage:** one S3 bucket, private, versioning on.
- **Frontend:** Amplify Hosting connected to GitHub `main`.
- **Maps:** Amazon Location Service API key allowing only map tiles and place
  search, restricted to the Amplify domain and localhost.
- **Warm-up:** EventBridge schedule pings `GET /health` every 5 minutes so
  judges rarely hit a cold start.
- **Observability:** CloudWatch logs (structured, one line per request with
  mode, transport, latency, error code); one alarm on API 5xx.
- **Cost guard:** $10 monthly budget with alerts; API throttling; no
  provisioned concurrency.

## Testing and validation

Tests (automated):
- Unit tests for every non-trivial function (pytest / Vitest).
- Routing on the fixture graph: safe route cost ≤ direct route cost under
  the safe weights; blocked edges never used; out-of-area raises.
- Shade: one building + known sun position → expected shadow side and
  approximate length.
- API: request validation, error shapes, example responses match Interfaces.
- Smoke test script against the live URL: each preset trip returns 200.

Validation (by eye, before trusting results):
- Plot shade for two slots (e.g. 09:00 and 15:00): shadows should fall
  west in the morning and east in the afternoon.
- Overlay terrain risk on the map: high-risk streets should include the
  known waterlogging spots from news reports.
- Spot-check route stats: safe route within ~30% of direct distance.

## Demo plan

- 3-4 preset trips that show clear differences, e.g.:
  1. Summer, walk, 1-3 pm: shaded inner lanes vs exposed main road.
  2. Monsoon, heavy rain, walk: detour around Sony World Signal / Ejipura.
  3. Monsoon, heavy rain, two-wheeler: route avoids a street a pedestrian
     could still use.
  4. Out-of-area point: friendly message.
- Demo video (2-3 min): problem (heat + flooding in Bengaluru, news clips or
  stats) → the app on a phone → each preset → architecture in 20 seconds →
  scaling story.

## Submission checklist

- [ ] Live link works in a fresh browser and on a phone, without anyone
      logged in.
- [ ] Demo video uploaded and link checked.
- [ ] README: what it is, live link, screenshots, how to run locally, how to
      run the pipeline, tech stack, team.
- [ ] Write-up: problem, solution, how shade and flood risk are computed,
      AWS architecture, scaling story, known simplifications, future scope.
- [ ] Architecture diagram (frontend, API, pipeline with Step Functions, S3,
      external data sources).
- [ ] Data attribution: © OpenStreetMap contributors (ODbL), Google Open
      Buildings (CC BY 4.0), Copernicus DEM, Open-Meteo.
- [ ] AI-tool use and any pre-built code disclosed if the rules ask.
- [ ] Repo visibility as the rules require.

## Risks and fallbacks

| Risk | Fallback |
|---|---|
| OSM / Overpass servers down | Data downloaded during prep and kept in S3 |
| Open Buildings heights look wrong | Default heights by building type |
| Step Functions pipeline not ready | Local runner, same functions, same output |
| Real routing not ready by Day 2 evening | Mock API stays; freeze features, fix only |
| Lambda cold start slow | Small image, graph loaded once, warm-up ping |
| Open-Meteo down | 30-min cache; heavy-rain scenario always works |
| Amazon Location key/style problem | Free OpenFreeMap style for the base map |
| Costs run away | API throttling, budget alerts, no provisioned concurrency |

## Future scope

- **Any area on demand:** compute tiles the first time someone routes there,
  cache in S3 (the tile pipeline already supports this).
- **More cities** via batch runs of the same pipeline.
- **Seasonal shade:** precompute several dates per year and use the nearest.
- **Real heat factor:** use temperature and humidity (heat index) instead of
  a constant.
- **Tree canopy** from satellite imagery instead of mapped trees.
- **Better flood data:** rainfall nowcasts, drainage data, crowd-reported
  waterlogging, municipal flood reports.
- **More transport:** cars, public transport, cycling, wheelchair-accessible
  routes.
- **Live traffic** and signal delays for two-wheelers.
- **Faster routing at city scale:** contraction hierarchies (as in OSRM).
- **Native mobile apps** (Capacitor for Android/iOS), offline maps, push
  alerts when a saved route floods.

## Interfaces

Build against these, not against each other's code. If an interface needs
to change, update it here in the same PR as the code. Items marked **TBD**
are decided at kickoff.

```
prepare -> tiles -> shade (per tile) -> merge (+ monsoon terrain) -> walk.pkl + two_wheeler.pkl -> routing/ -> api/ -> frontend/
```

### 0. Shared conventions

| Thing          | Rule                                                        |
|----------------|-------------------------------------------------------------|
| Coordinates    | API and GeoJSON: WGS84 `[lon, lat]` (GeoJSON order). Graph internals: local UTM metres. |
| Units          | metres, minutes, mm/hour. Fractions are `0.0`-`1.0`, never percent (except `shaded_pct` in API stats). |
| Timezone       | `Asia/Kolkata`. All slot maths in local time.               |
| Python         | 3.12. Pinned versions in root `requirements.txt` (networkx, shapely, numpy, scipy). The graph builder and the Lambda must use the same versions or the pickle may not load. |
| Transport      | `"walk"` \| `"two_wheeler"` everywhere (API, function args, file names). |
| Speeds         | walk 1.3 m/s, two_wheeler 5.0 m/s (~18 km/h city average). `duration_min = distance_m / speed / 60`. |
| Area           | Koramangala, Bengaluru (~2 × 2 km). Graph covers it plus a ~300 m buffer. |

### 1. Storage

All file access goes through one function. No `boto3`, no `s3://` paths, no
`open("data/...")` outside it.

```python
from shared.storage import read_bytes, write_bytes

data = read_bytes("graph/walk.pkl")        # -> bytes
write_bytes("graph/walk.pkl", payload)     # bytes -> None
```

- Env var `DATA_BUCKET` unset: reads/writes `./data/<key>` (local dev).
- `DATA_BUCKET` set: reads/writes `s3://$DATA_BUCKET/<key>` (deployed).
- Missing key raises `FileNotFoundError` in both modes.

| Key                            | Written by       | Read by        | Format |
|--------------------------------|------------------|----------------|--------|
| `raw/osm_walk.pkl`, `raw/osm_drive.pkl` | prepare | prepare | cached unprojected osmnx graphs |
| `raw/buildings.geojson`, `raw/trees.geojson`, `raw/water_points.geojson` | prepare | prepare | cached OSM features, WGS84 |
| `raw/building_heights.tif`     | prepare          | prepare (offline only) | GeoTIFF, Google Open Buildings 2.5D Temporal, 2023 height band, 2 m, clipped to area |
| `raw/dem.tif`                  | monsoon          | monsoon (offline only) | GeoTIFF, Copernicus GLO-30 clipped around the area |
| `tiles/index.json`             | prepare          | pipeline       | see section 3 |
| `tiles/<tile_id>/input.json`   | prepare          | shade          | see section 3 |
| `tiles/<tile_id>/shade.json`   | shade            | merge          | see section 3 |
| `graph/walk_base.pkl`, `graph/two_wheeler_base.pkl` | prepare | merge | section 2 schema without `shade` / `terrain_risk` |
| `terrain/terrain_risk.json`    | monsoon          | merge          | `{edge_id: float}` for every edge in both graphs |
| `graph/walk.pkl`, `graph/two_wheeler.pkl` | merge | routing | see section 2 |
| `data/water_points.geojson`    | prepare          | api            | FeatureCollection of Points, WGS84 |

Hand-marked known flood spots live in the repo at
`monsoon/known_flood_spots.geojson` (versioned, served by `GET /area`).

### 2. Graph files (`graph/walk.pkl`, `graph/two_wheeler.pkl`)

Each is `pickle.dumps(G, protocol=5)` of a `networkx.MultiDiGraph`, same
schema for both:

- `walk.pkl`: OSMnx `network_type="walk"`. Every street has an edge in both
  directions.
- `two_wheeler.pkl`: OSMnx `network_type="drive"`. One-way streets have an
  edge in one direction only.

**Graph attributes** (`G.graph`):

| Key            | Type  | Example                     |
|----------------|-------|-----------------------------|
| `crs`          | str   | `"EPSG:32643"`              |
| `area_name`    | str   | `"Koramangala, Bengaluru"`  |
| `transport`    | str   | `"walk"` or `"two_wheeler"` |
| `shade_date`   | str   | `"2026-04-15"` (peak summer; date the shade was computed for) |
| `slot_start`   | str   | `"06:00"` (local time of slot 0) |
| `slot_minutes` | int   | `15`                        |
| `slot_count`   | int   | `52` (06:00 to 18:45)       |

**Node attributes:**

| Attr       | Type  | Meaning           |
|------------|-------|-------------------|
| `x`, `y`   | float | UTM metres        |
| `lat`, `lon` | float | WGS84           |

**Edge attributes** (key `(u, v, k)`):

| Attr           | Type             | Meaning |
|----------------|------------------|---------|
| `edge_id`      | str              | Stable id, same for both directions of a street, e.g. `"osm-123456-0"` |
| `length`       | float            | metres, `> 0` |
| `geometry`     | shapely LineString | UTM, runs from `u` to `v` |
| `lonlat`       | list[[lon, lat]] | WGS84 coordinates of `geometry`, `u` to `v` (route drawing without pyproj in Lambda) |
| `name`         | str or None      | Street name, for popups/stats |
| `shade`        | list[float]      | length == `slot_count`; fraction of edge length shaded in that slot, `0.0`-`1.0` |
| `terrain_risk` | float            | `0.0`-`1.0`; known waterlogging spots = `1.0` |

`shade` comes from the tile pipeline, `terrain_risk` from monsoon/; the
merge step (section 3) attaches both. Missing values are build errors, not
defaults.

### 3. Shade pipeline (tiles)

**Tiles:** squares of `TILE_SIZE_M` = 500 m in the graph's UTM CRS. An edge
belongs to the tile containing its midpoint. Each tile's input includes every
building within `buffer_m` of the tile, where
`buffer_m = max_building_height / tan(10°)` (longest shadow we model).

`tiles/index.json`:

```json
{
  "shade_date": "2026-10-08",
  "slots": [{"slot": 0, "elevation_deg": 3.1, "azimuth_deg": 96.0}, "..."],
  "tiles": ["t_0_0", "t_0_1", "..."]
}
```

`slots` has `slot_count` entries (section 2), from pvlib, computed in prepare.

`tiles/<tile_id>/input.json`:

```json
{
  "tile_id": "t_0_0",
  "bbox": [774000.0, 1431000.0, 774500.0, 1431500.0],
  "edges": [{"edge_id": "osm-123456-0", "wkt": "LINESTRING (...)"}],
  "buildings": [{"wkt": "POLYGON ((...))", "height_m": 12.0}]
}
```

Edges from both graphs are included (deduplicated by `edge_id`). `bbox` is
`[min_x, min_y, max_x, max_y]` in UTM metres. All WKT is UTM.

`tiles/<tile_id>/shade.json`: `{edge_id: list[float]}`, one value per slot,
`0.0`-`1.0`, for every edge in that tile's input.

**Functions** (plain Python, no I/O, no AWS):

```python
# shade/
def compute_tile_shade(tile_input: dict, slots: list[dict]) -> dict[str, list[float]]
    # tile_input = parsed input.json; slots = index.json["slots"]

# shade/ (merge)
def merge_graph(
    base: nx.MultiDiGraph,
    shade_by_edge: dict[str, list[float]],
    terrain_by_edge: dict[str, float],
) -> nx.MultiDiGraph
    # raises ValueError if any edge is missing shade or terrain_risk
```

**Runners:**
- Local: `python -m pipeline.run_local` loops over `tiles/index.json`, calls
  `compute_tile_shade`, writes each `shade.json`, then merges. Uses
  `shared.storage` only (set `DATA_BUCKET` to run it against S3).
- AWS (Nithin): Step Functions Distributed Map over `tiles`, one Lambda per
  tile calling `compute_tile_shade`; `MaxConcurrency` 50; then a merge
  Lambda calling `merge_graph`. Same functions, same files.

### 4. Rain factor (monsoon/)

```python
def rain_factor(rain_mm_per_hour: float) -> float  # 0.0-1.0, non-decreasing, 0 mm -> 0.0
```

`flood_risk = terrain_risk * rain_factor(rain)` per edge, at request time.
Heavy-rain demo scenario = **50 mm/hour**. Live rain = Open-Meteo, cached 30 min
(api/ owns fetching).

### 5. Routing function (routing/)

```python
def find_routes(
    graph: nx.MultiDiGraph,               # the graph matching `transport`
    origin: tuple[float, float],          # (lat, lon)
    destination: tuple[float, float],     # (lat, lon)
    mode: Literal["summer", "monsoon"],
    transport: Literal["walk", "two_wheeler"],
    departure_time: datetime,             # timezone-aware
    rain_mm_per_hour: float,              # ignored in summer
) -> dict
```

**Costs** (all penalties non-negative so the A* straight-line heuristic stays admissible):

- summer: `length * (1 + ALPHA * heat_factor * (1 - shade[slot]))`
- monsoon: `length * (1 + BETA * flood_risk)`; edges with `flood_risk > BLOCK_THRESHOLD` are removed
- `slot = floor((departure - slot_start) / slot_minutes)`. Outside 0..slot_count-1 (night):
  shade is treated as 1.0 (no heat penalty).
- `heat_factor` = 1.0 for now. `ALPHA`, `BETA`, `BLOCK_THRESHOLD` live in `routing/config.py`
  as dicts keyed by transport (currently `BLOCK_THRESHOLD = {"walk": 0.85, "two_wheeler": 0.7}`);
  tuned so safe routes stay within ~30% of the shortest distance.
- `duration_min` uses the transport's speed (section 0).

**Returns:**

```python
{
  "safe_route":   <GeoJSON Feature dict, LineString, WGS84>,
  "direct_route": <GeoJSON Feature dict, LineString, WGS84>,   # shortest by length
  "stats": {"safe": <RouteStats>, "direct": <RouteStats>},
}
```

`RouteStats`:

| Key            | Type          | Meaning |
|----------------|---------------|---------|
| `distance_m`   | int           | |
| `duration_min` | float         | 1 decimal |
| `shaded_pct`   | int or None   | summer: length-weighted % shaded at the departure slot; monsoon: `None` |
| `risk_streets` | int or None   | monsoon: count of distinct `edge_id` with `flood_risk >= 0.5`; summer: `None` |

**Raises** (defined in `routing/errors.py`):

| Exception       | When |
|-----------------|------|
| `OutOfAreaError`| origin or destination is > 200 m from the nearest graph node |
| `NoRouteError`  | no path (e.g. every route blocked by flooding) |

Both subclass `ValueError` and carry a human-readable message.

### 6. HTTP API (api/)

Base URL from frontend env var `VITE_API_URL`. JSON only.

#### `POST /route`

Request:

```json
{
  "origin":      {"lat": 12.9352, "lon": 77.6245},
  "destination": {"lat": 12.9279, "lon": 77.6271},
  "mode": "summer",
  "transport": "walk",
  "departure_time": "2026-10-08T14:30:00+05:30",
  "rain_scenario": "live"
}
```

- `mode`: `"summer"` | `"monsoon"`
- `transport`: optional, `"walk"` (default) | `"two_wheeler"`
- `departure_time`: optional, ISO 8601 with offset; default = now.
- `rain_scenario`: optional, `"live"` (default) | `"heavy"`; ignored in summer.

Response `200`:

```json
{
  "safe_route":   {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.6245, 12.9352], "..."]}, "properties": {}},
  "direct_route": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": ["..."]}, "properties": {}},
  "stats": {
    "safe":   {"distance_m": 1420, "duration_min": 18.2, "shaded_pct": 65, "risk_streets": null},
    "direct": {"distance_m": 1180, "duration_min": 15.1, "shaded_pct": 20, "risk_streets": null}
  },
  "conditions": {"mode": "summer", "transport": "walk", "rain_mm_per_hour": 0.0, "slot_time": "14:30"}
}
```

#### `GET /area`

What the frontend needs to draw the covered area and summer extras.

```json
{
  "name": "Koramangala, Bengaluru",
  "bbox": [77.61, 12.92, 77.64, 12.94],
  "center": {"lat": 12.93, "lon": 77.625},
  "water_points": {"type": "FeatureCollection", "features": []},
  "flood_spots": {"type": "FeatureCollection", "features": []}
}
```

`bbox` is `[min_lon, min_lat, max_lon, max_lat]`.

#### `GET /health`

`{"status": "ok"}`

#### Errors

Every non-200 response uses one shape:

```json
{"error": {"code": "OUT_OF_AREA", "message": "Destination is outside the covered area (Koramangala)."}}
```

| HTTP | `code`         | When |
|------|----------------|------|
| 422  | `INVALID_REQUEST` | bad/missing fields |
| 422  | `OUT_OF_AREA`  | `OutOfAreaError` |
| 422  | `NO_ROUTE`     | `NoRouteError` |
| 429  | `THROTTLED`    | API Gateway throttling |
| 500  | `INTERNAL`     | anything else (details only in logs) |
| 503  | `RAIN_UNAVAILABLE` | Open-Meteo down with no cached value; frontend suggests the heavy-rain scenario |

`message` is safe to show to users as-is.

### 7. Repo layout and ownership

| Folder      | Owner      | Notes |
|-------------|------------|-------|
| `shared/`   | Nithin     | `storage.py` only |
| `prepare/`  | built      | laptop script: OSM, heights, sun positions, tiles, base graphs |
| `shade/`    | built      | `compute_tile_shade`, `merge_graph` |
| `pipeline/` | Nithin     | Lambda handlers + local runner wrapping shade/ |
| `monsoon/`  | built      | offline DEM work + `rain_factor` |
| `routing/`  | built      | pure functions, no I/O |
| `api/`      | Nithin     | FastAPI, Lambda image |
| `frontend/` | built      | React + Vite + MapLibre (web only) |
| `infra/`    | Nithin     | Terraform (`*.tf`), `pipeline.asl.json`, `push_image.sh` |
| `data/`     | everyone   | local dev files, git-ignored except small fixtures |

### How to run (current state)

Everything below is built and deployed; no stand-ins remain.

```bash
# 1. Prepare (laptop, ~2 min with cached downloads): OSM, heights, sun, tiles, terrain
uv pip install -r requirements-prepare.txt
python -m prepare.build
# 2. Upload to S3 and run the Step Functions shade pipeline (or: python -m pipeline.run_local)
aws s3 sync data/ s3://climaroute-data-723949188124/ --exclude "graph/walk.pkl" --exclude "graph/two_wheeler.pkl"
aws stepfunctions start-execution --state-machine-arn <pipeline_arn output>
# 3. Deploy API/pipeline code
TAG=$(infra/push_image.sh) && terraform -chdir=infra apply -var image_tag=$TAG
# 4. Frontend
cd frontend && npm install && npm run dev   # needs frontend/.env.local (see .env.example)
```

Current numbers (Koramangala): walk graph 1,682 nodes / 4,492 edges; two-wheeler
1,208 / 3,047; 17,136 buildings (17,072 heights from Open Buildings, 7 from OSM,
57 defaults) + tree canopies; 34 tiles. Routing takes 1-7 ms per request.

### Open items for kickoff

- [x] Neighborhood: Koramangala (OSM coverage checked)
- [x] `shade_date` 2026-04-15, slots 06:00-18:45 every 15 min
- [x] `risk_streets` threshold 0.5; `BLOCK_THRESHOLD` walk 0.85, two-wheeler 0.7
- [x] Two-wheeler speed 5.0 m/s; tiles 500 m; low-sun cut-off 10°; snap 200 m
- [ ] Verify `monsoon/known_flood_spots.geojson` locations and add news sources
- [ ] Hand-mark drinking-water points (OSM has none in the area)
