from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


SOURCE_LANGUAGES = ["Inglés", "Chino", "Japonés", "Mixto"]
TARGET_LANGUAGE = "Español"

_LANGUAGE_ALIASES = {
    "ingles": "Inglés",
    "inglés": "Inglés",
    "chino": "Chino",
    "japones": "Japonés",
    "japonés": "Japonés",
    "mixto": "Mixto",
    "espanol": "Español",
    "español": "Español",
}


def display_language(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return _LANGUAGE_ALIASES.get(normalized.casefold(), normalized)


def normalize_source_language(value: str) -> str:
    normalized = display_language(value)
    if normalized in SOURCE_LANGUAGES:
        return normalized
    return SOURCE_LANGUAGES[0]


def normalize_target_language(value: str) -> str:
    normalized = display_language(value)
    if normalized == TARGET_LANGUAGE:
        return normalized
    return TARGET_LANGUAGE


@dataclass
class Issue:
    wrong_text: str
    correction: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wrong_text": self.wrong_text,
            "correction": self.correction,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Issue":
        return cls(
            wrong_text=str(data.get("wrong_text", "")).strip(),
            correction=str(data.get("correction", "")).strip(),
            note=str(data.get("note", "")).strip(),
        )


@dataclass
class ScreenshotEntry:
    image_path: str
    issues: list[Issue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_path": self.image_path,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreenshotEntry":
        issues_data = data.get("issues", [])
        return cls(
            image_path=str(data.get("image_path", "")).strip(),
            issues=[Issue.from_dict(i) for i in issues_data if isinstance(i, dict)],
        )


@dataclass
class Report:
    game_name: str = ""
    translator: str = ""
    tester: str = ""
    source_language: str = SOURCE_LANGUAGES[0]
    target_language: str = TARGET_LANGUAGE
    report_date: str = field(default_factory=lambda: date.today().isoformat())
    screenshots: list[ScreenshotEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_name": self.game_name,
            "translator": self.translator,
            "tester": self.tester,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "report_date": self.report_date,
            "screenshots": [shot.to_dict() for shot in self.screenshots],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Report":
        screenshots_data = data.get("screenshots", [])
        return cls(
            game_name=str(data.get("game_name", "")).strip(),
            translator=str(data.get("translator", "")).strip(),
            tester=str(data.get("tester", "")).strip(),
            source_language=normalize_source_language(
                str(data.get("source_language", SOURCE_LANGUAGES[0]))
            ),
            target_language=normalize_target_language(
                str(data.get("target_language", TARGET_LANGUAGE))
            ),
            report_date=str(data.get("report_date", date.today().isoformat())),
            screenshots=[
                ScreenshotEntry.from_dict(s) for s in screenshots_data if isinstance(s, dict)
            ],
        )


@dataclass
class ReportProfile:
    game_name: str = ""
    translator: str = ""
    tester: str = ""
    source_language: str = SOURCE_LANGUAGES[0]
    target_language: str = TARGET_LANGUAGE

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_name": self.game_name,
            "translator": self.translator,
            "tester": self.tester,
            "source_language": self.source_language,
            "target_language": self.target_language,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportProfile":
        return cls(
            game_name=str(data.get("game_name", "")).strip(),
            translator=str(data.get("translator", "")).strip(),
            tester=str(data.get("tester", "")).strip(),
            source_language=normalize_source_language(
                str(data.get("source_language", SOURCE_LANGUAGES[0]))
            ),
            target_language=normalize_target_language(
                str(data.get("target_language", TARGET_LANGUAGE))
            ),
        )

    @classmethod
    def from_report(cls, report: Report) -> "ReportProfile":
        return cls(
            game_name=report.game_name,
            translator=report.translator,
            tester=report.tester,
            source_language=normalize_source_language(report.source_language),
            target_language=normalize_target_language(report.target_language),
        )

    def to_report(self) -> Report:
        return Report(
            game_name=self.game_name,
            translator=self.translator,
            tester=self.tester,
            source_language=normalize_source_language(self.source_language),
            target_language=normalize_target_language(self.target_language),
        )
