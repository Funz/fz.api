#!/usr/bin/env bash
#
# Example fz-api client using curl + jq.
#
# Demonstrates the full flow against a running server:
#   1. health check
#   2. parse an input template            (POST /parse)
#   3. launch a parametric run            (POST /runs)
#   4. poll the job until it completes    (GET  /runs/{id})
#
# Requires: curl, jq
#
# Usage:
#   ./fzapi_client.sh [BASE_URL]      # default http://localhost:8000
set -euo pipefail

BASE="${1:-http://localhost:8000}"

echo "== health =="
curl -s "$BASE/health" | jq .

echo "== parse =="
curl -s "$BASE/parse" -H 'content-type: application/json' -d '{
  "input_files": {"input.txt": "n_mol=$n_mol\nT_kelvin=@{$T_celsius + 273.15}\nV_m3=$V_L\n"},
  "model": {"varprefix": "$", "delim": "{}"}
}' | jq .

echo "== submit run =="
JOB=$(curl -s "$BASE/runs" -H 'content-type: application/json' -d '{
  "input_files": {
    "input.txt": "n_mol=$n_mol\nT_kelvin=@{$T_celsius + 273.15}\nV_m3=$V_L\n",
    "calc.sh": "#!/bin/bash\nsource \"$1\"\nawk \"BEGIN{printf \\\"pressure = %.4f\\\", $n_mol*8.314*$T_kelvin/$V_m3}\" > output.txt\n"
  },
  "input_path": "input.txt",
  "model": {
    "varprefix": "$", "delim": "{}",
    "output": {"pressure": "grep '"'"'pressure = '"'"' output.txt | awk '"'"'{print $3}'"'"'"}
  },
  "input_variables": {"n_mol": [1, 2], "T_celsius": 25, "V_L": 10},
  "calculators": ["sh://bash calc.sh"]
}' | jq -r '.job_id')
echo "job_id = $JOB"

echo "== poll =="
while true; do
  STATUS_JSON=$(curl -s "$BASE/runs/$JOB")
  STATUS=$(echo "$STATUS_JSON" | jq -r '.status')
  echo "status: $STATUS"
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo "$STATUS_JSON" | jq .
    break
  fi
  sleep 1
done
