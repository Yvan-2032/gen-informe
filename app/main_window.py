from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
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
from app.storage import load_report_json, save_report_json


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("QA Report Builder - Traducciones")
        self.resize(1280, 820)

        self.report = Report()
        self.current_preview_path: str | None = None

        self._build_ui()
        self._load_report_to_form()
        self._refresh_screenshots()

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        self._build_toolbar_actions()
        root.addWidget(self._build_header_form())
        root.addWidget(self._build_buttons_row())
        root.addWidget(self._build_main_splitter(), stretch=1)

        self.setCentralWidget(central)

    def _build_toolbar_actions(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Archivo")

        save_json_action = QAction("Guardar JSON...", self)
        save_json_action.triggered.connect(self.save_json_report)
        file_menu.addAction(save_json_action)

        load_json_action = QAction("Abrir JSON...", self)
        load_json_action.triggered.connect(self.load_json_report)
        file_menu.addAction(load_json_action)

    def _build_header_form(self) -> QGroupBox:
        box = QGroupBox("Datos del informe")
        form = QFormLayout(box)

        self.game_name_input = QLineEdit()
        self.translator_input = QLineEdit()
        self.tester_input = QLineEdit()

        self.source_language_input = QComboBox()
        self.source_language_input.addItems(SOURCE_LANGUAGES)

        self.target_language_input = QLineEdit(TARGET_LANGUAGE)
        self.target_language_input.setReadOnly(True)

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")

        form.addRow("Nombre del juego:", self.game_name_input)
        form.addRow("Traductor:", self.translator_input)
        form.addRow("Tester:", self.tester_input)
        form.addRow("Idioma original:", self.source_language_input)
        form.addRow("Idioma destino:", self.target_language_input)
        form.addRow("Fecha:", self.date_input)
        return box

    def _build_buttons_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.btn_new_report = QPushButton("Nuevo informe")
        self.btn_load_images = QPushButton("Cargar imagenes")
        self.btn_edit_screenshot = QPushButton("Editar captura")
        self.btn_delete_screenshot = QPushButton("Eliminar captura")
        self.btn_export = QPushButton("Exportar Word")

        self.btn_new_report.clicked.connect(self.new_report)
        self.btn_load_images.clicked.connect(self.add_screenshots)
        self.btn_edit_screenshot.clicked.connect(self.edit_selected_screenshot)
        self.btn_delete_screenshot.clicked.connect(self.delete_selected_screenshot)
        self.btn_export.clicked.connect(self.export_to_word)

        layout.addWidget(self.btn_new_report)
        layout.addWidget(self.btn_load_images)
        layout.addWidget(self.btn_edit_screenshot)
        layout.addWidget(self.btn_delete_screenshot)
        layout.addStretch(1)
        layout.addWidget(self.btn_export)
        return row

    def _build_main_splitter(self) -> QSplitter:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([320, 900])
        return splitter

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

        self.preview_label = QLabel("Selecciona una captura para vista previa")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(300)
        self.preview_label.setStyleSheet(
            "border: 1px solid #666; background-color: #111; color: #ddd; padding: 8px;"
        )

        layout.addWidget(QLabel("Vista previa"))
        layout.addWidget(self.preview_label, stretch=1)
        layout.addWidget(QLabel("Errores de la captura"))

        self.issue_list = QListWidget()
        self.issue_list.currentRowChanged.connect(self.on_issue_selected)
        layout.addWidget(self.issue_list, stretch=1)

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
        layout.addWidget(form_box)

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

        layout.addWidget(buttons)
        return widget

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_preview()

    def _load_report_to_form(self) -> None:
        self.game_name_input.setText(self.report.game_name)
        self.translator_input.setText(self.report.translator)
        self.tester_input.setText(self.report.tester)
        self.source_language_input.setCurrentText(
            normalize_source_language(self.report.source_language)
        )
        self.target_language_input.setText(
            normalize_target_language(self.report.target_language)
        )
        parsed_date = QDate.fromString(self.report.report_date, "yyyy-MM-dd")
        if not parsed_date.isValid():
            parsed_date = QDate.currentDate()
        self.date_input.setDate(parsed_date)

    def _read_form_to_report(self) -> None:
        self.report.game_name = self.game_name_input.text().strip()
        self.report.translator = self.translator_input.text().strip()
        self.report.tester = self.tester_input.text().strip()
        self.report.source_language = normalize_source_language(
            self.source_language_input.currentText().strip()
        )
        self.report.target_language = normalize_target_language(
            self.target_language_input.text().strip() or TARGET_LANGUAGE
        )
        self.report.report_date = self.date_input.date().toString("yyyy-MM-dd")

    def new_report(self) -> None:
        answer = QMessageBox.question(
            self,
            "Nuevo informe",
            "Se limpiaran los datos actuales. Continuar?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.report = Report()
        self.current_preview_path = None
        self._load_report_to_form()
        self._refresh_screenshots()
        self._clear_issue_form()
        self.preview_label.setText("Selecciona una captura para vista previa")
        self.preview_label.setPixmap(QPixmap())

    def add_screenshots(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Seleccionar capturas",
            "",
            "Imagenes (*.png *.jpg *.jpeg *.bmp *.webp *.tiff)",
        )
        if not files:
            return

        invalid_files: list[str] = []
        added = 0
        for file_path in files:
            if is_image_loadable(file_path):
                self.report.screenshots.append(ScreenshotEntry(image_path=file_path))
                added += 1
            else:
                invalid_files.append(Path(file_path).name)

        self._refresh_screenshots()

        if added > 0 and self.screenshot_list.currentRow() < 0:
            self.screenshot_list.setCurrentRow(0)

        if invalid_files:
            QMessageBox.warning(
                self,
                "Imagenes ignoradas",
                "No se pudieron cargar estas imagenes:\n- " + "\n- ".join(invalid_files),
            )

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
        self._refresh_issues_for_screenshot(row)
        self._refresh_preview()
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
        self.issue_list.setCurrentRow(len(self.report.screenshots[shot_idx].issues) - 1)

    def save_issue_changes(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        issue_idx = self.issue_list.currentRow()

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
        self.issue_list.setCurrentRow(issue_idx)

    def delete_issue(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        issue_idx = self.issue_list.currentRow()

        if shot_idx < 0:
            QMessageBox.warning(self, "Sin captura", "Selecciona una captura primero.")
            return
        if issue_idx < 0:
            QMessageBox.warning(self, "Sin error", "Selecciona un error para eliminar.")
            return

        self.report.screenshots[shot_idx].issues.pop(issue_idx)
        self._refresh_issues_for_screenshot(shot_idx)
        self._clear_issue_form()

    def export_to_word(self) -> None:
        self._read_form_to_report()

        if not self.report.game_name:
            QMessageBox.warning(self, "Dato faltante", "Debes ingresar el nombre del juego.")
            return
        if not self.report.screenshots:
            QMessageBox.warning(self, "Sin capturas", "Debes cargar al menos una captura.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar informe Word", "", "Documento Word (*.docx)"
        )
        if not out_path:
            return

        if not out_path.lower().endswith(".docx"):
            out_path += ".docx"

        try:
            export_report_to_docx(self.report, out_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "Error de exportacion",
                f"No se pudo exportar el documento:\n{exc}",
            )
            return

        QMessageBox.information(self, "Exportacion completada", f"Informe exportado:\n{out_path}")

    def save_json_report(self) -> None:
        self._read_form_to_report()
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Guardar informe JSON", "", "Archivo JSON (*.json)"
        )
        if not out_path:
            return

        if not out_path.lower().endswith(".json"):
            out_path += ".json"

        try:
            save_report_json(self.report, out_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo guardar el JSON:\n{exc}")
            return

        QMessageBox.information(self, "Guardado", f"Informe guardado en:\n{out_path}")

    def load_json_report(self) -> None:
        in_path, _ = QFileDialog.getOpenFileName(
            self, "Abrir informe JSON", "", "Archivo JSON (*.json)"
        )
        if not in_path:
            return

        try:
            report = load_report_json(in_path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Error", f"No se pudo abrir el JSON:\n{exc}")
            return

        self.report = report
        self._load_report_to_form()
        self._refresh_screenshots()
        self._clear_issue_form()
        self._refresh_preview()

    def _refresh_screenshots(self) -> None:
        self.screenshot_list.clear()
        for idx, shot in enumerate(self.report.screenshots, start=1):
            name = Path(shot.image_path).name
            item = QListWidgetItem(f"{idx}. {name}")
            item.setToolTip(shot.image_path)
            self.screenshot_list.addItem(item)

        if self.report.screenshots:
            self.screenshot_list.setCurrentRow(0)
        else:
            self.issue_list.clear()

    def _refresh_issues_for_screenshot(self, shot_idx: int) -> None:
        self.issue_list.clear()
        if shot_idx < 0 or shot_idx >= len(self.report.screenshots):
            return

        issues = self.report.screenshots[shot_idx].issues
        for idx, issue in enumerate(issues, start=1):
            preview = issue.wrong_text.strip().replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "..."
            self.issue_list.addItem(f"{idx}. {preview}")

    def _refresh_preview(self) -> None:
        shot_idx = self.screenshot_list.currentRow()
        if shot_idx < 0 or shot_idx >= len(self.report.screenshots):
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("Selecciona una captura para vista previa")
            self.current_preview_path = None
            return

        image_path = self.report.screenshots[shot_idx].image_path
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("No se pudo cargar la vista previa de esta imagen")
            self.current_preview_path = None
            return

        self.current_preview_path = image_path
        scaled = pixmap.scaled(
            self.preview_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(scaled)

    def _clear_issue_form(self) -> None:
        self.wrong_text_input.clear()
        self.correction_input.clear()
        self.note_input.clear()
