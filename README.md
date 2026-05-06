# QA Report Builder (Fase 1 MVP)

Aplicacion de escritorio en Python para crear informes de QA/testing de traducciones de juegos y exportarlos a Word (`.docx`), sin OCR.

## Requisitos

- Python 3.11.9
- Dependencias:
  - `PySide6`
  - `python-docx`
  - `Pillow`

Instalacion:

```bash
pip install -r requirements.txt
```

Si quieres recrear el entorno exactamente con esta version:

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Ejecucion

```bash
python main.py
```

## Flujo principal

1. Al iniciar, se muestra una pantalla tipo launcher con seccion **Projects**.
2. En el panel izquierdo estan **Projects** e **Iniciar sesion** (visual).
3. En **Projects**, usa **Nuevo proyecto** para abrir el popup con datos iniciales.
4. Luego se abre el editor para cargar capturas y registrar errores.
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
- Se guarda historial local de testeos recientes para mostrarlos en la pantalla inicial.
