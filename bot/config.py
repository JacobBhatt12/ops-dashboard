"""Configuration loading. All paths resolve relative to the project root."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class Config:
    def __init__(self, data: dict):
        self._d = data

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        p = Path(path) if path else ROOT / "config.yaml"
        with open(p, "r", encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    def __getitem__(self, key):
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)

    def path(self, key: str) -> Path:
        """Resolve a value from the paths: block against the project root."""
        raw = self._d["paths"][key]
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p
