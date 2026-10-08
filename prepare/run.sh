#!/usr/bin/env bash
# Needs AREA_NAME, AREA_BBOX, DATA_BUCKET, OSM_EXTRACT_URL (set in the task definition).
set -euo pipefail
export OSM_REGION_PBF=/tmp/region.osm.pbf
curl -fsSL -o "$OSM_REGION_PBF" "$OSM_EXTRACT_URL"
python -m prepare.build
