from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QDate, QObject, QPoint, QRect, QStandardPaths, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QGuiApplication, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.docx_exporter import export_report_to_docx
from app.image_utils import is_image_loadable
from app.models import (
    Issue,
    Report,
    SOURCE_LANGUAGES,
    ScreenshotEntry,
    TARGET_LANGUAGE,
    normalize_source_language,
    normalize_target_language,
)
from app.ocr.base import OcrDependencyError, OcrModelLoadError, OcrRuntimeError
from app.ocr.manager import get_last_ocr_warning, run_ocr
from app.storage import (
    REPORT_FILE_EXTENSION,
    add_recent_report,
    load_recent_reports,
    load_report_json,
    save_recent_reports,
    save_report_json,
)


class SelectionPreviewLabel(QLabel):
    selectionCompleted = Signal(QRect)
    selectionCancelled = Signal()

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._source_pixmap: QPixmap | None = None
        self._display_rect = QRect()
        self._selection_mode = False
        self._drag_origin: QPoint | None = None
        self._selection_rect = QRect()
        self.setMouseTracking(True)

    def has_image(self) -> bool:
        return self._source_pixmap is not None and not self._source_pixmap.isNull()

    def set_source_pixmap(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            self._source_pixmap = None
            return
        self._source_pixmap = QPixmap(pixmap)
        self._selection_mode = False
        self._drag_origin = None
        self._selection_rect = QRect()
        self.setText("")
        self.update()

    def clear_source(self, message: str) -> None:
        self._source_pixmap = None
        self.cancel_selection_mode(silent=True)
        self.setText(message)
        self.update()

    def begin_selection_mode(self) -> bool:
        if not self.has_image():
            return False
        self._selection_mode = True
        self._drag_origin = None
        self._selection_rect = QRect()
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.update()
        return True

    def cancel_selection_mode(self, *, silent: bool = False) -> None:
        was_active = self._selection_mode
        self._selection_mode = False
        self._drag_origin = None
        self._selection_rect = QRect()
        self.unsetCursor()
        self.update()
        if was_active and not silent:
            self.selectionCancelled.emit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self.has_image():
            self._display_rect = QRect()
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._display_rect = self._calculate_display_rect()
        if self._display_rect.isValid():
            painter.drawPixmap(self._display_rect, self._source_pixmap)

        if self._selection_mode and self._selection_rect.isValid():
            normalized = self._selection_rect.normalized()
            painter.fillRect(normalized, QColor(0, 120, 215, 55))
            painter.setPen(QPen(QColor(0, 170, 255), 2, Qt.PenStyle.DashLine))
            painter.drawRect(normalized)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._selection_mode:
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._display_rect.contains(event.position().toPoint()):
            return
        self._drag_origin = self._clamp_to_display_rect(event.position().toPoint())
        self._selection_rect = QRect(self._drag_origin, self._drag_origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if not self._selection_mode:
            super().mouseMoveEvent(event)
            return
        if self._drag_origin is None:
            return
        current = self._clamp_to_display_rect(event.position().toPoint())
        self._selection_rect = QRect(self._drag_origin, current).normalized()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not self._selection_mode:
            super().mouseReleaseEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton or self._drag_origin is None:
            return

        end_point = self._clamp_to_display_rect(event.position().toPoint())
        selected = QRect(self._drag_origin, end_point).normalized().intersected(self._display_rect)
        self._drag_origin = None

        if selected.width() < 4 or selected.height() < 4:
            self.cancel_selection_mode(silent=False)
            return

        image_rect = self._map_display_to_image_rect(selected)
        self.cancel_selection_mode(silent=True)
        if image_rect.width() < 2 or image_rect.height() < 2:
            self.selectionCancelled.emit()
            return
        self.selectionCompleted.emit(image_rect)

    def _calculate_display_rect(self) -> QRect:
        if not self.has_image():
            return QRect()
        source_size = self._source_pixmap.size()
        if source_size.width() <= 0 or source_size.height() <= 0:
            return QRect()
        scaled_size = source_size.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - scaled_size.width()) // 2
        y = (self.height() - scaled_size.height()) // 2
        return QRect(x, y, scaled_size.width(), scaled_size.height())

    def _clamp_to_display_rect(self, point: QPoint) -> QPoint:
        x = min(max(point.x(), self._display_rect.left()), self._display_rect.right())
        y = min(max(point.y(), self._display_rect.top()), self._display_rect.bottom())
        return QPoint(x, y)

    def _map_display_to_image_rect(self, selected_rect: QRect) -> QRect:
        if not self.has_image() or not self._display_rect.isValid():
            return QRect()

        pixmap_w = self._source_pixmap.width()
        pixmap_h = self._source_pixmap.height()
        disp_w = self._display_rect.width()
        disp_h = self._display_rect.height()
        if disp_w <= 0 or disp_h <= 0:
            return QRect()

        x1 = (selected_rect.left() - self._display_rect.left()) / disp_w * pixmap_w
        y1 = (selected_rect.top() - self._display_rect.top()) / disp_h * pixmap_h
        x2 = (selected_rect.right() + 1 - self._display_rect.left()) / disp_w * pixmap_w
        y2 = (selected_rect.bottom() + 1 - self._display_rect.top()) / disp_h * pixmap_h

        left = max(0, min(pixmap_w - 1, int(x1)))
        top = max(0, min(pixmap_h - 1, int(y1)))
        right = max(left + 1, min(pixmap_w, int(x2)))
        bottom = max(top + 1, min(pixmap_h, int(y2)))
        return QRect(left, top, right - left, bottom - top)


class OcrWorker(QObject):
    finished = Signal(str)
    failed = Signal(str)
    warning = Signal(str)
    completed = Signal()

    def __init__(self, image_path: str, source_language: str) -> None:
        super().__init__()
        self.image_path = image_path
        self.source_language = source_language

    def run(self) -> None:
        try:
            text = run_ocr(self.image_path, self.source_language)
            last_warning = get_last_ocr_warning()
            if last_warning:
                self.warning.emit(last_warning)
            self.finished.emit(text)
        except OcrDependencyError as exc:
            self.failed.emit(f"OCR no instalado correctamente:\n{exc}")
        except OcrModelLoadError as exc:
            self.failed.emit(f"No se pudo cargar el modelo OCR:\n{exc}")
        except OcrRuntimeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Error interno del OCR:\n{exc}")
        finally:
            self.completed.emit()


class ScreenSnipDialog(QDialog):
    def __init__(self, desktop_pixmap: QPixmap, virtual_rect: QRect, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._desktop_pixmap = desktop_pixmap
        self._virtual_rect = virtual_rect
        self._drag_origin: QPoint | None = None
        self._selection_rect = QRect()
        self._selected_rect = QRect()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setModal(True)
        self.setGeometry(virtual_rect)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def selected_rect(self) -> QRect:
        return self._selected_rect

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._desktop_pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

        if self._selection_rect.isValid():
            selection = self._selection_rect.normalized().intersected(self.rect())
            if selection.isValid():
                painter.drawPixmap(selection, self._desktop_pixmap, selection)
                painter.setPen(QPen(QColor(0, 170, 255), 2, Qt.PenStyle.SolidLine))
                painter.drawRect(selection)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._drag_origin = event.position().toPoint()
        self._selection_rect = QRect(self._drag_origin, self._drag_origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._drag_origin is None:
            return
        current = event.position().toPoint()
        self._selection_rect = QRect(self._drag_origin, current).normalized().intersected(self.rect())
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._drag_origin is None:
            return
        current = event.position().toPoint()
        selection = QRect(self._drag_origin, current).normalized().intersected(self.rect())
        self._drag_origin = None
        if selection.width() < 6 or selection.height() < 6:
            self._selection_rect = QRect()
            self.update()
            return
        self._selection_rect = selection
        self._selected_rect = selection
        self.accept()


class InitialDataDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_report: Report | None = None,
        submit_label: str = "Crear proyecto",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Datos iniciales del informe")
        self.setMinimumWidth(620)
        self.submit_label = submit_label
        self.initial_report = initial_report
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        box = QGroupBox("Datos del informe")
        form = QFormLayout(box)

        self.game_name_input = QLineEdit()
        self.translator_input = QLineEdit()
        self.tester_input = QLineEdit()
        self.source_language_input = QComboBox()
        self.source_language_input.addItems(SOURCE_LANGUAGES)

        self.target_language_input = QLineEdit(TARGET_LANGUAGE)
        self.target_language_input.setReadOnly(True)

        form.addRow("Nombre del juego:", self.game_name_input)
        form.addRow("Traductor:", self.translator_input)
        form.addRow("Tester:", self.tester_input)
        form.addRow("Idioma original:", self.source_language_input)
        form.addRow("Idioma destino:", self.target_language_input)

        root.addWidget(box)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.addStretch(1)

        cancel_button = QPushButton("Cancelar")
        create_button = QPushButton(self.submit_label)
        cancel_button.clicked.connect(self.reject)
        create_button.clicked.connect(self._on_create_clicked)
        buttons_layout.addWidget(cancel_button)
        buttons_layout.addWidget(create_button)
        root.addWidget(buttons)

        if self.initial_report is not None:
            self.game_name_input.setText(self.initial_report.game_name)
            self.translator_input.setText(self.initial_report.translator)
            self.tester_input.setText(self.initial_report.tester)
            self.source_language_input.setCurrentText(
                normalize_source_language(self.initial_report.source_language)
            )
            self.target_language_input.setText(
                normalize_target_language(self.initial_report.target_language)
            )

    def _on_create_clicked(self) -> None:
        report = self.to_report()
        if not report.game_name:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el nombre del juego.")
            return
        if not report.translator:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el traductor.")
            return
        if not report.tester:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el tester.")
            return
        self.accept()

    def to_report(self) -> Report:
        report = Report()
        report.game_name = self.game_name_input.text().strip()
        report.translator = self.translator_input.text().strip()
        report.tester = self.tester_input.text().strip()
        report.source_language = normalize_source_language(
            self.source_language_input.currentText().strip()
        )
        report.target_language = normalize_target_language(
            self.target_language_input.text().strip() or TARGET_LANGUAGE
        )
        report.report_date = QDate.currentDate().toString("yyyy-MM-dd")
        return report


class ReportEditorWindow(QMainWindow):
    def __init__(self, report: Report | None = None, project_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("QA Report Builder - Editor")
        self.resize(1280, 820)

        self.report = report if report is not None else Report()
        self.project_path = project_path
        self.current_preview_path: str | None = None
        self._ocr_thread: QThread | None = None
        self._ocr_worker: OcrWorker | None = None
        self._ocr_runtime_dir = Path("runtime") / "ocr_crops"

        self._build_ui()
        self._refresh_screenshots()
        self._refresh_preview()
        if self.project_path:
            self._update_title_with_path()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._build_toolbar_actions()
        root.addWidget(self._build_buttons_row())
        root.addWidget(self._build_main_splitter(), stretch=1)

        self.setCentralWidget(central)

    def _build_toolbar_actions(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Archivo")

        save_json_action = QAction("Guardar", self)
        save_json_action.setShortcut(QKeySequence.StandardKey.Save)
        save_json_action.triggered.connect(self.save_json_report)
        file_menu.addAction(save_json_action)

        save_json_as_action = QAction("Guardar como...", self)
        save_json_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_json_as_action.triggered.connect(self.save_json_report_as)
        file_menu.addAction(save_json_as_action)

        load_json_action = QAction("Abrir informe...", self)
        load_json_action.triggered.connect(self.load_json_report)
        file_menu.addAction(load_json_action)

        edit_header_action = QAction("Editar datos del informe...", self)
        edit_header_action.triggered.connect(self.edit_report_data)
        file_menu.addAction(edit_header_action)

    def _default_save_dir(self) -> str:
        if self.project_path:
            return self.project_path
        docs_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return docs_dir or ""

    def _default_docx_path(self) -> str:
        docs_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default_dir = Path(docs_dir) if docs_dir else Path.cwd()

        if self.project_path:
            project_ref = Path(self.project_path)
            base_name = project_ref.stem
            target_dir = project_ref.parent
        else:
            base_name = self.report.game_name.strip() if self.report.game_name else "proyecto"
            target_dir = default_dir

        safe_name = "".join(ch if (ch.isalnum() or ch in "_-") else "_" for ch in base_name)
        safe_name = safe_name.strip("_") or "proyecto"
        return str(target_dir / f"{safe_name}_informe_testeo.docx")

    def _build_buttons_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_new_report = QPushButton("Nuevo informe")
        self.btn_load_images = QPushButton("Cargar imagenes")
        self.btn_capture_screen = QPushButton("Capturar pantalla")
        self.btn_edit_screenshot = QPushButton("Editar captura")
        self.btn_delete_screenshot = QPushButton("Eliminar captura")
        self.btn_ocr_selection = QPushButton("OCR por seleccion")
        self.btn_export = QPushButton("Exportar Word")

        self.btn_new_report.clicked.connect(self.new_report)
        self.btn_load_images.clicked.connect(self.add_screenshots)
        self.btn_capture_screen.clicked.connect(self.capture_screen_image)
        self.btn_edit_screenshot.clicked.connect(self.edit_selected_screenshot)
        self.btn_delete_screenshot.clicked.connect(self.delete_selected_screenshot)
        self.btn_ocr_selection.clicked.connect(self.start_ocr_selection)
        self.btn_export.clicked.connect(self.export_to_word)

        layout.addWidget(self.btn_new_report)
        layout.addWidget(self.btn_load_images)
        layout.addWidget(self.btn_capture_screen)
        layout.addWidget(self.btn_edit_screenshot)
        layout.addWidget(self.btn_delete_screenshot)
        layout.addWidget(self.btn_ocr_selection)
        layout.addStretch(1)
        layout.addWidget(self.btn_export)
        return row

    def _build_main_splitter(self) -> QSplitter:
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(self._build_left_panel())
        self.main_splitter.addWidget(self._build_right_panel())
        self.main_splitter.setSizes([320, 900])
        return self.main_splitter

    def _build_left_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("Capturas")
        title.setStyleSheet("font-weight: bold;")
        self.screenshot_list = QListWidget()
        self.screenshot_list.currentRowChanged.connect(self.on_screenshot_selected)
        self.screenshot_list.itemDoubleClicked.connect(lambda _item: self.edit_selected_screenshot())

        layout.addWidget(title)
        layout.addWidget(self.screenshot_list, stretch=1)
        return widget

    def _build_right_panel(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.right_splitter = QSplitter(Qt.Vertical)

        preview_box = QWidget()
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)

        self.preview_label = SelectionPreviewLabel("Selecciona una captura para vista previa")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(360)
        self.preview_label.setStyleSheet(
            "border: 1px solid #666; background-color: #111; color: #ddd; padding: 8px;"
        )
        self.preview_label.selectionCompleted.connect(self._on_ocr_selection_completed)
        self.preview_label.selectionCancelled.connect(self._on_ocr_selection_cancelled)

        preview_layout.addWidget(QLabel("Vista previa"))
        preview_layout.addWidget(self.preview_label, stretch=1)

        details_box = QWidget()
        details_layout = QVBoxLayout(details_box)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(8)

        details_layout.addWidget(QLabel("Errores de la captura"))

        issue_nav_row = QWidget()
        issue_nav_layout = QHBoxLayout(issue_nav_row)
        issue_nav_layout.setContentsMargins(0, 0, 0, 0)
        issue_nav_layout.setSpacing(8)

        self.btn_prev_issue = QPushButton("Anterior")
        self.issue_selector = QComboBox()
        self.btn_next_issue = QPushButton("Siguiente")
        self.issue_selector.currentIndexChanged.connect(self.on_issue_selected)
        self.btn_prev_issue.clicked.connect(self.select_previous_issue)
        self.btn_next_issue.clicked.connect(self.select_next_issue)

        issue_nav_layout.addWidget(self.btn_prev_issue)
        issue_nav_layout.addWidget(self.issue_selector, stretch=1)
        issue_nav_layout.addWidget(self.btn_next_issue)
        details_layout.addWidget(issue_nav_row)

        form_box = QGroupBox("Detalle de error")
        form_layout = QFormLayout(form_box)
        self.wrong_text_input = QTextEdit()
        self.correction_input = QTextEdit()
        self.note_input = QTextEdit()
        self.wrong_text_input.setFixedHeight(70)
        self.correction_input.setFixedHeight(70)
        self.note_input.setFixedHeight(60)

        form_layout.addRow("Texto erroneo:", self.wrong_text_input)
        form_layout.addRow("Correccion:", self.correction_input)
        form_layout.addRow("Nota (opcional):", self.note_input)
        details_layout.addWidget(form_box)

        buttons = QWidget()
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)

        self.btn_add_issue = QPushButton("Agregar error")
        self.btn_save_issue = QPushButton("Guardar cambios del error")
        self.btn_delete_issue = QPushButton("Eliminar error")

        self.btn_add_issue.clicked.connect(self.add_issue)
        self.btn_save_issue.clicked.connect(self.save_issue_changes)
        self.btn_delete_issue.clicked.connect(self.delete_issue)

        buttons_layout.addWidget(self.btn_add_issue)
        buttons_layout.addWidget(self.btn_save_issue)
        buttons_layout.addWidget(self.btn_delete_issue)

        details_layout.addWidget(buttons)

        self.right_splitter.addWidget(preview_box)
        self.right_splitter.addWidget(details_box)
        self.right_splitter.setSizes([500, 500])
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)

        layout.addWidget(self.right_splitter, stretch=1)
        self._update_issue_selector_state(0, -1)
        return widget

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_preview()

    def edit_report_data(self) -> None:
        dialog = InitialDataDialog(
            self,
            initial_report=self.report,
            submit_label="Guardar cambios",
        )
        if dialog.exec() != QDialog.Accepted:
            return

        updated = dialog.to_report()
        self.report.game_name = updated.game_name
        self.report.translator = updated.translator
        self.report.tester = updated.tester
        self.report.source_language = updated.source_language
        self.report.target_language = updated.target_language
        self.report.report_date = updated.report_date

    def new_report(self) -> None:
        answer = QMessageBox.question(
            self,
            "Nuevo informe",
            "Se limpiaran capturas y errores del informe actual. Continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.report.screenshots = []
        self.current_preview_path = None
        self._refresh_screenshots()
        self._clear_issue_form()
        self.preview_label.clear_source("Selecciona una captura para vista previa")

    def add_screenshots(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar capturas",
            "",
            "Imagenes (*.png *.jpg *.jpeg *.bmp *.webp *.tiff)",
        )
        if not files:
            return

        initial_count = len(self.report.screenshots)
        invalid_files: list[str] = []
        for file_path in files:
            if is_image_loadable(file_path):
                self._append_screenshot(file_path)
            else:
                invalid_files.append(Path(file_path).name)

        added = len(self.report.screenshots) - initial_count
        if added > 0:
            self._refresh_screenshots(preferred_row=len(self.report.screenshots) - 1)
        else:
            self._refresh_screenshots()

        if invalid_files:
            QMessageBox.warning(
                self,
                "Imagenes ignoradas",
                "No se pudieron cargar estas imagenes:\n- " + "\n- ".join(invalid_files),
            )

    def capture_screen_image(self) -> None:
        self.hide()
        QApplication.processEvents()

        try:
            captured, virtual_rect = self._grab_virtual_desktop()
            if captured.isNull() or not virtual_rect.isValid():
                QMessageBox.critical(self, "Captura", "No se pudo obtener la captura de pantalla.")
                return

            snip_dialog = ScreenSnipDialog(captured, virtual_rect, None)
            if snip_dialog.exec() != QDialog.Accepted:
                self.statusBar().showMessage("Captura cancelada.", 2000)
                return

            selected = snip_dialog.selected_rect()
            if selected.width() < 6 or selected.height() < 6:
                QMessageBox.warning(self, "Captura", "La seleccion es demasiado pequena.")
                return

            captured = captured.copy(selected)
            if captured.isNull():
                QMessageBox.critical(self, "Captura", "No se pudo recortar la captura seleccionada.")
                return

            out_dir = Path("runtime") / "screen_captures"
            out_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            out_path = out_dir / f"screen_capture_{timestamp}.png"
            if not captured.save(str(out_path), "PNG"):
                QMessageBox.critical(self, "Captura", "No se pudo guardar la captura en disco.")
                return

            self._append_screenshot(str(out_path))
            self._refresh_screenshots(preferred_row=len(self.report.screenshots) - 1)
            self.statusBar().showMessage(f"Captura agregada: {out_path.name}", 3000)
        finally:
            self.show()
            self.raise_()
            self.activateWindow()

    def _grab_virtual_desktop(self) -> tuple[QPixmap, QRect]:
        screens = QGuiApplication.screens()
        if not screens:
            return QPixmap(), QRect()

        virtual_rect = QRect()
        for screen in screens:
            virtual_rect = virtual_rect.united(screen.geometry())

        if not virtual_rect.isValid() or virtual_rect.width() <= 0 or virtual_rect.height() <= 0:
            return QPixmap(), QRect()

        canvas = QPixmap(virtual_rect.size())
        canvas.fill(Qt.GlobalColor.black)
        painter = QPainter(canvas)
        for screen in screens:
            shot = screen.grabWindow(0)
            if shot.isNull():
                continue
            offset = screen.geometry().topLeft() - virtual_rect.topLeft()
            painter.drawPixmap(offset, shot)
        painter.end()
        return canvas, virtual_rect

    def _append_screenshot(self, image_path: str) -> None:
        self.report.screenshots.append(ScreenshotEntry(image_path=image_path))

    def delete_selected_screenshot(self) -> None:
        idx = self.screenshot_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Sin seleccion", "Selecciona una captura para eliminar.")
            return

        answer = QMessageBox.question(
            self,
            "Eliminar captura",
            "Se eliminara la captura seleccionada y sus errores asociados. Continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.report.screenshots.pop(idx)
        self._refresh_screenshots()
        self._clear_issue_form()
        self._refresh_preview()

    def edit_selected_screenshot(self) -> None:
        idx = self.screenshot_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "Sin seleccion", "Selecciona una captura para editar.")
            return

        current_path = self.report.screenshots[idx].image_path
        replacement_path, _ = QFileDialog.getOpenFileName(
            self,
            "Reemplazar captura",
            str(Path(current_path).parent),
            "Imagenes (*.png *.jpg *.jpeg *.bmp *.webp *.tiff)",
        )
        if not replacement_path:
            return

        if not is_image_loadable(replacement_path):
            QMessageBox.warning(self, "Imagen invalida", "No se pudo cargar la imagen seleccionada.")
            return

        self.report.screenshots[idx].image_path = replacement_path
        self._refresh_screenshots()
        self.screenshot_list.setCurrentRow(idx)

    def on_screenshot_selected(self, row: int) -> None:
        self.preview_label.cancel_selection_mode(silent=True)
        self._refresh_issues_for_screenshot(row)
        self._refresh_preview()
        if self.issue_selector.count() == 0:
            self._clear_issue_form()

    def on_issue_selected(self, row: int) -> None:
        shot_idx = self.screenshot_list.currentRow()
        if shot_idx < 0:
            return
        if row < 0:
            self._clear_issue_form()
            return

        issue = self.report.screenshots[shot_idx].issues[row]
        self.wrong_text_input.setPlainText(issue.wrong_text)
        self.correction_input.setPlainText(issue.correction)
        self.note_input.setPlainText(issue.note)
        self._update_issue_selector_state(len(self.report.screenshots[shot_idx].issues), row)

    def select_previous_issue(self) -> None:
        current = self.issue_selector.currentIndex()
        if current > 0:
            self.issue_selector.setCurrentIndex(current - 1)

    def select_next_issue(self) -> None:
        current = self.issue_selector.currentIndex()
        total = self.issue_selector.count()
        if 0 <= current < (total - 1):
            self.issue_selector.setCurrentIndex(current + 1)

    def add_issue(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        if shot_idx < 0:
            QMessageBox.warning(self, "Sin captura", "Selecciona una captura primero.")
            return

        wrong = self.wrong_text_input.toPlainText().strip()
        correction = self.correction_input.toPlainText().strip()
        note = self.note_input.toPlainText().strip()

        if not wrong:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el texto erroneo.")
            return
        if not correction:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar la correccion.")
            return

        self.report.screenshots[shot_idx].issues.append(
            Issue(wrong_text=wrong, correction=correction, note=note)
        )
        self._refresh_issues_for_screenshot(shot_idx)
        self.issue_selector.setCurrentIndex(len(self.report.screenshots[shot_idx].issues) - 1)

    def save_issue_changes(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        issue_idx = self.issue_selector.currentIndex()

        if shot_idx < 0:
            QMessageBox.warning(self, "Sin captura", "Selecciona una captura primero.")
            return
        if issue_idx < 0:
            QMessageBox.warning(self, "Sin error", "Selecciona un error para guardar cambios.")
            return

        wrong = self.wrong_text_input.toPlainText().strip()
        correction = self.correction_input.toPlainText().strip()
        note = self.note_input.toPlainText().strip()

        if not wrong:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el texto erroneo.")
            return
        if not correction:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar la correccion.")
            return

        issue = self.report.screenshots[shot_idx].issues[issue_idx]
        issue.wrong_text = wrong
        issue.correction = correction
        issue.note = note

        self._refresh_issues_for_screenshot(shot_idx)
        self.issue_selector.setCurrentIndex(issue_idx)

    def delete_issue(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        issue_idx = self.issue_selector.currentIndex()

        if shot_idx < 0:
            QMessageBox.warning(self, "Sin captura", "Selecciona una captura primero.")
            return
        if issue_idx < 0:
            QMessageBox.warning(self, "Sin error", "Selecciona un error para eliminar.")
            return

        self.report.screenshots[shot_idx].issues.pop(issue_idx)
        self._refresh_issues_for_screenshot(shot_idx)
        remaining = len(self.report.screenshots[shot_idx].issues)
        if remaining <= 0:
            self._clear_issue_form()
            return
        next_idx = min(issue_idx, remaining - 1)
        self.issue_selector.setCurrentIndex(next_idx)

    def start_ocr_selection(self) -> None:
        if self._ocr_thread is not None and self._ocr_thread.isRunning():
            QMessageBox.information(self, "OCR en progreso", "Espera a que termine el OCR actual.")
            return

        shot_idx = self.screenshot_list.currentRow()
        if shot_idx < 0:
            QMessageBox.warning(self, "Sin captura", "Selecciona una captura primero.")
            return
        if shot_idx >= len(self.report.screenshots):
            QMessageBox.warning(self, "Sin captura", "La captura seleccionada no es valida.")
            return

        image_path = self.report.screenshots[shot_idx].image_path
        if not is_image_loadable(image_path):
            QMessageBox.warning(self, "Imagen invalida", "No se pudo cargar la captura seleccionada.")
            return
        if not self.preview_label.begin_selection_mode():
            QMessageBox.warning(self, "Vista previa", "No hay vista previa disponible para OCR.")
            return

        self.statusBar().showMessage(
            "Modo OCR activo: dibuja un rectangulo sobre el texto a reconocer."
        )

    def _on_ocr_selection_cancelled(self) -> None:
        self.statusBar().clearMessage()

    def _on_ocr_selection_completed(self, image_rect: QRect) -> None:
        if image_rect.width() < 12 or image_rect.height() < 12:
            QMessageBox.warning(
                self,
                "Seleccion pequena",
                "La seleccion es demasiado pequena para OCR. Intenta con un area mayor.",
            )
            self.statusBar().clearMessage()
            return

        shot_idx = self.screenshot_list.currentRow()
        if shot_idx < 0 or shot_idx >= len(self.report.screenshots):
            QMessageBox.warning(self, "Sin captura", "No hay captura seleccionada para OCR.")
            self.statusBar().clearMessage()
            return

        source_image_path = self.report.screenshots[shot_idx].image_path
        if not is_image_loadable(source_image_path):
            QMessageBox.warning(self, "Imagen invalida", "No se pudo cargar la imagen para recortar.")
            self.statusBar().clearMessage()
            return

        try:
            crop_path = self._save_ocr_crop(source_image_path, image_rect)
        except ValueError as exc:
            QMessageBox.warning(self, "Seleccion invalida", str(exc))
            self.statusBar().clearMessage()
            return
        except (OSError, UnidentifiedImageError) as exc:
            QMessageBox.critical(self, "Error", f"No se pudo recortar la imagen:\n{exc}")
            self.statusBar().clearMessage()
            return

        self._start_ocr_worker(crop_path)

    def _save_ocr_crop(self, source_image_path: str, image_rect: QRect) -> Path:
        self._ocr_runtime_dir.mkdir(parents=True, exist_ok=True)
        crop_path = self._ocr_runtime_dir / f"ocr_crop_{uuid4().hex}.png"

        left = int(image_rect.left())
        top = int(image_rect.top())
        right = left + int(image_rect.width())
        bottom = top + int(image_rect.height())
        if right <= left or bottom <= top:
            raise ValueError("La seleccion debe tener ancho y alto mayores a cero.")

        with Image.open(source_image_path) as image:
            image_w, image_h = image.size
            left = max(0, min(image_w - 1, left))
            top = max(0, min(image_h - 1, top))
            right = max(left + 1, min(image_w, right))
            bottom = max(top + 1, min(image_h, bottom))
            if right - left < 2 or bottom - top < 2:
                raise ValueError("La seleccion es demasiado pequena para OCR.")
            crop = image.crop((left, top, right, bottom))
            crop.save(crop_path, format="PNG")
        return crop_path

    def _start_ocr_worker(self, crop_path: Path) -> None:
        self._set_ocr_busy(True)
        self.statusBar().showMessage("Procesando OCR...")

        thread = QThread(self)
        worker = OcrWorker(str(crop_path), self.report.target_language)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ocr_finished)
        worker.failed.connect(self._on_ocr_failed)
        worker.warning.connect(self._on_ocr_warning)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_ocr_thread_finished)

        self._ocr_thread = thread
        self._ocr_worker = worker
        thread.start()

    def _on_ocr_warning(self, message: str) -> None:
        QMessageBox.information(self, "OCR", message)

    def _on_ocr_failed(self, message: str) -> None:
        QMessageBox.critical(self, "OCR", message)

    def _on_ocr_finished(self, text: str) -> None:
        self.statusBar().clearMessage()
        selected_text = str(text or "").strip()
        if not selected_text:
            QMessageBox.information(
                self, "OCR", "No se aplico texto porque el resultado esta vacio."
            )
            return
        self.wrong_text_input.setPlainText(selected_text)
        self.statusBar().showMessage("Texto OCR aplicado en 'Texto erroneo'.", 3000)

    def _on_ocr_thread_finished(self) -> None:
        self._set_ocr_busy(False)
        self.statusBar().clearMessage()
        self._ocr_worker = None
        self._ocr_thread = None

    def _set_ocr_busy(self, is_busy: bool) -> None:
        self.btn_ocr_selection.setEnabled(not is_busy)
        self.btn_capture_screen.setEnabled(not is_busy)
        self.btn_add_issue.setEnabled(not is_busy)
        self.btn_save_issue.setEnabled(not is_busy)
        self.btn_delete_issue.setEnabled(not is_busy)
        if is_busy:
            self.btn_prev_issue.setEnabled(False)
            self.btn_next_issue.setEnabled(False)
            self.issue_selector.setEnabled(False)
            return
        self._update_issue_selector_state(
            self.issue_selector.count(),
            self.issue_selector.currentIndex(),
        )

    def export_to_word(self) -> None:
        if not self.report.game_name:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el nombre del juego.")
            return
        if not self.report.screenshots:
            QMessageBox.warning(self, "Sin capturas", "Debes cargar al menos una captura.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar informe Word",
            self._default_docx_path(),
            "Documento Word (*.docx)",
        )
        if not out_path:
            return

        if not out_path.lower().endswith(".docx"):
            out_path += ".docx"

        try:
            skipped_paths = export_report_to_docx(self.report, out_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Error de exportacion",
                f"No se pudo exportar el documento:\n{exc}",
            )
            return

        if skipped_paths:
            skipped = "\n- ".join(Path(path).name for path in skipped_paths)
            QMessageBox.warning(
                self,
                "Exportacion completada con omisiones",
                f"Informe exportado:\n{out_path}\n\n"
                f"Se omitieron {len(skipped_paths)} capturas invalidas o no disponibles:\n- {skipped}",
            )
            return
        QMessageBox.information(self, "Exportacion completada", f"Informe exportado:\n{out_path}")

    def save_json_report(self) -> None:
        if not self.project_path:
            self.save_json_report_as()
            return

        try:
            save_report_json(self.report, self.project_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo guardar el informe:\n{exc}")
            return

        self._update_title_with_path()
        add_recent_report(self.project_path)
        QMessageBox.information(self, "Guardado", f"Informe guardado en:\n{self.project_path}")

    def save_json_report_as(self) -> None:
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar informe como",
            self._default_save_dir(),
            f"Informe QA (*{REPORT_FILE_EXTENSION});;Archivo JSON (*.json)",
        )
        if not out_path:
            return

        lowered_path = out_path.lower()
        if not lowered_path.endswith(REPORT_FILE_EXTENSION) and not lowered_path.endswith(".json"):
            out_path += REPORT_FILE_EXTENSION

        try:
            save_report_json(self.report, out_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo guardar el informe:\n{exc}")
            return

        self.project_path = out_path
        self._update_title_with_path()
        add_recent_report(out_path)
        QMessageBox.information(self, "Guardado", f"Informe guardado en:\n{out_path}")

    def load_json_report(self) -> None:
        in_path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir informe",
            "",
            f"Informe QA (*{REPORT_FILE_EXTENSION});;Archivo JSON (*.json)",
        )
        if not in_path:
            return

        self._load_project_path(in_path)

    def _load_project_path(self, in_path: str) -> None:
        try:
            report = load_report_json(in_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo abrir el informe:\n{exc}")
            return

        self.report = report
        self.project_path = in_path
        self._update_title_with_path()
        self._refresh_screenshots()
        self._clear_issue_form()
        self._refresh_preview()
        add_recent_report(in_path)

    def _update_title_with_path(self) -> None:
        if not self.project_path:
            self.setWindowTitle("QA Report Builder - Editor")
            return
        self.setWindowTitle(f"QA Report Builder - Editor - {Path(self.project_path).name}")

    def _refresh_screenshots(self, preferred_row: int | None = None) -> None:
        previous_row = self.screenshot_list.currentRow()
        self.screenshot_list.clear()
        for idx, shot in enumerate(self.report.screenshots, start=1):
            name = Path(shot.image_path).name
            item = QListWidgetItem(f"{idx}. {name}")
            item.setToolTip(shot.image_path)
            self.screenshot_list.addItem(item)

        if self.report.screenshots:
            target_row = 0
            if preferred_row is not None and 0 <= preferred_row < len(self.report.screenshots):
                target_row = preferred_row
            elif 0 <= previous_row < len(self.report.screenshots):
                target_row = previous_row
            self.screenshot_list.setCurrentRow(target_row)
        else:
            self.issue_selector.clear()
            self._update_issue_selector_state(0, -1)

    def _refresh_issues_for_screenshot(self, shot_idx: int) -> None:
        self.issue_selector.blockSignals(True)
        self.issue_selector.clear()
        if shot_idx < 0 or shot_idx >= len(self.report.screenshots):
            self.issue_selector.blockSignals(False)
            self._update_issue_selector_state(0, -1)
            return

        issues = self.report.screenshots[shot_idx].issues
        for idx, issue in enumerate(issues, start=1):
            preview = issue.wrong_text.strip().replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "..."
            self.issue_selector.addItem(f"{idx}. {preview}")

        self.issue_selector.blockSignals(False)
        if issues:
            self.issue_selector.setCurrentIndex(0)
            self._update_issue_selector_state(len(issues), 0)
        else:
            self._update_issue_selector_state(0, -1)

    def _update_issue_selector_state(self, total: int, current: int) -> None:
        has_issues = total > 0 and current >= 0
        self.btn_prev_issue.setEnabled(has_issues and current > 0)
        self.btn_next_issue.setEnabled(has_issues and current < (total - 1))
        self.issue_selector.setEnabled(total > 0)

    def _refresh_preview(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        if shot_idx < 0 or shot_idx >= len(self.report.screenshots):
            self.preview_label.clear_source("Selecciona una captura para vista previa")
            self.current_preview_path = None
            return

        image_path = self.report.screenshots[shot_idx].image_path
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.preview_label.clear_source("No se pudo cargar la vista previa de esta imagen")
            self.current_preview_path = None
            return

        self.current_preview_path = image_path
        self.preview_label.set_source_pixmap(pixmap)

    def _clear_issue_form(self) -> None:
        self.wrong_text_input.clear()
        self.correction_input.clear()
        self.note_input.clear()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QA Report Builder")
        self.resize(1180, 760)
        self.editor_windows: list[ReportEditorWindow] = []
        self.all_recent_paths: list[str] = []

        self._build_ui()
        self._load_recent_projects()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        left.setFixedWidth(250)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 20, 16, 16)
        left_layout.setSpacing(14)

        product_label = QLabel("QA Report Builder")
        product_label.setStyleSheet("font-size: 20px; font-weight: 600;")
        left_layout.addWidget(product_label)

        self.nav_list = QListWidget()
        self.nav_list.addItem("Projects")
        self.nav_list.addItem("Iniciar sesion")
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)
        left_layout.addWidget(self.nav_list, stretch=1)
        left_layout.addStretch(1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_projects_page())
        self.stack.addWidget(self._build_login_page())
        right_layout.addWidget(self.stack, stretch=1)

        root.addWidget(left)
        root.addWidget(right, stretch=1)
        self.setCentralWidget(central)

    def _build_projects_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        top_row = QWidget()
        top_layout = QHBoxLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Buscar proyectos")
        self.search_input.textChanged.connect(self._filter_recent_projects)
        self.btn_new_project = QPushButton("Nuevo proyecto")
        self.btn_open_project = QPushButton("Abrir")
        self.btn_new_project.clicked.connect(self._new_project)
        self.btn_open_project.clicked.connect(self._open_existing_project)

        top_layout.addWidget(self.search_input, stretch=1)
        top_layout.addWidget(self.btn_new_project)
        top_layout.addWidget(self.btn_open_project)

        layout.addWidget(top_row)
        layout.addWidget(QLabel("Testeos recientes"))

        self.recent_list = QListWidget()
        self.recent_list.itemDoubleClicked.connect(self._open_recent_item)
        layout.addWidget(self.recent_list, stretch=1)
        return page

    def _build_login_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Iniciar sesion")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        description = QLabel("Vista solo visual. Aun no implementado.")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)
        layout.addStretch(1)
        return page

    def _on_nav_changed(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)

    def _load_recent_projects(self) -> None:
        self.all_recent_paths = load_recent_reports()
        self._filter_recent_projects()

    def _path_key(self, raw_path: str) -> str:
        candidate = Path(str(raw_path).strip()).expanduser()
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            resolved = candidate.absolute()
        return str(resolved).casefold()

    def _filter_recent_projects(self) -> None:
        query = self.search_input.text().strip().casefold()
        self.recent_list.clear()

        for raw_path in self.all_recent_paths:
            p = Path(raw_path)
            display_name = p.stem or p.name
            full_path = str(p)
            if query and query not in display_name.casefold() and query not in full_path.casefold():
                continue

            item = QListWidgetItem(f"{display_name}\n{full_path}")
            item.setData(Qt.UserRole, full_path)
            item.setToolTip(full_path)
            self.recent_list.addItem(item)

    def _new_project(self) -> None:
        dialog = InitialDataDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        report = dialog.to_report()
        self._open_editor(report=report, project_path=None)

    def _open_existing_project(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Abrir informe",
            "",
            f"Informe QA (*{REPORT_FILE_EXTENSION});;Archivo JSON (*.json)",
        )
        if not file_path:
            return
        self._open_report_path(file_path)

    def _open_recent_item(self, item: QListWidgetItem) -> None:
        file_path = str(item.data(Qt.UserRole) or "").strip()
        if not file_path:
            return
        self._open_report_path(file_path)

    def _open_report_path(self, file_path: str) -> None:
        try:
            report = load_report_json(file_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo abrir el informe:\n{exc}")
            self._remove_recent_path(file_path)
            return

        add_recent_report(file_path)
        self._open_editor(report=report, project_path=file_path)
        self._load_recent_projects()

    def _open_editor(self, report: Report, project_path: str | None) -> None:
        editor = ReportEditorWindow(report=report, project_path=project_path)
        editor.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.editor_windows.append(editor)
        editor.destroyed.connect(lambda _obj=None, win=editor: self._on_editor_closed(win))
        editor.show()
        editor.raise_()
        editor.activateWindow()
        self.hide()

    def _on_editor_closed(self, win: ReportEditorWindow) -> None:
        self.editor_windows = [w for w in self.editor_windows if w is not win]
        self._load_recent_projects()
        if not self.editor_windows:
            self.show()
            self.raise_()
            self.activateWindow()

    def _remove_recent_path(self, path: str) -> None:
        path_key = self._path_key(path)
        updated = [p for p in self.all_recent_paths if self._path_key(p) != path_key]
        save_recent_reports(updated)
        self.all_recent_paths = updated
        self._filter_recent_projects()
