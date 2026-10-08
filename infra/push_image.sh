#!/usr/bin/env bash
# Builds and pushes the Lambda image, prints its tag. `push_image.sh prepare` pushes the
# Fargate image as tag "prepare".
set -euo pipefail
cd "$(dirname "$0")/.."

REGION=ap-south-1
REPO=$(terraform -chdir=infra output -raw ecr_repository_url)
TAG=$(git rev-parse --short HEAD 2>/dev/null || echo dev)-$(date +%Y%m%d%H%M%S)
DOCKERFILE=Dockerfile
if [ "${1:-}" = prepare ]; then TAG=prepare DOCKERFILE=prepare/Dockerfile; fi

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}" >&2
# --provenance=false: Lambda rejects multi-manifest image indexes.
docker build --platform linux/amd64 --provenance=false -f "$DOCKERFILE" -t "$REPO:$TAG" . >&2
docker push "$REPO:$TAG" >&2
echo "$TAG"
