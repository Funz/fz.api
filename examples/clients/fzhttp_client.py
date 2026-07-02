#!/usr/bin/env python3
"""Example fz-http client using only the Python standard library.

Runs the full flow against a running server:
  1. health check
  2. parse an input template            (POST /parse)
  3. launch a parametric run            (POST /runs)
  4. poll the job until it completes    (GET  /runs/{id})

Usage:
    python fzhttp_client.py [BASE_URL]      # default http://localhost:8000
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

INPUT_TXT = "n_mol=$n_mol\nT_kelvin=@{$T_celsius + 273.15}\nV_m3=$V_L\n"
CALC_SH = (
    '#!/bin/bash\nsource "$1"\n'
    'awk "BEGIN{printf \\"pressure = %.4f\\", '
    '$n_mol*8.314*$T_kelvin/$V_m3}" > output.txt\n'
)
MODEL = {
    "varprefix": "$",
    "delim": "{}",
    "output": {"pressure": "grep 'pressure = ' output.txt | awk '{print $3}'"},
}


def request(method: str, path: str, body: dict | None = None) -> dict:
    """Send a JSON request and return the parsed JSON response."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:  # surface fz error details (400/404/422)
        detail = exc.read().decode()
        raise SystemExit(f"HTTP {exc.code} on {method} {path}: {detail}")


def main() -> None:
    print("== health ==")
    print(request("GET", "/health"))

    print("\n== parse ==")
    parsed = request(
        "POST",
        "/parse",
        {"input_files": {"input.txt": INPUT_TXT}, "model": MODEL},
    )
    print("variables/formulas:", list(parsed))

    print("\n== submit run ==")
    ref = request(
        "POST",
        "/runs",
        {
            "input_files": {"input.txt": INPUT_TXT, "calc.sh": CALC_SH},
            "input_path": "input.txt",
            "model": MODEL,
            "input_variables": {"n_mol": [1, 2], "T_celsius": 25, "V_L": 10},
            "calculators": ["sh://bash calc.sh"],
        },
    )
    job_id = ref["job_id"]
    print("job_id =", job_id)

    print("\n== poll ==")
    while True:
        status = request("GET", f"/runs/{job_id}")
        p = status["progress"]
        print(f"status: {status['status']} ({p['completed']}/{p['total']})")
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(1)

    if status["status"] == "failed":
        raise SystemExit(f"run failed: {status['error']}")

    print("\n== results ==")
    for row in status["result"]:
        print(f"  n_mol={row['n_mol']} -> pressure={row['pressure']}")


if __name__ == "__main__":
    main()
