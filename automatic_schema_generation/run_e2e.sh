#!/usr/bin/env bash
# End-to-end pipeline driver for one or more apps.
#
# Runs every stage (init → ... → test_endpoints) for each app in
# sequence. The seed_template stage handles dropping the postgres
# template + bouncing uvicorn between apps, so no two-phase loop is
# needed any more.
#
# Usage:
#   ./run_e2e.sh                      # asana github todoist
#   ./run_e2e.sh asana                # one app
#   ./run_e2e.sh asana todoist        # any subset
#
# Requires the backend container to be up (``docker compose up`` from
# ops/), since seed_template + test_endpoints both shell into it.

set -euo pipefail

cd "$(dirname "$0")"

APPS=("${@:-asana github todoist}")
if [[ "${#APPS[@]}" -eq 1 && "${APPS[0]}" == "asana github todoist" ]]; then
    APPS=(asana github todoist)
fi

echo ">>> Running end-to-end pipeline for: ${APPS[*]}"
echo

for app in "${APPS[@]}"; do
    echo "================================================================"
    echo "  $app"
    echo "================================================================"
    python -m pipeline.run "apps/$app/app.yaml"
    echo
done

echo ">>> All done."
