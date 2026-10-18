"""Small durable store for recent Laravel projects."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional


class ProjectStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        self.path = path or base / "LaravelQueryScanner" / "settings.json"

    def recent_projects(self) -> List[str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return [str(Path(item)) for item in payload.get("recent_projects", []) if Path(item).is_dir()]
        except (OSError, ValueError, TypeError):
            return []

    def remember(self, project: Path) -> None:
        resolved = str(project.resolve())
        projects = [item for item in self.recent_projects() if item.lower() != resolved.lower()]
        projects.insert(0, resolved)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"recent_projects": projects[:10]}, indent=2), encoding="utf-8")
        temporary.replace(self.path)

