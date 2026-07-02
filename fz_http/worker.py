"""Worker logic executed inside a job subprocess.

Running fzr/fzd in a child process means the fz call sits in that process's
*main thread* (fzr installs a SIGINT handler that only works there) and gets a
private working directory, so concurrent jobs neither race on ``os.chdir`` nor
need the global lock.
"""

from typing import Any, Callable, Dict

import fz

from .serialization import to_jsonable
from .workspace import pushd, resolve_input_path, workspace

try:
    import pandas as pd

    _PANDAS = True
except Exception:  # pragma: no cover
    _PANDAS = False


def variables(spec: Any):
    """List of row dicts -> DataFrame (non-factorial); dict -> passthrough (grid)."""
    if isinstance(spec, list):
        if not _PANDAS:
            raise ValueError("pandas required for list/row-based designs")
        return pd.DataFrame(spec)
    return spec


def _run_callbacks(progress: Callable[..., None]) -> Dict[str, Callable]:
    return {
        "on_start": lambda total, calcs: progress(total=total),
        "on_progress": lambda completed, total, eta: progress(
            completed=completed, total=total, eta_seconds=eta
        ),
        "on_case_complete": lambda i, total, combo, status, result: progress(
            completed=i + 1, total=total
        ),
    }


def execute(kind: str, payload: Dict[str, Any], progress: Callable[..., None]) -> Any:
    """Run the requested fz operation and return a JSON-serializable result.

    The call runs with the workspace as the current directory so fz can resolve
    both the input file(s) and any auxiliary uploaded files (e.g. calculator
    scripts referenced by ``sh://bash calc.sh``) relative to it.
    """
    input_files = payload.get("input_files", {})
    with workspace(input_files) as ws, pushd(ws):
        ip = resolve_input_path(ws, input_files, payload.get("input_path"))
        if kind == "run":
            result = fz.fzr(
                str(ip),
                variables(payload["input_variables"]),
                payload["model"],
                results_dir=str(ws / "__results__"),
                calculators=payload.get("calculators"),
                callbacks=_run_callbacks(progress),
                timeout=payload.get("timeout"),
            )
        elif kind == "design":
            result = fz.fzd(
                str(ip),
                payload["input_variables"],
                payload["model"],
                payload["output_expression"],
                payload["algorithm"],
                calculators=payload.get("calculators"),
                algorithm_options=payload.get("algorithm_options"),
                analysis_dir=str(ws / "__analysis__"),
            )
        else:  # pragma: no cover - guarded by callers
            raise ValueError(f"Unknown job kind: {kind}")
        return to_jsonable(result)
