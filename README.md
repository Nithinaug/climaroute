# ClimaRoute

Safer routes through Indian cities in extreme weather, for people walking or on two-wheelers.

- **Summer mode** finds the route with the most shade from buildings and trees for the time you
  leave, weighted by the current temperature and cloud cover.
- **Monsoon mode** avoids low-lying streets that flood, scaled by live rainfall (including rain from
  the last few hours that hasn't drained yet, and rain forecast for the next hour) and by flood
  reports sent to the API. Heavier rain due in the next 2 hours is shown as a warning.

Every answer shows the safe route next to the direct route, so you can see what the detour buys you
(e.g. "34% shaded vs 4%", "0 flood-prone streets vs 3").

Live for five cities:

| City | Area covered | Street segments (walk) | Buildings | Shade tiles |
|---|---|---|---|---|
| Bengaluru | 77.46–77.78 E, 12.83–13.14 N | 614k | 802k | 5,025 |
| Delhi | 77.00–77.35 E, 28.45–28.80 N | 654k | 1.39M | 4,842 |
| Mumbai | 72.77–73.00 E, 18.89–19.30 N | 154k | 527k | 2,138 |
| Chennai | 80.15–80.32 E, 12.92–13.23 N | 234k | 765k | 2,169 |
| Hyderabad | 78.30–78.60 E, 17.30–17.56 N | 545k | 1.25M | 3,861 |

## How it works

```
OFFLINE (weekly)                                             ONLINE (per request)

ECS Fargate: prepare/                                        React + MapLibre (Amplify)
  OSM streets + buildings, building heights,                      │ POST /route
  elevation -> street graphs + 500 m tiles  ──► S3 ◄──┐            ▼
                                                      │      API Gateway -> Lambda (FastAPI)
Step Functions (Mondays 05:00 IST)                    │        loads graphs from S3, Dijkstra on
  SetSun -> Distributed Map: one Lambda per tile ─────┘        numpy/scipy, live weather
  computes building shadows for every 15 min -> Merge          (Open-Meteo), flood reports (DynamoDB)
```

**Shade.** For each 15-minute slot of the day we compute the sun's position, cast every building's
shadow (footprint swept away from the sun by `height / tan(elevation)`), and measure how much of
each street segment is in shadow. Tiles are independent, so Step Functions shades the whole city in
parallel. At request time the two nearest slots are blended, so shade changes minute by minute.

**Flood risk.** From the Copernicus 30 m elevation model we fill depressions and compute flow
accumulation, then score each street by how much water collects there. Risk is multiplied by a rain
factor; streets above a threshold are blocked (lower for two-wheelers, which stall in water a
pedestrian can wade through). A flood report (`POST /reports`) blocks a street for an hour, then
fades out over two. The API accepts reports; the web app doesn't have a report button.

**Routing.** Street graphs are stored as compact numpy arrays. Edge costs are recomputed for every
request (length × a heat or flood penalty, never below the length) and routed with scipy's Dijkstra.

## AWS services

| Service | Used for |
|---|---|
| Lambda (container image) | API, per-tile shade computation, pipeline steps |
| API Gateway (HTTP API) | Public API with throttling |
| Step Functions (Distributed Map) | Weekly shade pipeline over all tiles |
| ECS Fargate | Building an area's data (too large and long-running for Lambda) |
| S3 | Raw data, tiles, street graphs |
| DynamoDB | Flood reports sent to the API (TTL expiry) |
| EventBridge | Weekly pipeline schedule, API warm-up |
| ECR, CloudWatch | Images, logs |
| Amplify Hosting | Frontend |

All infrastructure is Terraform (`infra/`).

## Data

| Data | Source |
|---|---|
| Streets, trees, drinking water | OpenStreetMap (Geofabrik extract) |
| Building footprints | Overture Maps (OSM + Microsoft + Google, AWS Open Data) |
| Building heights | Google Open Buildings 2.5D Temporal (2023) |
| Elevation | Copernicus GLO-30 DEM (AWS Open Data) |
| Weather | Open-Meteo (live) |

## Running locally

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-prepare.txt
python -m prepare.build          # downloads the area and writes ./data
python -m pipeline.run_local     # shades every tile and builds the graphs
uvicorn api.main:app --reload    # API on :8000

cd frontend && npm install && npm run dev   # set VITE_API_URL in frontend/.env.local
```

Tests: `pytest` and `cd frontend && npm test`.

## Deploying

```bash
terraform -chdir=infra/bootstrap apply           # once: Terraform state bucket
infra/push_image.sh prepare                      # Fargate image
TAG=$(infra/push_image.sh)                       # Lambda image
terraform -chdir=infra apply -var image_tag=$TAG -var area_name=Bengaluru \
  -var area_bbox=77.46,12.83,77.78,13.14
infra/run_prepare.sh                             # build the area's data
aws stepfunctions start-execution --state-machine-arn $(terraform -chdir=infra output -raw pipeline_arn)
```

Each city is its own copy of the backend in a Terraform workspace (`default` is Bengaluru):
`terraform -chdir=infra workspace new delhi`, then the same apply with that city's `area_name`,
`area_bbox` and `osm_extract_url` (Geofabrik zone). Add its `api_url` to the
`VITE_API_URLS` environment variable in the Amplify console (and in `frontend/.env.local`
for local builds).

## Attribution and licences

Data:

| Source | Licence |
|---|---|
| OpenStreetMap contributors (streets, trees, water points; via Geofabrik) | ODbL 1.0 |
| Overture Maps Foundation, buildings theme (includes OSM, Microsoft and Google footprints) | ODbL 1.0 |
| Google Open Buildings 2.5D Temporal (building heights) | CC BY 4.0 |
| Copernicus GLO-30 DEM, © DLR/Airbus, provided by ESA (via AWS Open Data) | Copernicus DEM licence |
| Open-Meteo weather API | CC BY 4.0 |
| Map tiles: OpenFreeMap, OpenMapTiles schema | OpenFreeMap terms; OpenMapTiles CC BY 4.0 |
| Place search and names: Amazon Location Service (HERE / Esri data) | AWS service terms |

Main libraries: MapLibre GL JS (BSD-3), React (MIT), Vite (MIT), Tailwind CSS (MIT), Motion (MIT), Material Symbols (Apache-2.0), FastAPI (MIT), Mangum (MIT),
NumPy and SciPy (BSD-3), Shapely (BSD-3), OSMnx (MIT), NetworkX (BSD-3), GeoPandas (BSD-3),
rasterio (BSD-3), pysheds (GPL-3.0, used only in the offline prepare step), pyosmium and
osmium-tool (BSD-2 / GPL-3.0, prepare step only), DuckDB (MIT), pytest (MIT), Vitest (MIT),
Terraform (BUSL-1.1, used as a tool).

Built with help from AI coding tools: Claude Code (Anthropic).

## Limitations

- Building heights are satellite estimates (Google Open Buildings) or defaults by building type,
  not surveys. Footprint coverage depends on Overture/OSM and is thinner in some neighbourhoods.
- Tree shade only covers trees mapped in OpenStreetMap.
- Flood risk is a terrain model (30 m elevation) plus known waterlogging spots and reports sent to the API,
  not a hydrological simulation. It predicts rain-driven waterlogging; flooding with no local rain
  (lake overflow, blocked drains, dam releases, high tide in Mumbai) is only caught if it's
  reported to the API, and the web app has no report button.
- Weather is read on a ~9 km grid, so very local storms can be missed. The 15-minute rain forecast
  is interpolated from hourly models for India, so the time of an incoming storm is approximate.
- Shade is computed for a given date and refreshed by re-running the pipeline (weekly schedule
  via `shade_schedule = true`); within a week the difference is small.
- Travel times use constant speeds; no live traffic or road closures.
- Flood reports are anonymous and unverified, so a false report can block a street for up to 3 h.

## Future work

- **Confirmed crowd reports:** bring the report button back with the safeguards map apps use: a
  street counts as flooded once two people report it nearby, others can confirm or clear it
  ("still flooded?"), and reports per device are limited.
- **Traffic as a flood signal:** roads where traffic suddenly stops during rain are often under
  water. A live traffic or incident feed would catch flooding that terrain and rain can't predict.
- **Tides and official alerts:** raise Mumbai's flood risk at high tide, and use authority sources
  (IMD warnings, city flood-monitoring systems) where they're available.

Design notes for contributors: [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md).
