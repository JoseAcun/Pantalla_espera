#!/usr/bin/env bash
# Update the checked-out GitHub repository and restart its systemd service.
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

git pull --ff-only
.venv/bin/pip install --requirement requirements.txt
sudo systemctl restart "stream-overlay@${USER}.service"
sudo systemctl --no-pager --full status "stream-overlay@${USER}.service"
