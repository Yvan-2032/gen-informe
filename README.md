# QA Report Builder (Fase 1 MVP)

Aplicacion de escritorio en Python para crear informes de QA/testing de traducciones de juegos y exportarlos a Word (`.docx`), sin OCR.

## Requisitos

- Python 3.10+
- Dependencias:
  - `PySide6`
  - `python-docx`
  - `Pillow`

Instalacion:

```bash
pip install -r requirements.txt
```

## Ejecucion

```bash
python main.py
```

## Flujo principal

1. Al iniciar por primera vez, completar datos del informe y pulsar **Guardar datos iniciales**.
2. Esos datos quedan guardados localmente y se reutilizan automaticamente en los siguientes inicios.
3. Cargar capturas con **Cargar imagenes**.
4. Seleccionar una captura y agregar/editar/eliminar errores.
5. Exportar con **Exportar Word**.

## Estructura

- `main.py`
- `app/main_window.py`
- `app/models.py`
- `app/docx_exporter.py`
- `app/storage.py`
- `app/image_utils.py`

Extras:

- Guardar/abrir informe desde menu **Archivo** en formato `*.iarc` (o `*.json` si prefieres).
- Los datos iniciales se guardan como perfil local `*.qaprof`.
