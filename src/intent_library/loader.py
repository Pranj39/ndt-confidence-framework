"""JSON persistence for intent suites and endpoint-group registries."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .schema import EndpointGroupRegistry, IntentSuite

_Model = TypeVar("_Model", bound=BaseModel)


def load_intent_suite(path: str | Path) -> IntentSuite:
    """Read and validate an intent suite JSON file."""
    return _load(IntentSuite, path, "intent suite")


def save_intent_suite(suite: IntentSuite, path: str | Path) -> None:
    """Write ``suite`` as indented JSON, replacing ``path`` atomically."""
    _save(suite, path)


def load_group_registry(path: str | Path) -> EndpointGroupRegistry:
    """Read and validate an endpoint-group registry JSON file."""
    return _load(EndpointGroupRegistry, path, "endpoint group registry")


def save_group_registry(registry: EndpointGroupRegistry, path: str | Path) -> None:
    """Write ``registry`` as indented JSON, replacing ``path`` atomically."""
    _save(registry, path)


def _load(model: type[_Model], path: str | Path, label: str) -> _Model:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    try:
        return model.model_validate_json(text)
    except ValidationError as error:
        raise ValueError(f"{file_path} is not a valid {label}:\n{error}") from error


def _save(model: BaseModel, path: str | Path) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump_json(indent=2, exclude_none=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        os.replace(temporary, file_path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
