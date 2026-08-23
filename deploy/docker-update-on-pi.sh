#!/usr/bin/env bash
# Pull the latest approved Git commit, rebuild, and recreate the container.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

git pull --ff-only
docker compose up --build --detach --remove-orphans
docker compose ps
