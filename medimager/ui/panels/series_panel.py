"""
序列面板模块

重新设计的序列面板，支持多序列管理、视图绑定和详细信息显示。
包含序列列表、绑定管理和信息展示等多个子组件。
"""

from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget, QTreeWidgetItem,
    QTreeView, QLabel, QPushButton, QGroupBox, QComboBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QScrollArea, QFrame,
    QMessageBox, QStyledItemDelegate, QAbstractItemView, QStyle
)
from PySide6.QtCore import (
    Qt, Signal, QPoint, QSize, QMimeData, QSignalBlocker, QAbstractItemModel,
    QSortFilterProxyModel, QModelIndex, QItemSelectionModel, QTimer, QRect
)
from PySide6.QtGui import QPixmap, QIcon, QFont, QColor, QDrag, QPainter, QBrush, QPen, QFontMetrics

from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo
from medimager.core.series_view_binding import SeriesViewBindingManager
from medimager.core.image_data_model import ImageDataModel
from medimager.core.thumbnail_cache import ThumbnailDiskCache
from medimager.core.view_presentation_state import (
    ViewPresentationState,
    build_render_request,
    render_and_cache_request,
)
from medimager.ui.qt_image_utils import qimage_from_display_data
from medimager.utils.logger import get_logger
from medimager.utils.i18n import t
from medimager.utils.settings import get_performance_manager, get_settings_manager

logger = get_logger(__name__)

_INLINE_SLICE_LIMIT = 200
_SLICE_PAGE_SIZE = 100
_THUMBNAIL_SIZE = QSize(72, 56)


def _fit_thumbnail_array(data: np.ndarray) -> np.ndarray:
    """Downsample and letterbox on a worker using only immutable arrays."""
    pixels = np.asarray(data)
    height, width = pixels.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("empty thumbnail source")
    scale = min(_THUMBNAIL_SIZE.width() / width, _THUMBNAIL_SIZE.height() / height)
    target_width = max(1, min(_THUMBNAIL_SIZE.width(), round(width * scale)))
    target_height = max(1, min(_THUMBNAIL_SIZE.height(), round(height * scale)))
    x_index = np.linspace(0, width - 1, target_width).astype(np.intp)
    y_index = np.linspace(0, height - 1, target_height).astype(np.intp)
    sampled = pixels[y_index][:, x_index]
    shape = (_THUMBNAIL_SIZE.height(), _THUMBNAIL_SIZE.width()) + pixels.shape[2:]
    canvas = np.full(shape, 22, dtype=np.uint8)
    top = (canvas.shape[0] - target_height) // 2
    left = (canvas.shape[1] - target_width) // 2
    canvas[top:top + target_height, left:left + target_width] = sampled
    return np.ascontiguousarray(canvas)


def _render_thumbnail_request(cache_key: str, request) -> np.ndarray:
    return _fit_thumbnail_array(render_and_cache_request(cache_key, request))


def _parse_tree_item_data(data):
    """Return ``(kind, series_id, payload)`` for series-tree item data."""
    if isinstance(data, tuple) and data:
        if data[0] == "slice" and len(data) == 3:
            return "slice", str(data[1]), int(data[2])
        if data[0] == "slice_range" and len(data) == 4:
            return "slice_range", str(data[1]), (int(data[2]), int(data[3]))
    if isinstance(data, str) and data:
        # Backward-compatible parsing for trees created before paged slice items.
        if ":" in data:
            series_id, possible_index = data.rsplit(":", 1)
            try:
                return "slice", series_id, int(possible_index)
            except ValueError:
                pass
        return "series", data, None
    return None, None, None


class DraggableTreeWidget(QTreeWidget):
    """支持拖拽的树形控件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragOnly)
    
    def startDrag(self, supportedActions):
        """开始拖拽操作"""
        item = self.currentItem()
        if not item:
            return
        
        # 检查是否是序列项目（不是分组项目）
        _, series_id, _ = _parse_tree_item_data(item.data(0, Qt.UserRole))
        if not series_id:
            return
        
        # 创建拖拽数据
        mimeData = QMimeData()
        mimeData.setText(f"series:{series_id}")
        mimeData.setData("application/x-medimager-series", series_id.encode())
        
        # 创建拖拽对象
        drag = QDrag(self)
        drag.setMimeData(mimeData)
        
        # 创建更好的拖拽图标
        series_text = item.text(0)
        pixmap = self._create_drag_pixmap(series_text)
        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())
        
        # 执行拖拽
        drag.exec_(Qt.CopyAction)
    
    def _create_drag_pixmap(self, text: str) -> QPixmap:
        """创建拖拽图标"""
        # 计算文本大小
        font = QFont()
        font.setPointSize(10)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()
        
        # 创建图标
        padding = 8
        width = min(text_width + padding * 2, 200)  # 限制最大宽度
        height = text_height + padding * 2
        
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 绘制背景
        rect = pixmap.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(QBrush(QColor(70, 130, 180, 200)))  # 半透明蓝色
        painter.setPen(QPen(QColor(70, 130, 180), 2))
        painter.drawRoundedRect(rect, 4, 4)
        
        # 绘制文本
        painter.setPen(QPen(Qt.white))
        painter.setFont(font)
        text_rect = rect.adjusted(padding, 0, -padding, 0)
        
        # 如果文本太长，截断并添加省略号
        if text_width > text_rect.width():
            text = metrics.elidedText(text, Qt.ElideRight, text_rect.width())
        
        painter.drawText(text_rect, Qt.AlignCenter, text)
        painter.end()
        
        return pixmap


@dataclass
class _StudyBrowserNode:
    kind: str
    values: tuple[str, str, str]
    parent: Optional["_StudyBrowserNode"] = None
    series_id: str = ""
    modality: str = ""
    series_number: str = ""
    orientation: str = ""
    slice_count: int = 0
    loaded: bool = False
    bound_views: tuple[str, ...] = ()
    search_blob: str = ""
    children: list["_StudyBrowserNode"] = field(default_factory=list)

    def append(self, child: "_StudyBrowserNode") -> None:
        child.parent = self
        self.children.append(child)

    def row(self) -> int:
        if self.parent is None:
            return 0
        return self.parent.children.index(self)


@dataclass(frozen=True)
class SeriesCardPresentation:
    """Structured, display-only values consumed by the series-card delegate."""

    title: str
    modality: str
    series_number: str
    orientation: str
    slice_count: int
    loaded: bool
    bound_views: tuple[str, ...]


class StudyBrowserModel(QAbstractItemModel):
    """Patient -> Study -> Series model used by the visible v2.6 navigator."""

    KindRole = Qt.UserRole
    SeriesIdRole = Qt.UserRole + 1
    SearchRole = Qt.UserRole + 2
    ModalityRole = Qt.UserRole + 3
    OrientationRole = Qt.UserRole + 4
    LoadedRole = Qt.UserRole + 5
    TitleRole = Qt.UserRole + 6
    SeriesNumberRole = Qt.UserRole + 7
    SliceCountRole = Qt.UserRole + 8
    BoundViewsRole = Qt.UserRole + 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root = _StudyBrowserNode("root", ("", "", ""))
        self._series_nodes: Dict[str, _StudyBrowserNode] = {}
        self._icons: Dict[str, QIcon] = {}
        self._placeholder = QIcon()

    def rebuild(
        self,
        manager: MultiSeriesManager,
        icons: Dict[str, QIcon],
        placeholder: QIcon,
        *,
        privacy: bool = False,
    ) -> None:
        # Build the Python tree off-model first.  A proxy view may query this
        # model synchronously while Qt processes a reset; mutating the active
        # root during that window can leave proxy indexes pointing at detached
        # internal pointers.  Swap the completed snapshot atomically instead.
        new_root = _StudyBrowserNode("root", ("", "", ""))
        new_series_nodes: Dict[str, _StudyBrowserNode] = {}
        hierarchy = manager.get_study_hierarchy()
        for patient_index, patient in enumerate(hierarchy.patients, start=1):
            if privacy:
                patient_label = t("serieslistwidget.anonymous_patient").replace(
                    "%1", f"{patient_index:02d}"
                )
            else:
                patient_label = patient.display_name or t(
                    "serieslistwidget.unknown_patient"
                )
                if patient.patient_id:
                    patient_label = f"{patient_label} · {patient.patient_id}"
            patient_node = _StudyBrowserNode(
                "patient",
                (
                    patient_label,
                    t("serieslistwidget.study_count").replace(
                        "%1", str(len(patient.studies))
                    ),
                    "",
                ),
                search_blob=patient_label.casefold(),
            )
            new_root.append(patient_node)
            for study_index, study in enumerate(patient.studies, start=1):
                date = SeriesListWidget._format_dicom_date(study.study_date)
                if privacy:
                    description = t("serieslistwidget.anonymous_study").replace(
                        "%1", f"{study_index:02d}"
                    )
                else:
                    description = study.description or t(
                        "serieslistwidget.unknown_research"
                    )
                modalities = "/".join(study.modalities) or "—"
                study_node = _StudyBrowserNode(
                    "study",
                    (
                        description,
                        date or "—",
                        f"{modalities} · {study.series_count}",
                    ),
                    search_blob=f"{description} {date} {modalities}".casefold(),
                )
                patient_node.append(study_node)
                for series_index, series in enumerate(study.series, start=1):
                    info = manager.get_series_info(series.series_id)
                    if info is None:
                        continue
                    if privacy:
                        label = t("serieslistwidget.anonymous_series").replace(
                            "%1", f"{series_index:02d}"
                        )
                    else:
                        label = SeriesListWidget._series_label(info)
                    status = (
                        t("serieslistwidget.loaded")
                        if info.is_loaded
                        else t("seriesinfowidget.not_loaded")
                    )
                    bound = sorted(
                        manager.get_bound_views_for_series(series.series_id)
                    )
                    binding_text = (
                        " · ".join(value.replace("view_", "V") for value in bound)
                        if bound
                        else t("seriesinfowidget.unbound")
                    )
                    series_number = str(info.series_number or "").strip()
                    sequence_details = [str(info.modality or "—")]
                    if series_number:
                        sequence_details.append(f"#{series_number}")
                    sequence_details.extend(
                        (
                            str(info.orientation or "unknown").capitalize(),
                            str(int(info.slice_count or 0)),
                        )
                    )
                    series_node = _StudyBrowserNode(
                        "series",
                        (
                            label,
                            " · ".join(sequence_details),
                            f"{status} · {binding_text}",
                        ),
                        series_id=series.series_id,
                        modality=str(info.modality or "").upper(),
                        series_number=series_number,
                        orientation=str(info.orientation or "unknown").lower(),
                        slice_count=max(0, int(info.slice_count or 0)),
                        loaded=bool(info.is_loaded),
                        bound_views=tuple(bound),
                        search_blob=" ".join(
                            (
                                label,
                                str(info.modality or ""),
                                str(info.series_number or ""),
                                str(info.orientation or ""),
                                str(info.protocol_name or ""),
                                str(info.body_part_examined or ""),
                            )
                        ).casefold(),
                    )
                    study_node.append(series_node)
                    new_series_nodes[series.series_id] = series_node
        self.beginResetModel()
        self._root = new_root
        self._series_nodes = new_series_nodes
        self._icons = dict(icons)
        self._placeholder = placeholder
        self.endResetModel()

    def columnCount(self, parent=QModelIndex()) -> int:
        return 3

    def rowCount(self, parent=QModelIndex()) -> int:
        # A tree can expose children only from its first column.  Returning
        # children for columns 1/2 violates QAbstractItemModel's contract and
        # can make QTreeView.expandToDepth walk invalid proxy indexes.
        if parent.isValid() and parent.column() != 0:
            return 0
        node = self._node(parent)
        return len(node.children)

    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if parent.isValid() and parent.column() != 0:
            return QModelIndex()
        parent_node = self._node(parent)
        if row < 0 or row >= len(parent_node.children) or not 0 <= column < 3:
            return QModelIndex()
        return self.createIndex(row, column, parent_node.children[row])

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        node = self._node(index)
        parent = node.parent
        if parent is None or parent is self._root:
            return QModelIndex()
        return self.createIndex(parent.row(), 0, parent)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = self._node(index)
        if role == Qt.DisplayRole:
            return node.values[index.column()]
        if role == Qt.DecorationRole and index.column() == 0 and node.kind == "series":
            return self._icons.get(node.series_id, self._placeholder)
        if role == Qt.FontRole and node.kind in {"patient", "study"}:
            return QFont("", 9, QFont.Bold)
        if role == self.KindRole:
            return node.kind
        if role == self.SeriesIdRole:
            return node.series_id
        if role == self.SearchRole:
            return node.search_blob
        if role == self.ModalityRole:
            return node.modality
        if role == self.OrientationRole:
            return node.orientation
        if role == self.LoadedRole:
            return node.loaded
        if role == self.TitleRole:
            return node.values[0]
        if role == self.SeriesNumberRole:
            return node.series_number
        if role == self.SliceCountRole:
            return node.slice_count
        if role == self.BoundViewsRole:
            return node.bound_views
        if role == Qt.ToolTipRole and node.kind == "series":
            return " · ".join(value for value in node.values if value)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return (
                t("serieslistwidget.series"),
                t("serieslistwidget.status"),
                t("serieslistwidget.view"),
            )[section]
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.data(index, self.KindRole) == "series":
            flags |= Qt.ItemIsDragEnabled
        return flags

    def mimeTypes(self):
        return ["application/x-medimager-series", "text/plain"]

    def mimeData(self, indexes):
        series_ids = []
        for index in indexes:
            if index.column() != 0:
                continue
            series_id = self.data(index, self.SeriesIdRole)
            if series_id and series_id not in series_ids:
                series_ids.append(series_id)
        mime = QMimeData()
        if series_ids:
            mime.setData(
                "application/x-medimager-series", series_ids[0].encode("utf-8")
            )
            mime.setText(f"series:{series_ids[0]}")
        return mime

    def supportedDragActions(self):
        return Qt.CopyAction

    def index_for_series(self, series_id: str) -> QModelIndex:
        node = self._series_nodes.get(series_id)
        if node is None:
            return QModelIndex()
        return self.createIndex(node.row(), 0, node)

    def set_series_icon(self, series_id: str, icon: QIcon) -> None:
        self._icons[series_id] = icon
        index = self.index_for_series(series_id)
        if index.isValid():
            self.dataChanged.emit(index, index, [Qt.DecorationRole])

    def _node(self, index: QModelIndex) -> _StudyBrowserNode:
        if index.isValid():
            return index.internalPointer()
        return self._root


class StudyBrowserProxyModel(QSortFilterProxyModel):
    """Recursive multi-field filter for the study browser."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._query = ""
        self._modality = ""
        self._orientation = ""
        self._load_state = "all"
        self.setDynamicSortFilter(True)

    def set_filters(
        self,
        *,
        query: str = "",
        modality: str = "",
        orientation: str = "",
        load_state: str = "all",
    ) -> None:
        self._query = str(query or "").strip().casefold()
        self._modality = str(modality or "").upper()
        self._orientation = str(orientation or "").lower()
        self._load_state = str(load_state or "all")
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        kind = model.data(index, StudyBrowserModel.KindRole)
        if kind == "series":
            if self._query and self._query not in str(
                model.data(index, StudyBrowserModel.SearchRole) or ""
            ):
                return False
            if self._modality and model.data(
                index, StudyBrowserModel.ModalityRole
            ) != self._modality:
                return False
            if self._orientation and model.data(
                index, StudyBrowserModel.OrientationRole
            ) != self._orientation:
                return False
            loaded = bool(model.data(index, StudyBrowserModel.LoadedRole))
            if self._load_state == "loaded" and not loaded:
                return False
            if self._load_state == "pending" and loaded:
                return False
            return True
        for child_row in range(model.rowCount(index)):
            if self.filterAcceptsRow(child_row, index):
                return True
        return not any(
            (self._query, self._modality, self._orientation)
        ) and self._load_state == "all"


class StudyBrowserDelegate(QStyledItemDelegate):
    CARD_HEIGHT = 92
    CARD_MARGIN_X = 4
    CARD_MARGIN_Y = 3
    THUMBNAIL_WIDTH = 76
    THUMBNAIL_HEIGHT = 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self._card_mode = False

    def set_card_mode(self, enabled: bool) -> None:
        self._card_mode = bool(enabled)

    def uses_card_painting(self, index: QModelIndex) -> bool:
        return (
            self._card_mode
            and index.column() == 0
            and index.data(StudyBrowserModel.KindRole) == "series"
        )

    def card_data(self, index: QModelIndex) -> SeriesCardPresentation:
        return SeriesCardPresentation(
            title=str(index.data(StudyBrowserModel.TitleRole) or ""),
            modality=str(index.data(StudyBrowserModel.ModalityRole) or "—"),
            series_number=str(
                index.data(StudyBrowserModel.SeriesNumberRole) or ""
            ),
            orientation=str(
                index.data(StudyBrowserModel.OrientationRole) or "unknown"
            ),
            slice_count=max(
                0, int(index.data(StudyBrowserModel.SliceCountRole) or 0)
            ),
            loaded=bool(index.data(StudyBrowserModel.LoadedRole)),
            bound_views=tuple(
                str(view_id)
                for view_id in (
                    index.data(StudyBrowserModel.BoundViewsRole) or ()
                )
            ),
        )

    @staticmethod
    def viewport_badge_text(view_id: str) -> str:
        parts = str(view_id or "").split("_")
        if (
            len(parts) == 3
            and parts[0] == "view"
            and parts[1].isdigit()
            and parts[2].isdigit()
        ):
            return f"V{int(parts[1]) + 1}:{int(parts[2]) + 1}"
        return str(view_id or "—").replace("view_", "V", 1)

    @staticmethod
    def metadata_text(card: SeriesCardPresentation) -> str:
        values = [card.modality or "—"]
        if card.series_number:
            values.append(f"#{card.series_number}")
        values.extend(
            (
                (card.orientation or "unknown").capitalize(),
                t("serieslistwidget.slices_count").replace(
                    "%1", str(card.slice_count)
                ),
            )
        )
        return " · ".join(values)

    def paint(self, painter, option, index):
        kind = index.data(StudyBrowserModel.KindRole)
        if self._card_mode and kind == "series":
            if index.column() == 0:
                self._paint_series_card(painter, option, index)
            return
        super().paint(painter, option, index)

    def _paint_series_card(self, painter, option, index) -> None:
        card = self.card_data(index)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        palette = option.palette
        card_rect = option.rect.adjusted(
            self.CARD_MARGIN_X,
            self.CARD_MARGIN_Y,
            -self.CARD_MARGIN_X,
            -self.CARD_MARGIN_Y,
        )

        if selected:
            background = palette.highlight().color()
            border = palette.highlight().color().lighter(118)
            primary_text = palette.highlightedText().color()
        else:
            background = (
                palette.alternateBase().color()
                if hovered
                else palette.base().color()
            )
            border = (
                palette.highlight().color()
                if hovered
                else palette.mid().color()
            )
            primary_text = palette.text().color()

        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(background))
        painter.setPen(QPen(border, 2 if selected else 1))
        painter.drawRoundedRect(card_rect, 8, 8)

        thumbnail_rect = QRect(
            card_rect.left() + 8,
            card_rect.top() + 11,
            self.THUMBNAIL_WIDTH,
            self.THUMBNAIL_HEIGHT,
        )
        thumbnail_background = QColor(20, 23, 28)
        painter.setBrush(QBrush(thumbnail_background))
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(thumbnail_rect, 5, 5)

        icon = index.data(Qt.DecorationRole)
        pixmap = icon.pixmap(thumbnail_rect.size()) if isinstance(icon, QIcon) else QPixmap()
        if not pixmap.isNull():
            fitted = pixmap.scaled(
                thumbnail_rect.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            origin = QPoint(
                thumbnail_rect.center().x() - fitted.width() // 2,
                thumbnail_rect.center().y() - fitted.height() // 2,
            )
            painter.drawPixmap(origin, fitted)
        else:
            painter.setPen(QPen(QColor(220, 224, 230)))
            fallback_font = QFont(option.font)
            fallback_font.setBold(True)
            painter.setFont(fallback_font)
            painter.drawText(
                thumbnail_rect,
                Qt.AlignCenter,
                (card.modality or "—")[:3],
            )

        text_left = thumbnail_rect.right() + 11
        text_width = max(0, card_rect.right() - text_left - 8)
        title_rect = QRect(text_left, card_rect.top() + 7, text_width, 22)
        metadata_rect = QRect(text_left, title_rect.bottom() + 1, text_width, 18)
        badges_rect = QRect(text_left, metadata_rect.bottom() + 3, text_width, 22)

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QPen(primary_text))
        title = QFontMetrics(title_font).elidedText(
            card.title or "—", Qt.ElideRight, title_rect.width()
        )
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

        metadata_font = QFont(option.font)
        if metadata_font.pointSizeF() > 0:
            metadata_font.setPointSizeF(max(7.5, metadata_font.pointSizeF() - 1.0))
        painter.setFont(metadata_font)
        secondary_text = QColor(primary_text)
        secondary_text.setAlpha(205)
        painter.setPen(QPen(secondary_text))
        metadata = QFontMetrics(metadata_font).elidedText(
            self.metadata_text(card), Qt.ElideRight, metadata_rect.width()
        )
        painter.drawText(metadata_rect, Qt.AlignLeft | Qt.AlignVCenter, metadata)

        badge_font = QFont(metadata_font)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        next_left = self._draw_badge(
            painter,
            badges_rect,
            badges_rect.left(),
            t("serieslistwidget.loaded")
            if card.loaded
            else t("seriesinfowidget.not_loaded"),
            QColor(42, 128, 82) if card.loaded else QColor(176, 116, 32),
            QColor(255, 255, 255),
        )
        if card.bound_views:
            binding_background = palette.link().color()
            binding_foreground = QColor(255, 255, 255)
            for view_id in card.bound_views:
                next_left = self._draw_badge(
                    painter,
                    badges_rect,
                    next_left,
                    self.viewport_badge_text(view_id),
                    binding_background,
                    binding_foreground,
                )
                if next_left > badges_rect.right():
                    break
        else:
            self._draw_badge(
                painter,
                badges_rect,
                next_left,
                t("seriesinfowidget.unbound"),
                palette.mid().color(),
                primary_text,
            )
        painter.restore()

    @staticmethod
    def _draw_badge(
        painter,
        bounds: QRect,
        left: int,
        text: str,
        background: QColor,
        foreground: QColor,
    ) -> int:
        available = bounds.right() - left + 1
        if available < 16:
            return bounds.right() + 1
        metrics = painter.fontMetrics()
        display_text = metrics.elidedText(
            str(text), Qt.ElideRight, max(1, available - 12)
        )
        width = min(available, metrics.horizontalAdvance(display_text) + 14)
        badge_rect = QRect(left, bounds.top() + 1, width, bounds.height() - 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(background))
        painter.drawRoundedRect(badge_rect, 7, 7)
        painter.setPen(QPen(foreground))
        painter.drawText(badge_rect, Qt.AlignCenter, display_text)
        return badge_rect.right() + 5

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        kind = index.data(StudyBrowserModel.KindRole)
        if kind == "series":
            hint.setHeight(self.CARD_HEIGHT if self._card_mode else 64)
        else:
            hint.setHeight(max(28, hint.height()))
        return hint


class SeriesListWidget(QWidget):
    """序列列表组件
    
    显示所有已加载序列的列表，支持分组、筛选和拖拽操作。
    
    Signals:
        series_selected (str): 序列被选中时发出，参数为序列ID
        series_double_clicked (str): 序列被双击时发出，参数为序列ID
        series_context_menu (str, QPoint): 请求右键菜单时发出
    """
    
    series_selected = Signal(str)
    series_double_clicked = Signal(str)
    series_context_menu = Signal(str, QPoint)
    compare_requested = Signal(object)
    thumbnail_ready = Signal(str, object)
    
    def __init__(
        self,
        series_manager: MultiSeriesManager,
        parent: Optional[QWidget] = None,
        *,
        thumbnail_loading: bool = True,
    ) -> None:
        """初始化序列列表组件
        
        Args:
            series_manager: 多序列管理器
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug("[SeriesListWidget.__init__] 初始化序列列表组件")
        
        self._series_manager = series_manager
        self._thumbnail_loading_enabled = bool(thumbnail_loading)
        self._series_items: Dict[str, QTreeWidgetItem] = {}
        self._thumbnail_cache: Dict[str, QIcon] = {}
        self._thumbnail_pending: Set[str] = set()
        self._thumbnail_placeholder = self._create_thumbnail_placeholder()
        settings_manager = get_settings_manager()
        self._thumbnail_disk_cache = ThumbnailDiskCache(settings_manager)
        self._thumbnail_disk_cache.prune()
        self._privacy_enabled = self._to_bool(
            settings_manager.get_setting("privacy.screen_mode", False)
        )
        self.thumbnail_ready.connect(self._on_thumbnail_ready)

        self._setup_ui()
        self._connect_signals()
        self._refresh_tree()
        
        logger.debug("[SeriesListWidget.__init__] 序列列表组件初始化完成")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug("[SeriesListWidget._setup_ui] 设置序列列表UI")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # 标题和控制栏
        header_layout = QHBoxLayout()
        
        title_label = QLabel(t("serieslistwidget.sequence_listing"))
        title_label.setFont(QFont("", 10, QFont.Bold))
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # 分组选项
        self._group_combo = QComboBox()
        self._group_combo.addItems([
            t("serieslistwidget.study_browser"),
            t("serieslistwidget.group_by_patient"),
            t("serieslistwidget.group_by_study"),
            t("serieslistwidget.group_by_modal"),
            t("serieslistwidget.no_grouping"),
        ])
        self._group_combo.setCurrentIndex(0)
        self._group_combo.currentTextChanged.connect(self._on_group_changed)
        header_layout.addWidget(self._group_combo)
        self._group_combo.hide()
        
        layout.addLayout(header_layout)

        search_row = QHBoxLayout()
        search_row.setSpacing(4)
        self._search_edit = QLineEdit()
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setPlaceholderText(
            t("serieslistwidget.search_placeholder")
        )
        search_row.addWidget(self._search_edit, 1)

        self._modality_filter = QComboBox()
        self._modality_filter.addItem(t("serieslistwidget.all_modalities"), "")
        for modality in ("CT", "MR", "PT", "US", "CR", "DX", "NM"):
            self._modality_filter.addItem(modality, modality)
        self._modality_filter.setToolTip(t("serieslistwidget.filter_modality"))
        search_row.addWidget(self._modality_filter)
        layout.addLayout(search_row)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)
        self._orientation_filter = QComboBox()
        self._orientation_filter.addItem(
            t("serieslistwidget.all_orientations"), ""
        )
        for key in ("axial", "coronal", "sagittal", "oblique", "unknown"):
            self._orientation_filter.addItem(
                t(f"serieslistwidget.orientation_{key}"), key
            )
        filter_row.addWidget(self._orientation_filter)

        self._load_filter = QComboBox()
        self._load_filter.addItem(t("serieslistwidget.all_states"), "all")
        self._load_filter.addItem(t("serieslistwidget.loaded"), "loaded")
        self._load_filter.addItem(
            t("serieslistwidget.pending_or_failed"), "pending"
        )
        filter_row.addWidget(self._load_filter)

        self._density_combo = QComboBox()
        self._density_combo.addItem(
            t("serieslistwidget.compact_view"), "compact"
        )
        self._density_combo.addItem(t("serieslistwidget.card_view"), "cards")
        filter_row.addWidget(self._density_combo)

        self._compare_button = QPushButton(
            t("serieslistwidget.compare_selected")
        )
        self._compare_button.setEnabled(False)
        self._compare_button.setToolTip(
            t("serieslistwidget.compare_selected_tooltip")
        )
        filter_row.addWidget(self._compare_button)
        layout.addLayout(filter_row)

        self._browser_model = StudyBrowserModel(self)
        self._browser_proxy = StudyBrowserProxyModel(self)
        self._browser_proxy.setSourceModel(self._browser_model)
        self._browser_view = QTreeView()
        self._browser_view.setModel(self._browser_proxy)
        self._browser_view.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        self._browser_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._browser_view.setDragEnabled(True)
        self._browser_view.setDragDropMode(QAbstractItemView.DragOnly)
        self._browser_view.setIconSize(_THUMBNAIL_SIZE)
        self._browser_view.setUniformRowHeights(False)
        self._browser_view.setAlternatingRowColors(True)
        self._browser_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._browser_delegate = StudyBrowserDelegate(self._browser_view)
        self._browser_view.setItemDelegate(self._browser_delegate)
        self._browser_expand_timer = QTimer(self)
        self._browser_expand_timer.setSingleShot(True)
        self._browser_expand_timer.timeout.connect(self._expand_browser_groups)
        browser_header = self._browser_view.header()
        browser_header.setStretchLastSection(False)
        browser_header.setSectionResizeMode(0, QHeaderView.Stretch)
        browser_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        browser_header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self._browser_view, 1)
        
        # 序列树形列表
        self._tree_widget = DraggableTreeWidget()
        self._tree_widget.setHeaderLabels([
            t("serieslistwidget.series"),
            t("serieslistwidget.status"),
            t("serieslistwidget.view")
        ])
        self._tree_widget.setIconSize(_THUMBNAIL_SIZE)
        
        # 设置列宽
        header = self._tree_widget.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        # 连接信号
        self._tree_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree_widget.itemExpanded.connect(self._on_item_expanded)
        self._tree_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree_widget.customContextMenuRequested.connect(self._on_context_menu)
        self._tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree_widget.hide()
        
        layout.addWidget(self._tree_widget, 0)
        
        # 统计信息
        self._stats_label = QLabel(t("serieslistwidget.total_0_sequences"))
        self._stats_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._stats_label)

        self._search_edit.textChanged.connect(self._apply_browser_filters)
        self._modality_filter.currentIndexChanged.connect(
            self._apply_browser_filters
        )
        self._orientation_filter.currentIndexChanged.connect(
            self._apply_browser_filters
        )
        self._load_filter.currentIndexChanged.connect(
            self._apply_browser_filters
        )
        self._density_combo.currentIndexChanged.connect(
            self._on_density_changed
        )
        self._compare_button.clicked.connect(self._emit_compare_requested)
        self._browser_view.selectionModel().selectionChanged.connect(
            self._on_browser_selection_changed
        )
        self._browser_view.doubleClicked.connect(
            self._on_browser_double_clicked
        )
        self._browser_view.customContextMenuRequested.connect(
            self._on_browser_context_menu
        )
        
        logger.debug("[SeriesListWidget._setup_ui] 序列列表UI设置完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[SeriesListWidget._connect_signals] 连接序列列表信号槽")
        
        self._series_manager.series_added.connect(self._on_series_added)
        self._series_manager.series_removed.connect(self._on_series_removed)
        self._series_manager.series_loaded.connect(self._on_series_loaded)
        self._series_manager.binding_changed.connect(self._on_binding_changed)
    
    def _on_group_changed(self) -> None:
        """处理分组方式变更"""
        logger.debug(f"[SeriesListWidget._on_group_changed] 分组方式变更: {self._group_combo.currentText()}")
        self._refresh_tree()
    
    def _refresh_tree(self) -> None:
        """刷新树形列表"""
        logger.debug("[SeriesListWidget._refresh_tree] 刷新序列树形列表")
        
        try:
            self._tree_widget.clear()
            self._series_items.clear()
            
            series_ids = self._series_manager.get_all_series_ids()
            group_mode = self._group_combo.currentIndex()
            
            if group_mode == 0:
                self._add_study_hierarchy()
            elif group_mode == 4:  # 不分组
                self._add_series_flat(series_ids)
            else:
                self._add_series_grouped(series_ids, group_mode - 1)
            
            # 更新统计信息
            self._stats_label.setText(t("serieslistwidget.total_value_sequences").replace("%1", str(len(series_ids))))
            
            # Only expand grouping nodes. Series and slice pages stay lazy.
            for index in range(self._tree_widget.topLevelItemCount()):
                top_level = self._tree_widget.topLevelItem(index)
                if top_level.data(0, Qt.UserRole) is None:
                    top_level.setExpanded(True)

            self._refresh_browser_model()
            
            logger.debug(f"[SeriesListWidget._refresh_tree] 树形列表刷新完成: {len(series_ids)}个序列")
            
        except Exception as e:
            logger.error(f"[SeriesListWidget._refresh_tree] 刷新失败: {e}", exc_info=True)
    
    def _add_study_hierarchy(self) -> None:
        """Render the stable Patient -> Study -> Series inspection tree."""
        hierarchy = self._series_manager.get_study_hierarchy()
        for patient in hierarchy.patients:
            patient_item = QTreeWidgetItem(self._tree_widget)
            patient_label = patient.display_name or t("serieslistwidget.unknown_patient")
            if patient.patient_id:
                patient_label = f"{patient_label} · {patient.patient_id}"
            patient_item.setText(
                0,
                t("serieslistwidget.patient_summary")
                .replace("%1", patient_label)
                .replace("%2", str(len(patient.studies))),
            )
            patient_item.setFont(0, QFont("", 9, QFont.Bold))
            patient_item.setExpanded(True)

            for study in patient.studies:
                study_item = QTreeWidgetItem(patient_item)
                date = self._format_dicom_date(study.study_date)
                description = study.description or t("serieslistwidget.unknown_research")
                modalities = "/".join(study.modalities) or "—"
                label = t("serieslistwidget.study_summary")
                for marker, value in (
                    ("%1", date or "—"),
                    ("%2", description),
                    ("%3", modalities),
                    ("%4", str(study.series_count)),
                ):
                    label = label.replace(marker, value)
                study_item.setText(0, label)
                study_item.setFont(0, QFont("", 9, QFont.Bold))
                study_item.setExpanded(True)
                for series in study.series:
                    self._add_series_item(study_item, series.series_id)

    @staticmethod
    def _format_dicom_date(value: str) -> str:
        digits = str(value or "").strip()
        if len(digits) == 8 and digits.isdigit():
            return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
        return digits

    def _add_series_flat(self, series_ids: List[str]) -> None:
        """平铺方式添加序列"""
        for series_id in series_ids:
            self._add_series_item(None, series_id)
    
    def _add_series_grouped(self, series_ids: List[str], group_mode: int) -> None:
        """分组方式添加序列"""
        groups = {}
        
        for series_id in series_ids:
            series_info = self._series_manager.get_series_info(series_id)
            if not series_info:
                continue
            
            # 确定分组键
            if group_mode == 0:  # 按患者分组
                group_key = series_info.patient_name or t("serieslistwidget.unknown_patient")
            elif group_mode == 1:  # 按研究分组
                group_key = series_info.study_description or t("serieslistwidget.unknown_research")
            elif group_mode == 2:  # 按模态分组
                group_key = series_info.modality or t("serieslistwidget.unknown_modal")
            else:
                group_key = t("serieslistwidget.other")
            
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(series_id)
        
        # 创建分组节点
        for group_name, group_series in groups.items():
            group_item = QTreeWidgetItem(self._tree_widget)
            group_item.setText(0, f"{group_name} ({len(group_series)})")
            group_item.setFont(0, QFont("", 9, QFont.Bold))
            
            for series_id in group_series:
                self._add_series_item(group_item, series_id)
    
    def _add_series_item(self, parent: Optional[QTreeWidgetItem], series_id: str) -> None:
        """添加序列项目"""
        try:
            series_info = self._series_manager.get_series_info(series_id)
            if not series_info:
                return
            
            if parent:
                item = QTreeWidgetItem(parent)
            else:
                item = QTreeWidgetItem(self._tree_widget)
            
            # 设置序列信息
            series_desc = self._format_series_text(series_info)
            item.setText(0, series_desc)
            item.setData(0, Qt.UserRole, series_id)
            item.setToolTip(0, self._format_series_tooltip(series_info))
            item.setIcon(
                0, self._thumbnail_cache.get(
                    series_id, self._thumbnail_placeholder
                )
            )
            
            # 设置状态
            status_text = t("serieslistwidget.loaded") if series_info.is_loaded else t("seriesinfowidget.not_loaded")
            item.setText(1, status_text)
            
            # 设置绑定视图信息
            bound_views = self._series_manager.get_bound_views_for_series(series_id)
            if bound_views:
                view_text = t("serieslistwidget.view_count").replace("%1", str(len(bound_views)))
            else:
                view_text = t("seriesinfowidget.unbound")
            item.setText(2, view_text)
            
            # 添加切片子项目
            self._add_slice_items(item, series_id)
            
            # 存储项目引用
            self._series_items[series_id] = item
            if (
                self._thumbnail_loading_enabled
                and series_info.is_loaded
                and series_id not in self._thumbnail_cache
            ):
                self._schedule_thumbnail(series_id)
            
            logger.debug(f"[SeriesListWidget._add_series_item] 添加序列项目: {series_id}")
            
        except Exception as e:
            logger.error(f"[SeriesListWidget._add_series_item] 添加序列项目失败: {e}", exc_info=True)
    
    def _add_slice_items(self, series_item: QTreeWidgetItem, series_id: str) -> None:
        """Add inline slices for small volumes and lazy pages for large ones."""
        try:
            series_item.takeChildren()
            series_info = self._series_manager.get_series_info(series_id)
            if not series_info or not series_info.is_loaded:
                return
            
            # 获取图像数据模型
            image_model = self._series_manager.get_series_model(series_id)
            if not image_model or not image_model.has_image():
                return
            
            slice_count = image_model.get_slice_count()
            
            if slice_count <= _INLINE_SLICE_LIMIT:
                for slice_index in range(slice_count):
                    self._create_slice_item(series_item, series_id, slice_index)
            else:
                for start in range(0, slice_count, _SLICE_PAGE_SIZE):
                    end = min(start + _SLICE_PAGE_SIZE, slice_count)
                    range_item = QTreeWidgetItem(series_item)
                    range_label = f"{start + 1}–{end}"
                    range_item.setText(
                        0,
                        t("serieslistwidget.slice_value").replace("%1", range_label),
                    )
                    range_item.setData(
                        0, Qt.UserRole, ("slice_range", series_id, start, end)
                    )
                    # A placeholder supplies an expand affordance without creating
                    # hundreds of QTreeWidgetItems during series loading.
                    placeholder = QTreeWidgetItem(range_item)
                    placeholder.setData(0, Qt.UserRole, ("slice_placeholder",))
                
            logger.debug(f"[SeriesListWidget._add_slice_items] 添加切片项目: {series_id}, 数量: {slice_count}")
            
        except Exception as e:
            logger.error(f"[SeriesListWidget._add_slice_items] 添加切片项目失败: {e}", exc_info=True)

    def _create_slice_item(
        self, parent: QTreeWidgetItem, series_id: str, slice_index: int
    ) -> QTreeWidgetItem:
        slice_item = QTreeWidgetItem(parent)
        slice_item.setText(
            0,
            t("serieslistwidget.slice_value").replace("%1", str(slice_index + 1)),
        )
        slice_item.setData(0, Qt.UserRole, ("slice", series_id, slice_index))
        slice_item.setFont(0, QFont("", 8))
        return slice_item

    @staticmethod
    def _create_thumbnail_placeholder() -> QIcon:
        pixmap = QPixmap(_THUMBNAIL_SIZE)
        pixmap.fill(QColor('#30353b'))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#6f7a85'), 1))
        painter.drawRoundedRect(pixmap.rect().adjusted(1, 1, -2, -2), 4, 4)
        painter.setPen(QColor('#aeb7c0'))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, 'DICOM')
        painter.end()
        return QIcon(pixmap)

    def _thumbnail_identity(self, series_id: str) -> str:
        info = self._series_manager.get_series_info(series_id)
        return (
            getattr(info, "series_instance_uid", "")
            or ("|".join(getattr(info, "file_paths", [])[:2]) if info else "")
            or series_id
        )

    def _thumbnail_disk_path(self, series_id: str) -> Path:
        return self._thumbnail_disk_cache.path_for_identity(
            self._thumbnail_identity(series_id)
        )

    def _schedule_thumbnail(self, series_id: str) -> None:
        """Snapshot on the GUI thread; render and resize on a worker."""
        if series_id in self._thumbnail_cache or series_id in self._thumbnail_pending:
            return
        identity = self._thumbnail_identity(series_id)
        disk_path = self._thumbnail_disk_cache.lookup(identity)
        if disk_path is not None:
            icon = QIcon(str(disk_path))
            if not icon.isNull():
                self._thumbnail_cache[series_id] = icon
                if hasattr(self, "_browser_model"):
                    self._browser_model.set_series_icon(series_id, icon)
                item = self._series_items.get(series_id)
                if item is not None:
                    item.setIcon(0, icon)
                return
            self._thumbnail_disk_cache.discard(identity)
        try:
            model = self._series_manager.get_series_model(series_id)
            if model is None or not model.has_image():
                return
            middle_slice = model.get_slice_count() // 2
            if str(getattr(model, "image_mode", "")).startswith("rgb"):
                pixels = np.asarray(model.get_slice_data(middle_slice)).copy()
                future = get_performance_manager().get_thread_pool().submit(
                    _fit_thumbnail_array, model._as_uint8_rgb(pixels)
                )
            else:
                state = ViewPresentationState.from_model(model, series_id=series_id)
                state.slice_index = middle_slice
                cache_key, request = build_render_request(
                    model, state, copy_pixels=True
                )
                if request is None:
                    return
                future = get_performance_manager().get_thread_pool().submit(
                    _render_thumbnail_request, cache_key, request
                )
            self._thumbnail_pending.add(series_id)
        except Exception as error:
            logger.warning("[SeriesListWidget] 无法提交缩略图任务: %s", error)
            self._on_thumbnail_ready(series_id, None)
            return

        def done(done_future, sid=series_id):
            try:
                result = done_future.result()
            except Exception as error:
                logger.warning("[SeriesListWidget] 生成缩略图失败: %s", error)
                result = None
            try:
                self.thumbnail_ready.emit(sid, result)
            except RuntimeError:
                pass

        future.add_done_callback(done)

    def _on_thumbnail_ready(self, series_id: str, display_data) -> None:
        self._thumbnail_pending.discard(series_id)
        icon = self._thumbnail_placeholder
        if display_data is not None:
            try:
                image = qimage_from_display_data(display_data).copy()
                icon = QIcon(QPixmap.fromImage(image))
            except Exception as error:
                logger.warning("[SeriesListWidget] 缩略图转为图标失败: %s", error)
            else:
                try:
                    self._thumbnail_disk_cache.write_png(
                        self._thumbnail_identity(series_id),
                        lambda path: image.save(str(path), "PNG"),
                    )
                except OSError as error:
                    logger.warning("[SeriesListWidget] 无法写入缩略图缓存: %s", error)
        self._thumbnail_cache[series_id] = icon
        if hasattr(self, "_browser_model"):
            self._browser_model.set_series_icon(series_id, icon)
        item = self._series_items.get(series_id)
        if item is not None:
            item.setIcon(0, icon)


    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        kind, series_id, payload = _parse_tree_item_data(item.data(0, Qt.UserRole))
        if kind != "slice_range" or not series_id:
            return
        first_child = item.child(0) if item.childCount() else None
        if first_child is None or first_child.data(0, Qt.UserRole) != ("slice_placeholder",):
            return
        item.takeChildren()
        start, end = payload
        for slice_index in range(start, end):
            self._create_slice_item(item, series_id, slice_index)

    def find_slice_item(
        self, series_id: str, slice_index: int
    ) -> Optional[QTreeWidgetItem]:
        """Find and, for a large series, materialize only the requested page."""
        series_item = self._series_items.get(series_id)
        if series_item is None:
            return None
        for child_index in range(series_item.childCount()):
            child = series_item.child(child_index)
            kind, child_series_id, payload = _parse_tree_item_data(
                child.data(0, Qt.UserRole)
            )
            if kind == "slice" and child_series_id == series_id and payload == slice_index:
                return child
            if kind == "slice_range" and child_series_id == series_id:
                start, end = payload
                if start <= slice_index < end:
                    self._on_item_expanded(child)
                    child.setExpanded(True)
                    for page_index in range(child.childCount()):
                        slice_item = child.child(page_index)
                        item_kind, item_series_id, item_slice_index = _parse_tree_item_data(
                            slice_item.data(0, Qt.UserRole)
                        )
                        if (
                            item_kind == "slice"
                            and item_series_id == series_id
                            and item_slice_index == slice_index
                        ):
                            return slice_item
        return None

    def find_materialized_slice_item(
        self, series_id: str, slice_index: int
    ) -> Optional[QTreeWidgetItem]:
        """Find an already-created slice without expanding or allocating pages."""
        series_item = self._series_items.get(series_id)
        if series_item is None:
            return None
        pending = [series_item]
        while pending:
            parent = pending.pop()
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                kind, child_series_id, payload = _parse_tree_item_data(
                    child.data(0, Qt.UserRole)
                )
                if (
                    kind == "slice"
                    and child_series_id == series_id
                    and payload == slice_index
                ):
                    return child
                # Do not descend into collapsed range pages. Navigation must
                # remain O(materialized items), not allocate on every frame.
                if child.isExpanded():
                    pending.append(child)
        return None

    def update_current_slice_indicator(
        self, series_id: str, slice_index: int
    ) -> None:
        series_item = self._series_items.get(series_id)
        model = self._series_manager.get_series_model(series_id)
        if series_item is None or model is None:
            return
        status = t("serieslistwidget.loaded")
        count = model.get_slice_count()
        if count > 1:
            status = f"{status} · {slice_index + 1}/{count}"
        series_item.setText(1, status)
    
    @staticmethod
    def _format_series_tooltip(series_info: SeriesInfo) -> str:
        parts = [
            str(series_info.modality or ""),
            str(series_info.protocol_name or ""),
            str(series_info.body_part_examined or ""),
            str(series_info.orientation or "").capitalize(),
            t("serieslistwidget.slices_count").replace("%1", str(int(series_info.slice_count or 0))),
        ]
        return " · ".join(part for part in parts if part)

    def _format_series_text(self, series_info: SeriesInfo) -> str:
        """格式化序列显示文本"""
        return self._series_label(series_info)

    @staticmethod
    def _series_label(series_info: SeriesInfo) -> str:
        if series_info.series_description:
            return str(series_info.series_description)
        if series_info.modality:
            return (
                f"{series_info.modality} - "
                f"{t('serieslistwidget.series')}{series_info.series_number}"
            )
        return t("viewbindingwidget.sequence_value").replace(
            "%1", str(series_info.series_number)
        )

    def _refresh_browser_model(self) -> None:
        selected = set(self.get_selected_series_ids())
        self._browser_model.rebuild(
            self._series_manager,
            self._thumbnail_cache,
            self._thumbnail_placeholder,
            privacy=self._privacy_enabled,
        )
        self._schedule_browser_expand()
        if selected:
            selection_model = self._browser_view.selectionModel()
            for series_id in selected:
                source_index = self._browser_model.index_for_series(series_id)
                proxy_index = self._browser_proxy.mapFromSource(source_index)
                if proxy_index.isValid():
                    selection_model.select(
                        proxy_index,
                        QItemSelectionModel.Select | QItemSelectionModel.Rows,
                    )
        self._apply_browser_filters()

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _apply_browser_filters(self, *_args) -> None:
        self._browser_proxy.set_filters(
            query=self._search_edit.text(),
            modality=self._modality_filter.currentData() or "",
            orientation=self._orientation_filter.currentData() or "",
            load_state=self._load_filter.currentData() or "all",
        )
        self._schedule_browser_expand()

    def _schedule_browser_expand(self) -> None:
        # Expanding synchronously from a manager signal means QTreeView may
        # recurse through proxy indexes in the same stack as modelReset.  Qt 6
        # on Windows can dereference an invalid transient proxy index there.
        # A zero-delay, widget-owned timer lets the reset settle first and is
        # automatically cancelled when this panel is destroyed.
        if self._browser_view.isVisible():
            self._browser_expand_timer.start(0)

    def _expand_browser_groups(self) -> None:
        if not self._browser_view.isVisible():
            return
        for patient_row in range(self._browser_proxy.rowCount()):
            patient_index = self._browser_proxy.index(patient_row, 0)
            if not patient_index.isValid():
                continue
            self._browser_view.setExpanded(patient_index, True)
            for study_row in range(self._browser_proxy.rowCount(patient_index)):
                study_index = self._browser_proxy.index(study_row, 0, patient_index)
                if study_index.isValid():
                    self._browser_view.setExpanded(study_index, True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_browser_expand()

    def _on_density_changed(self, *_args) -> None:
        cards = self._density_combo.currentData() == "cards"
        self._browser_delegate.set_card_mode(cards)
        self._browser_view.setIconSize(
            QSize(96, 72) if cards else _THUMBNAIL_SIZE
        )
        self._browser_view.setAlternatingRowColors(not cards)
        self._browser_view.setMouseTracking(cards)
        # Do not traverse proxy indexes here. This slot can run synchronously
        # after a source-model reset; retaining recursive proxy QModelIndex
        # parents in that window can dereference invalid Qt internal pointers
        # on Windows. Hiding the secondary columns gives column zero the full
        # viewport width without touching model indexes at all.
        self._browser_view.setColumnHidden(1, cards)
        self._browser_view.setColumnHidden(2, cards)
        self._browser_view.doItemsLayout()
        self._browser_view.viewport().update()

    def _source_index(self, proxy_index: QModelIndex) -> QModelIndex:
        return self._browser_proxy.mapToSource(proxy_index)

    def get_selected_series_ids(self) -> List[str]:
        if not hasattr(self, "_browser_view"):
            return []
        result = []
        for proxy_index in self._browser_view.selectionModel().selectedRows(0):
            source_index = self._source_index(proxy_index)
            series_id = self._browser_model.data(
                source_index, StudyBrowserModel.SeriesIdRole
            )
            if series_id and series_id not in result:
                result.append(str(series_id))
        return result

    def _on_browser_selection_changed(self, *_args) -> None:
        series_ids = self.get_selected_series_ids()
        self._compare_button.setEnabled(bool(series_ids))
        if series_ids:
            self.series_selected.emit(series_ids[0])

    def _on_browser_double_clicked(self, proxy_index: QModelIndex) -> None:
        source_index = self._source_index(proxy_index)
        series_id = self._browser_model.data(
            source_index, StudyBrowserModel.SeriesIdRole
        )
        if series_id:
            self.series_double_clicked.emit(str(series_id))

    def _on_browser_context_menu(self, position: QPoint) -> None:
        proxy_index = self._browser_view.indexAt(position)
        if not proxy_index.isValid():
            return
        source_index = self._source_index(proxy_index)
        series_id = self._browser_model.data(
            source_index, StudyBrowserModel.SeriesIdRole
        )
        if series_id:
            self.series_context_menu.emit(
                str(series_id),
                self._browser_view.viewport().mapToGlobal(position),
            )

    def _emit_compare_requested(self) -> None:
        series_ids = self.get_selected_series_ids()
        if series_ids:
            self.compare_requested.emit(tuple(series_ids))

    def set_privacy_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._privacy_enabled != enabled:
            self._privacy_enabled = enabled
            self._refresh_browser_model()

    def set_density(self, density: str) -> None:
        index = self._density_combo.findData(
            "cards" if density == "cards" else "compact"
        )
        if index >= 0:
            self._density_combo.setCurrentIndex(index)
    
    def _on_selection_changed(self) -> None:
        """处理选择变更"""
        selected_items = self._tree_widget.selectedItems()
        if selected_items:
            item = selected_items[0]
            data = item.data(0, Qt.UserRole)
            if data:
                kind, series_id, payload = _parse_tree_item_data(data)
                if kind == "slice" and series_id is not None:
                    slice_index = payload
                    logger.debug(f"[SeriesListWidget._on_selection_changed] 选择切片: {series_id}, 切片: {slice_index}")
                    image_model = self._series_manager.get_series_model(series_id)
                    if image_model:
                        image_model.set_current_slice(slice_index)
                    self.series_selected.emit(series_id)
                elif kind in ("series", "slice_range") and series_id is not None:
                    logger.debug(f"[SeriesListWidget._on_selection_changed] 选择序列: {series_id}")
                    self.series_selected.emit(series_id)
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """处理项目双击"""
        data = item.data(0, Qt.UserRole)
        if data:
            kind, series_id, _ = _parse_tree_item_data(data)
            if kind == "slice" and series_id is not None:
                logger.debug(f"[SeriesListWidget._on_item_double_clicked] 双击切片，所属序列: {series_id}")
                self.series_double_clicked.emit(series_id)
            elif kind in ("series", "slice_range") and series_id is not None:
                logger.debug(f"[SeriesListWidget._on_item_double_clicked] 双击序列: {series_id}")
                self.series_double_clicked.emit(series_id)
    
    def _on_context_menu(self, position: QPoint) -> None:
        """处理右键菜单"""
        item = self._tree_widget.itemAt(position)
        if item:
            data = item.data(0, Qt.UserRole)
            if data:
                _, series_id, _ = _parse_tree_item_data(data)
                if not series_id:
                    return
                global_pos = self._tree_widget.mapToGlobal(position)
                logger.debug(f"[SeriesListWidget._on_context_menu] 请求右键菜单: {series_id}")
                self.series_context_menu.emit(series_id, global_pos)
    
    def _on_series_added(self, series_id: str) -> None:
        """处理序列添加事件"""
        logger.debug(f"[SeriesListWidget._on_series_added] 序列添加: {series_id}")
        self._refresh_tree()
    
    def _on_series_removed(self, series_id: str) -> None:
        """处理序列移除事件"""
        logger.debug(f"[SeriesListWidget._on_series_removed] 序列移除: {series_id}")
        self._thumbnail_cache.pop(series_id, None)
        self._thumbnail_pending.discard(series_id)
        self._refresh_tree()
    
    def _on_series_loaded(self, series_id: str) -> None:
        """处理序列加载事件"""
        logger.debug(f"[SeriesListWidget._on_series_loaded] 序列加载: {series_id}")
        
        # 更新对应项目的状态
        if series_id in self._series_items:
            item = self._series_items[series_id]
            item.setText(1, t("serieslistwidget.loaded"))
            
            # 添加切片子项目
            self._add_slice_items(item, series_id)
            item.setIcon(0, self._thumbnail_placeholder)
            self._schedule_thumbnail(series_id)
        self._refresh_browser_model()
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[SeriesListWidget._on_binding_changed] 绑定变更: view_id={view_id}, series_id={series_id}")
        
        # 刷新所有项目的绑定状态
        for sid in self._series_items:
            bound_views = self._series_manager.get_bound_views_for_series(sid)
            item = self._series_items[sid]
            if bound_views:
                item.setText(2, t("serieslistwidget.view_count").replace("%1", str(len(bound_views))))
            else:
                item.setText(2, t("seriesinfowidget.unbound"))
        self._refresh_browser_model()


class ViewBindingWidget(QWidget):
    """视图绑定组件
    
    管理序列与视图的绑定关系，支持拖拽分配和手动绑定。
    
    Signals:
        binding_requested (str, str): 请求绑定时发出，参数为(view_id, series_id)
        unbinding_requested (str): 请求解绑时发出，参数为view_id
    """
    
    binding_requested = Signal(str, str)
    unbinding_requested = Signal(str)
    
    def __init__(self, series_manager: MultiSeriesManager, parent: Optional[QWidget] = None) -> None:
        """初始化视图绑定组件
        
        Args:
            series_manager: 多序列管理器
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug("[ViewBindingWidget.__init__] 初始化视图绑定组件")
        
        self._series_manager = series_manager
        
        self._setup_ui()
        self._connect_signals()
        
        logger.debug("[ViewBindingWidget.__init__] 视图绑定组件初始化完成")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug("[ViewBindingWidget._setup_ui] 设置视图绑定UI")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # 标题
        title_label = QLabel(t("viewbindingwidget.view_binding"))
        title_label.setFont(QFont("", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # 视图绑定表格
        self._binding_table = QTableWidget()
        self._binding_table.setColumnCount(3)
        self._binding_table.setHorizontalHeaderLabels([
            t("viewbindingwidget.view_position"),
            t("viewbindingwidget.binding_sequence"),
            t("viewbindingwidget.actions")
        ])
        
        # 设置表格属性
        header = self._binding_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        self._binding_table.setSelectionBehavior(QTableWidget.SelectRows)
        
        layout.addWidget(self._binding_table)
        
        logger.debug("[ViewBindingWidget._setup_ui] 视图绑定UI设置完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[ViewBindingWidget._connect_signals] 连接视图绑定信号槽")
        
        self._series_manager.layout_changed.connect(self._on_layout_changed_signal)
        self._series_manager.binding_changed.connect(self._on_binding_changed)
        self._series_manager.active_view_changed.connect(self._on_active_view_changed)
    
    def _refresh_binding_table(self) -> None:
        """刷新绑定表格"""
        logger.debug("[ViewBindingWidget._refresh_binding_table] 刷新绑定表格")
        
        try:
            view_ids = self._series_manager.get_all_view_ids()
            self._binding_table.setRowCount(len(view_ids))
            
            for row, view_id in enumerate(view_ids):
                binding = self._series_manager.get_view_binding(view_id)
                if not binding:
                    continue
                
                # 位置列
                pos_text = f"{binding.position.value[0]+1}-{binding.position.value[1]+1}"
                if binding.is_active:
                    pos_text += " ★"
                
                pos_item = QTableWidgetItem(pos_text)
                self._binding_table.setItem(row, 0, pos_item)
                
                # 绑定序列列
                if binding.series_id:
                    series_info = self._series_manager.get_series_info(binding.series_id)
                    if series_info:
                        series_text = self._format_series_text(series_info)
                    else:
                        series_text = binding.series_id
                else:
                    series_text = t("seriesinfowidget.unbound")
                
                series_item = QTableWidgetItem(series_text)
                self._binding_table.setItem(row, 1, series_item)
                
                # 操作列 - 创建解绑按钮
                if binding.series_id:
                    unbind_btn = QPushButton(t("viewbindingwidget.unbind"))
                    unbind_btn.clicked.connect(lambda checked, vid=view_id: self._on_unbind_clicked(vid))
                    self._binding_table.setCellWidget(row, 2, unbind_btn)
                else:
                    self._binding_table.setItem(row, 2, QTableWidgetItem(""))
            
            logger.debug(f"[ViewBindingWidget._refresh_binding_table] 绑定表格刷新完成: {len(view_ids)}行")
            
        except Exception as e:
            logger.error(f"[ViewBindingWidget._refresh_binding_table] 刷新绑定表格失败: {e}", exc_info=True)
    
    def _format_series_text(self, series_info: SeriesInfo) -> str:
        """格式化序列文本"""
        if series_info.series_description:
            return f"{series_info.series_description}"
        return t("viewbindingwidget.sequence_value").replace("%1", str(series_info.series_number))
    
    def _on_unbind_clicked(self, view_id: str) -> None:
        """处理解绑点击"""
        logger.debug(f"[ViewBindingWidget._on_unbind_clicked] 解绑视图: {view_id}")
        self.unbinding_requested.emit(view_id)
    
    def _on_layout_changed_signal(self, layout: tuple) -> None:
        """处理布局变更信号"""
        logger.debug(f"[ViewBindingWidget._on_layout_changed_signal] 布局变更信号: {layout}")
        
        
        # 刷新绑定表格
        self._refresh_binding_table()
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更信号"""
        logger.debug(f"[ViewBindingWidget._on_binding_changed] 绑定变更信号: view_id={view_id}, series_id={series_id}")
        self._refresh_binding_table()
    
    def _on_active_view_changed(self, view_id: str) -> None:
        """处理活动视图变更信号"""
        logger.debug(f"[ViewBindingWidget._on_active_view_changed] 活动视图变更: {view_id}")
        self._refresh_binding_table()


class SeriesInfoWidget(QWidget):
    """序列信息组件
    
    显示选中序列的详细信息，包括DICOM元数据和统计信息。
    """
    
    def __init__(self, series_manager: MultiSeriesManager, parent: Optional[QWidget] = None) -> None:
        """初始化序列信息组件
        
        Args:
            series_manager: 多序列管理器
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug("[SeriesInfoWidget.__init__] 初始化序列信息组件")
        
        self._series_manager = series_manager
        self._current_series_id: Optional[str] = None
        
        self._setup_ui()
        
        logger.debug("[SeriesInfoWidget.__init__] 序列信息组件初始化完成")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug("[SeriesInfoWidget._setup_ui] 设置序列信息UI")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # 标题
        title_label = QLabel(t("seriesinfowidget.sequence_information"))
        title_label.setFont(QFont("", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(QFrame.NoFrame)
        
        info_widget = QWidget()
        self._info_layout = QVBoxLayout(info_widget)
        self._info_layout.setContentsMargins(4, 4, 4, 4)
        self._info_layout.setSpacing(8)
        
        # 基本信息组
        self._basic_group = self._create_info_group(t("seriesinfowidget.basic_information"))
        self._info_layout.addWidget(self._basic_group)
        
        # 技术参数组
        self._tech_group = self._create_info_group(t("seriesinfowidget.technical_parameters"))
        self._info_layout.addWidget(self._tech_group)
        
        # 状态信息组
        self._status_group = self._create_info_group(t("seriesinfowidget.status_information"))
        self._info_layout.addWidget(self._status_group)
        
        self._info_layout.addStretch()
        
        scroll.setWidget(info_widget)
        layout.addWidget(scroll)
        
        # 初始显示空状态
        self._show_empty_state()
        
        logger.debug("[SeriesInfoWidget._setup_ui] 序列信息UI设置完成")
    
    def _create_info_group(self, title: str) -> QGroupBox:
        """创建信息分组"""
        group = QGroupBox(title)
        group.setVisible(False)  # 初始隐藏
        return group
    
    def _show_empty_state(self) -> None:
        """显示空状态"""
        # 隐藏所有分组
        self._basic_group.setVisible(False)
        self._tech_group.setVisible(False)
        self._status_group.setVisible(False)
        
        # 显示提示
        if not hasattr(self, '_empty_label'):
            self._empty_label = QLabel(t("seriesinfowidget.please_select_a_sequence_to_view_details"))
            self._empty_label.setAlignment(Qt.AlignCenter)
            self._empty_label.setStyleSheet("color: gray; font-style: italic;")
            self._info_layout.addWidget(self._empty_label)
        
        self._empty_label.setVisible(True)
    
    def show_series_info(self, series_id: str) -> None:
        """显示序列信息
        
        Args:
            series_id: 序列ID
        """
        logger.debug(f"[SeriesInfoWidget.show_series_info] 显示序列信息: {series_id}")
        
        try:
            self._current_series_id = series_id
            series_info = self._series_manager.get_series_info(series_id)
            
            if not series_info:
                self._show_empty_state()
                return
            
            # 隐藏空状态标签
            if hasattr(self, '_empty_label'):
                self._empty_label.setVisible(False)
            
            # 填充基本信息
            self._fill_basic_info(series_info)
            
            # 填充技术参数
            self._fill_tech_info(series_info)
            
            # 填充状态信息
            self._fill_status_info(series_info)
            
            # 显示所有分组
            self._basic_group.setVisible(True)
            self._tech_group.setVisible(True)
            self._status_group.setVisible(True)
            
            logger.debug(f"[SeriesInfoWidget.show_series_info] 序列信息显示完成: {series_id}")
            
        except Exception as e:
            logger.error(f"[SeriesInfoWidget.show_series_info] 显示序列信息失败: {e}", exc_info=True)
            self._show_empty_state()
    
    def _fill_basic_info(self, series_info: SeriesInfo) -> None:
        """填充基本信息"""
        layout = self._basic_group.layout()
        if layout is None:
            layout = QVBoxLayout(self._basic_group)
            self._basic_group.setLayout(layout)
        else:
            self._clear_group_layout(self._basic_group)
        
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # 添加信息项
        self._add_info_item(layout, t("seriesinfowidget.patient_name"), series_info.patient_name)
        self._add_info_item(layout, t("seriesinfowidget.patient_id"), series_info.patient_id)
        self._add_info_item(layout, t("seriesinfowidget.study_description"), series_info.study_description)
        self._add_info_item(layout, t("seriesinfowidget.sequence_description"), series_info.series_description)
        self._add_info_item(layout, t("seriesinfowidget.inspection_mode"), series_info.modality)
        self._add_info_item(layout, t("seriesinfowidget.serial_no"), series_info.series_number)
    
    def _fill_tech_info(self, series_info: SeriesInfo) -> None:
        """填充技术参数"""
        layout = self._tech_group.layout()
        if layout is None:
            layout = QVBoxLayout(self._tech_group)
            self._tech_group.setLayout(layout)
        else:
            self._clear_group_layout(self._tech_group)
        
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # 添加技术参数
        self._add_info_item(layout, t("seriesinfowidget.number_of_slices"), str(series_info.slice_count))
        self._add_info_item(layout, t("seriesinfowidget.date_of_acquisition"), series_info.acquisition_date)
        self._add_info_item(layout, t("seriesinfowidget.time_of_acquisition"), series_info.acquisition_time)
        
        # 如果有图像数据模型，显示更多信息
        image_model = self._series_manager.get_series_model(series_info.series_id)
        if image_model and image_model.has_image():
            shape = image_model.get_image_shape()
            if shape:
                self._add_info_item(layout, t("seriesinfowidget.image_size"), f"{shape[1]} × {shape[2]}")
            
            self._add_info_item(layout, t("seriesinfowidget.window_width"), str(image_model.window_width))
            self._add_info_item(layout, t("seriesinfowidget.window_level"), str(image_model.window_level))
    
    def _fill_status_info(self, series_info: SeriesInfo) -> None:
        """填充状态信息"""
        layout = self._status_group.layout()
        if layout is None:
            layout = QVBoxLayout(self._status_group)
            self._status_group.setLayout(layout)
        else:
            self._clear_group_layout(self._status_group)
        
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        
        # 状态信息
        status = t("serieslistwidget.loaded") if series_info.is_loaded else t("seriesinfowidget.not_loaded")
        self._add_info_item(layout, t("seriesinfowidget.loading_status"), status)
        
        # 绑定视图信息
        bound_views = self._series_manager.get_bound_views_for_series(series_info.series_id)
        view_count = len(bound_views)
        view_info = t("serieslistwidget.view_count").replace("%1", str(view_count)) if view_count > 0 else t("seriesinfowidget.unbound")
        self._add_info_item(layout, t("seriesinfowidget.bind_view"), view_info)
        
        # 文件路径信息
        if series_info.file_paths:
            file_count = len(series_info.file_paths)
            self._add_info_item(layout, t("seriesinfowidget.number_of_documents"), str(file_count))
    
    def _clear_group_layout(self, group: QGroupBox) -> None:
        """清除分组的布局"""
        if group.layout():
            while group.layout().count():
                child = group.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
    
    def _add_info_item(self, layout: QVBoxLayout, label: str, value: str) -> None:
        """添加信息项"""
        if not value:
            value = t("seriesinfowidget.unknown")

        item_layout = QHBoxLayout()
        item_layout.setContentsMargins(0, 0, 0, 0)

        label_widget = QLabel(f"{label}:")
        label_widget.setMinimumWidth(70)
        label_widget.setMaximumWidth(100)
        label_widget.setAlignment(Qt.AlignRight | Qt.AlignTop)

        value_widget = QLabel(str(value))
        value_widget.setWordWrap(True)
        value_widget.setTextInteractionFlags(Qt.TextSelectableByMouse)

        item_layout.addWidget(label_widget)
        item_layout.addWidget(value_widget, 1)

        layout.addLayout(item_layout)


class SeriesPanel(QWidget):
    """序列面板

    整合序列列表、视图绑定和序列信息等功能的完整面板。

    Signals:
        series_selected (str): 序列被选中时发出
        binding_requested (str, str): 请求绑定时发出
        layout_change_requested (int, int): 请求布局变更时发出
    """

    series_selected = Signal(str)
    binding_requested = Signal(str, str)
    layout_change_requested = Signal(int, int)
    compare_requested = Signal(object)

    def __init__(
        self,
        series_manager: MultiSeriesManager,
        binding_manager: SeriesViewBindingManager,
        parent: Optional[QWidget] = None,
        *,
        thumbnail_loading: bool = True,
    ) -> None:
        """初始化序列面板
        
        Args:
            series_manager: 多序列管理器
            binding_manager: 绑定管理器
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug("[SeriesPanel.__init__] 初始化序列面板")
        
        self._series_manager = series_manager
        self._binding_manager = binding_manager
        self._connected_slice_signals: Dict[str, tuple[ImageDataModel, object]] = {}
        self._series_removal_handler = None
        
        self._thumbnail_loading = bool(thumbnail_loading)
        self._setup_ui()
        self._connect_signals()
        
        # 主题管理器注册
        self._theme_manager = None
        self._register_to_theme_manager()
        
        logger.info("[SeriesPanel.__init__] 序列面板初始化完成")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug("[SeriesPanel._setup_ui] 设置序列面板UI")
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        details_row = QHBoxLayout()
        details_row.addStretch()
        self._details_button = QPushButton(t("seriespanel.show_details"))
        self._details_button.setCheckable(True)
        self._details_button.setChecked(False)
        details_row.addWidget(self._details_button)
        main_layout.addLayout(details_row)
        
        # 创建分割器
        splitter = QSplitter(Qt.Vertical)
        
        # 序列列表组件
        self._series_list = SeriesListWidget(
            self._series_manager,
            thumbnail_loading=self._thumbnail_loading,
        )
        splitter.addWidget(self._series_list)
        
        # 视图绑定组件
        self._binding_widget = ViewBindingWidget(self._series_manager)
        splitter.addWidget(self._binding_widget)
        self._binding_widget.hide()
        
        # 序列信息组件
        self._info_widget = SeriesInfoWidget(self._series_manager)
        splitter.addWidget(self._info_widget)
        self._info_widget.hide()
        
        # 设置分割器比例
        splitter.setSizes([500, 0, 0])
        
        main_layout.addWidget(splitter)
        
        logger.debug("[SeriesPanel._setup_ui] 序列面板UI设置完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[SeriesPanel._connect_signals] 连接序列面板信号槽")
        
        # 序列列表信号
        self._series_list.series_selected.connect(self._on_series_selected)
        self._series_list.series_double_clicked.connect(self._on_series_double_clicked)
        self._series_list.series_context_menu.connect(self._on_series_context_menu)
        self._series_list.compare_requested.connect(self.compare_requested)
        self._details_button.toggled.connect(self._info_widget.setVisible)
        
        # 序列管理器信号 - 监听切片变化
        self._series_manager.active_view_changed.connect(self._on_active_view_changed)
        self._series_manager.series_loaded.connect(self._on_series_loaded_for_sync)
        self._series_manager.series_removed.connect(self._on_series_removed_for_sync)
        self._series_manager.binding_changed.connect(self._on_binding_changed_for_sync)
        
        # 绑定组件信号
        self._binding_widget.binding_requested.connect(self.binding_requested)
        self._binding_widget.unbinding_requested.connect(self._on_unbinding_requested)
    
    def _on_series_selected(self, series_id: str) -> None:
        """处理序列选择"""
        logger.debug(f"[SeriesPanel._on_series_selected] 序列选择: {series_id}")
        
        # 显示序列信息
        self._info_widget.show_series_info(series_id)
        
        # 转发信号
        self.series_selected.emit(series_id)
    
    def _on_series_double_clicked(self, series_id: str) -> None:
        """处理序列双击"""
        logger.debug(f"[SeriesPanel._on_series_double_clicked] 序列双击: {series_id}")
        
        # 使用绑定管理器智能绑定序列
        success = self._binding_manager.smart_bind_series(series_id)
        if success:
            logger.info(f"[SeriesPanel._on_series_double_clicked] 智能绑定成功: {series_id}")
        else:
            logger.warning(f"[SeriesPanel._on_series_double_clicked] 智能绑定失败: {series_id}")
    
    def _on_series_context_menu(self, series_id: str, position: QPoint) -> None:
        """处理序列右键菜单"""
        logger.debug(f"[SeriesPanel._on_series_context_menu] 序列右键菜单: {series_id}")
        
        menu = QMenu(self)
        
        # 添加菜单项
        bind_action = menu.addAction(t("seriespanel.bind_to_active_view"))
        bind_action.triggered.connect(lambda: self._bind_to_active_view(series_id))
        
        unbind_action = menu.addAction(t("seriespanel.unbind_all"))
        unbind_action.triggered.connect(lambda: self._unbind_all_views(series_id))
        
        menu.addSeparator()
        
        remove_action = menu.addAction(t("seriespanel.remove_sequence"))
        remove_action.triggered.connect(lambda: self._remove_series(series_id))
        
        menu.exec_(position)
    
    def _bind_to_active_view(self, series_id: str) -> None:
        """绑定到活动视图"""
        active_view_id = self._series_manager.get_active_view_id()
        if active_view_id:
            success = self._binding_manager.bind_series_to_view(
                active_view_id, series_id
            )
            if success:
                logger.info(f"[SeriesPanel._bind_to_active_view] 绑定成功: {series_id} -> {active_view_id}")
        else:
            logger.warning("[SeriesPanel._bind_to_active_view] 没有活动视图")
    
    def _unbind_all_views(self, series_id: str) -> None:
        """解除所有绑定"""
        bound_views = self._series_manager.get_bound_views_for_series(series_id)
        for view_id in bound_views:
            self._series_manager.unbind_series_from_view(view_id)
        
        logger.info(f"[SeriesPanel._unbind_all_views] 解除绑定完成: {series_id}")
    
    def _remove_series(self, series_id: str) -> None:
        """Remove a series only after an explicit, annotation-aware confirmation."""
        if callable(self._series_removal_handler):
            self._series_removal_handler(series_id)
            return
        summary = self._series_manager.get_series_removal_summary(series_id)
        if not summary.exists:
            logger.warning(f"[SeriesPanel._remove_series] 序列不存在: {series_id}")
            return

        series_info = self._series_manager.get_series_info(series_id)
        display_name = (
            self._series_list._format_series_text(series_info)
            if series_info is not None
            else series_id
        )
        message_lines = [f"{t('seriespanel.remove_sequence')}?", "", display_name]
        if summary.annotation_count:
            message_lines.append("")
            if summary.has_unsaved_annotations:
                message_lines.append(f"⚠ {t('seriespanel.unsaved_annotations')}")
            message_lines.extend(
                [
                    f"{t('settingsdialog.roi_settings')}: {summary.roi_count}",
                    f"{t('measurementtool.measurements')}: {summary.measurement_count}",
                    f"{t('mainwindow.angle_measurement')}: {summary.angle_measurement_count}",
                ]
            )

        dialog_title = (
            f"⚠ {t('seriespanel.remove_sequence')}"
            if summary.has_unsaved_annotations
            else t("seriespanel.remove_sequence")
        )
        answer = QMessageBox.warning(
            self,
            dialog_title,
            "\n".join(message_lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            logger.info(f"[SeriesPanel._remove_series] 用户取消移除: {series_id}")
            return

        success = self._series_manager.remove_series(
            series_id,
            allow_unsaved_annotations=summary.has_unsaved_annotations,
        )
        if success:
            logger.info(f"[SeriesPanel._remove_series] 序列移除成功: {series_id}")
        else:
            logger.warning(f"[SeriesPanel._remove_series] 序列移除失败: {series_id}")
    
    def _on_unbinding_requested(self, view_id: str) -> None:
        """处理解绑请求"""
        logger.debug(f"[SeriesPanel._on_unbinding_requested] 解绑请求: {view_id}")
        
        success = self._series_manager.unbind_series_from_view(view_id)
        if success:
            logger.info(f"[SeriesPanel._on_unbinding_requested] 解绑成功: {view_id}")
        else:
            logger.warning(f"[SeriesPanel._on_unbinding_requested] 解绑失败: {view_id}")
    
    # 公共接口方法
    
    def refresh_all(self) -> None:
        """刷新所有子组件"""
        logger.debug("[SeriesPanel.refresh_all] 刷新所有子组件")
        
        # 序列列表会自动响应管理器信号，不需要手动刷新
        # 这里可以添加其他需要手动刷新的逻辑
        pass
    
    def _on_active_view_changed(self, view_id: str) -> None:
        """处理活动视图变更，同步序列面板中的切片选择"""
        logger.debug(f"[SeriesPanel._on_active_view_changed] 活动视图变更: {view_id}")
        
        try:
            # 获取活动视图的绑定信息
            binding = self._series_manager.get_view_binding(view_id)
            if not binding or not binding.series_id:
                return
            
            # 获取图像模型
            image_model = self._series_manager.get_series_model(binding.series_id)
            if not image_model or not image_model.has_image():
                return
            
            # 连接切片变化信号（如果还没有连接）
            self._connect_slice_change_signal(binding.series_id, image_model)
            
            # 更新序列信息
            self._info_widget.show_series_info(binding.series_id)

            # 同步当前切片选择
            self.sync_slice_selection(binding.series_id, image_model.current_slice_index)
            
        except Exception as e:
            logger.error(f"[SeriesPanel._on_active_view_changed] 处理活动视图变更失败: {e}", exc_info=True)
    
    def _connect_slice_change_signal(self, series_id: str, image_model) -> None:
        """连接图像模型的切片变化信号"""
        try:
            existing = self._connected_slice_signals.get(series_id)
            if existing is not None:
                existing_model, existing_slot = existing
                if existing_model is image_model:
                    return
                try:
                    existing_model.slice_changed.disconnect(existing_slot)
                except (RuntimeError, TypeError):
                    pass

            def slot(slice_index, sid=series_id):
                self.sync_slice_selection(sid, slice_index)

            image_model.slice_changed.connect(slot)
            self._connected_slice_signals[series_id] = (image_model, slot)
            logger.debug(f"[SeriesPanel._connect_slice_change_signal] 连接切片变化信号: {series_id}")
            
        except Exception as e:
            logger.error(f"[SeriesPanel._connect_slice_change_signal] 连接信号失败: {e}", exc_info=True)

    def _on_binding_changed_for_sync(self, view_id: str, series_id: str) -> None:
        """绑定变化后连接新序列的切片同步，并同步活动视图当前切片。"""
        if not series_id:
            return

        try:
            image_model = self._series_manager.get_series_model(series_id)
            if not image_model or not image_model.has_image():
                return

            self._connect_slice_change_signal(series_id, image_model)

            if view_id == self._series_manager.get_active_view_id():
                self._info_widget.show_series_info(series_id)
                self.sync_slice_selection(series_id, image_model.current_slice_index)
        except Exception as e:
            logger.error(f"[SeriesPanel._on_binding_changed_for_sync] 处理绑定变化失败: {e}", exc_info=True)
    
    def sync_slice_selection(self, series_id: str, slice_index: int) -> None:
        """同步序列面板中的切片选择"""
        logger.debug(f"[SeriesPanel._sync_slice_selection] 同步切片选择: series_id={series_id}, slice_index={slice_index}")
        
        try:
            # 检查当前活动视图是否是这个序列
            active_view_id = self._series_manager.get_active_view_id()
            if active_view_id:
                binding = self._series_manager.get_view_binding(active_view_id)
                if not binding or binding.series_id != series_id:
                    logger.debug("[SeriesPanel._sync_slice_selection] 切片变化不是来自活动视图，跳过同步")
                    return
            
            self._series_list.update_current_slice_indicator(series_id, slice_index)
            series_item = self._series_list._series_items.get(series_id)
            # Browsing images must not force open the tree or scroll the side
            # panel.  If the user has explicitly expanded the series/page, we
            # may update an already materialized selection in place.
            if series_item is None or not series_item.isExpanded():
                return
            slice_item = self._series_list.find_materialized_slice_item(
                series_id, slice_index
            )
            if slice_item is not None:
                tree_widget = self._series_list._tree_widget
                blocker = QSignalBlocker(tree_widget)
                try:
                    tree_widget.setCurrentItem(slice_item)
                finally:
                    del blocker
                logger.debug(f"[SeriesPanel._sync_slice_selection] 选中切片项目: {slice_index}")
            
        except Exception as e:
            logger.error(f"[SeriesPanel._sync_slice_selection] 同步切片选择失败: {e}", exc_info=True)
    
    def _on_series_loaded_for_sync(self, series_id: str) -> None:
        """处理序列加载完成，为切片同步做准备"""
        logger.debug(f"[SeriesPanel._on_series_loaded_for_sync] 序列加载完成，准备同步: {series_id}")
        
        try:
            # 获取图像模型
            image_model = self._series_manager.get_series_model(series_id)
            if image_model and image_model.has_image():
                # 连接切片变化信号
                self._connect_slice_change_signal(series_id, image_model)
                
        except Exception as e:
            logger.error(f"[SeriesPanel._on_series_loaded_for_sync] 处理序列加载失败: {e}", exc_info=True)

    def _on_series_removed_for_sync(self, series_id: str) -> None:
        """Disconnect the exact lambda associated with a removed series model."""
        connection = self._connected_slice_signals.pop(series_id, None)
        if connection is None:
            return
        model, slot = connection
        try:
            model.slice_changed.disconnect(slot)
        except (RuntimeError, TypeError):
            pass
    
    def get_selected_series_id(self) -> Optional[str]:
        """获取当前选中的序列ID"""
        selected_items = self._series_list._tree_widget.selectedItems()
        if not selected_items:
            return None
        _, series_id, _ = _parse_tree_item_data(
            selected_items[0].data(0, Qt.UserRole)
        )
        return series_id

    def set_series_removal_handler(self, handler) -> None:
        """Delegate annotation-aware removal to the owning main window."""
        self._series_removal_handler = handler
    
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                self._theme_manager = main_window.theme_manager
                self._theme_manager.register_component(self)
                logger.debug("[SeriesPanel._register_to_theme_manager] 成功注册到主题管理器")
                
                # 立即应用当前主题
                current_theme = self._theme_manager.get_current_theme()
                self.update_theme(current_theme)
            else:
                logger.debug("[SeriesPanel._register_to_theme_manager] 未找到主题管理器")
        except Exception as e:
            logger.error(f"[SeriesPanel._register_to_theme_manager] 注册主题管理器失败: {e}", exc_info=True)
    
    def update_theme(self, theme_name: str) -> None:
        """主题更新接口 - 由ThemeManager调用"""
        logger.info(f"[SeriesPanel.update_theme] 开始更新主题: {theme_name} (ID: {id(self)})")
        try:
            # 更新面板背景色和文本颜色
            if theme_name == 'light':
                stylesheet = """
                    QWidget {
                        background-color: #ffffff;
                        color: #000000;
                    }
                    QTreeWidget {
                        background-color: #ffffff;
                        color: #000000;
                        border: 1px solid #cccccc;
                    }
                    QTableWidget {
                        background-color: #ffffff;
                        color: #000000;
                        border: 1px solid #cccccc;
                    }
                    QLabel {
                        color: #000000;
                    }
                """
                logger.info("[SeriesPanel.update_theme] 应用浅色主题样式")
            else:  # dark theme
                stylesheet = """
                    QWidget {
                        background-color: #2b2b2b;
                        color: #ffffff;
                    }
                    QTreeWidget {
                        background-color: #3c3c3c;
                        color: #ffffff;
                        border: 1px solid #555555;
                    }
                    QTableWidget {
                        background-color: #3c3c3c;
                        color: #ffffff;
                        border: 1px solid #555555;
                    }
                    QLabel {
                        color: #ffffff;
                    }
                """
                logger.info("[SeriesPanel.update_theme] 应用深色主题样式")
            
            self.setStyleSheet(stylesheet)
            logger.info("[SeriesPanel.update_theme] 样式表已应用")
            
            logger.info(f"[SeriesPanel.update_theme] 主题更新完成: {theme_name}")
        except Exception as e:
            logger.error(f"[SeriesPanel.update_theme] 主题更新失败: {e}", exc_info=True)
