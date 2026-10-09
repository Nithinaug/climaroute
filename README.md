# ClimaRoute

Safer routes through Indian cities in extreme weather, for people walking or riding two-wheelers.

Map apps find the fastest route. In a 40°C summer or a monsoon downpour, the fastest route can be
the one that leaves you in full sun for 40 minutes or wading through a flooded underpass.
ClimaRoute finds the route that keeps you in the shade, or out of the water, and shows what the
detour costs next to the direct route.

Covers five cities: Bengaluru, Delhi, Mumbai, Chennai and Hyderabad.

## What it does

**Summer**
- Routes through the most shade from buildings and trees at the time you leave, weighted by how
  hot it is (temperature and cloud cover). Shade is worked out for every 15 minutes of the day, so
  leaving at 16:00 gives a different route than leaving at 12:00.
- Warns when it will feel dangerously hot or the sun is fierce ("Feels like 41°C · UV 10 (very
  high) at 12:00"), using the feels-like temperature (heat plus humidity) and the UV index, and a
  warm haze builds at the edges of the map.
- **Best time to leave:** compares leaving now with every half hour over the next 3 hours and
  suggests the departure with the least sun exposure.

**Monsoon**
- Avoids low-lying streets that collect water, scaled by the rain where you're going: rain now,
  rain from the last few hours that hasn't drained yet, and rain forecast for the next hour.
  Two-wheelers avoid more streets than pedestrians, since a scooter stalls in water a person can
  wade through.
- Warns when heavier rain is on its way ("Rain expected around 17:30"), and rain falls over the
  map as heavily as the rain the route was planned for.
- **Best time to leave:** the departure in the next 3 hours with the fewest flood-risk streets.
- **Simulate heavy rain** (50 mm/h) shows what the city looks like in a downpour on a dry day.

**Everywhere**
- The safe route (green) is drawn over the direct route (red), with a comparison such as
  "2 min longer · 33% shaded vs 22%" or "avoids 14 flood-risk streets". If the direct route is
  already the best, only one route is shown.
- Place search and street names for tapped points (Amazon Location Service), "use my location",
  and a departure-time picker. Points too far from any street (a lake, a park) are rejected with
  a message.
- The map follows the sun: it turns to a night palette after sunset at your departure time, and
  the panel shows the city's temperature now or at the time you picked.
- A route set to "leave now" refreshes itself every 10 minutes while the page is open.
- **Share:** the address bar always holds the current trip (city, start, end, season, transport,
  time), so a link opens the same route for someone else.

| City | Area covered | Street segments (walk) | Buildings | Shade tiles |
|---|---|---|---|---|
| Bengaluru | 77.46–77.78 E, 12.83–13.14 N | 614k | 802k | 5,025 |
| Delhi | 77.00–77.35 E, 28.45–28.80 N | 654k | 1.39M | 4,842 |
| Mumbai | 72.77–73.00 E, 18.89–19.30 N | 154k | 527k | 2,138 |
| Chennai | 80.15–80.32 E, 12.92–13.23 N | 234k | 765k | 2,169 |
| Hyderabad | 78.30–78.60 E, 17.30–17.56 N | 545k | 1.25M | 3,861 |

## How it works

```
OFFLINE (per city, when the data is rebuilt)          ONLINE (per request)

ECS Fargate task: prepare/                            React + MapLibre (Amplify Hosting)
  streets (OpenStreetMap), buildings (Overture),           │
  building heights, elevation                              ▼
  -> street graphs + 500 m tiles ──────► S3 ◄────  API Gateway (HTTP API)
                                         ▲                 │
Step Functions                           │                 ▼
  SetSun -> Distributed Map:             │          Lambda (FastAPI): loads the street graph
  one Lambda per tile casts building ────┘          from S3, routes with Dijkstra, adds live
  shadows for every 15 min -> Merge                 weather (Open-Meteo) and place names
                                                    (Amazon Location)
```

**Shade.** For each 15-minute slot of the day we compute the sun's position (NOAA formula), cast
every building's shadow (its footprint swept away from the sun by `height / tan(elevation)`), and
measure how much of each street segment lies in shadow. Tiles are independent, so Step Functions
shades a whole city in parallel: about 5,000 tiles across 150 concurrent Lambdas. At request time
the two nearest slots are blended, so shade changes minute by minute.

**Flood risk.** From the Copernicus 30 m elevation model we fill depressions and compute flow
accumulation, then score each street by how much water collects there. Known waterlogging spots
(43 across the five cities) mark the streets around them as risky. The score is multiplied by a
rain factor; streets above a threshold are blocked.

**Weather.** Open-Meteo on a grid of points about 9 km apart over each city, fetched in one call
and cached for 10 minutes. A trip uses the wettest grid cell along its way for flood risk and the
cell at its middle for heat. Past rain counts with a 1.5-hour drainage half-life.

**Routing.** Street graphs are stored as compact numpy arrays (a whole city fits in a Lambda).
Edge costs are recomputed for every request (length × a heat or flood penalty, never below the
length) and routed with scipy's Dijkstra. A route takes about half a second.

## API

Each city has its own API (see [Deploying](#deploying)).

| Endpoint | What it returns | Data it uses |
|---|---|---|
| `GET /area` | City name, bounding box, centre, drinking-water points | S3 (city data) |
| `POST /route` | Safe and direct routes as GeoJSON, their stats, and the conditions used | S3 (street graph with shade and flood risk), Open-Meteo (weather), DynamoDB (flood reports) |
| `POST /best-time` | The route for now and every 30 min over the next 3 h, and the best one | Same as `/route`, run 7 times |
| `GET /now?at=` | Temperature (and feels-like) at the city centre now, or forecast for `at` | Open-Meteo |
| `GET /search?q=` | Place search within the city | Amazon Location (SearchText) |
| `GET /place?lat=&lon=` | Street name for a point, and whether a route can start or end there | Amazon Location (ReverseGeocode), S3 (street graph) |
| `GET /reports`, `POST /reports` | Flood reports (accepted by the API; not used by the web app) | DynamoDB |

Open-Meteo is fetched once for the whole city and cached for 10 minutes, so most requests don't
call it. Amazon Location calls are throttled and capped per day (see [Cost](#cost)).

`/route` body: `{"origin": {"lat", "lon"}, "destination": {"lat", "lon"}, "mode": "summer" |
"monsoon", "transport": "walk" | "two_wheeler", "departure_time"?, "simulate_rain_mm_per_hour"?}`.
The request and response models are defined in `api/main.py`.

## AWS services

| Service | Used for |
|---|---|
| Lambda (container images) | The API, per-tile shade computation, pipeline steps |
| API Gateway (HTTP API) | Public API, throttling |
| Step Functions (Distributed Map) | Shading every tile of a city in parallel |
| ECS Fargate | Building a city's data (too large and long-running for Lambda) |
| S3 | Raw data, shade tiles, street graphs |
| Amazon Location Service | Place search and street names |
| DynamoDB | Flood reports, daily usage counter (TTL expiry) |
| EventBridge | Keeping two API Lambdas warm, optional weekly shade refresh |
| ECR, CloudWatch, Budgets | Images, logs, spend alerts |
| Amplify Hosting | The website |

Everything is serverless, so a city costs almost nothing when nobody is using it. All
infrastructure is Terraform (`infra/`); each city is its own copy of the backend in a Terraform
workspace.

## Cost

| Action | Approx. cost |
|---|---|
| A route | $0.00002 (Lambda ~0.4 s at 3 GB, plus API Gateway) |
| Best time to leave | $0.00013 (about 7 routes) |
| A place search or tapped street name | $0.0005 (Amazon Location, $0.50 per 1,000) |
| Shading a whole city | $1.50–2 (about 5,000 tile Lambdas) |

Safeguards: each city's API is throttled to 20 requests/s, and to 5/s on `/place` and `/search`.
Amazon Location calls are capped at 2,000 per city per day (`LOCATION_DAILY_LIMIT`); past it,
search and street names pause until midnight and routing carries on. Passing
`-var budget_email=...` to Terraform sets up email alerts at $5, $15 and $30 of monthly spend.

## Project layout

```
api/        FastAPI app (Lambda): routes, weather, place search, flood reports
routing/    Street graph (numpy), edge costs, Dijkstra, route stats
prepare/    Builds a city's data: OSM extract, Overture buildings, heights, tiles, graphs
shade/      Sun position and per-tile shadow casting
monsoon/    Terrain flood model, known waterlogging spots
pipeline/   Step Functions Lambda handlers, and a local runner
shared/     Area settings, S3/local storage
frontend/   React + MapLibre web app
infra/      Terraform, per-city settings (cities/*.tfvars), deploy scripts
tests/      pytest suite with a small synthetic area
```

## Running locally

Backend (Python 3.12):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-prepare.txt uvicorn
python -m prepare.build          # downloads the default area and writes ./data
python -m pipeline.run_local     # shades every tile and builds the graphs
uvicorn api.main:app --reload    # API on http://localhost:8000
```

`AREA_NAME` and `AREA_BBOX` (`min_lon,min_lat,max_lon,max_lat`) choose the area; without
`DATA_BUCKET` everything is read from and written to `./data`.

Frontend:

```bash
cd frontend
cp .env.example .env.local       # VITE_API_URL=http://localhost:8000
npm install && npm run dev       # http://localhost:5173
```

For several cities, set `VITE_API_URLS` to a comma-separated list of API URLs.

Tests: `pytest` (backend) and `cd frontend && npm test`. Lint: `ruff check .`

## Deploying

Once per AWS account:

```bash
terraform -chdir=infra/bootstrap apply           # Terraform state bucket
```

Per city (each a Terraform workspace; `default` is Bengaluru, settings in `infra/cities/`):

```bash
export TF_WORKSPACE=delhi                        # or default, mumbai, chennai, hyderabad
infra/push_image.sh prepare                      # Fargate image for building data
TAG=$(infra/push_image.sh)                       # Lambda image
terraform -chdir=infra apply -var-file=cities/$TF_WORKSPACE.tfvars -var image_tag=$TAG
infra/run_prepare.sh                             # build the city's data (Fargate)
aws stepfunctions start-execution \
  --state-machine-arn $(terraform -chdir=infra output -raw pipeline_arn)   # shade every tile
```

After a code change, deploy every city at once (extra arguments go to `terraform apply`):

```bash
TAG=$(infra/push_image.sh) && infra/deploy_all.sh $TAG
```

The website builds on Amplify from the `main` branch. Add each city's `api_url` output to the
`VITE_API_URLS` environment variable in the Amplify console. Shade can be refreshed weekly by
setting `shade_schedule = true` (off by default to save cost).

## Limitations

- Building heights are satellite estimates (Google Open Buildings) or defaults by building type,
  not surveys. Footprint coverage depends on Overture/OSM and is thinner in some neighbourhoods.
- Tree shade only covers trees mapped in OpenStreetMap.
- Flood risk is a terrain model (30 m elevation) plus known waterlogging spots, not a
  hydrological simulation. It predicts rain-driven waterlogging; flooding with no local rain
  (lake overflow, blocked drains, dam releases, high tide in Mumbai) is only caught if it's
  reported to the API, and the web app has no report button.
- Weather is read on a ~9 km grid, so very local storms can be missed. For India, Open-Meteo's
  15-minute rain forecast is interpolated from hourly models, so storm timing is approximate.
- Shade is computed for a given date and refreshed by re-running the pipeline; within a week the
  difference is small.
- Travel times use constant speeds; no live traffic or road closures.

## Future work

- **Confirmed crowd reports:** bring back flood reporting with the safeguards map apps use: a
  street counts as flooded once two people report it nearby, others can confirm or clear it, and
  reports per device are limited.
- **Traffic as a flood signal:** roads where traffic suddenly stops during rain are often under
  water. A live traffic or incident feed would catch flooding that terrain and rain can't predict.
- **Tides and official alerts:** raise Mumbai's flood risk at high tide, and use authority sources
  (IMD warnings, city flood-monitoring systems) where they're available.
- **Per-user rate limits:** CloudFront with AWS WAF in front of the API (HTTP APIs can't use WAF
  directly).

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

Main libraries: MapLibre GL JS (BSD-3), React (MIT), Vite (MIT), Tailwind CSS (MIT), Motion (MIT),
Material Symbols (Apache-2.0), FastAPI (MIT), Mangum (MIT), NumPy and SciPy (BSD-3), Shapely
(BSD-3), OSMnx (MIT), NetworkX (BSD-3), GeoPandas (BSD-3), rasterio (BSD-3), pysheds (GPL-3.0,
offline prepare step only), pyosmium and osmium-tool (BSD-2 / GPL-3.0, prepare step only),
DuckDB (MIT), pytest (MIT), Vitest (MIT), Terraform (BUSL-1.1, used as a tool).

Built with help from AI coding tools: Claude Code (Anthropic).
