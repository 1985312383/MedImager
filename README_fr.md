<div align="center">

![MedImager Banner](medimager/icons/banner.png)

</div>

<div align="center">

# MedImager
**Un Visualiseur DICOM et Outil d'Analyse d'Images Moderne et Multiplateforme**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python Version](https://img.shields.io/badge/Python-3.11+-brightgreen.svg)](https://www.python.org/)
[![PySide6](https://img.shields.io/badge/UI-PySide6-informational.svg)](https://www.qt.io/qt-for-python)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub stars](https://img.shields.io/github/stars/1985312383/MedImager.svg?style=social&label=Star)](https://github.com/1985312383/MedImager)

[English](README.md) | [简体中文](README_zh.md) | [Deutsch](README_de.md) | [Español](README_es.md) | **Français**

</div>

MedImager est un visualiseur d'images médicales et outil d'analyse open source avec l'objectif à long terme de se rapprocher de flux de lecture de type RadiAnt. La version 2.4 enrichit la base DICOM 2D fiable avec un modèle de volume dans l’espace patient et une MPR axiale, coronale et sagittale liée : visualisation multi-séries, mesure et analyse ROI, couverture DICOM synthétique professionnelle, persistance des annotations et baselines de performance répétables.

## 1. Vision du Projet

Créer un visualiseur open source pragmatique pouvant évoluer vers des flux de travail de type RadiAnt. MedImager 2.4 fournit une MPR orthogonale validée géométriquement ; les versions suivantes ajouteront DICOMDIR/PACS, les hanging protocols, la reconstruction oblique et des flux plus complets.

<div align="center">

![MedImager Demo](preview.png)

</div>

## 2. Fonctionnalités Principales

### ✅ V2.0 - Base DICOM 2D (PRÊTE)
- [x] **Gestion des Fichiers :**
    - [x] Ouvrir et analyser les séries DICOM depuis les dossiers.
    - [x] Ouvrir des fichiers d'image individuels (PNG, JPG, BMP).
    - [x] Visualiseur de balises DICOM.
- [x] **Affichage d'Images :**
    - [x] Visualiseur 2D avec panoramique et zoom fluides.
    - [x] Multi-viewport pour la comparaison d'images avec des mises en page flexibles.
    - [x] Affichage des informations patient et des superpositions d'image (échelle, marqueur d'orientation).
- [x] **Outils d'Interaction d'Images :**
    - [x] **Fenêtrage :** Ajustement interactif de la largeur/niveau de fenêtre HU (WW/WL) avec préréglages dans la barre d'outils.
    - [x] **Outils de Mesure :**
        - [x] Outil règle pour la mesure de distance.
        - [x] Outil de mesure d'angle.
        - [x] Outils ROI ellipse/rectangle/cercle.
    - [x] **Analyse ROI :** Calculer les statistiques dans la ROI (moyenne, écart-type, aire, HU max/min).
    - [x] **Transformations d'Image :** Retournement (horizontal/vertical), rotation (90° gauche/droite), inversion, avec état indépendant par vue.
    - [x] **Lecture Ciné :** Lecture automatique des coupes avec FPS ajustable.
    - [x] **Export d'Image :** Exporter la vue actuelle en PNG/JPG, ou copier dans le presse-papiers.
- [x] **Fonctionnalités Avancées :**
    - [x] **Gestion Multi-Séries :** Charger et gérer plusieurs séries DICOM simultanément.
    - [x] **Liaison Série-Vue :** Système de liaison flexible avec attribution automatique et contrôle manuel.
    - [x] **Synchronisation :** Synchronisation inter-viewport pour position, panoramique, zoom et fenêtre/niveau.
    - [x] **Système de Mise en Page :** Mises en page en grille (1×1 à 3×4) et mises en page spéciales (division verticale/horizontale, triple colonne).
- [x] **Interface Utilisateur :**
    - [x] Interface multilingue moderne (Chinois/Anglais).
    - [x] Système de thèmes personnalisable (thèmes clair/sombre) avec commutation en temps réel.
    - [x] Système de paramètres complet avec personnalisation de l'apparence des outils.
    - [x] Barre d'outils unifiée avec icônes adaptatives au thème.
    - [x] Mise en page de panneau ancrable.
- [x] **Exactitude DICOM et base qualité :**
    - [x] Jeu de tests DICOM synthétiques professionnels pour CT/MR/CR/US/PET, balises manquantes, ordre inversé, géométrie oblique, données multi-frame, syntaxes de transfert compressées et variantes PixelSpacing.
    - [x] Parser robuste avec dépendances de décodeur explicites, expansion multi-frame en niveaux de gris, warnings de géométrie incohérente et erreurs claires pour les variantes non supportées.
    - [x] Baselines de performance pour chargement de grandes séries, affichage window/level, accès cache et conversion QImage.
    - [x] Persistance JSON versionnée pour les annotations ROI, mesures de distance et mesures d'angle.

### Prochaine Feuille de Route - Flux Type RadiAnt
- [x] **Reconstruction multiplanaire orthogonale (MPR) :** Vues axiale, coronale et sagittale liées dans l’espace patient LPS.
- [ ] **Rendu de Volume 3D :** Visualisation 3D de base des séries DICOM.
- [ ] **Fusion d'Images :** Superposer deux séries différentes (ex. PET/CT).
- [ ] **DICOMDIR / PACS :** Navigation sur médias locaux et requête/récupération DICOM réseau après stabilisation de la base 2D.
- [ ] **Hanging Protocols :** Sauvegarder et restaurer des mises en page pratiques pour la revue répétée d'études.
- [ ] **Système de Plugins :** Permettre aux utilisateurs d'étendre les fonctionnalités via des scripts Python personnalisés pour la recherche.

## 3. Stack Technologique

* **Langage :** Python 3.11+
* **Framework GUI :** PySide6 (LGPL)
* **Analyse DICOM :** pydicom
* **Traitement Numérique/Images :** NumPy
* **Visualisation 2D :** Qt Graphics View Framework
* **Empaquetage :** PyInstaller
* **i18n :** Catalogues source YAML compilés en catalogues JSON d'exécution

## 4. Structure du Projet

Le projet suit un modèle similaire à MVC pour séparer la logique des données, l'UI et l'interaction utilisateur.

```
medimager/
├── main.py                 # Point d'entrée de l'application
├── icons/                  # Icônes UI et ressources SVG
├── i18n/                   # Catalogues source YAML et catalogues JSON d'exécution
├── themes/                 # Fichiers de configuration de thèmes
│   ├── ui/                 # Thèmes UI (dark.toml, light.toml)
│   ├── roi/                # Thèmes d'apparence ROI
│   └── measurement/        # Thèmes d'outils de mesure
│
├── core/                   # Logique centrale, indépendante de l'UI (Modèle MVC)
│   ├── __init__.py
│   ├── dicom_parser.py     # Chargement/analyse DICOM via pydicom
│   ├── image_data_model.py # Modèle de données pour image unique ou série DICOM
│   ├── multi_series_manager.py # Gestion multi-séries et contrôle de mise en page
│   ├── series_view_binding.py  # Gestion de liaison série-vue
│   ├── sync_manager.py     # Synchronisation inter-viewport
│   ├── roi.py              # Formes ROI et logique
│   └── analysis.py         # Calculs statistiques (statistiques HU, etc.)
│
├── ui/                     # Tous les composants UI (Vue et Contrôleur MVC)
│   ├── __init__.py
│   ├── main_window.py      # Fenêtre principale avec support multi-séries
│   ├── main_toolbar.py     # Gestion de barre d'outils unifiée (outils, mise en page, sync)
│   ├── image_viewer.py     # Visualiseur d'images 2D central (QGraphicsView)
│   ├── viewport.py         # Viewport autonome avec image_viewer
│   ├── multi_viewer_grid.py# Gestionnaire de mise en page de grille multi-viewport
│   ├── panels/             # Panneaux ancrables
│   │   ├── __init__.py
│   │   ├── series_panel.py     # Panneau de gestion multi-séries
│   │   └── dicom_tag_panel.py  # Panneau de balises DICOM
│   ├── tools/              # Implémentations d'outils interactifs
│   │   ├── __init__.py
│   │   ├── base_tool.py        # Classe de base abstraite pour les outils
│   │   ├── default_tool.py     # Outil par défaut pointeur/panoramique/zoom/fenêtre
│   │   ├── roi_tool.py         # Outils ROI (ellipse, rectangle, cercle)
│   │   ├── measurement_tool.py # Outil de mesure de distance
│   │   └── angle_tool.py       # Outil de mesure d'angle
│   ├── dialogs/            # Fenêtres de dialogue
│   │   ├── custom_wl_dialog.py # Dialogue personnalisé fenêtre/niveau
│   │   └── settings_dialog.py  # Dialogue de paramètres d'application
│   └── widgets/            # Widgets UI personnalisés
│       ├── __init__.py
│       ├── magnifier.py        # Widget loupe
│       ├── roi_stats_box.py    # Affichage des statistiques ROI
│       ├── layout_grid_selector.py # Widget sélecteur de mise en page
│       └── panel_toggle_strip.py   # Widget bande de basculement de panneau
│
├── utils/                  # Utilitaires généraux (Support Modèle MVC)
│   ├── __init__.py
│   ├── logger.py           # Configuration de logging globale
│   ├── settings.py         # Gestion des paramètres utilisateur
│   ├── theme_manager.py    # Système de thèmes avec gestion d'icônes
│   ├── resource_path.py    # Résolution des chemins de ressources/icônes
│   └── i18n.py             # Utilitaires d'internationalisation
│
├── tests/                  # Tests unitaires/intégration
│   ├── __init__.py
│   ├── dcm/                # Données DICOM de test
│   ├── scripts/            # Scripts de génération de données de test
│   ├── test_dicom_parser.py
│   ├── test_roi.py
│   └── test_multi_series_components.py
│
├── pyproject.toml          # Métadonnées du projet et dépendances
└── README_zh.md            # Documentation chinoise
```

## 5. Utilisation

D'abord, assurez-vous d'avoir [uv](https://github.com/astral-sh/uv) installé. C'est un installateur et résolveur de paquets Python extrêmement rapide.

1.  **Cloner le dépôt :**
    ```bash
    git clone https://github.com/1985312383/MedImager.git
    cd MedImager
    ```

2.  **Configurer l'Environnement et Installer les Dépendances :**
    ```bash
    # Créer un environnement virtuel et synchroniser les dépendances depuis pyproject.toml
    uv venv
    uv sync
    ```

3.  **Exécuter l'application :**
    ```bash
    # `uv run` exécute la commande dans l'environnement virtuel du projet,
    # évitant le besoin de l'activer dans votre shell.
    uv run python medimager/main.py
    ```
    Pour les développeurs qui préfèrent un environnement actif :
    ```bash
    # Pour activer l'environnement dans votre shell actuel :
    # Windows
    .venv\\Scripts\\activate
    # macOS / Linux
    source .venv/bin/activate
    
    # Ensuite vous pouvez exécuter les commandes directement :
    python medimager/main.py
    ```

4.  **Exécuter la baseline de performance (développeurs) :**
    ```bash
    uv run python -m medimager.performance.baseline \
      --slices 300 \
      --rows 512 \
      --cols 512 \
      --repeats 3 \
      --display-samples 64 \
      --output performance_baseline.json
    ```
    Cette commande génère une grande série DICOM synthétique et désidentifiée, puis mesure le chargement de série, l'affichage window/level, l'affichage avec cache et la conversion QImage. Les tests unitaires n'imposent pas de seuils de performance fixes ; sauvegardez le JSON avant les releases pour comparer les versions.

---

## 🤝 Contribuer

Les contributions sont les bienvenues ! Que vous corrigiez un bug, ajoutiez une fonctionnalité ou amélioriez la documentation, votre aide est appréciée. N'hésitez pas à ouvrir une issue ou soumettre une pull request.

## 📄 Licence

Ce projet est sous licence GNU GENERAL PUBLIC LICENSE. Voir le fichier [LICENSE](LICENSE) pour les détails.

---

## Contributeurs

[![contributors](https://contrib.rocks/image?repo=1985312383/MedImager)](https://github.com/1985312383/MedImager/graphs/contributors)

![Alt](https://repobeats.axiom.co/api/embed/13581311607b3b5dcd5a54cdde3bad22212af439.svg "Repobeats analytics image")
