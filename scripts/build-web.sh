#!/usr/bin/env bash
# Build the SvelteKit front end into web/build (served by the FastAPI app).
set -euo pipefail
cd "$(dirname "$0")/../web"
[ -d node_modules ] || npm install --no-audit --no-fund
npm run build
echo "built web/build ($(du -sh build | cut -f1))"
