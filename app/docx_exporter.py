from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Inches, RGBColor

from app.image_utils import calculate_fit_size_inches
from app.models import Issue, Report, ScreenshotEntry


def export_report_to_docx(report: Report, output_path: str) -> None:
    document = Document()
    _add_cover_page(document, report)
    _add_screenshots(document, report)
    document.save(output_path)


def _add_cover_page(document: Document, report: Report) -> None:
    document.add_heading("Informe QA de Traduccion", 0)

    _add_label_value(document, "Juego", report.game_name)
    _add_label_value(document, "Traductor", report.translator)
    _add_label_value(document, "Tester", report.tester)
    _add_label_value(document, "Idioma original", report.source_language)
    _add_label_value(document, "Idioma destino", report.target_language)
    _add_label_value(document, "Fecha", report.report_date)

    document.add_page_break()


def _add_screenshots(document: Document, report: Report) -> None:
    slots_remaining = 2
    total = len(report.screenshots)

    for index, shot in enumerate(report.screenshots):
        compact = _is_compact_entry(shot)
        needed_slots = 1 if compact else 2

        if needed_slots > slots_remaining:
            document.add_page_break()
            slots_remaining = 2

        _add_screenshot_block(document, index + 1, shot, compact=compact)
        slots_remaining -= needed_slots

        is_last = index == (total - 1)
        if slots_remaining == 0 and not is_last:
            document.add_page_break()
            slots_remaining = 2


def _is_compact_entry(entry: ScreenshotEntry) -> bool:
    if len(entry.issues) > 2:
        return False

    total_chars = sum(
        len(issue.wrong_text) + len(issue.correction) + len(issue.note) for issue in entry.issues
    )
    return total_chars <= 450


def _add_screenshot_block(
    document: Document, index: int, entry: ScreenshotEntry, *, compact: bool
) -> None:
    image_name = Path(entry.image_path).name
    heading = document.add_paragraph()
    heading.paragraph_format.keep_with_next = True
    heading_run = heading.add_run(f"Captura {index}: {image_name}")
    heading_run.bold = True

    max_width_in = 6.0
    max_height_in = 3.1 if compact else 5.0
    width_in, height_in = calculate_fit_size_inches(entry.image_path, max_width_in, max_height_in)

    pic_paragraph = document.add_paragraph()
    pic_paragraph.paragraph_format.keep_with_next = True
    pic_paragraph.add_run().add_picture(
        entry.image_path, width=Inches(width_in), height=Inches(height_in)
    )

    if not entry.issues:
        empty_paragraph = document.add_paragraph("Sin errores registrados.")
        empty_paragraph.runs[0].italic = True
        return

    for issue_idx, issue in enumerate(entry.issues, start=1):
        _add_issue_block(document, issue_idx, issue)

    document.add_paragraph("")


def _add_issue_block(document: Document, issue_idx: int, issue: Issue) -> None:
    title = document.add_paragraph()
    title_run = title.add_run(f"Error {issue_idx}")
    title_run.bold = True

    wrong_p = document.add_paragraph()
    wrong_p.add_run("Texto erroneo: ").bold = True
    wrong_run = wrong_p.add_run(issue.wrong_text or "(vacio)")
    wrong_run.font.color.rgb = RGBColor(0xFF, 0x00, 0x00)

    correction_p = document.add_paragraph()
    correction_p.add_run("Correccion: ").bold = True
    correction_run = correction_p.add_run(issue.correction or "(vacio)")
    correction_run.font.color.rgb = RGBColor(0x00, 0x00, 0x00)

    if issue.note.strip():
        note_p = document.add_paragraph()
        note_p.add_run("Nota: ").bold = True
        note_run = note_p.add_run(issue.note.strip())
        note_run.font.color.rgb = RGBColor(0x00, 0x64, 0x00)
