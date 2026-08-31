"""Performance measurement utilities for MedImager."""

from importlib import import_module

__all__ = [
    "BASELINE_VERSION",
    "DEFAULT_REGRESSION_METRICS",
    "DEFAULT_RELATIVE_LIMIT",
    "QUICK_PROFILE",
    "RegressionFinding",
    "RegressionMetric",
    "RegressionReport",
    "compare_release_baselines",
    "load_release_baseline",
    "run_v26_release_baseline",
]


def __getattr__(name: str):
    """Lazily expose v2.6 helpers without preloading the ``-m`` CLI module."""

    if name not in __all__:
        raise AttributeError(name)
    module = import_module("medimager.performance.v26_release")
    return getattr(module, name)
