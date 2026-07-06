# fz-api

An HTTP API for [**fz**](https://github.com/funz/fz) (`funz-fz`), the parametric
scientific computing framework. It exposes fz's public functions
(`fzi`/`fzc`/`fzo`/`fzr`/`fzl`/`fzd` + model install) over a FastAPI service, so
you can parse inputs, compile parameterized files, run parametric studies, and
drive design-of-experiments from any HTTP client.

This is a **thin adapter** over the public `fz` Python API — it depends on
`funz-fz` and only calls its exported surface, so it stays decoupled and easy to
maintain alongside fz.

## Contents

- [Install](#install)
- [Run](#run)
- [Quickstart](#quickstart)
- [How files are passed](#how-files-are-passed)
- [Endpoints](#endpoints)
- [Endpoint reference](#endpoint-reference)
- [Result serialization](#result-serialization)
- [Error handling](#error-handling)
- [Client examples](#client-examples)
- [Architecture &amp; design notes](#architecture--design-notes)
- [Tests](#tests)

## Install

```bash
pip install funz-api          # pulls funz-fz, fastapi, uvicorn
# or, for local development against a checkout:
pip install -e ".[dev]"
```

## Run

```bash
fz-api --host 0.0.0.0 --port 8000        # start the server
# interactive OpenAPI docs at http://localhost:8000/docs
```

Or with uvicorn directly:

```bash
uvicorn fz_api.app:app --reload
```

CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address (`0.0.0.0` to expose externally) |
| `--port` | `8000` | Bind port |
| `--reload` | off | Auto-reload on code changes (development) |
| `--workers` | `1` | Number of worker processes |
| `--version` | – | Print the fz-api version and exit |

## Quickstart

Once the server is running, confirm it is healthy and see the fz version it
wraps:

```console
$ curl -s localhost:8000/health
{"status":"ok","fz_version":"1.1"}
```

Then open http://localhost:8000/docs for interactive, self-documenting
request forms for every endpoint.

## How files are passed

HTTP clients don't share the server's filesystem, so file-based operations send
their input files **inline** as a JSON mapping of relative path → text content.
fz inputs are text templates (e.g. `x = $x`), which makes this natural. Each
request runs in an isolated temporary directory that is cleaned up afterwards.

```jsonc
{
  "input_files": { "input.txt": "x = $x\ny = $y\n" },
  "model": { "varprefix": "$", "delim": "{}" }   // alias string also accepted
}
```

**Choosing the input path.** fz needs to know which uploaded file is the input
template. The `input_path` field (a relative path within `input_files`)
controls this:

- omit it with a **single** uploaded file → that file is used;
- omit it with **multiple** files → the workspace directory is used;
- set it explicitly (e.g. `"input_path": "input.txt"`) to pick one file when you
  upload several.

**Auxiliary files.** You can upload more than just the input template — for
example a calculator script referenced by `sh://bash calc.sh`. All uploaded
files land in the same workspace, and jobs run with that workspace as their
working directory, so relative references resolve correctly.

**Path safety.** Keys in `input_files` must be relative paths inside the
workspace; absolute paths or `..` escapes are rejected with `400`.

## Endpoints

| Method & path            | fz function | Description |
|--------------------------|-------------|-------------|
| `GET  /health`           | –           | Liveness + fz version |
| `GET  /models`           | `fzl`       | Installed models (`?pattern=&check=`) |
| `GET  /calculators`      | `fzl`       | Available calculators (`?pattern=&check=`) |
| `POST /parse`            | `fzi`       | Find variables/formulas in inputs |
| `POST /compile`          | `fzc`       | Substitute values; returns compiled file tree |
| `POST /read`             | `fzo`       | Parse output files → records |
| `POST /runs`             | `fzr`       | Launch a parametric run (async job) |
| `GET  /runs/{id}`        | –           | Run job status/progress/result |
| `POST /designs`          | `fzd`       | Launch a design-of-experiments (async job) |
| `GET  /designs/{id}`     | –           | Design job status/progress/result |
| `POST /models/install`   | `install`   | Install a model |
| `DELETE /models/{name}`  | `uninstall` | Uninstall a model |

Fast operations (`parse`, `compile`, `read`, listings) are synchronous.
Long-running `fzr`/`fzd` return a **job id** (`202 Accepted`); poll the job
endpoint for `status` (`pending`→`running`→`completed`/`failed`), live
`progress`, and the final `result`. See the
[Endpoint reference](#endpoint-reference) below for a worked example of each.

## Endpoint reference

Every example below assumes the server is at `localhost:8000`. Responses shown
are real output from the API.

### `GET /health`

```console
$ curl -s localhost:8000/health
{"status":"ok","fz_version":"1.1"}
```

### `GET /models` &nbsp;·&nbsp; `GET /calculators`

List installed models / available calculators (`fzl`). Optional query params:
`pattern` (glob/regex, default `*`) and `check` (`true` runs a validation probe).

```console
$ curl -s localhost:8000/calculators
{"sh://": {"supports_models": "all", "check_status": "not_checked"}}
```

### `POST /parse` (fzi)

Find the variables, formulas and static objects in the input files. Values are
`null` because parsing does not assign them.

```bash
curl -s localhost:8000/parse -H 'content-type: application/json' -d '{
  "input_files": {"input.txt": "x = $x\ny = @{x*2}\n"},
  "model": {"varprefix": "$", "delim": "{}"}
}'
```

```json
{"x": null, "x*2": null}
```

### `POST /compile` (fzc)

Substitute variable values into the input template(s) and return the compiled
file tree as `{relative_path: content}`. Lists produce a factorial grid, so each
combination becomes its own subdirectory.

```bash
curl -s localhost:8000/compile -H 'content-type: application/json' -d '{
  "input_files": {"input.txt": "x = ${x}\n"},
  "model": {"varprefix": "$", "delim": "{}"},
  "input_variables": {"x": 42}
}'
```

```json
{
  "output_files": {
    "x=42/.fz_hash": "7d57bfe0f11fda8589fe691743da3761  input.txt\n",
    "x=42/input.txt": "x = 42\n"
  },
  "skipped": []
}
```

Binary files or files larger than 1&nbsp;MB are omitted from `output_files` and
listed by name under `skipped`.

### `POST /read` (fzo)

Parse output files that already exist. Upload the output directories as
`input_files` and point `input_path` at them with a glob; the model's `output`
commands run against each matched directory. Variables encoded in directory
names (`key=value`) are extracted into columns automatically.

```bash
curl -s localhost:8000/read -H 'content-type: application/json' -d '{
  "input_files": {
    "x=1/output.txt": "pressure = 247.88\n",
    "x=2/output.txt": "pressure = 495.76\n"
  },
  "input_path": "x=*",
  "model": {"output": {"pressure": "grep '"'"'pressure = '"'"' output.txt | awk '"'"'{print $3}'"'"'"}}
}'
```

```json
[
  {"path": "x=1", "pressure": 247.88, "x": 1},
  {"path": "x=2", "pressure": 495.76, "x": 2}
]
```

### `POST /runs` (fzr) &nbsp;·&nbsp; `GET /runs/{id}`

Launch a parametric run. Because a run can take a while, `POST /runs` returns
`202 Accepted` with a job id immediately; poll `GET /runs/{id}` until `status`
is `completed` or `failed`.

This example uploads both the input template and the calculator script it uses,
selects the template with `input_path`, and sweeps `n_mol` over two values:

```bash
JOB=$(curl -s localhost:8000/runs -H 'content-type: application/json' -d '{
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
}' | python -c "import sys,json;print(json.load(sys.stdin)['job_id'])")

curl -s localhost:8000/runs/$JOB      # repeat until status == completed
```

A completed run status looks like:

```json
{
  "job_id": "a1b2c3…",
  "kind": "run",
  "status": "completed",
  "progress": {"completed": 2, "total": 2, "eta_seconds": 0.0},
  "result": [
    {"n_mol": 1, "T_celsius": 25, "V_L": 10, "pressure": 247.8819, "status": "done", "error": null},
    {"n_mol": 2, "T_celsius": 25, "V_L": 10, "pressure": 495.7638, "status": "done", "error": null}
  ],
  "error": null
}
```

Request fields: `input_files`, `input_path` (optional), `model`,
`input_variables` (dict for a factorial grid, or a list of row dicts for an
explicit design), `calculators` (optional), `timeout` (optional, seconds).

### `POST /designs` (fzd) &nbsp;·&nbsp; `GET /designs/{id}`

Launch an iterative design-of-experiments driven by an algorithm. Same
async job pattern as `/runs`. Variable ranges use fz's `[min;max]` syntax:

```bash
curl -s localhost:8000/designs -H 'content-type: application/json' -d '{
  "input_files": {"input.txt": "x = ${x}\n", "calc.sh": "..."},
  "input_path": "input.txt",
  "model": {"varprefix": "$", "delim": "{}", "output": {"y": "cat output.txt"}},
  "input_variables": {"x": "[0;10]"},
  "output_expression": "y",
  "algorithm": "algorithms/montecarlo_uniform.py",
  "algorithm_options": {"batch_sample_size": 20, "max_iterations": 50},
  "calculators": ["sh://bash calc.sh"]
}'
```

Poll `GET /designs/{id}`; the completed `result` contains the algorithm's
`input_vars`, `output_values`, `analysis`, and `summary`.

### `POST /models/install` &nbsp;·&nbsp; `DELETE /models/{name}`

Install or remove a model. `model` may be a GitHub name, a URL, or a local zip
path; `global_install` targets `~/.fz/models/` instead of `./.fz/models/`.

```bash
curl -s localhost:8000/models/install -H 'content-type: application/json' \
  -d '{"model": "perfectgas"}'

curl -s -X DELETE localhost:8000/models/perfectgas
```

## Result serialization

fz DataFrame results (`fzo`, `fzr`) are serialized as a list of record objects
(one per row), matching the fz CLI's `--format json`. Dict results (`fzi`,
`fzl`, `fzd`) are returned as-is. `NaN` values become `null` so payloads are
valid JSON.

## Error handling

Synchronous endpoints map fz errors to HTTP status codes:

| Status | When |
|--------|------|
| `400 Bad Request` | Invalid arguments, bad values, or an illegal `input_files` path (`..`/absolute). |
| `404 Not Found` | A referenced input file or model does not exist. |
| `422 Unprocessable Entity` | Request body fails schema validation (FastAPI/Pydantic). |

The response body is `{"detail": "<message>"}`.

For **async jobs**, transport is always `202`/`200`: a failure during execution
is reported *in the job status* as `"status": "failed"` with an `"error"`
message, rather than as an HTTP error.

## Client examples

Complete, runnable clients that exercise the full flow (health → parse → submit
run → poll → results) live in
[`examples/clients/`](examples/clients). Each takes an optional base-URL
argument (default `http://localhost:8000`):

```bash
# start the server in one terminal
fz-api --port 8000

# then run any client against it
bash   examples/clients/fzapi_client.sh     http://localhost:8000   # needs curl + jq
python examples/clients/fzapi_client.py     http://localhost:8000
java   examples/clients/FzApiClient.java     http://localhost:8000   # Java 11+
```

### Shell (curl + jq)

```bash
# submit a run, capturing the job id
JOB=$(curl -s localhost:8000/runs -H 'content-type: application/json' -d '{
  "input_files": {"input.txt": "x = ${x}\n", "calc.sh": "#!/bin/bash\ncp \"$1\" output.txt\n"},
  "input_path": "input.txt",
  "model": {"varprefix": "$", "delim": "{}", "output": {"out": "cat output.txt"}},
  "input_variables": {"x": [1, 2, 3]},
  "calculators": ["sh://bash calc.sh"]
}' | jq -r '.job_id')

# poll until done
curl -s localhost:8000/runs/$JOB | jq .
```

### Python (standard library only)

```python
import json, time, urllib.request

BASE = "http://localhost:8000"

def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)

ref = request("POST", "/runs", {
    "input_files": {"input.txt": "x = ${x}\n", "calc.sh": '#!/bin/bash\ncp "$1" output.txt\n'},
    "input_path": "input.txt",
    "model": {"varprefix": "$", "delim": "{}", "output": {"out": "cat output.txt"}},
    "input_variables": {"x": [1, 2, 3]},
    "calculators": ["sh://bash calc.sh"],
})
job_id = ref["job_id"]

while True:
    status = request("GET", f"/runs/{job_id}")
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(1)

print(status["result"])
```

### Java (JDK `java.net.http`, no dependencies)

> **Note:** build the client with `HttpClient.Version.HTTP_1_1`. The default
> HTTP/2 upgrade is mishandled by the HTTP/1.1-only server and silently drops
> the request body.

```java
import java.net.URI;
import java.net.http.*;

var http = HttpClient.newBuilder()
        .version(HttpClient.Version.HTTP_1_1)   // required — see note above
        .build();

String body = """
    {"input_files": {"input.txt": "x = ${x}\\n",
                     "calc.sh": "#!/bin/bash\\ncp \\"$1\\" output.txt\\n"},
     "input_path": "input.txt",
     "model": {"varprefix": "$", "delim": "{}", "output": {"out": "cat output.txt"}},
     "input_variables": {"x": [1, 2, 3]},
     "calculators": ["sh://bash calc.sh"]}
    """;

HttpRequest req = HttpRequest.newBuilder(URI.create("http://localhost:8000/runs"))
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(body))
        .build();

HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
System.out.println(resp.body());   // {"job_id": "...", "status": "running", ...}
```

See [`FzApiClient.java`](examples/clients/FzApiClient.java) for the full version
that also polls `GET /runs/{id}` until completion.

## Architecture & design notes

- **Decoupling.** `fz_api` only imports fz's public API; it never reaches into
  fz internals. If it ever needs to grow (auth, DB, web UI) it can, without
  touching the fz repo.
- **Concurrency & cwd safety.** fz core functions call `os.chdir` on the
  process. Synchronous endpoints are serialized through a global lock. Each
  long-running job runs in its **own subprocess**, giving it a private working
  directory *and* a main thread (which `fzr` requires for its signal handler),
  and enabling true parallelism across jobs.
- **Progress.** `fzr`'s `on_start`/`on_progress`/`on_case_complete` callbacks
  are streamed from the job subprocess back to the job status endpoint.
- **State.** Job state is in-memory (single process); jobs are lost on restart.
  Back it with Redis/a database for durability, and run behind a process
  manager for horizontal scale.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## License

BSD-3-Clause (same as fz).
