from __future__ import annotations

import json
from pathlib import Path

from app.models import Report


def save_report_json(report: Report, file_path: str | Path) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_report_json(file_path: str | Path) -> Report:
    path = Path(file_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("El archivo JSON no contiene un informe valido.")
    return Report.from_dict(data)
