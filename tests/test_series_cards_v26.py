from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.ui.panels import series_panel
from medimager.ui.panels.series_panel import (
    SeriesListWidget,
    StudyBrowserDelegate,
    StudyBrowserModel,
)


class _Settings:
    def __init__(self, root: Path):
        self._root = root

    def get_config_directory(self) -> Path:
        return self._root

    @staticmethod
    def get_setting(_key, default=None):
        return default


def _manager_with_card_series() -> MultiSeriesManager:
    manager = MultiSeriesManager()
    assert manager.set_layout(1, 2)
    manager.add_series(
        SeriesInfo(
            series_id="card-series",
            patient_name="Example^Patient",
            patient_id="EXAMPLE-01",
            study_description="Example study",
            study_instance_uid="1.2.826.0.1.1",
            series_description="Arterial phase",
            series_instance_uid="1.2.826.0.1.1.7",
            modality="CT",
            series_number="7",
            orientation="axial",
            slice_count=42,
            is_loaded=True,
        )
    )
    assert manager.bind_series_to_view("view_0_0", "card-series")
    assert manager.bind_series_to_view("view_0_1", "card-series")
    return manager


def _browser_model(manager: MultiSeriesManager) -> StudyBrowserModel:
    thumbnail = QPixmap(32, 24)
    thumbnail.fill(QColor("#607d8b"))
    model = StudyBrowserModel()
    model.rebuild(manager, {"card-series": QIcon(thumbnail)}, QIcon())
    return model


def test_study_browser_model_exposes_structured_card_roles(qapp):
    model = _browser_model(_manager_with_card_series())
    index = model.index_for_series("card-series")

    assert index.isValid()
    assert model.data(index, StudyBrowserModel.TitleRole) == "Arterial phase"
    assert model.data(index, StudyBrowserModel.ModalityRole) == "CT"
    assert model.data(index, StudyBrowserModel.SeriesNumberRole) == "7"
    assert model.data(index, StudyBrowserModel.OrientationRole) == "axial"
    assert model.data(index, StudyBrowserModel.SliceCountRole) == 42
    assert model.data(index, StudyBrowserModel.LoadedRole) is True
    assert model.data(index, StudyBrowserModel.BoundViewsRole) == (
        "view_0_0",
        "view_0_1",
    )


def test_series_card_delegate_uses_roles_and_paints_selected_card(qapp):
    model = _browser_model(_manager_with_card_series())
    index = model.index_for_series("card-series")
    delegate = StudyBrowserDelegate()
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 420, StudyBrowserDelegate.CARD_HEIGHT)
    option.palette = qapp.palette()
    option.font = qapp.font()
    option.state = (
        QStyle.StateFlag.State_Enabled | QStyle.StateFlag.State_Selected
    )

    delegate.set_card_mode(True)
    assert delegate.uses_card_painting(index)
    card = delegate.card_data(index)
    assert card.title == "Arterial phase"
    assert card.modality == "CT"
    assert card.series_number == "7"
    assert card.orientation == "axial"
    assert card.slice_count == 42
    assert card.loaded is True
    assert card.bound_views == ("view_0_0", "view_0_1")
    assert all(
        value in delegate.metadata_text(card)
        for value in ("CT", "#7", "Axial", "42")
    )
    assert delegate.viewport_badge_text("view_0_1") == "V1:2"

    image = QImage(
        option.rect.size(), QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    delegate.paint(painter, option, index)
    painter.end()
    assert image.pixelColor(10, 10).alpha() > 0

    parent = model.parent(index)
    second_column = model.index(index.row(), 1, parent)
    assert not delegate.uses_card_painting(second_column)
    card_height = delegate.sizeHint(option, index).height()
    delegate.set_card_mode(False)
    assert not delegate.uses_card_painting(index)
    assert card_height > delegate.sizeHint(option, index).height()


def test_card_density_uses_full_width_and_restores_native_three_columns(
    qapp, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        series_panel, "get_settings_manager", lambda: _Settings(tmp_path)
    )
    manager = _manager_with_card_series()
    widget = SeriesListWidget(manager)
    qapp.processEvents()

    assert widget._browser_proxy.columnCount() == 3

    widget.set_density("cards")
    qapp.processEvents()
    assert widget._browser_view.isColumnHidden(1)
    assert widget._browser_view.isColumnHidden(2)
    assert not widget._browser_view.alternatingRowColors()

    widget.set_density("compact")
    qapp.processEvents()
    assert not widget._browser_view.isColumnHidden(1)
    assert not widget._browser_view.isColumnHidden(2)
    assert widget._browser_view.alternatingRowColors()

    widget.deleteLater()
    qapp.processEvents()


def test_card_mode_survives_series_add_model_resets(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(
        series_panel, "get_settings_manager", lambda: _Settings(tmp_path)
    )
    manager = _manager_with_card_series()
    widget = SeriesListWidget(manager)
    widget.show()
    widget.set_density("cards")
    qapp.processEvents()

    for number in range(8, 12):
        series_id = f"card-series-{number}"
        manager.add_series(
            SeriesInfo(
                series_id=series_id,
                patient_name="Example^Patient",
                patient_id="EXAMPLE-01",
                study_description="Example study",
                study_instance_uid="1.2.826.0.1.1",
                series_description=f"Phase {number}",
                series_instance_uid=f"1.2.826.0.1.1.{number}",
                modality="CT",
                series_number=str(number),
                orientation="axial",
                slice_count=42,
            )
        )
        qapp.processEvents()
        assert widget._browser_model.index_for_series(series_id).isValid()
        assert widget._browser_view.isColumnHidden(1)
        assert widget._browser_view.isColumnHidden(2)

    assert widget._browser_proxy.columnCount() == 3
    widget.set_density("compact")
    qapp.processEvents()
    assert not widget._browser_view.isColumnHidden(1)
    assert not widget._browser_view.isColumnHidden(2)

    widget.close()
    widget.deleteLater()
    qapp.processEvents()
