"""HTTP routes mapping onto the public fz API (fzi/fzc/fzo/fzr/fzl/fzd + install)."""

from typing import Any

import fz
from fastapi import APIRouter, HTTPException

from .jobs import JobManager
from .schemas import (
    CompileRequest,
    DesignRequest,
    InstallRequest,
    JobRef,
    JobStatus,
    ParseRequest,
    ReadRequest,
    RunRequest,
)
from .serialization import to_jsonable
from .worker import variables
from .workspace import (
    FZ_LOCK,
    WorkspaceError,
    collect_file_tree,
    pushd,
    resolve_input_path,
    workspace,
)

router = APIRouter()
jobs = JobManager()


def _run_fz(fn, *args, **kwargs):
    """Serialize a synchronous fz call (global cwd safety) and map errors to HTTP."""
    try:
        with FZ_LOCK:
            return fn(*args, **kwargs)
    except (WorkspaceError, ValueError, TypeError) as exc:
        raise HTTPException(400, f"{type(exc).__name__}: {exc}")
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc))


# --- health / discovery ----------------------------------------------------


@router.get("/health")
def health():
    return {"status": "ok", "fz_version": getattr(fz, "__version__", "unknown")}


@router.get("/models")
def list_models(pattern: str = "*", check: bool = False):
    result = _run_fz(fz.fzl, models=pattern, calculators="*", check=check)
    return to_jsonable(result.get("models", {}))


@router.get("/calculators")
def list_calculators(pattern: str = "*", check: bool = False):
    result = _run_fz(fz.fzl, models="*", calculators=pattern, check=check)
    return to_jsonable(result.get("calculators", {}))


# --- fast, synchronous operations ------------------------------------------


@router.post("/parse")
def parse(req: ParseRequest):
    """fzi: find variables/formulas/static objects in the input files."""
    with workspace(req.input_files) as ws:
        ip = resolve_input_path(ws, req.input_files, req.input_path)
        result = _run_fz(fz.fzi, str(ip), req.model)
    return to_jsonable(result)


@router.post("/compile")
def compile_input(req: CompileRequest):
    """fzc: substitute variable values and return the compiled file tree."""
    with workspace(req.input_files) as ws:
        ip = resolve_input_path(ws, req.input_files, req.input_path)
        out_dir = ws / "__fzc_output__"
        _run_fz(
            fz.fzc,
            str(ip),
            variables(req.input_variables),
            req.model,
            output_dir=str(out_dir),
        )
        files, skipped = collect_file_tree(out_dir)
    return {"output_files": files, "skipped": skipped}


@router.post("/read")
def read_output(req: ReadRequest):
    """fzo: parse output files in the uploaded directory(ies)."""
    with workspace(req.input_files) as ws:
        target = req.input_path or "."
        with pushd(ws):
            result = _run_fz(fz.fzo, target, req.model)
    return to_jsonable(result)


# --- long-running jobs ------------------------------------------------------


@router.post("/runs", response_model=JobRef, status_code=202)
def create_run(req: RunRequest):
    """fzr: launch a parametric run as a background job."""
    payload = _payload(
        req, ("model", "input_variables", "calculators", "timeout")
    )
    job = jobs.submit("run", payload)
    return JobRef(job_id=job.job_id, status=job.status, kind=job.kind)


@router.post("/designs", response_model=JobRef, status_code=202)
def create_design(req: DesignRequest):
    """fzd: launch an iterative design-of-experiments as a background job."""
    payload = _payload(
        req,
        (
            "model",
            "input_variables",
            "output_expression",
            "algorithm",
            "calculators",
            "algorithm_options",
        ),
    )
    job = jobs.submit("design", payload)
    return JobRef(job_id=job.job_id, status=job.status, kind=job.kind)


@router.get("/runs/{job_id}", response_model=JobStatus)
def get_run(job_id: str):
    return _job_status(job_id, "run")


@router.get("/designs/{job_id}", response_model=JobStatus)
def get_design(job_id: str):
    return _job_status(job_id, "design")


def _payload(req: Any, fields) -> dict:
    """Build a picklable job payload dict from a request model."""
    data = {"input_files": req.input_files, "input_path": req.input_path}
    for f in fields:
        data[f] = getattr(req, f)
    return data


def _job_status(job_id: str, kind: str) -> JobStatus:
    snap = jobs.snapshot(job_id)
    if snap is None or snap["kind"] != kind:
        raise HTTPException(404, f"No {kind} job with id {job_id}")
    return JobStatus(**snap)


# --- model installation -----------------------------------------------------


@router.post("/models/install")
def install_model(req: InstallRequest):
    result = _run_fz(fz.install, req.model, global_install=req.global_install)
    return to_jsonable(result)


@router.delete("/models/{name}")
def uninstall_model(name: str, global_uninstall: bool = False):
    ok = _run_fz(fz.uninstall, name, global_uninstall=global_uninstall)
    if not ok:
        raise HTTPException(404, f"Model {name!r} not found")
    return {"uninstalled": name}
