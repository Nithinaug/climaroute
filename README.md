# ClimaRoute

Safer routes through Indian cities in extreme weather, for people walking or on two-wheelers.

- **Summer mode** finds the route with the most shade from buildings and trees for the time you
  leave, weighted by the current temperature and cloud cover.
- **Monsoon mode** avoids low-lying streets that flood, scaled by live rainfall (including rain from
  the last few hours that hasn't drained yet) and by flooding reported by other users.

Every answer shows the safe route next to the direct route, so you can see what the detour buys you
(e.g. "34% shaded vs 4%", "0 flood-prone streets vs 3").

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
pedestrian can wade through). A user report blocks a street for an hour, then fades out over two.

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
| DynamoDB | Crowd flood reports (TTL expiry) |
| EventBridge | Weekly pipeline schedule, API warm-up |
| ECR, CloudWatch | Images, logs |
| Amplify Hosting | Frontend |

All infrastructure is Terraform (`infra/`).

## Data

| Data | Source |
|---|---|
| Streets, buildings, trees | OpenStreetMap (Geofabrik extract) |
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

Design notes for contributors: [docs/PROJECT_BRIEF.md](docs/PROJECT_BRIEF.md).
