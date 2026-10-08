"""Versions of the learned head: candidate -> active (by an administrator) -> retired.

``<root>/registry.json`` lists every version with its training data, its gate
results and who activated it. ``v0`` is the shipped model's own head. Only a
version whose gates passed can be activated; activation records the person
and time; rollback activates an earlier version. Weights live in
``<root>/versions/<version>.pt``.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import torch


class Registry:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self) -> Path:
        return self.root / "registry.json"

    def read(self) -> dict:
        p = self._path()
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"active": "v0", "versions": [{"version": "v0", "status": "active", "created": None,
                                              "note": "shipped model (no local learning)"}]}

    def _write(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path())

    def active(self) -> str:
        return self.read()["active"]

    def weights(self, version: str) -> dict | None:
        if version == "v0":
            return None
        p = self.root / "versions" / f"{version}.pt"
        return torch.load(p, map_location="cpu", weights_only=False) if p.is_file() else None

    def add_candidate(self, state: dict, record: dict) -> str:
        with self._lock:
            data = self.read()
            version = f"v{1 + max(int(v['version'][1:]) for v in data['versions'])}"
            (self.root / "versions").mkdir(parents=True, exist_ok=True)
            torch.save(state, self.root / "versions" / f"{version}.pt")
            data["versions"].append({"version": version, "status": "candidate",
                                     "created": datetime.now(timezone.utc).isoformat(), **record})
            self._write(data)
            return version

    def activate(self, version: str, by: str) -> dict:
        with self._lock:
            data = self.read()
            entry = next((v for v in data["versions"] if v["version"] == version), None)
            if entry is None:
                raise ValueError(f"No version {version}.")
            if version != "v0" and not (entry.get("gates") or {}).get("passed"):
                raise ValueError(f"{version} did not pass its gates and cannot be activated.")
            for v in data["versions"]:
                if v["status"] == "active":
                    v["status"] = "retired"
            entry["status"] = "active"
            entry["activated_by"] = by
            entry["activated_at"] = datetime.now(timezone.utc).isoformat()
            data["active"] = version
            self._write(data)
            return entry

    def reject(self, version: str, by: str) -> dict:
        with self._lock:
            data = self.read()
            entry = next((v for v in data["versions"] if v["version"] == version), None)
            if entry is None or entry["status"] != "candidate":
                raise ValueError(f"{version} is not a candidate.")
            entry["status"] = "rejected"
            entry["rejected_by"] = by
            self._write(data)
            return entry
