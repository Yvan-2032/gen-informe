from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import (
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
from app.storage import (
    REPORT_FILE_EXTENSION,
    add_recent_report,
    load_recent_reports,
    load_report_json,
    save_recent_reports,
    save_report_json,
)


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

        save_json_action = QAction("Guardar informe...", self)
        save_json_action.triggered.connect(self.save_json_report)
        file_menu.addAction(save_json_action)

        load_json_action = QAction("Abrir informe...", self)
        load_json_action.triggered.connect(self.load_json_report)
        file_menu.addAction(load_json_action)

        edit_header_action = QAction("Editar datos del informe...", self)
        edit_header_action.triggered.connect(self.edit_report_data)
        file_menu.addAction(edit_header_action)

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
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar informe",
            self.project_path or "",
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
        self.close()

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
        self.editor_windows.append(editor)
        editor.destroyed.connect(lambda _obj=None, win=editor: self._on_editor_closed(win))
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _on_editor_closed(self, win: ReportEditorWindow) -> None:
        self.editor_windows = [w for w in self.editor_windows if w is not win]
        self._load_recent_projects()

    def _remove_recent_path(self, path: str) -> None:
        updated = [p for p in self.all_recent_paths if p.casefold() != path.casefold()]
        save_recent_reports(updated)
        self.all_recent_paths = updated
        self._filter_recent_projects()
