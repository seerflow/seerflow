#!/usr/bin/env bash
# Build the React dashboard into src/seerflow/web/dist/ (S-057).
set -euo pipefail
cd "$(dirname "$0")"
npm ci --prefix frontend
npm run build --prefix frontend
du -sh src/seerflow/web/dist
