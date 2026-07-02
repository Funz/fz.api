"""Serialization helpers: convert fz return values into JSON-friendly structures.

fz functions return either plain dicts/lists (fzi, fzl, fzd, install/list) or a
pandas DataFrame (fzo, fzr). This module normalizes both into JSON-serializable
Python objects, mirroring the CLI's ``--format json`` behavior
(``DataFrame.to_dict(orient="records")``).
"""

from typing import Any

try:  # pandas is a hard dependency of funz-fz, but guard just in case
    import pandas as pd

    _PANDAS = True
except Exception:  # pragma: no cover - pandas always present with funz-fz
    _PANDAS = False


def to_jsonable(data: Any) -> Any:
    """Return a JSON-serializable representation of an fz result.

    - pandas DataFrame -> list of record dicts (one per row)
    - dict/list/scalars -> returned as-is (non-serializable leaves stringified)
    """
    if _PANDAS and isinstance(data, pd.DataFrame):
        # NaN -> None so the payload is valid JSON
        return data.where(pd.notnull(data), None).to_dict(orient="records")
    return _coerce(data)


def _coerce(value: Any) -> Any:
    """Best-effort recursive coercion of values into JSON-safe primitives."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    if _PANDAS and isinstance(value, pd.DataFrame):
        return to_jsonable(value)
    # Fallback for numpy scalars, Paths, etc.
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return value.item()
    except Exception:
        pass
    return str(value)
