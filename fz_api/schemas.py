"""Pydantic request/response schemas for the fz HTTP API.

``model``, ``calculators`` and ``algorithm_options`` accept either a string
(alias / inline JSON / path, as fz's own resolvers handle) or a JSON object,
so they are typed as ``Union`` and passed through to fz unchanged.
"""

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

# fz accepts a model alias string or an inline model definition dict.
ModelSpec = Union[str, Dict[str, Any]]
# fz accepts a string, dict, or list of string/dict for calculators.
CalculatorsSpec = Union[str, Dict[str, Any], List[Union[str, Dict[str, Any]]]]
# input_variables: dict of scalars/lists (factorial grid) or list of row dicts.
VariablesSpec = Union[Dict[str, Any], List[Dict[str, Any]]]


class InputFilesMixin(BaseModel):
    input_files: Dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of relative path -> text content for the input files.",
    )
    input_path: Optional[str] = Field(
        default=None,
        description=(
            "Relative path (inside the uploaded files) to use as the fz input_path. "
            "Defaults to the single uploaded file, or the workspace root otherwise."
        ),
    )


class ParseRequest(InputFilesMixin):
    model: ModelSpec = Field(..., description="Model alias or inline definition.")


class CompileRequest(InputFilesMixin):
    model: ModelSpec
    input_variables: VariablesSpec = Field(
        ..., description="Variable values (scalars/lists for a grid, or row dicts)."
    )


class ReadRequest(InputFilesMixin):
    """For fzo: input_files carry the output directory contents to parse."""

    model: ModelSpec


class RunRequest(InputFilesMixin):
    model: ModelSpec
    input_variables: VariablesSpec
    calculators: Optional[CalculatorsSpec] = None
    timeout: Optional[int] = Field(
        default=None, description="Per-case timeout in seconds."
    )


class DesignRequest(InputFilesMixin):
    model: ModelSpec
    input_variables: Dict[str, str] = Field(
        ..., description='Variable ranges, e.g. {"x1": "[0;10]", "x2": "[0;5]"}.'
    )
    output_expression: str = Field(..., description="Expression to optimize/extract.")
    algorithm: str = Field(..., description="Path to the algorithm .py file.")
    calculators: Optional[CalculatorsSpec] = None
    algorithm_options: Optional[Union[Dict[str, Any], str]] = None


class InstallRequest(BaseModel):
    model: str = Field(..., description="GitHub name, URL, or local zip path.")
    global_install: bool = False


# --- responses -------------------------------------------------------------


class JobRef(BaseModel):
    job_id: str
    status: str
    kind: str


class Progress(BaseModel):
    completed: int = 0
    total: int = 0
    eta_seconds: Optional[float] = None


class JobStatus(BaseModel):
    job_id: str
    kind: str
    status: str  # pending | running | completed | failed
    progress: Progress = Field(default_factory=Progress)
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
