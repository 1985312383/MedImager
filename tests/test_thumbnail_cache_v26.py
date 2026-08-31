from __future__ import annotations

from pathlib import Path

import numpy as np

from medimager.core.multi_series_manager import MultiSeriesManager
from medimager.core.thumbnail_cache import ThumbnailDiskCache
from medimager.ui.panels import series_panel
from medimager.ui.panels.series_panel import SeriesListWidget


PNG = b"\x89PNG\r\n\x1a\nsynthetic"


class _Settings:
    def __init__(self, root: Path, *, max_items: int = 256, max_age_days: int = 30):
        self.root = root
        self.values = {
            "cache.thumbnail.max_items": max_items,
            "cache.thumbnail.max_age_days": max_age_days,
            "privacy.screen_mode": False,
        }

    def get_config_directory(self) -> Path:
        return self.root

    def get_setting(self, key: str, default=None):
        return self.values.get(key, default)


def _write_payload(payload: bytes = PNG):
    def writer(path: Path) -> bool:
        path.write_bytes(payload)
        return True

    return writer


def test_thumbnail_cache_enforces_settings_lru_and_touches_reads(tmp_path):
    clock = [1_000_000.0]
    settings = _Settings(tmp_path, max_items=2, max_age_days=30)
    cache = ThumbnailDiskCache(settings, now_provider=lambda: clock[0])

    first = cache.write_png("first-patient-sensitive-identity", _write_payload())
    clock[0] += 1
    second = cache.write_png("second", _write_payload())
    clock[0] += 1
    assert cache.lookup("first-patient-sensitive-identity") == first
    clock[0] += 1
    third = cache.write_png("third", _write_payload())

    assert first and first.is_file()
    assert third and third.is_file()
    assert second and not second.exists()
    assert len(tuple(cache.directory.glob("*.png"))) == 2
    assert "patient" not in first.name
    assert len(first.stem) == 64


def test_thumbnail_cache_expires_by_configured_age(tmp_path):
    clock = [10_000.0]
    settings = _Settings(tmp_path, max_items=10, max_age_days=1)
    cache = ThumbnailDiskCache(settings, now_provider=lambda: clock[0])
    stale = cache.write_png("stale", _write_payload())
    assert stale and stale.is_file()

    clock[0] += 86_401

    assert cache.lookup("stale") is None
    assert not stale.exists()


def test_thumbnail_cache_failed_atomic_write_preserves_previous_entry(tmp_path):
    settings = _Settings(tmp_path)
    cache = ThumbnailDiskCache(settings)
    target = cache.write_png("series", _write_payload())
    assert target and target.read_bytes() == PNG

    assert cache.write_png("series", _write_payload(b"not a png")) is None

    assert target.read_bytes() == PNG
    assert not tuple(cache.directory.glob("*.tmp"))


def test_series_navigator_uses_configured_disk_cache_limit(qapp, monkeypatch, tmp_path):
    settings = _Settings(tmp_path, max_items=2, max_age_days=30)
    monkeypatch.setattr(series_panel, "get_settings_manager", lambda: settings)
    manager = MultiSeriesManager()
    widget = SeriesListWidget(manager)
    thumbnail = np.zeros((56, 72), dtype=np.uint8)
    for series_id in ("101", "102", "103"):
        widget._on_thumbnail_ready(series_id, thumbnail)

    assert len(widget._thumbnail_cache) == 3
    assert len(tuple((tmp_path / "thumbnail_cache").glob("*.png"))) == 2

    widget.deleteLater()
    qapp.processEvents()
