"""Loading of ``config/scoring.yaml`` (thresholds, split, seeds, model parameters)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SCORING_CONFIG = ROOT / "config" / "scoring.yaml"


def load_scoring_config(path: str | Path | None = None) -> dict[str, Any]:
    """Read the YAML scoring configuration (PyYAML is part of the ``dev`` and ``models`` extras)."""
    import yaml

    source = Path(path) if path else DEFAULT_SCORING_CONFIG
    with source.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise TypeError(f"{source} must contain a YAML mapping")
    return config
