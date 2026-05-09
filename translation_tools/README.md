# MedImager i18n Tools

MedImager now uses YAML as the human-maintained translation source.

Source files:

```text
medimager/i18n/locales/<language>.yml
```

Runtime catalogs:

```text
medimager/i18n/compiled/<language>.json
```

## Daily Workflow

Edit YAML files, then compile:

```bash
python translation_tools/main.py
```

or directly:

```bash
python translation_tools/i18n_compile.py
```

The compiler validates placeholder consistency and writes JSON catalogs used by
`medimager.utils.i18n`. The toolchain then runs `i18n_check.py` to ensure
non-Chinese catalogs do not contain Chinese UI text.

## Removed Legacy Chain

The old Qt `.ts/.qm` toolchain and `self.tr(...)` compatibility map have been
removed. Runtime translation is served from YAML-derived JSON catalogs only.

## Runtime Usage

New UI code should use stable keys:

```python
from medimager.utils.i18n import t

title = t("settings.title")
label = t("viewer.active_view", position="A")
```
