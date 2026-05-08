<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**Ein moderner, plattformübergreifender DICOM-Viewer und Bildanalyse-Tool**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

[English](README.md) | [简体中文](README_zh.md) | **Deutsch** | [Español](README_es.md) | [Français](README_fr.md)

</div>

MedImager ist ein Open-Source-Medizinbildbetrachter und Analysewerkzeug mit dem langfristigen Ziel, sich RadiAnt-ähnlichen Befundungsabläufen anzunähern. Version 2.0 fasst die abgeschlossenen Arbeiten aus 1.0 und 1.x zu einer zuverlässigen 2D-DICOM-Basis zusammen: Multi-Serien-Anzeige, Messung und ROI-Analyse, professionelle synthetische DICOM-Testabdeckung, Annotationspersistenz und wiederholbare Performance-Baselines.

## 1. Projektvision

Erstellen Sie einen pragmatischen Open-Source-Viewer, der zu RadiAnt-ähnlichen Workflows wachsen kann. MedImager 2.0 ist als stabile 2D-Basisversion bereit; spätere Versionen sollen darauf MPR, DICOMDIR/PACS, Hanging Protocols und weitere klinikähnliche Workflows aufbauen.

<div align="center">

![MedImager Demo](preview.png)

</div>

## 2. Kernfunktionen

### ✅ V2.0 - 2D-DICOM-Basis (BEREIT)
- [x] **Dateiverarbeitung:**
    - [x] DICOM-Serien aus Ordnern öffnen und analysieren.
    - [x] Einzelne Bilddateien öffnen (PNG, JPG, BMP).
    - [x] DICOM-Tag-Viewer.
- [x] **Bildanzeige:**
    - [x] Reibungsloser Pan- und Zoom-2D-Viewer.
    - [x] Multi-Viewport für Bildvergleiche mit flexiblen Layouts.
    - [x] Anzeige von Patienteninformationen und Bildüberlagerungen (Maßstab, Orientierungsmarker).
- [x] **Bildinteraktions-Tools:**
    - [x] **Fensterung:** Interaktive Anpassung der HU-Fensterbreite/-ebene (WW/WL) mit Symbolleisten-Voreinstellungen.
    - [x] **Messwerkzeuge:**
        - [x] Lineal-Tool für Entfernungsmessungen.
        - [x] Winkelmesswerkzeug.
        - [x] Ellipse/Rechteck/Kreis-ROI-Tools.
    - [x] **ROI-Analyse:** Berechnung von Statistiken innerhalb der ROI (Mittelwert, Std, Fläche, max/min HU).
    - [x] **Bildtransformationen:** Spiegeln (horizontal/vertikal), Drehen (90° links/rechts), Invertieren, mit separatem Zustand pro Ansicht.
    - [x] **Cine-Wiedergabe:** Automatische Wiedergabe durch Schichten mit einstellbarer Bildrate.
    - [x] **Bildexport:** Aktuelle Ansicht als PNG/JPG exportieren oder in die Zwischenablage kopieren.
- [x] **Erweiterte Funktionen:**
    - [x] **Multi-Serien-Management:** Gleichzeitiges Laden und Verwalten mehrerer DICOM-Serien.
    - [x] **Serien-View-Bindung:** Flexibles Bindungssystem mit automatischer Zuweisung und manueller Kontrolle.
    - [x] **Synchronisation:** Viewport-übergreifende Synchronisation für Position, Pan, Zoom und Fenster/Ebene.
    - [x] **Layout-System:** Raster-Layouts (1×1 bis 3×4) und spezielle Layouts (vertikale/horizontale Teilung, dreispaltig).
- [x] **Benutzeroberfläche:**
    - [x] Moderne mehrsprachige Oberfläche (Chinesisch/Englisch).
    - [x] Anpassbares Themensystem (helle/dunkle Themen) mit Echtzeit-Umschaltung.
    - [x] Vollständiges Einstellungssystem mit Tool-Erscheinungsanpassung.
    - [x] Einheitliche Symbolleiste mit themenadaptiven Symbolen.
    - [x] Andockbares Panel-Layout.
- [x] **DICOM-Korrektheit und Qualitätsbasis:**
    - [x] Professioneller synthetischer DICOM-Testsatz für CT/MR/CR/US/PET, fehlende Tags, umgekehrte Sortierung, schräge Geometrie, Multi-Frame-Daten, komprimierte Transfer-Syntaxen und PixelSpacing-Varianten.
    - [x] Robuster Parser mit klaren Decoder-Abhängigkeiten, Multi-Frame-Graustufen-Entfaltung, Warnungen bei inkonsistenter Geometrie und verständlichen Fehlern für nicht unterstützte Varianten.
    - [x] Performance-Baselines für große Serien, Window/Level-Anzeige, Cache-Hits und QImage-Konvertierung.
    - [x] Versionierte JSON-Persistenz für ROI-, Distanz- und Winkelmessungs-Annotationen.

### Nächste Roadmap - RadiAnt-ähnliche Workflows
- [ ] **Multi-Planar-Rekonstruktion (MPR):** Anzeige axialer, sagittaler und koronaler Ebenen aus 3D-Volumendaten.
- [ ] **3D-Volumen-Rendering:** Grundlegende 3D-Visualisierung von DICOM-Serien.
- [ ] **Bildfusion:** Überlagerung zweier verschiedener Serien (z.B. PET/CT).
- [ ] **DICOMDIR / PACS:** Lokale Mediennavigation und DICOM-Netzwerkabfrage/-abruf nach stabiler 2D-Parser-Basis.
- [ ] **Hanging Protocols:** Praktische Leselayouts für wiederholte Studienprüfung speichern und wiederherstellen.
- [ ] **Plugin-System:** Ermöglicht Benutzern, Funktionen über benutzerdefinierte Python-Skripte für die Forschung zu erweitern.

## 3. Tech Stack

* **Sprache:** Python 3.11+
* **GUI-Framework:** PySide6 (LGPL)
* **DICOM-Parsing:** pydicom
* **Numerische/Bildverarbeitung:** NumPy
* **2D-Visualisierung:** Qt Graphics View Framework
* **Verpackung:** PyInstaller
* **i18n:** Qt Linguist (`pylupdate6`, `lrelease`)

## 4. Projektstruktur

Das Projekt folgt einem MVC-ähnlichen Muster zur Trennung von Datenlogik, UI und Benutzerinteraktion.

```
medimager/
├── main.py                 # Anwendungseinstiegspunkt
├── icons/                  # UI-Symbole und SVG-Ressourcen
├── translations/           # Übersetzungsdateien (.ts, .qm)
├── themes/                 # Theme-Konfigurationsdateien
│   ├── ui/                 # UI-Themes (dark.toml, light.toml)
│   ├── roi/                # ROI-Erscheinungsthemes
│   └── measurement/        # Messwerkzeug-Themes
│
├── core/                   # Kernlogik, UI-unabhängig (MVC-Modell)
│   ├── __init__.py
│   ├── dicom_parser.py     # DICOM-Laden/Parsing über pydicom
│   ├── image_data_model.py # Datenmodell für einzelnes Bild oder DICOM-Serie
│   ├── multi_series_manager.py # Multi-Serien-Management und Layout-Kontrolle
│   ├── series_view_binding.py  # Serien-View-Bindungsmanagement
│   ├── sync_manager.py     # Viewport-übergreifende Synchronisation
│   ├── roi.py              # ROI-Formen und -Logik
│   └── analysis.py         # Statistische Berechnungen (HU-Statistiken usw.)
│
├── ui/                     # Alle UI-Komponenten (MVC View & Controller)
│   ├── __init__.py
│   ├── main_window.py      # Hauptfenster mit Multi-Serien-Unterstützung
│   ├── main_toolbar.py     # Einheitliches Symbolleisten-Management (Tools, Layout, Sync)
│   ├── image_viewer.py     # Kern-2D-Bildbetrachter (QGraphicsView)
│   ├── viewport.py         # Eigenständiger Viewport mit image_viewer
│   ├── multi_viewer_grid.py# Multi-Viewport-Raster-Layout-Manager
│   ├── panels/             # Andockbare Panels
│   │   ├── __init__.py
│   │   ├── series_panel.py     # Multi-Serien-Management-Panel
│   │   ├── dicom_tag_panel.py  # DICOM-Tag-Panel
│   │   └── analysis_panel.py   # ROI-Analyse-Panel
│   ├── tools/              # Interaktive Tool-Implementierungen
│   │   ├── __init__.py
│   │   ├── base_tool.py        # Abstrakte Basisklasse für Tools
│   │   ├── default_tool.py     # Standard-Zeiger/Pan/Zoom/Fenster-Tool
│   │   ├── roi_tool.py         # ROI-Tools (Ellipse, Rechteck, Kreis)
│   │   └── measurement_tool.py # Entfernungsmess-Tool
│   ├── dialogs/            # Dialog-Fenster
│   │   ├── custom_wl_dialog.py # Benutzerdefinierter Fenster/Ebene-Dialog
│   │   └── settings_dialog.py  # Anwendungseinstellungs-Dialog
│   └── widgets/            # Benutzerdefinierte UI-Widgets
│       ├── __init__.py
│       ├── magnifier.py        # Lupen-Widget
│       ├── roi_stats_box.py    # ROI-Statistik-Anzeige
│       └── layout_grid_selector.py # Layout-Auswahl-Widget
│
├── utils/                  # Allgemeine Hilfsprogramme (MVC-Modell-Unterstützung)
│   ├── __init__.py
│   ├── logger.py           # Globale Logging-Konfiguration
│   ├── settings.py         # Benutzereinstellungs-Management
│   ├── theme_manager.py    # Themensystem mit Symbol-Management
│   └── i18n.py             # Internationalisierungs-Hilfsprogramme
│
├── tests/                  # Unit-/Integrationstests
│   ├── __init__.py
│   ├── dcm/                # Test-DICOM-Daten
│   ├── scripts/            # Testdaten-Generierungsskripte
│   ├── test_dicom_parser.py
│   ├── test_roi.py
│   └── test_multi_series_components.py
│
├── pyproject.toml          # Projekt-Metadaten und Abhängigkeiten
└── README_zh.md            # Chinesische Dokumentation
```

## 5. Verwendung

Stellen Sie zunächst sicher, dass Sie [uv](https://github.com/astral-sh/uv) installiert haben. Es ist ein extrem schneller Python-Paket-Installer und -Resolver.

1.  **Repository klonen:**
    ```bash
    git clone https://github.com/1985312383/MedImager.git
    cd MedImager
    ```

2.  **Umgebung einrichten und Abhängigkeiten installieren:**
    ```bash
    # Virtuelle Umgebung erstellen und Abhängigkeiten aus pyproject.toml synchronisieren
    uv venv
    uv sync
    ```

3.  **App ausführen:**
    ```bash
    # `uv run` führt den Befehl innerhalb der virtuellen Umgebung des Projekts aus,
    # wodurch die Notwendigkeit vermieden wird, sie in Ihrer Shell zu aktivieren.
    uv run python medimager/main.py
    ```
    Für Entwickler, die eine aktive Umgebung bevorzugen:
    ```bash
    # Um die Umgebung in Ihrer aktuellen Shell zu aktivieren:
    # Windows
    .venv\\Scripts\\activate
    # macOS / Linux
    source .venv/bin/activate
    
    # Dann können Sie Befehle direkt ausführen:
    python medimager/main.py
    ```

4.  **Performance-Baseline ausführen (Entwickler):**
    ```bash
    uv run python -m medimager.performance.baseline \
      --slices 300 \
      --rows 512 \
      --cols 512 \
      --repeats 3 \
      --display-samples 64 \
      --output performance_baseline.json
    ```
    Dieser Befehl erzeugt eine synthetische, de-identifizierte DICOM-Großserie und misst Serienladen, Window/Level-Anzeige, Cache-Hit-Anzeige und QImage-Konvertierung. Die Unit-Tests setzen bewusst keine festen Performance-Grenzwerte; speichern Sie die JSON-Ergebnisse vor Releases für Versionsvergleiche.

---

## 🤝 Mitwirken

Beiträge sind willkommen! Ob Sie einen Fehler beheben, eine Funktion hinzufügen oder die Dokumentation verbessern, Ihre Hilfe wird geschätzt. Bitte zögern Sie nicht, ein Issue zu öffnen oder einen Pull Request zu senden.

## 📄 Lizenz

Dieses Projekt ist unter der GNU GENERAL PUBLIC LICENSE lizenziert. Siehe die [LICENSE](LICENSE)-Datei für Details.

---

## Mitwirkende

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")
