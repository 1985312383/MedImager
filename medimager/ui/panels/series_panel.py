"""
序列面板模块

重新设计的序列面板，支持多序列管理、视图绑定和详细信息显示。
包含序列列表、绑定管理和信息展示等多个子组件。
"""

from typing import Dict, List, Optional, Set
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QLabel, QPushButton, QGroupBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QCheckBox, QSpinBox,
    QProgressBar, QTabWidget, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QMimeData
from PySide6.QtGui import QAction, QPixmap, QIcon, QFont, QColor, QPalette, QDrag, QPainter, QBrush, QPen, QFontMetrics

from medimager.core.multi_series_manager import MultiSeriesManager, SeriesInfo, ViewPosition
from medimager.core.series_view_binding import SeriesViewBindingManager, BindingStrategy, SortOrder
from medimager.core.image_data_model import ImageDataModel
from medimager.utils.logger import get_logger

logger = get_logger(__name__)


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
        series_id = item.data(0, Qt.UserRole)
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
    
    def __init__(self, series_manager: MultiSeriesManager, parent: Optional[QWidget] = None) -> None:
        """初始化序列列表组件
        
        Args:
            series_manager: 多序列管理器
            parent: 父组件
        """
        super().__init__(parent)
        logger.debug("[SeriesListWidget.__init__] 初始化序列列表组件")
        
        self._series_manager = series_manager
        self._series_items: Dict[str, QTreeWidgetItem] = {}
        
        self._setup_ui()
        self._connect_signals()
        
        logger.debug("[SeriesListWidget.__init__] 序列列表组件初始化完成")
    
    def _setup_ui(self) -> None:
        """设置UI"""
        logger.debug("[SeriesListWidget._setup_ui] 设置序列列表UI")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # 标题和控制栏
        header_layout = QHBoxLayout()
        
        title_label = QLabel(self.tr("序列列表"))
        title_label.setFont(QFont("", 10, QFont.Bold))
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # 分组选项
        self._group_combo = QComboBox()
        self._group_combo.addItems([
            self.tr("按患者分组"),
            self.tr("按研究分组"),
            self.tr("按模态分组"),
            self.tr("不分组")
        ])
        self._group_combo.setCurrentIndex(3) # 设置默认选项为"不分组"
        self._group_combo.currentTextChanged.connect(self._on_group_changed)
        header_layout.addWidget(self._group_combo)
        
        layout.addLayout(header_layout)
        
        # 序列树形列表
        self._tree_widget = DraggableTreeWidget()
        self._tree_widget.setHeaderLabels([
            self.tr("序列"),
            self.tr("状态"),
            self.tr("视图")
        ])
        
        # 设置列宽
        header = self._tree_widget.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        
        # 连接信号
        self._tree_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree_widget.customContextMenuRequested.connect(self._on_context_menu)
        self._tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        
        layout.addWidget(self._tree_widget)
        
        # 统计信息
        self._stats_label = QLabel(self.tr("共 0 个序列"))
        self._stats_label.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self._stats_label)
        
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
            
            if group_mode == 3:  # 不分组
                self._add_series_flat(series_ids)
            else:
                self._add_series_grouped(series_ids, group_mode)
            
            # 更新统计信息
            self._stats_label.setText(self.tr("共 %1 个序列").replace("%1", str(len(series_ids))))
            
            # 展开所有分组
            self._tree_widget.expandAll()
            
            logger.debug(f"[SeriesListWidget._refresh_tree] 树形列表刷新完成: {len(series_ids)}个序列")
            
        except Exception as e:
            logger.error(f"[SeriesListWidget._refresh_tree] 刷新失败: {e}", exc_info=True)
    
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
                group_key = series_info.patient_name or self.tr("未知患者")
            elif group_mode == 1:  # 按研究分组
                group_key = series_info.study_description or self.tr("未知研究")
            elif group_mode == 2:  # 按模态分组
                group_key = series_info.modality or self.tr("未知模态")
            else:
                group_key = self.tr("其他")
            
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
            
            # 设置状态
            status_text = self.tr("已加载") if series_info.is_loaded else self.tr("未加载")
            item.setText(1, status_text)
            
            # 设置绑定视图信息
            bound_views = self._series_manager.get_bound_views_for_series(series_id)
            if bound_views:
                view_text = self.tr("%1个视图").replace("%1", str(len(bound_views)))
            else:
                view_text = self.tr("未绑定")
            item.setText(2, view_text)
            
            # 添加切片子项目
            self._add_slice_items(item, series_id)
            
            # 存储项目引用
            self._series_items[series_id] = item
            
            logger.debug(f"[SeriesListWidget._add_series_item] 添加序列项目: {series_id}")
            
        except Exception as e:
            logger.error(f"[SeriesListWidget._add_series_item] 添加序列项目失败: {e}", exc_info=True)
    
    def _add_slice_items(self, series_item: QTreeWidgetItem, series_id: str) -> None:
        """为序列添加切片子项目"""
        try:
            series_info = self._series_manager.get_series_info(series_id)
            if not series_info or not series_info.is_loaded:
                return
            
            # 获取图像数据模型
            image_model = self._series_manager.get_series_model(series_id)
            if not image_model or not image_model.has_image():
                return
            
            slice_count = image_model.get_slice_count()
            
            # 为每个切片创建子项目
            for slice_index in range(slice_count):
                slice_item = QTreeWidgetItem(series_item)
                slice_item.setText(0, self.tr("切片 %1").replace("%1", str(slice_index + 1)))
                slice_item.setData(0, Qt.UserRole, f"{series_id}:{slice_index}")  # 存储序列ID和切片索引
                
                # 设置切片状态（如果需要）
                slice_item.setText(1, "")
                slice_item.setText(2, "")
                
                # 设置不同的图标或颜色来区分切片项目
                slice_item.setFont(0, QFont("", 8))
                
            logger.debug(f"[SeriesListWidget._add_slice_items] 添加切片项目: {series_id}, 数量: {slice_count}")
            
        except Exception as e:
            logger.error(f"[SeriesListWidget._add_slice_items] 添加切片项目失败: {e}", exc_info=True)
    
    def _format_series_text(self, series_info: SeriesInfo) -> str:
        """格式化序列显示文本"""
        if series_info.series_description:
            return f"{series_info.series_description}"
        elif series_info.modality:
            return f"{series_info.modality} - {self.tr('序列')}{series_info.series_number}"
        else:
            return self.tr("序列 %1").replace("%1", str(series_info.series_number))
    
    def _on_selection_changed(self) -> None:
        """处理选择变更"""
        selected_items = self._tree_widget.selectedItems()
        if selected_items:
            item = selected_items[0]
            data = item.data(0, Qt.UserRole)
            if data:
                if ":" in str(data):
                    # 这是一个切片项目
                    series_id, slice_index_str = str(data).split(":", 1)
                    try:
                        slice_index = int(slice_index_str)
                        logger.debug(f"[SeriesListWidget._on_selection_changed] 选择切片: {series_id}, 切片: {slice_index}")
                        
                        # 切换到对应的切片
                        image_model = self._series_manager.get_series_model(series_id)
                        if image_model:
                            image_model.set_current_slice(slice_index)
                        
                        # 发出序列选择信号
                        self.series_selected.emit(series_id)
                    except (ValueError, IndexError):
                        logger.warning(f"[SeriesListWidget._on_selection_changed] 无效的切片索引: {data}")
                else:
                    # 这是一个序列项目
                    series_id = str(data)
                    logger.debug(f"[SeriesListWidget._on_selection_changed] 选择序列: {series_id}")
                    self.series_selected.emit(series_id)
    
    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """处理项目双击"""
        data = item.data(0, Qt.UserRole)
        if data:
            if ":" in str(data):
                # 这是一个切片项目，双击时发出序列选择信号
                series_id, _ = str(data).split(":", 1)
                logger.debug(f"[SeriesListWidget._on_item_double_clicked] 双击切片，所属序列: {series_id}")
                self.series_double_clicked.emit(series_id)
            else:
                # 这是一个序列项目
                series_id = str(data)
                logger.debug(f"[SeriesListWidget._on_item_double_clicked] 双击序列: {series_id}")
                self.series_double_clicked.emit(series_id)
    
    def _on_context_menu(self, position: QPoint) -> None:
        """处理右键菜单"""
        item = self._tree_widget.itemAt(position)
        if item:
            data = item.data(0, Qt.UserRole)
            if data:
                if ":" in str(data):
                    # 这是一个切片项目，获取序列ID
                    series_id, _ = str(data).split(":", 1)
                else:
                    # 这是一个序列项目
                    series_id = str(data)
                
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
        self._refresh_tree()
    
    def _on_series_loaded(self, series_id: str) -> None:
        """处理序列加载事件"""
        logger.debug(f"[SeriesListWidget._on_series_loaded] 序列加载: {series_id}")
        
        # 更新对应项目的状态
        if series_id in self._series_items:
            item = self._series_items[series_id]
            item.setText(1, self.tr("已加载"))
            
            # 添加切片子项目
            self._add_slice_items(item, series_id)
            
            # 展开该序列项目以显示切片
            item.setExpanded(True)
    
    def _on_binding_changed(self, view_id: str, series_id: str) -> None:
        """处理绑定变更事件"""
        logger.debug(f"[SeriesListWidget._on_binding_changed] 绑定变更: view_id={view_id}, series_id={series_id}")
        
        # 刷新所有项目的绑定状态
        for sid in self._series_items:
            bound_views = self._series_manager.get_bound_views_for_series(sid)
            item = self._series_items[sid]
            if bound_views:
                item.setText(2, self.tr("%1个视图").replace("%1", str(len(bound_views))))
            else:
                item.setText(2, self.tr("未绑定"))


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
        title_label = QLabel(self.tr("视图绑定"))
        title_label.setFont(QFont("", 10, QFont.Bold))
        layout.addWidget(title_label)
        
        # 视图绑定表格
        self._binding_table = QTableWidget()
        self._binding_table.setColumnCount(3)
        self._binding_table.setHorizontalHeaderLabels([
            self.tr("视图位置"),
            self.tr("绑定序列"),
            self.tr("操作")
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
                    series_text = self.tr("未绑定")
                
                series_item = QTableWidgetItem(series_text)
                self._binding_table.setItem(row, 1, series_item)
                
                # 操作列 - 创建解绑按钮
                if binding.series_id:
                    unbind_btn = QPushButton(self.tr("解绑"))
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
        return self.tr("序列 %1").replace("%1", str(series_info.series_number))
    
    def _on_unbind_clicked(self, view_id: str) -> None:
        """处理解绑点击"""
        logger.debug(f"[ViewBindingWidget._on_unbind_clicked] 解绑视图: {view_id}")
        self.unbinding_requested.emit(view_id)
    
    def _on_layout_changed_signal(self, layout: tuple) -> None:
        """处理布局变更信号"""
        logger.debug(f"[ViewBindingWidget._on_layout_changed_signal] 布局变更信号: {layout}")
        
        # 更新布局选择器
        rows, cols = layout
        layout_text = f"{rows}×{cols}"
        
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
        title_label = QLabel(self.tr("序列信息"))
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
        self._basic_group = self._create_info_group(self.tr("基本信息"))
        self._info_layout.addWidget(self._basic_group)
        
        # 技术参数组
        self._tech_group = self._create_info_group(self.tr("技术参数"))
        self._info_layout.addWidget(self._tech_group)
        
        # 状态信息组
        self._status_group = self._create_info_group(self.tr("状态信息"))
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
            self._empty_label = QLabel(self.tr("请选择一个序列查看详细信息"))
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
        self._add_info_item(layout, self.tr("患者姓名"), series_info.patient_name)
        self._add_info_item(layout, self.tr("患者ID"), series_info.patient_id)
        self._add_info_item(layout, self.tr("研究描述"), series_info.study_description)
        self._add_info_item(layout, self.tr("序列描述"), series_info.series_description)
        self._add_info_item(layout, self.tr("检查模态"), series_info.modality)
        self._add_info_item(layout, self.tr("序列号"), series_info.series_number)
    
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
        self._add_info_item(layout, self.tr("切片数量"), str(series_info.slice_count))
        self._add_info_item(layout, self.tr("获取日期"), series_info.acquisition_date)
        self._add_info_item(layout, self.tr("获取时间"), series_info.acquisition_time)
        
        # 如果有图像数据模型，显示更多信息
        image_model = self._series_manager.get_series_model(series_info.series_id)
        if image_model and image_model.has_image():
            shape = image_model.get_image_shape()
            if shape:
                self._add_info_item(layout, self.tr("图像尺寸"), f"{shape[1]} × {shape[2]}")
            
            self._add_info_item(layout, self.tr("窗宽"), str(image_model.window_width))
            self._add_info_item(layout, self.tr("窗位"), str(image_model.window_level))
    
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
        status = self.tr("已加载") if series_info.is_loaded else self.tr("未加载")
        self._add_info_item(layout, self.tr("加载状态"), status)
        
        # 绑定视图信息
        bound_views = self._series_manager.get_bound_views_for_series(series_info.series_id)
        view_count = len(bound_views)
        view_info = self.tr("%1个视图").replace("%1", str(view_count)) if view_count > 0 else self.tr("未绑定")
        self._add_info_item(layout, self.tr("绑定视图"), view_info)
        
        # 文件路径信息
        if series_info.file_paths:
            file_count = len(series_info.file_paths)
            self._add_info_item(layout, self.tr("文件数量"), str(file_count))
    
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
            value = self.tr("未知")
        
        item_layout = QHBoxLayout()
        item_layout.setContentsMargins(0, 0, 0, 0)
        
        label_widget = QLabel(f"{label}:")
        label_widget.setFixedWidth(80)
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
    
    def __init__(self, series_manager: MultiSeriesManager, 
                 binding_manager: SeriesViewBindingManager,
                 parent: Optional[QWidget] = None) -> None:
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
        
        # 创建分割器
        splitter = QSplitter(Qt.Vertical)
        
        # 序列列表组件
        self._series_list = SeriesListWidget(self._series_manager)
        splitter.addWidget(self._series_list)
        
        # 视图绑定组件
        self._binding_widget = ViewBindingWidget(self._series_manager)
        splitter.addWidget(self._binding_widget)
        
        # 序列信息组件
        self._info_widget = SeriesInfoWidget(self._series_manager)
        splitter.addWidget(self._info_widget)
        
        # 设置分割器比例
        splitter.setSizes([200, 150, 150])
        
        main_layout.addWidget(splitter)
        
        logger.debug("[SeriesPanel._setup_ui] 序列面板UI设置完成")
    
    def _connect_signals(self) -> None:
        """连接信号槽"""
        logger.debug("[SeriesPanel._connect_signals] 连接序列面板信号槽")
        
        # 序列列表信号
        self._series_list.series_selected.connect(self._on_series_selected)
        self._series_list.series_double_clicked.connect(self._on_series_double_clicked)
        self._series_list.series_context_menu.connect(self._on_series_context_menu)
        
        # 序列管理器信号 - 监听切片变化
        self._series_manager.active_view_changed.connect(self._on_active_view_changed)
        self._series_manager.series_loaded.connect(self._on_series_loaded_for_sync)
        
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
        bind_action = menu.addAction(self.tr("绑定到活动视图"))
        bind_action.triggered.connect(lambda: self._bind_to_active_view(series_id))
        
        unbind_action = menu.addAction(self.tr("解除所有绑定"))
        unbind_action.triggered.connect(lambda: self._unbind_all_views(series_id))
        
        menu.addSeparator()
        
        remove_action = menu.addAction(self.tr("移除序列"))
        remove_action.triggered.connect(lambda: self._remove_series(series_id))
        
        menu.exec_(position)
    
    def _bind_to_active_view(self, series_id: str) -> None:
        """绑定到活动视图"""
        active_view_id = self._series_manager.get_active_view_id()
        if active_view_id:
            success = self._series_manager.bind_series_to_view(active_view_id, series_id)
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
        """移除序列"""
        success = self._series_manager.remove_series(series_id)
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
            # 为了避免重复连接，先断开可能存在的连接
            if hasattr(self, '_connected_slice_signals'):
                if series_id in self._connected_slice_signals:
                    return  # 已经连接过了
            else:
                self._connected_slice_signals = set()
            
            # 连接切片变化信号
            image_model.slice_changed.connect(
                lambda slice_index, sid=series_id: self.sync_slice_selection(sid, slice_index)
            )
            
            self._connected_slice_signals.add(series_id)
            logger.debug(f"[SeriesPanel._connect_slice_change_signal] 连接切片变化信号: {series_id}")
            
        except Exception as e:
            logger.error(f"[SeriesPanel._connect_slice_change_signal] 连接信号失败: {e}", exc_info=True)
    
    def sync_slice_selection(self, series_id: str, slice_index: int) -> None:
        """同步序列面板中的切片选择"""
        logger.debug(f"[SeriesPanel._sync_slice_selection] 同步切片选择: series_id={series_id}, slice_index={slice_index}")
        
        try:
            # 检查当前活动视图是否是这个序列
            active_view_id = self._series_manager.get_active_view_id()
            if active_view_id:
                binding = self._series_manager.get_view_binding(active_view_id)
                if not binding or binding.series_id != series_id:
                    logger.debug(f"[SeriesPanel._sync_slice_selection] 切片变化不是来自活动视图，跳过同步")
                    return
            
            # 在序列列表中找到对应的切片项目并选中
            if hasattr(self._series_list, '_series_items') and series_id in self._series_list._series_items:
                series_item = self._series_list._series_items[series_id]
                
                # 查找对应的切片子项目
                for i in range(series_item.childCount()):
                    slice_item = series_item.child(i)
                    data = slice_item.data(0, Qt.UserRole)
                    
                    if data and ":" in str(data):
                        item_series_id, item_slice_index_str = str(data).split(":", 1)
                        try:
                            item_slice_index = int(item_slice_index_str)
                            if item_series_id == series_id and item_slice_index == slice_index:
                                # 找到了对应的切片项目，暂时断开信号以避免循环
                                self._series_list._tree_widget.itemSelectionChanged.disconnect(self._series_list._on_selection_changed)
                                
                                # 选中切片项目
                                self._series_list._tree_widget.setCurrentItem(slice_item)
                                
                                # 确保父项目展开
                                series_item.setExpanded(True)
                                
                                # 重新连接信号
                                self._series_list._tree_widget.itemSelectionChanged.connect(self._series_list._on_selection_changed)
                                
                                logger.debug(f"[SeriesPanel._sync_slice_selection] 选中切片项目: {slice_index}")
                                break
                        except (ValueError, IndexError):
                            continue
            
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
    
    def get_selected_series_id(self) -> Optional[str]:
        """获取当前选中的序列ID"""
        # 这里需要从序列列表组件获取选中项
        # 实现省略，返回None
        return None
    
    def _register_to_theme_manager(self) -> None:
        """注册到主题管理器"""
        try:
            # 尝试从父窗口获取主题管理器
            main_window = self.window()
            if hasattr(main_window, 'theme_manager'):
                self._theme_manager = main_window.theme_manager
                self._theme_manager.register_component(self)
                logger.debug(f"[SeriesPanel._register_to_theme_manager] 成功注册到主题管理器")
                
                # 立即应用当前主题
                current_theme = self._theme_manager.get_current_theme()
                self.update_theme(current_theme)
            else:
                logger.debug(f"[SeriesPanel._register_to_theme_manager] 未找到主题管理器")
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
                logger.info(f"[SeriesPanel.update_theme] 应用浅色主题样式")
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
                logger.info(f"[SeriesPanel.update_theme] 应用深色主题样式")
            
            self.setStyleSheet(stylesheet)
            logger.info(f"[SeriesPanel.update_theme] 样式表已应用")
            
            logger.info(f"[SeriesPanel.update_theme] 主题更新完成: {theme_name}")
        except Exception as e:
            logger.error(f"[SeriesPanel.update_theme] 主题更新失败: {e}", exc_info=True)