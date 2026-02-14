<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**Un Visor DICOM y Herramienta de Análisis de Imágenes Moderno y Multiplataforma**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.9+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

[English](README.md) | [简体中文](README_zh.md) | [Deutsch](README_de.md) | **Español** | [Français](README_fr.md)

</div>

MedImager es un visor de imágenes médicas de código abierto potente, fácil de usar y orientado a la investigación. Su objetivo es proporcionar interacción fluida con imágenes, soporte multi-formato (DICOM, PNG, etc.) y funciones de análisis avanzadas para flujos de trabajo académicos y clínicos.

## 1. Visión del Proyecto

Crear un visor de imágenes médicas de código abierto potente, fácil de usar y orientado a la investigación. MedImager tiene como objetivo proporcionar interacción fluida con imágenes, soporte multi-formato (DICOM, PNG, etc.) y funciones de análisis avanzadas para flujos de trabajo académicos y clínicos, aspirando a ser una alternativa de código abierto a RadiAnt.

<div align="center">

![MedImager Demo](preview.png)

</div>

## 2. Características Principales (Hoja de Ruta)

### ✅ V1.0 - Características Principales (COMPLETADO)
- [x] **Manejo de Archivos:**
    - [x] Abrir y analizar series DICOM desde carpetas.
    - [x] Abrir archivos de imagen individuales (PNG, JPG, BMP).
    - [x] Visor de etiquetas DICOM.
- [x] **Visualización de Imágenes:**
    - [x] Visor 2D con desplazamiento y zoom suaves.
    - [x] Multi-viewport para comparación de imágenes con diseños flexibles.
    - [x] Mostrar información del paciente y superposiciones de imagen (escala, marcador de orientación).
- [x] **Herramientas de Interacción con Imágenes:**
    - [x] **Ventana:** Ajuste interactivo del ancho/nivel de ventana HU (WW/WL) con preajustes en la barra de herramientas.
    - [x] **Herramientas de Medición:**
        - [x] Herramienta de regla para medición de distancias.
        - [x] Herramienta de medición de ángulos.
        - [x] Herramientas ROI de elipse/rectángulo/círculo.
    - [x] **Análisis ROI:** Calcular estadísticas dentro de ROI (media, desv. est., área, HU máx/mín).
    - [x] **Transformaciones de Imagen:** Voltear (horizontal/vertical), rotar (90° izquierda/derecha), invertir, con estado independiente por vista.
    - [x] **Reproducción Cine:** Reproducción automática de cortes con FPS ajustable.
    - [x] **Exportación de Imagen:** Exportar vista actual como PNG/JPG, o copiar al portapapeles.
- [x] **Características Avanzadas:**
    - [x] **Gestión Multi-Series:** Cargar y gestionar múltiples series DICOM simultáneamente.
    - [x] **Vinculación Serie-Vista:** Sistema de vinculación flexible con asignación automática y control manual.
    - [x] **Sincronización:** Sincronización entre viewports para posición, desplazamiento, zoom y ventana/nivel.
    - [x] **Sistema de Diseño:** Diseños de cuadrícula (1×1 a 3×4) y diseños especiales (división vertical/horizontal, triple columna).
- [x] **Interfaz de Usuario:**
    - [x] Interfaz multiidioma moderna (Chino/Inglés).
    - [x] Sistema de temas personalizable (temas claro/oscuro) con cambio en tiempo real.
    - [x] Sistema de configuración completo con personalización de apariencia de herramientas.
    - [x] Barra de herramientas unificada con iconos adaptativos al tema.
    - [x] Diseño de panel acoplable.

### V2.0 - Características Avanzadas
- [ ] **Reconstrucción Multi-Planar (MPR):** Ver planos axial, sagital y coronal desde datos de volumen 3D.
- [ ] **Renderizado de Volumen 3D:** Visualización 3D básica de series DICOM.
- [ ] **Fusión de Imágenes:** Superponer dos series diferentes (ej. PET/CT).
- [ ] **Persistencia de Anotaciones:** Guardar y recargar anotaciones (ROIs, mediciones) entre sesiones.
- [ ] **Sistema de Plugins:** Permitir a los usuarios extender funciones mediante scripts Python personalizados para investigación.

## 3. Stack Tecnológico

* **Lenguaje:** Python 3.9+
* **Framework GUI:** PySide6 (LGPL)
* **Análisis DICOM:** pydicom
* **Procesamiento Numérico/Imágenes:** NumPy
* **Visualización 2D/3D:** Qt Graphics View Framework (2D), VTK 9+ (3D)
* **Empaquetado:** PyInstaller
* **i18n:** Qt Linguist (`pylupdate6`, `lrelease`)

## 4. Estructura del Proyecto

El proyecto sigue un patrón similar a MVC para separar la lógica de datos, UI e interacción del usuario.

```
medimager/
├── main.py                 # Punto de entrada de la aplicación
├── icons/                  # Iconos UI y recursos SVG
├── translations/           # Archivos de traducción (.ts, .qm)
├── themes/                 # Archivos de configuración de temas
│   ├── ui/                 # Temas UI (dark.toml, light.toml)
│   ├── roi/                # Temas de apariencia ROI
│   └── measurement/        # Temas de herramientas de medición
│
├── core/                   # Lógica central, independiente de UI (Modelo MVC)
│   ├── __init__.py
│   ├── dicom_parser.py     # Carga/análisis DICOM vía pydicom
│   ├── image_data_model.py # Modelo de datos para imagen única o serie DICOM
│   ├── multi_series_manager.py # Gestión multi-series y control de diseño
│   ├── series_view_binding.py  # Gestión de vinculación serie-vista
│   ├── sync_manager.py     # Sincronización entre viewports
│   ├── roi.py              # Formas ROI y lógica
│   └── analysis.py         # Cálculos estadísticos (estadísticas HU, etc.)
│
├── ui/                     # Todos los componentes UI (Vista y Controlador MVC)
│   ├── __init__.py
│   ├── main_window.py      # Ventana principal con soporte multi-series
│   ├── main_toolbar.py     # Gestión de barra de herramientas unificada (herramientas, diseño, sync)
│   ├── image_viewer.py     # Visor de imágenes 2D central (QGraphicsView)
│   ├── viewport.py         # Viewport independiente con image_viewer
│   ├── multi_viewer_grid.py# Gestor de diseño de cuadrícula multi-viewport
│   ├── panels/             # Paneles acoplables
│   │   ├── __init__.py
│   │   ├── series_panel.py     # Panel de gestión multi-series
│   │   ├── dicom_tag_panel.py  # Panel de etiquetas DICOM
│   │   └── analysis_panel.py   # Panel de análisis ROI
│   ├── tools/              # Implementaciones de herramientas interactivas
│   │   ├── __init__.py
│   │   ├── base_tool.py        # Clase base abstracta para herramientas
│   │   ├── default_tool.py     # Herramienta predeterminada puntero/desplazar/zoom/ventana
│   │   ├── roi_tool.py         # Herramientas ROI (elipse, rectángulo, círculo)
│   │   └── measurement_tool.py # Herramienta de medición de distancia
│   ├── dialogs/            # Ventanas de diálogo
│   │   ├── custom_wl_dialog.py # Diálogo personalizado de ventana/nivel
│   │   └── settings_dialog.py  # Diálogo de configuración de aplicación
│   └── widgets/            # Widgets UI personalizados
│       ├── __init__.py
│       ├── magnifier.py        # Widget lupa
│       ├── roi_stats_box.py    # Visualización de estadísticas ROI
│       └── layout_grid_selector.py # Widget selector de diseño
│
├── utils/                  # Utilidades generales (Soporte Modelo MVC)
│   ├── __init__.py
│   ├── logger.py           # Configuración de logging global
│   ├── settings.py         # Gestión de configuración de usuario
│   ├── theme_manager.py    # Sistema de temas con gestión de iconos
│   └── i18n.py             # Utilidades de internacionalización
│
├── tests/                  # Pruebas unitarias/integración
│   ├── __init__.py
│   ├── dcm/                # Datos DICOM de prueba
│   ├── scripts/            # Scripts de generación de datos de prueba
│   ├── test_dicom_parser.py
│   ├── test_roi.py
│   └── test_multi_series_components.py
│
├── pyproject.toml          # Metadatos del proyecto y dependencias
└── README_zh.md            # Documentación china
```

## 5. Uso

Primero, asegúrese de tener [uv](https://github.com/astral-sh/uv) instalado. Es un instalador y resolvedor de paquetes Python extremadamente rápido.

1.  **Clonar el repositorio:**
    ```bash
    git clone https://github.com/1985312383/MedImager.git
    cd MedImager
    ```

2.  **Configurar Entorno e Instalar Dependencias:**
    ```bash
    # Crear un entorno virtual y sincronizar dependencias desde pyproject.toml
    uv venv
    uv sync
    ```

3.  **Ejecutar la aplicación:**
    ```bash
    # `uv run` ejecuta el comando dentro del entorno virtual del proyecto,
    # evitando la necesidad de activarlo en su shell.
    uv run python medimager/main.py
    ```
    Para desarrolladores que prefieren un entorno activo:
    ```bash
    # Para activar el entorno en su shell actual:
    # Windows
    .venv\\Scripts\\activate
    # macOS / Linux
    source .venv/bin/activate
    
    # Entonces puede ejecutar comandos directamente:
    python medimager/main.py
    ```

---

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Ya sea que esté corrigiendo un error, agregando una característica o mejorando la documentación, su ayuda es apreciada. No dude en abrir un issue o enviar un pull request.

## 📄 Licencia

Este proyecto está licenciado bajo la LICENCIA PÚBLICA GENERAL GNU. Consulte el archivo [LICENSE](LICENSE) para más detalles.

---

## Contribuidores

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")