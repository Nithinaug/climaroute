#!/usr/bin/env bash
# Applies the current Terraform and Lambda image to every city: infra/deploy_all.sh <image_tag>
# Extra arguments go to terraform apply, e.g. infra/deploy_all.sh <image_tag> -auto-approve
# Each city's settings live in cities/<workspace>.tfvars (default = Bengaluru).
set -euo pipefail
cd "$(dirname "$0")"
for f in cities/*.tfvars; do
  ws=$(basename "$f" .tfvars)
  echo "=== $ws" >&2
  TF_WORKSPACE=$ws terraform apply -var-file="$f" -var image_tag="$1" "${@:2}"
done
