import pytest
from fastapi.testclient import TestClient

from fz_http.app import create_app

# A minimal inline model: `$` prefix, `{}` delimiters, one output command that
# echoes the compiled x value into result.txt and reads it back.
MODEL = {
    "varprefix": "$",
    "delim": "{}",
    "output": {"result": "cat result.txt"},
}

INPUT = {"input.txt": "# test input\nx = ${x}\n"}


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "fz_version" in body


def test_list_models_and_calculators(client):
    # No models installed in the test env -> empty mapping, but must return 200.
    assert client.get("/models").status_code == 200
    assert client.get("/calculators").status_code == 200


def test_parse(client):
    r = client.post("/parse", json={"input_files": INPUT, "model": MODEL})
    assert r.status_code == 200, r.text
    # fzi should discover variable x
    assert "x" in r.json()


def test_compile(client):
    r = client.post(
        "/compile",
        json={
            "input_files": INPUT,
            "model": MODEL,
            "input_variables": {"x": 42},
        },
    )
    assert r.status_code == 200, r.text
    files = r.json()["output_files"]
    # Exactly one compiled input.txt with x substituted
    compiled = next(v for k, v in files.items() if k.endswith("input.txt"))
    assert "x = 42" in compiled


def test_parse_rejects_path_traversal(client):
    r = client.post(
        "/parse",
        json={"input_files": {"../evil.txt": "x=${x}"}, "model": MODEL},
    )
    assert r.status_code == 400


def _wait(client, url, timeout=60):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(url)
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.2)
    raise AssertionError(f"job {url} did not finish in {timeout}s")


def test_run_job(client):
    r = client.post(
        "/runs",
        json={
            "input_files": INPUT,
            "model": MODEL,
            "input_variables": {"x": [1, 2, 3]},
            "calculators": ["sh://echo ${x} > result.txt"],
        },
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]

    body = _wait(client, f"/runs/{job_id}")
    assert body["status"] == "completed", body
    result = body["result"]
    assert isinstance(result, list)
    assert len(result) == 3
    # x values round-tripped through the calculator output
    xs = sorted(int(float(row["x"])) for row in result)
    assert xs == [1, 2, 3]


def test_run_with_auxiliary_script(client):
    """A run may upload extra files (e.g. a calculator script) alongside input."""
    input_txt = "n_mol=$n_mol\nT_kelvin=@{$T_celsius + 273.15}\nV_m3=$V_L\n"
    calc_sh = (
        '#!/bin/bash\nsource "$1"\n'
        'awk "BEGIN{printf \\"pressure = %.4f\\", '
        '$n_mol*8.314*$T_kelvin/$V_m3}" > output.txt\n'
    )
    r = client.post(
        "/runs",
        json={
            "input_files": {"input.txt": input_txt, "calc.sh": calc_sh},
            "input_path": "input.txt",
            "model": {
                "varprefix": "$",
                "delim": "{}",
                "output": {
                    "pressure": "grep 'pressure = ' output.txt | awk '{print $3}'"
                },
            },
            "input_variables": {"n_mol": 1, "T_celsius": 25, "V_L": 10},
            "calculators": ["sh://bash calc.sh"],
        },
    )
    assert r.status_code == 202, r.text
    body = _wait(client, f"/runs/{r.json()['job_id']}")
    assert body["status"] == "completed", body
    row = body["result"][0]
    assert row["status"] == "done", row
    # n_mol*R*T/V = 1*8.314*298.15/10 = 247.8819
    assert abs(float(row["pressure"]) - 247.8819) < 1e-3


def test_run_job_unknown_id(client):
    assert client.get("/runs/does-not-exist").status_code == 404


def test_run_wrong_kind_lookup(client):
    # A run job id must not resolve under /designs/{id}
    r = client.post(
        "/runs",
        json={
            "input_files": INPUT,
            "model": MODEL,
            "input_variables": {"x": [1]},
            "calculators": ["sh://echo ${x} > result.txt"],
        },
    )
    job_id = r.json()["job_id"]
    assert client.get(f"/designs/{job_id}").status_code == 404
