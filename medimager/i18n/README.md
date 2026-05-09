# MedImager i18n

YAML files in `locales/` are the human-maintained translation source.
Runtime code reads JSON catalogs from `compiled/`.

Edit translations in:

```text
medimager/i18n/locales/<language>.yml
```

The locale files contain only translated `messages`; keys are stable English
identifiers, not source-language UI text.

Then rebuild runtime catalogs:

```bash
python translation_tools/main.py
```

The old Qt `.ts/.qm` translation chain and `self.tr(...)` compatibility map
have been removed.

Use stable keys in application code:

```python
from medimager.utils.i18n import t

title = t("settings.title")
label = t("viewer.active_view", position="A")
```

Do not use visible Chinese text as a translation key for new UI code.
