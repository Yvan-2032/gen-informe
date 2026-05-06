from __future__ import annotations

import json
from pathlib import Path

from app.models import Report, ReportProfile


REPORT_FILE_EXTENSION = ".iarc"
PROFILE_FILE_EXTENSION = ".qaprof"
_APP_STORAGE_DIRNAME = ".qa-report-builder"
_DEFAULT_PROFILE_FILENAME = f"default_profile{PROFILE_FILE_EXTENSION}"
_RECENTS_FILENAME = "recent_reports.json"


def _app_storage_dir() -> Path:
    return Path.home() / _APP_STORAGE_DIRNAME


def get_default_profile_path() -> Path:
    return _app_storage_dir() / _DEFAULT_PROFILE_FILENAME


def _recents_path() -> Path:
    return _app_storage_dir() / _RECENTS_FILENAME


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


def save_default_profile(profile: ReportProfile) -> Path:
    path = get_default_profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_default_profile() -> ReportProfile | None:
    path = get_default_profile_path()
    if not path.exists():
        return None

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("El perfil por defecto no es valido.")
    return ReportProfile.from_dict(data)


def load_recent_reports() -> list[str]:
    path = _recents_path()
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    recent = data.get("recent_reports", [])
    if not isinstance(recent, list):
        return []
    return [str(item).strip() for item in recent if str(item).strip()]


def save_recent_reports(paths: list[str]) -> None:
    path = _recents_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        normalized = str(raw).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)

    payload = {"recent_reports": cleaned[:30]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def add_recent_report(file_path: str | Path) -> None:
    normalized = str(file_path).strip()
    if not normalized:
        return

    current = load_recent_reports()
    ordered = [normalized]
    for item in current:
        if item.casefold() != normalized.casefold():
            ordered.append(item)
    save_recent_reports(ordered)
