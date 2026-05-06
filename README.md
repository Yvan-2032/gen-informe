# QA Report Builder (Fase 2 OCR)

Aplicación de escritorio en Python para crear informes de QA/testing de traducciones de juegos, guardar proyectos (`.iarc/.json`) y exportar a Word (`.docx`).

Incluye OCR por **selección manual** sobre capturas para sugerir el campo **Texto erróneo**.

## Requisitos

- Python `3.11.9`
- Dependencias (CPU):
  - `PySide6`
  - `python-docx`
  - `Pillow`
  - `easyocr`

Instalación:

```bash
pip install -r requirements.txt
```

Entorno recomendado (Windows PowerShell):

```bash
py -3.11 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Nota GPU (opcional)

- El backend OCR principal es EasyOCR.
- La app intenta usar GPU cuando PyTorch/CUDA está disponible.
- Si GPU falla, reintenta automáticamente en CPU.
- No se fuerza instalación CUDA desde `requirements.txt`; para GPU debes instalar una versión de `torch` compatible con tu hardware/controladores.

## Ejecución

```bash
python main.py
```

## Flujo principal

1. Abrir launcher (Projects).
2. Crear o abrir proyecto.
3. Cargar capturas.
4. Registrar errores manualmente o usar OCR por selección.
5. Guardar proyecto (`Guardar`/`Guardar como`).
6. Exportar a Word.

## OCR por selección

1. Selecciona una captura.
2. Pulsa **OCR por selección**.
3. Dibuja un rectángulo sobre el texto.
4. Se recorta la zona y se ejecuta OCR en segundo plano.
5. Se abre un diálogo editable con el texto detectado.
6. Puedes usar el resultado como **Texto erróneo**, copiarlo o cancelar.

Notas:

- OCR es una ayuda, no reemplaza revisión humana.
- El resultado siempre puede editarse.
- En equipos de bajos recursos el OCR puede tardar más.

## Estructura OCR (desacoplada de UI)

```
app/ocr/
  __init__.py
  base.py
  easyocr_engine.py
  manager.py
```

La UI no llama EasyOCR directamente; usa `app.ocr.manager`.

## Archivos temporales OCR

- Recortes: `runtime/ocr_crops/`
- `runtime/` ya está ignorado por Git.

