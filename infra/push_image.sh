#!/usr/bin/env bash
# Build the Lambda image and push it to ECR. Prints the tag to pass to terraform:
#   TAG=$(infra/push_image.sh) && terraform -chdir=infra apply -var image_tag=$TAG
set -euo pipefail
cd "$(dirname "$0")/.."

REGION=ap-south-1
REPO=$(terraform -chdir=infra output -raw ecr_repository_url)
TAG=$(git rev-parse --short HEAD 2>/dev/null || echo dev)-$(date +%Y%m%d%H%M%S)

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}" >&2
# --provenance=false: Lambda rejects multi-manifest image indexes.
docker build --platform linux/amd64 --provenance=false -t "$REPO:$TAG" . >&2
docker push "$REPO:$TAG" >&2
echo "$TAG"
