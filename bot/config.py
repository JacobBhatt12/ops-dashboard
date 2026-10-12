"""Configuration loading. All paths resolve relative to the project root."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE per line, # comments). Never overrides
    a variable that's already set in the real environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


class Config:
    def __init__(self, data: dict):
        self._d = data

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        p = Path(path) if path else ROOT / "config.yaml"
        with open(p, "r", encoding="utf-8") as fh:
            cfg = cls(yaml.safe_load(fh))
        # volume.ramp steps daily_target up on set dates; resolve today's
        # step here so every reader (bot, dashboard, status) sees one number.
        step = cfg.ramp_target(date.today())
        if step is not None:
            cfg._d["volume"]["daily_target"] = step
        return cfg

    def ramp_target(self, day: date) -> int | None:
        """daily_target from the latest volume.ramp step on or before `day`."""
        best = None
        for s in self._d.get("volume", {}).get("ramp") or []:
            start = s["from"] if isinstance(s["from"], date) else date.fromisoformat(str(s["from"]))
            if start <= day and (best is None or start >= best[0]):
                best = (start, int(s["daily_target"]))
        return best[1] if best else None

    def __getitem__(self, key):
        return self._d[key]

    def get(self, key, default=None):
        return self._d.get(key, default)

    def path(self, key: str) -> Path:
        """Resolve a value from the paths: block against the project root."""
        raw = self._d["paths"][key]
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p
