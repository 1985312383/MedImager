<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**Una herramienta moderna y multiplataforma de visualización de DICOM y análisis de imágenes**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

**English** | [简体中文](README_zh.md) | [Deutsch](README_de.md) | [Español](README_es.md) | [Français](README_fr.md)

</div>

MedImager es un visor de imágenes médicas y herramienta de análisis de código abierto con el objetivo a largo plazo de alcanzar flujos de trabajo de lectura de nivel RadiAnt. La versión 2.0 consolida el trabajo completado en las versiones 1.0 y 1.x en una base de DICOM 2D fiable: visualización de series múltiples, medición y análisis de ROI, cobertura profesional de DICOM sintéticos, persistencia de anotaciones y líneas base de rendimiento repetibles.

## 1. Visión del Proyecto

Crear un visor de código abierto pragmático que pueda evolucionar hacia flujos de trabajo de grado RadiAnt. MedImager 2.0 está listo como el lanzamiento de la base estable en 2D; las versiones posteriores deberán basarse en este cimiento con MPR, DICOMDIR/PACS, protocolos de suspensión (hanging protocols) y flujos de trabajo clínicos avanzados.

<div align="center">

![MedImager Demo](preview.png)

</div>

## 2. Características Principales

### ✅ V2.0 - Base DICOM 2D (LISTO)
- [x] **Manejo de Archivos:**
    - [x] Abrir y analizar series DICOM desde carpetas.
    - [x] Abrir archivos de imagen individuales (PNG, JPG, BMP).
    - [x] Visor de etiquetas (tags) DICOM.
- [x] **Visualización de Imágenes:**
    - [x] Visor 2D con desplazamiento (pan) y zoom fluidos.
    - [x] Multi-ventana para comparación de imágenes con diseños flexibles.
    - [x] Visualización de información del paciente y superposiciones de imagen (escala, marcador de orientación).
- [x] **Herramientas de Interacción con la Imagen:**
    - [x] **Ventaneo (Windowing):** Ajuste interactivo del ancho y nivel de ventana HU (WW/WL) con preajustes en la barra de herramientas.
    - [x] **Herramientas de Medición:**
        - [x] Herramienta de regla para medición de distancias.
        - [x] Herramienta de medición de ángulos.
        - [x] Herramientas de ROI de elipse/rectángulo/círculo.
    - [x] **Análisis de ROI:** Cálculo de estadísticas dentro del ROI (media, desviación estándar, área, HU máx/mín).
    - [x] **Transformaciones de Imagen:** Volteo (horizontal/vertical), rotación (90° izquierda/derecha), inversión, con estado por vista.
    - [x] **Reproducción Cine:** Reproducción automática de cortes con FPS ajustable.
    - [x] **Exportación de Imágenes:** Exportar la vista actual a PNG/JPG o copiar al portapapeles.
- [x] **Características Avanzadas:**
    - [x] **Gestión de Series Múltiples:** Cargar y gestionar múltiples series DICOM simultáneamente.
    - [x] **Vinculación Serie-Vista:** Sistema de vinculación flexible con asignación automática y control manual.
    - [x] **Sincronización:** Sincronización entre ventanas para posición, desplazamiento, zoom y ventana/nivel.
    - [x] **Sistema de Diseño (Layout):** Diseños de cuadrícula (1×1 a 3×4) y diseños especiales (división vertical/horizontal, triple columna).
- [x] **Interfaz de Usuario:**
    - [x] Interfaz moderna multilingüe (chino/inglés).
    - [x] Sistema de temas personalizable (temas claro/oscuro) con cambio en tiempo real.
    - [x] Sistema de configuración completo con personalización de la apariencia de las herramientas.
    - [x] Barra de herramientas unificada con iconos adaptables al tema.
    - [x] Diseño de paneles acoplables.
- [x] **Correctitud de DICOM y Línea Base de Calidad:**
    - [x] Conjunto de pruebas DICOM sintéticas profesionales que cubren CT/MR/CR/US/PET, etiquetas faltantes, orden inverso, geometría oblicua, datos multi-trama, sintaxis de transferencia comprimidas y variantes de PixelSpacing.
    - [x] Robustez del analizador para dependencias de decodificación, expansión de escala de grises multi-trama, advertencias de geometría inconsistente y variantes de DICOM no soportadas.
    - [x] Líneas base de rendimiento para carga de series grandes, visualización de ventana/nivel, visualización de aciertos de caché y conversión a QImage.
    - [x] Persistencia de anotaciones en JSON versionado para ROI, medición de distancia y medición de ángulos.

### Próxima Hoja de Ruta - Flujo de Trabajo Nivel RadiAnt
- [ ] **Reconstrucción Multiplanar (MPR):** Vista de los planos axial, sagital y coronal a partir de datos de volumen 3D.
- [ ] **Renderizado de Volumen 3D:** Visualización 3D básica de series DICOM.
- [ ] **Fusión de Imágenes:** Superponer dos series diferentes (ej. PET/CT).
- [ ] **DICOMDIR / PACS:** Exploración de medios locales y consulta/recuperación de red DICOM una vez que la base del analizador 2D sea estable.
- [ ] **Protocolos de Suspensión (Hanging Protocols):** Guardar y restaurar diseños de lectura prácticos para la revisión repetida de estudios.
- [ ] **Sistema de Plugins:** Permitir a los usuarios extender funcionalidades mediante scripts de Python personalizados para investigación.

## 3. Stack Tecnológico

* **Lenguaje:** Python 3.11+
* **Framework de GUI:** PySide6 (LGPL)
* **Análisis de DICOM:** pydicom
* **Procesamiento Numérico/Imágenes:** NumPy
* **Visualización 2D:** Qt Graphics View Framework
* **Empaquetado:** PyInstaller
* **i18n:** Catálogos fuente YAML compilados a catálogos JSON de tiempo de ejecución

## 4. Estructura del Proyecto

El proyecto sigue un patrón similar a MVC para separar la lógica de datos, la interfaz de usuario y la interacción del usuario.

```
medimager/
├── main.py                 # Punto de entrada de la aplicación
├── icons/                  # Iconos de UI y recursos SVG
├── i18n/                   # Catálogos fuente YAML y catálogos JSON compilados
├── themes/                 # Archivos de configuración de temas
│   ├── ui/                 # Temas de UI (dark.toml, light.toml)
│   ├── roi/                # Temas de apariencia de ROI
│   └── measurement/        # Temas de herramientas de medición
│
├── core/                   # Lógica central, independiente de la UI (Modelo MVC)
│   ├── __init__.py
│   ├── dicom_parser.py     # Carga/análisis de DICOM vía pydicom
│   ├── image_data_model.py # Modelo de datos para imagen única o series DICOM
│   ├── multi_series_manager.py # Gestión de series múltiples y control de diseño
│   ├── series_view_binding.py  # Gestión de vinculación serie-vista
│   ├── sync_manager.py     # Sincronización entre ventanas
│   ├── roi.py              # Formas y lógica de ROI
│   └── analysis.py         # Cálculos estadísticos (estadísticas HU, etc.)
│
├── ui/                     # Todos los componentes de UI (Vista y Controlador MVC)
│   ├── __init__.py
│   ├── main_window.py      # Ventana principal con soporte para series múltiples
│   ├── main_toolbar.py     # Gestión de la barra de herramientas unificada (herramientas, diseño, sync)
│   ├── image_viewer.py     # Visor de imágenes 2D central (QGraphicsView)
│   ├── viewport.py         # Ventana independiente con image_viewer
│   ├── multi_viewer_grid.py# Gestor de diseño de cuadrícula multi-ventana
│   ├── panels/             # Paneles acoplables
│   │   ├── __init__.py
│   │   ├── series_panel.py     # Panel de gestión de series múltiples
│   │   └── dicom_tag_panel.py  # Panel de etiquetas DICOM
│   ├── tools/              # Implementaciones de herramientas interactivas
│   │   ├── __init__.py
│   │   ├── base_tool.py        # Clase base abstracta para herramientas
│   │   ├── default_tool.py     # Herramienta por defecto (puntero/pan/zoom/ventana)
│   │   ├── roi_tool.py         # Herramientas de ROI (elipse, rectángulo, círculo)
│   │   ├── measurement_tool.py # Herramienta de medición de distancia
│   │   └── angle_tool.py       # Herramienta de medición de ángulos
│   ├── dialogs/            # Ventanas de diálogo
│   │   ├── custom_wl_dialog.py # Diálogo personalizado de ventana/nivel
│   │   └── settings_dialog.py  # Diálogo de configuración de la aplicación
│   └── widgets/            # Widgets de UI personalizados
│       ├── __init__.py
│       ├── magnifier.py        # Widget de lupa
│       ├── roi_stats_box.py    # Visualización de estadísticas de ROI
│       ├── layout_grid_selector.py # Widget de selección de diseño
│       └── panel_toggle_strip.py   # Widget de tira de alternancia de paneles
│
├── utils/                  # Utilidades generales (Soporte Modelo MVC)
│   ├── __init__.py
│   ├── logger.py           # Configuración global de logs
│   ├── settings.py         # Gestión de configuración del usuario
│   ├── theme_manager.py    # Sistema de temas con gestión de iconos
│   ├── resource_path.py    # Resolución de rutas de recursos/iconos
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
└── README_zh.md            # Documentación en chino
```

## 5. Uso

Primero, asegúrese de tener instalado [uv](https://github.com/astral-sh/uv). Es un instalador y resolutor de paquetes de Python extremadamente rápido.

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
    
    # Luego puede ejecutar los comandos directamente:
    python medimager/main.py
    ```

4.  **Ejecutar la línea base de rendimiento (desarrolladores):**
    ```bash
    uv run python -m medimager.performance.baseline \
      --slices 300 \
      --rows 512 \
      --cols 512 \
      --repeats 3 \
      --display-samples 64 \
      --output performance_baseline.json
    ```
    Esto crea una serie DICOM sintética desidentificada y registra los tiempos de carga de series, visualización de ventana/nivel, visualización de aciertos de caché y conversión a QImage. Las pruebas unitarias intencionalmente no imponen umbrales de rendimiento estrictos para evitar fallos específicos de la máquina; guarde el JSON antes de los lanzamientos para comparaciones entre versiones.

5.  **Actualizar traducciones (desarrolladores):**
    ```bash
    # Edite medimager/i18n/locales/*.yml primero, luego reconstruya los catálogos de tiempo de ejecución.
    python translation_tools/main.py
    ```
    El código de la UI debe usar claves estables mediante `t("...")`. No se utiliza la cadena antigua de Qt `.ts/.qm`.

---

## 🤝 Contribuir

¡Las contribuciones son bienvenidas! Ya sea que esté corrigiendo un error, añadiendo una característica o mejorando la documentación, se agradece su ayuda. No dude en abrir un issue o enviar un pull request.

## 📄 Licencia

Este proyecto está licenciado bajo la LICENCIA PÚBLICA GENERAL de GNU. Vea el archivo [LICENSE](LICENSE) para más detalles.

---

## Colaboradores

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")
