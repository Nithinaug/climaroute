# ClimaRoute: Project Brief

Context for anyone working on this project. The
**Interfaces** section at the end is the source of truth for data formats,
function signatures and the API.

## What we're building

A web app that finds the **safest route on foot or by two-wheeler**
(scooter/motorbike) between two points for current conditions:

- **Summer mode:** prefers streets shaded by buildings, using the sun's
  position at the departure time and the live heat. Suggests the best time to
  leave in the next 3 hours. Shows drinking-water points.
- **Monsoon mode:** avoids low-lying streets likely to waterlog, scaled by
  live rainfall per part of the city, known flood spots and crowd reports.
  A "simulate heavy rain" switch demonstrates it on a dry day.
- **Five cities:** Bengaluru, Delhi, Mumbai, Chennai, Hyderabad, chosen from a
  dropdown; place search and street names via Amazon Location Service.

It always returns two routes, the safe one and the direct (shortest) one, with
a comparison, e.g. *"6 min longer, 65% shaded vs 20%"* or *"avoids 2
flood-risk streets"*.

## Hackathon context

- Online AWS environmental hackathon, track **"Heat and Water"**: *"Too much
  water, too little of it, and the heat in between."*
- 3 days (deadline 11 Oct 2026, 23:59), 4 people. Submission: demo video,
  README, write-up, architecture diagram, live link. No live pitch.
- The live stacks stay up for about a week after the deadline for judging,
  then are destroyed (`terraform destroy` per workspace).
- **Judges may open the live link days later with nobody around.** The app
  must work standalone, on live data only (no demo scenarios),
  and clear messages for anything outside the covered area.

## Scope

- **Two transport options: walking and two-wheeler.** Pedestrians and
  two-wheeler riders are the most exposed to heat and street flooding
  (a scooter stalls in ~30 cm of water). Cars and public transport are
  future scope.
- **Deployed cities: Bengaluru, Delhi, Mumbai, Chennai, Hyderabad.** Each city is its
  own copy of the backend (Terraform workspace: `default` = Bengaluru, then `delhi`,
  `mumbai`, `chennai`, `hyderabad`), built from the same code and images with
  `AREA_NAME` / `AREA_BBOX` / `OSM_EXTRACT_URL`. The UTM zone is derived from the
  longitude (43N for most, 44N for Chennai and Hyderabad). The frontend lists every
  city's API in `VITE_API_URLS` and switches between them (city kept in the URL hash).

  | Workspace | `area_bbox` | Geofabrik extract |
  |---|---|---|
  | default (Bengaluru) | 77.46,12.83,77.78,13.14 | southern-zone |
  | delhi | 77.0,28.45,77.35,28.8 | northern-zone |
  | mumbai | 72.77,18.89,73.0,19.3 | western-zone |
  | chennai | 80.15,12.92,80.32,13.23 | southern-zone |
  | hyderabad | 78.3,17.3,78.6,17.56 | southern-zone |

  Run at most 2 cities' shade pipelines at once (2 × `MaxConcurrency` 150 within the
  account's 400 Lambda limit); weekly runs are staggered 30 min apart from 05:00 IST.
- **First area (development): Koramangala, Bengaluru**, about 2 × 2 km around 4th to 6th Block,
  Sony World Signal and Ejipura. Chosen because:
  - it's a well-known waterlogging area, so our terrain model can be checked
    against real flood reports;
  - it mixes narrow built-up lanes and wide open roads, so shaded routes
    differ from direct ones;
  - OSM building coverage is excellent (~19k buildings traced in the wider
    area).
- **Web only** (React, mobile-friendly layout). No native app.
- The map is locked to the selected city; taps outside it are ignored and
  "Use my location" outside the city gets a clear message.

## How it works

Everything heavy is **precomputed** for the area. Nothing calls OSM or does
geometry work when a user searches. The precompute has three stages:

```
1. PREPARE (ECS Fargate task, or laptop for a small area)
   Geofabrik OSM extract clipped with osmium (Overpass for small areas),
   OSM streets + buildings, Open Buildings heights, sun positions
     -> split area into tiles -> tiles/<id>/input.json + base graphs   -> S3
   Copernicus DEM -> terrain risk per edge                             -> S3

2. SHADE (AWS Step Functions, Distributed Map)
   one Lambda per tile, all in parallel -> tiles/<id>/shade.json       -> S3

3. MERGE (Lambda)
   base graphs + all shade.json + terrain risk -> walk.npz, two_wheeler.npz -> S3

ONLINE (per request)
user -> frontend -> POST /route -> Lambda (loads both graphs once) -> Dijkstra -> 2 routes + stats
                                     └─ Open-Meteo weather (cached 10 min)
```

Step 2 is the expensive part (every building's shadow × every time slot), so
it fans out across tiles. A whole city takes about as long as one tile, which
is how the project scales: adding an area = re-running the pipeline over more
tiles. The same shade function also runs in a plain local loop over the
tiles, which is the fallback if the AWS pipeline isn't ready.

## Data sources

| Data | Source | Notes |
|---|---|---|
| Building footprints | Overture Maps buildings (AWS Open Data, us-west-2), read with DuckDB for the city bbox; cached at `raw/<bbox>/buildings_overture.pkl` | Includes OSM, Microsoft and Google footprints (4x OSM alone in Delhi) |
| Streets, trees, drinking water | OpenStreetMap via OSMnx | Two street networks: `network_type="walk"` and `network_type="drive"` (two-wheelers follow road rules, incl. one-ways). Projected to local UTM (`estimate_utm_crs`) |
| Building heights | Google Open Buildings 2.5D Temporal, 2023 height band (4 m raster) | Free; download only the tile/clip covering the area |
| Elevation | Copernicus GLO-30 DEM (AWS Open Data) | One tile covers the area |
| Weather | Open-Meteo API | Live rain (mm/hour, past 6 h), temperature and cloud cover forecast |
| Known flood spots, extra trees, water points | Hand-marked GeoJSON | OSM has <50 trees and few water points here |

**Building height priority:** OSM `height` → OSM `building:levels` × 3 m →
Open Buildings median height inside the footprint → default by building type
(e.g. house 9 m, apartments/commercial 12-15 m, garage/shed 3 m). Under 1% of
OSM buildings here have height or levels, so most come from Open Buildings.
Sanity-check a few known buildings before trusting it.

## Algorithms

**Shade (offline):**
- Sun elevation and azimuth for each 15-minute slot over daylight hours
  (built-in NOAA formula in `shade/sun.py`, within 0.5° of pvlib), for the
  current date; recomputed weekly.
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
- Dijkstra (`scipy.sparse.csgraph.dijkstra`) on a compact numpy graph
  (`routing.Net`); per-request edge costs are computed for all edges at once
  with numpy. **Penalties must never be negative** (Dijkstra needs costs ≥ 0,
  and every cost stays ≥ its length).
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
| Frontend | React + Vite + MapLibre GL JS, OpenFreeMap base map; hosted on AWS Amplify |
| Place search and names | Amazon Location Service (Places: SearchText, ReverseGeocode), called from the API Lambda |
| API | FastAPI on AWS Lambda (container image, Mangum adapter), behind API Gateway HTTP API |
| Precompute pipeline | AWS Step Functions (Distributed Map over tiles) + Lambda |
| Area build (prepare) | ECS Fargate task (4 vCPU / 30 GB), started on demand; too long and memory-heavy for Lambda |
| Infrastructure as code | Terraform (S3 state backend) for all AWS resources, plus a few one-time console steps. No SAM, CDK or SDK-based deploy tooling |
| Storage | S3 (one bucket per city) for raw data, tiles and the two graph files; DynamoDB for flood reports |
| Per city | Each city is a separate Terraform workspace with its own copy of every resource; one shared ECR repository |
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
  in the prepare step and passed in, so heavy libraries stay in the prepare image.
- The Lambda image stays small: shapely, numpy, scipy only (networkx is used
  only offline and in tests). **No
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
  everyone works from the latest version.
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
- Shade is recomputed weekly for the current sun path, not daily.
- Tree shade comes only from mapped and hand-marked trees.
- Flood risk is a terrain model plus known spots and crowd reports, not a
  hydrological simulation.
- Building coverage depends on Overture/OSM footprints (thinner in some areas;
  Bengaluru still uses OSM-only footprints).
- Travel times use constant speeds; no traffic or signal delays.

## Development setup

- Python 3.12 virtual env per person. Three pinned requirement files at the
  repo root:
  - `requirements.txt` — runtime (Lambda): fastapi, mangum, shapely,
    numpy, scipy
  - `requirements-dev.txt` — tests: `-r requirements.txt` plus httpx,
    networkx, pytest, ruff
  - `requirements-prepare.txt` — prepare image / laptop: `-r requirements-dev.txt`
    plus osmnx, geopandas, rasterio, pysheds, osmium, duckdb (and the `osmium-tool` CLI
    in the image)
- Frontend: `cd frontend && npm install && npm run dev`.
- Local API: `uvicorn api.main:app --reload` with `DATA_BUCKET` unset (reads
  `./data/`).
- Shared test fixture: a tiny graph (~10 nodes) in `data/fixtures/` that
  matches the graph schema, so routing and API can be tested without the
  real pipeline.

## Configuration (environment variables)

| Variable | Where | Purpose |
|---|---|---|
| `DATA_BUCKET` | api, pipeline Lambdas, prepare task | S3 bucket; unset = local `./data/` |
| `AREA_NAME`, `AREA_BBOX` | api, pipeline, prepare | the city (from `infra/cities/<workspace>.tfvars`) |
| `REPORTS_TABLE` | api | DynamoDB table for flood reports; unset = in memory |
| `OSM_EXTRACT_URL` | prepare task | Geofabrik regional extract to clip the city from |
| `ALLOWED_ORIGINS` | api | CORS: Amplify URL + `http://localhost:5173` |
| `LOG_LEVEL` | api, pipeline | default `INFO` |
| `VITE_API_URLS` | frontend | comma-separated API URL of every city (Amplify console environment variable; `frontend/.env.local` locally) |

No secrets in the repo. Amazon Location is called from the API Lambda with its
IAM role, so no map key reaches the browser.

## Git workflow

- `main` is protected and always deployable. Amplify auto-deploys `main`.
- Branch per change: `<name>/<short-topic>`. PR into `main`, small and often.
- PRs that change behaviour, interfaces or setup also update this brief.
- CI (GitHub Actions): `ruff check`, `pytest`, `npm test` on every PR.
- Backend deploys (after merging API, pipeline or infra changes):
  `infra/push_image.sh` (docker build + push to ECR, new image tag), then
  `terraform apply` in `infra/` with that tag.

## Frontend features

Built:
- Full-screen MapLibre map (OpenFreeMap style), locked to the selected city.
- City dropdown (city kept in the URL hash, e.g. `#delhi`).
- From/To by place search (Amazon Location, limited to the city), tapping the
  map (box fills with the street name), or "Use my location".
- Toggles: mode (summer / monsoon), transport (walk / two-wheeler).
- "Leaving at" time picker, default "Now", any minute.
- Monsoon: "Simulate heavy rain (50 mm/h)" checkbox; result says live or simulated.
- Routes: safe route solid green, direct route solid red; comparison card,
  e.g. "2 min longer · 33% shaded vs 22%" or "avoids 14 flood-risk streets".
  Durations over an hour show as "1 h 33 min".
- Summer: "Best time to leave?" (next 3 h) with "Use this time".
- Report flooding (amber dots that fade over 3 h), Use my location, Clear,
  below the results.
- Summer: drinking-water points at street zoom. Monsoon: known flood spots layer.
- Clear states: loading, no route, API error, rain unavailable.
- Mobile layout (bottom sheet); keyboard-reachable controls with labels.

Not built (nice to have): shade/flood heat-map layer on streets, street popups,
PWA install.

## AWS setup (Nithin)

- **API:** FastAPI Lambda (container image, Mangum adapter, 2 GB
  memory) behind API Gateway HTTP API. CORS from `ALLOWED_ORIGINS`.
  Throttling on the stage (e.g. 20 req/s, burst 40).
- **Pipeline:** tile-shade Lambda + merge Lambda + Step Functions workflow
  (Distributed Map, `MaxConcurrency` 150). The state machine definition lives
  in `infra/pipeline.asl.json`, loaded by Terraform with `templatefile`.
- **One container image, four Lambdas per city:** API, set-sun, tile-shade and merge share
  the image in ECR; each Lambda sets its own handler via `image_config`.
- **Terraform manages (per city workspace):** S3 data bucket, IAM roles, the four
  Lambdas, DynamoDB reports table, ECS cluster + Fargate prepare task, API Gateway HTTP API (CORS, throttling), Step Functions state
  machine, EventBridge warm-up schedule, CloudWatch log groups and alarm.
  State in an S3 backend with `use_lockfile = true` (Terraform 1.10+).
- **Console (one-time):** Terraform state bucket, Amplify ↔ GitHub
  connection, service quotas (Lambda concurrency 400).
- **Script:** `infra/push_image.sh` builds the image and pushes it to ECR
  (`aws ecr get-login-password | docker login`, `docker push`). Terraform
  doesn't build images.
- **Only SDK use:** `shared/storage.py` uses boto3 (preinstalled in the
  Lambda base image) to read and write S3 at runtime. No other AWS SDK code.
- **Storage:** one S3 bucket per city, private, versioning on.
- **Frontend:** Amplify Hosting connected to GitHub `main`.
- **Maps:** OpenFreeMap base map; Amazon Location Places (search, reverse
  geocode) through the API Lambda's IAM role.
- **Warm-up:** EventBridge schedule invokes the API Lambda every 5 minutes
  (preloading graphs) so judges rarely hit a cold start.
- **Weekly shade:** EventBridge runs each city's pipeline on Mondays, staggered
  05:00-07:00 IST (the sun moves <0.5° a day). Run it by hand any time.
  `SetSun` rewrites `tiles/index.json` for today's sun (built-in solar position,
  no pvlib), then tiles are shaded in parallel and merged (~45 s for Koramangala; Bengaluru's 5,025 tiles
  took 29 min at `MaxConcurrency` 50, ~10 min at 150, then merge ~3.5 min).
  The API re-reads graphs every 10 minutes. Manual run for any date:
  `aws stepfunctions start-execution --state-machine-arn <arn> --input '{"date":"2026-04-15"}'`.
- **Flood reports:** DynamoDB on-demand table with TTL.
- **Observability:** CloudWatch logs (structured, one line per request with
  mode, transport, latency, error code); one alarm on API 5xx.
- **Cost guard:** API throttling, weekly (not daily) shade, no provisioned
  concurrency; a city shade run is ~$1-2.5. Stacks are destroyed after judging.

## Testing and validation

Tests (automated):
- Unit tests for every non-trivial function (pytest / Vitest).
- Routing on the fixture graph: safe route cost ≤ direct route cost under
  the safe weights; blocked edges never used; out-of-area raises.
- Shade: one building + known sun position → expected shadow side and
  approximate length.
- API: request validation, error shapes, example responses match Interfaces.
- Smoke test against the live URL: a few known trips return 200.

Validation (by eye, before trusting results):
- Plot shade for two slots (e.g. 09:00 and 15:00): shadows should fall
  west in the morning and east in the afternoon.
- Overlay terrain risk on the map: high-risk streets should include the
  known waterlogging spots from news reports.
- Spot-check route stats: safe route within ~30% of direct distance.

## Demo plan

- Delhi, summer, walk, leaving 16:00: shaded route vs exposed main road, then
  "Best time to leave" picks a later, shadier departure.
- Mumbai or Chennai, monsoon: tick "Simulate heavy rain"; the safe route avoids
  flood-risk streets the direct route crosses. Mention live rain is used otherwise.
- Report flooding on the route and show it re-route at once.
- City dropdown: all five cities, place search and street names.
- 20 s of architecture: Fargate prepare, Step Functions fanning out to 150
  Lambdas per city, Terraform workspace per city, serverless cost.

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
| Open-Meteo down | 10-min cache (stale value reused); summer falls back to a default heat weight |
| No rain during judging | "Simulate heavy rain" switch in monsoon mode |
| Lambda cold start slow | Warm-up ping every 5 min preloads the graphs |
| A shade tile runs out of memory | shade-tile Lambda 2048 MB; a failed run leaves the previous graphs live |
| Lambda concurrency (400) | MaxConcurrency 150 per city; at most 2 cities' pipelines at once; staggered weekly schedule |
| Costs run away | API throttling (20 rps), weekly not daily shade, destroy after judging |

## Future scope

- **Any area on demand:** compute tiles the first time someone routes there,
  cache in S3 (the tile pipeline already supports this).
- **More cities:** one more workspace + tfvars file each (about an hour of AWS time).
- **Heat index:** add humidity to the live temperature/cloud heat factor.
- **Tree canopy** from satellite imagery instead of mapped trees.
- **Better flood data:** rainfall nowcasts, drainage data, municipal flood
  reports; report moderation (confirmations, abuse limits).
- **More transport:** cars, public transport, cycling, wheelchair-accessible
  routes.
- **Live traffic** and signal delays for two-wheelers.
- **Faster routing at city scale:** contraction hierarchies (as in OSRM).
- **Native mobile apps**, offline maps, push
  alerts when a saved route floods.

## Interfaces

Build against these, not against each other's code. If an interface needs
to change, update it here in the same PR as the code.

```
prepare -> tiles -> shade (per tile) -> merge (+ monsoon terrain) -> walk.npz + two_wheeler.npz -> routing/ -> api/ -> frontend/
```

### 0. Shared conventions

| Thing          | Rule                                                        |
|----------------|-------------------------------------------------------------|
| Coordinates    | API and GeoJSON: WGS84 `[lon, lat]` (GeoJSON order). Graph internals: local UTM metres. |
| Units          | metres, minutes, mm/hour. Fractions are `0.0`-`1.0`, never percent (except `shaded_pct` in API stats). |
| Timezone       | `Asia/Kolkata`. All slot maths in local time.               |
| Python         | 3.12. Pinned versions in root `requirements.txt` (shapely, numpy, scipy). |
| Transport      | `"walk"` \| `"two_wheeler"` everywhere (API, function args, file names). |
| Speeds         | walk 1.3 m/s, two_wheeler 5.0 m/s (~18 km/h city average). `duration_min = distance_m / speed / 60`. |
| Area           | Env `AREA_NAME` / `AREA_BBOX` (Terraform vars `area_name` / `area_bbox`, passed to the Lambdas and the prepare task). Deployed: Bengaluru. Graph covers the bbox plus a ~400 m buffer. Raw caches live under `raw/<bbox>/`. |

### 1. Storage

All file access goes through one function. No `boto3`, no `s3://` paths, no
`open("data/...")` outside it.

```python
from shared.storage import read_bytes, write_bytes

data = read_bytes("graph/walk.npz")        # -> bytes
write_bytes("graph/walk.npz", payload)     # bytes -> None
```

- Env var `DATA_BUCKET` unset: reads/writes `./data/<key>` (local dev).
- `DATA_BUCKET` set: reads/writes `s3://$DATA_BUCKET/<key>` (deployed).
- Missing key raises `FileNotFoundError` in both modes.

| Key                            | Written by       | Read by        | Format |
|--------------------------------|------------------|----------------|--------|
| `raw/<bbox>/osm_walk.pkl`, `raw/<bbox>/osm_drive.pkl` (Overpass mode only) | prepare | prepare | cached unprojected osmnx graphs |
| `raw/<bbox>/buildings.geojson`, `trees.geojson`, `water_points.geojson` (Overpass mode only) | prepare | prepare | cached OSM features, WGS84 |
| `raw/<bbox>/building_heights.tif` | prepare          | prepare (offline only) | GeoTIFF, Google Open Buildings 2.5D Temporal, 2023 height band, 2 m, clipped to area |
| `raw/<bbox>/dem.tif` | monsoon          | monsoon (offline only) | GeoTIFF, Copernicus GLO-30 clipped around the area |
| `tiles/index.json`             | prepare          | pipeline       | see section 3 |
| `tiles/<tile_id>/input.json`   | prepare          | shade          | see section 3 |
| `tiles/<tile_id>/shade.json`   | shade            | merge          | see section 3 |
| `graph/walk_base.npz`, `graph/two_wheeler_base.npz` | prepare | merge | section 2 `Net` with empty `shade` / `terrain` |
| `terrain/terrain_risk.json`    | monsoon          | merge          | `{edge_id: float}` for every edge in both graphs |
| `graph/walk.npz`, `graph/two_wheeler.npz` | merge | api, routing | see section 2 |
| `data/water_points.geojson`    | prepare          | api            | FeatureCollection of Points, WGS84 |

Known flood spots (43 across the 5 cities, positions from Amazon Location search; add news
links in `source`) are applied when the API loads a graph (streets within 60 m get terrain
risk 1.0), so adding a spot needs only a redeploy. They live in the repo at
`monsoon/known_flood_spots.geojson` (versioned, served by `GET /area`).

### 2. Graph files (`graph/walk.npz`, `graph/two_wheeler.npz`)

Each is a `routing.Net`, saved with `Net.to_bytes()` (numpy `savez_compressed`,
no pickle) and loaded with `Net.from_bytes()`. Compact numpy arrays instead of
networkx so a whole city fits in the Lambda (Koramangala walk: 170 KB, loads in
3 ms, routes in ~1 ms).

- `walk`: OSMnx `network_type="walk"`. Every street has an edge in both directions.
- `two_wheeler`: OSMnx `network_type="drive"`. One-way streets have an edge in
  one direction only.

prepare/ builds a networkx `MultiDiGraph` (node attrs `x`, `y`, `lat`, `lon`;
edge attrs `edge_id`, `length`, `geometry`, `lonlat`, `name`) and converts it
with `Net.from_graph(g)`. Parallel edges between the same two nodes keep only
the shortest.

**`meta`** (dict, stored as JSON):

| Key            | Type  | Example                     |
|----------------|-------|-----------------------------|
| `crs`          | str   | `"EPSG:32643"`              |
| `area_name`    | str   | `"Bengaluru"`               |
| `transport`    | str   | `"walk"` or `"two_wheeler"` |
| `shade_date`   | str   | `"2026-10-08"` (date the shade was computed for; set by each pipeline run, weekly) |
| `slot_start`   | str   | `"06:00"` (local time of slot 0) |
| `slot_minutes` | int   | `15`                        |
| `slot_count`   | int   | `52` (06:00 to 18:45)       |

**Arrays.** A *street* is one OSM segment (one `edge_id`), shared by both
travel directions. An *edge* is one direction of travel.

| Field          | Shape / dtype          | Meaning |
|----------------|------------------------|---------|
| `node_lat`, `node_lon` | `[N]` float64  | WGS84 |
| `src`, `dst`   | `[E]` int32            | node indices of each directed edge |
| `length`       | `[E]` float32          | metres, `> 0` |
| `street`       | `[E]` int32            | index into the street arrays |
| `reverse`      | `[E]` bool             | edge runs against the street's coordinate order |
| `street_id`    | `[S]` str              | stable `edge_id`, e.g. `"osm-123456-789-0"` |
| `street_name`  | `[S]` str              | `""` if unnamed |
| `coords`, `coord_start` | `[C,2]` float64, `[S+1]` int64 | street `s` is `coords[coord_start[s]:coord_start[s+1]]` as `[lon, lat]` |
| `shade`        | `[S, slot_count]` uint8 | fraction shaded × 255 per slot (empty in `*_base.npz`) |
| `terrain`      | `[S]` float32          | terrain risk `0.0`-`1.0`; known waterlogging spots = `1.0` (empty in `*_base.npz`) |

`shade` comes from the tile pipeline, `terrain` from monsoon/; the merge step
(section 3) fills both. Missing values are build errors, not defaults.

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

`slots` has `slot_count` entries (section 2), from `shade/sun.py`, rewritten for
the current date by the pipeline's SetSun step.

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
    base: Net,
    shade_by_edge: dict[str, list[float]],
    terrain_by_edge: dict[str, float],
) -> Net
    # raises ValueError if any street is missing shade or terrain_risk
```

**Runners:**
- Local: `python -m pipeline.run_local` loops over `tiles/index.json`, calls
  `compute_tile_shade`, writes each `shade.json`, then merges. Uses
  `shared.storage` only (set `DATA_BUCKET` to run it against S3).
- AWS (Nithin): Step Functions Distributed Map over `tiles`, one Lambda per
  tile calling `compute_tile_shade`; `MaxConcurrency` 150; then a merge
  Lambda calling `merge_graph`. Same functions, same files.

### 4. Rain factor (monsoon/)

```python
def rain_factor(rain_mm_per_hour: float) -> float  # 0.0-1.0, non-decreasing, 0 mm -> 0.0
```

`flood_risk = terrain_risk * rain_factor(rain)` per edge, at request time.
Live rain = Open-Meteo on a ~9 km grid over the city (16 points for Bengaluru; each trip uses
the worst rain among cells its box touches, and the nearest cell for heat), cached 10 min
(api/weather.py): the larger of the current rate and each of the past 6 hours'
rain decayed with a 1.5 h drainage half-life, so risk lingers after a storm.

### 5. Routing function (routing/)

```python
def find_routes(
    net: Net,                             # the graph matching `transport`
    origin: tuple[float, float],          # (lat, lon)
    destination: tuple[float, float],     # (lat, lon)
    mode: Literal["summer", "monsoon"],
    transport: Literal["walk", "two_wheeler"],
    departure_time: datetime,             # timezone-aware
    rain_mm_per_hour: float,              # ignored in summer
    heat_factor: float = 1.0,             # routing.heat_factor(temp_c, cloud_pct); summer only
    reports: dict[str, float] | None = None,  # {edge_id: strength 0-1} from flood reports
) -> dict

def nearest_edge(net, lat, lon) -> str   # street for a flood report; OutOfAreaError if > 60 m
def heat_factor(temperature_c, cloud_cover_pct) -> float  # 0 at <=26 C, 1 at 34 C, max 1.5; x(1-0.8*cloud)
```

Flood reports: strength 1.0 blocks the edge; lower strengths multiply its cost by
`1 + REPORT_PENALTY * strength` (applied on top of either mode).

**Costs** (all penalties non-negative; Dijkstra needs costs ≥ 0):

- summer: `length * (1 + ALPHA * heat_factor * (1 - shade[slot]))`
- monsoon: `length * (1 + BETA * flood_risk)`; edges with `flood_risk > BLOCK_THRESHOLD` are blocked (cost `1e9`; a route that needs one raises `NoRouteError`)
- `slot = (departure - slot_start) / slot_minutes` as a fraction; shade is blended
  linearly between the two nearest slots (16:07 = 53% of 16:00 + 47% of 16:15), so it
  changes minute by minute. Outside the slot window (night): shade is 1.0 (no heat penalty).
- `heat_factor` comes from the forecast temperature and cloud cover at the departure
  hour. `ALPHA`, `BETA`, `BLOCK_THRESHOLD` live in `routing/config.py`
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
| `reported_streets` | int       | distinct `edge_id`s on the route with an active flood report |

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
  "simulate_rain_mm_per_hour": 50,       // optional, monsoon demo: overrides live rain (0-200)
}
```

- `mode`: `"summer"` | `"monsoon"`
- `transport`: optional, `"walk"` (default) | `"two_wheeler"`
- `departure_time`: optional, ISO 8601 with offset; default = now.
- All weather is live (Open-Meteo); there are no demo scenarios.

Response `200`:

```json
{
  "safe_route":   {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[77.6245, 12.9352], "..."]}, "properties": {}},
  "direct_route": {"type": "Feature", "geometry": {"type": "LineString", "coordinates": ["..."]}, "properties": {}},
  "stats": {
    "safe":   {"distance_m": 1420, "duration_min": 18.2, "shaded_pct": 65, "risk_streets": null},
    "direct": {"distance_m": 1180, "duration_min": 15.1, "shaded_pct": 20, "risk_streets": null}
  },
  "conditions": {"mode": "summer", "transport": "walk", "rain_mm_per_hour": 0.0, "slot_time": "14:30",
                 "temperature_c": 31.0, "cloud_cover_pct": 20.0, "heat_factor": 0.53,
                 "shade_date": "2026-10-08", "active_reports": 0}
}
```

#### `GET /area`

What the frontend needs to draw the covered area and summer extras.

```json
{
  "name": "Bengaluru",
  "bbox": [77.61, 12.92, 77.64, 12.94],
  "center": {"lat": 12.93, "lon": 77.625},
  "water_points": {"type": "FeatureCollection", "features": []},
  "flood_spots": {"type": "FeatureCollection", "features": []}
}
```

`bbox` is `[min_lon, min_lat, max_lon, max_lat]`.

#### `GET /reports`, `POST /reports`

Crowd flood reports (DynamoDB `climaroute-flood-reports`, TTL on `expires_at`).
`POST {"lat": .., "lon": ..}` snaps to the nearest street (≤ 60 m) and returns
`201` with a GeoJSON Point Feature. `GET` returns active reports as a
FeatureCollection with `properties.age_min` and `properties.strength`. A report
blocks its street for 1 h, then fades to nothing at 3 h.

#### `POST /best-time`

Same body as `/route`. Runs the summer route for now and every 30 min for 3 h and returns
`{"options": [{"time", "shaded_pct", "temperature_c", "heat_factor", "exposure"}], "best": <option>}`,
where `exposure = (1 - shaded) x heat_factor` (lower is better). ~7 route runs, so ~2-3 s.

#### `GET /search?q=<text>`

Place search via Amazon Location Service (Places API `SearchText`, called from the
API Lambda so no map key reaches the browser), restricted to the area's bbox.
`q` is 2-100 characters. Returns `{"results": [{"name": str, "lat": float, "lon": float}]}`
(up to 5). `503 SEARCH_UNAVAILABLE` if the service can't be reached (always locally,
where there is no boto3).

#### `GET /health`

`{"status": "ok"}`

#### Errors

Every non-200 response uses one shape:

```json
{"error": {"code": "OUT_OF_AREA", "message": "Destination is outside the covered area (Bengaluru)."}}
```

| HTTP | `code`         | When |
|------|----------------|------|
| 422  | `INVALID_REQUEST` | bad/missing fields |
| 422  | `OUT_OF_AREA`  | `OutOfAreaError` |
| 422  | `NO_ROUTE`     | `NoRouteError` |
| 429  | `THROTTLED`    | API Gateway throttling |
| 500  | `INTERNAL`     | anything else (details only in logs) |
| 422  | `NOT_ON_STREET` | flood report more than 60 m from any street |
| 503  | `RAIN_UNAVAILABLE` | Open-Meteo down with no cached value (summer falls back to heat factor 1.0 instead) |

`message` is safe to show to users as-is.

### 7. Repo layout and ownership

| Folder      | Owner      | Notes |
|-------------|------------|-------|
| `shared/`   | Nithin     | `storage.py` only |
| `prepare/`  | built      | Fargate task (or laptop): OSM via pbf/Overpass, heights, sun positions, tiles, base graphs |
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
# 1. Images (Lambda + Fargate prepare)
infra/push_image.sh prepare
TAG=$(infra/push_image.sh)
# 2. Infrastructure, with the area to cover (always pass the area vars)
terraform -chdir=infra apply -var image_tag=$TAG -var area_name=Bengaluru \
  -var area_bbox=77.46,12.83,77.78,13.14
# 3. Build the area's data on Fargate (~25 min for Bengaluru; logs: /ecs/climaroute-prepare)
infra/run_prepare.sh
# 4. Shade + merge (also runs automatically on Mondays 05:00 IST)
aws stepfunctions start-execution --state-machine-arn $(terraform -chdir=infra output -raw pipeline_arn)
# Another city: same steps in its own workspace, e.g.
#   terraform -chdir=infra workspace new delhi    (select back with: workspace select default)
#   apply with -var area_name=Delhi -var area_bbox=77.0,28.45,77.35,28.8 \
#     -var osm_extract_url=https://download.geofabrik.de/asia/india/northern-zone-latest.osm.pbf
#   then add its api_url to VITE_API_URLS in the Amplify console (and frontend/.env.local)
# 5. Frontend
cd frontend && npm install && npm run dev   # needs frontend/.env.local (see .env.example)
```

Small area on a laptop instead (Overpass, no Fargate): `AREA_BBOX=... python -m prepare.build`
then `python -m pipeline.run_local`. With `OSM_REGION_PBF=<file.osm.pbf>` set, prepare
reads a local extract instead of Overpass (needs the `osmium` CLI).

Current numbers (buildings from Overture, except Bengaluru which still uses OSM):

| City | Walk edges | Buildings | Tiles | Streets with terrain risk |
|---|---|---|---|---|
| Bengaluru | 614,194 | 801,624 | 5,025 | 324,256 |
| Delhi | 653,658 | 1,393,454 | 4,842 | 338,292 |
| Mumbai | 153,690 | 527,461 | 2,138 | 83,082 |
| Chennai | 233,758 | 764,566 | 2,169 | 119,988 |
| Hyderabad | 544,742 | 1,250,471 | 3,861 | 278,772 |

A cross-city route takes ~0.4 s end to end. Prepare (Fargate, 4 vCPU / 30 GB)
25-45 min per city; a shade run ~$1-2.5 of Lambda time (shade-tile Lambda 2048 MB).

### Settled values and open items

- [x] Cities: Bengaluru, Delhi, Mumbai, Chennai, Hyderabad (bboxes in `infra/cities/`)
- [x] Slots 06:00-18:45 every 15 min; shade recomputed weekly for the current date
- [x] `risk_streets` threshold 0.5; `BLOCK_THRESHOLD` walk 0.85, two-wheeler 0.7
- [x] Two-wheeler speed 5.0 m/s; tiles 500 m; low-sun cut-off 10°; snap 200 m
- [ ] Add news source links to `monsoon/known_flood_spots.geojson` (43 spots, `source` is null)
- [ ] Optional: rebuild Bengaluru with Overture footprints
