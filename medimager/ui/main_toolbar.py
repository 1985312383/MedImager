import os
from PySide6.QtWidgets import QToolBar, QMenu, QToolButton, QStyle
from PySide6.QtGui import QAction, QIcon, QActionGroup, QPixmap, QPainter, QColor, QPen
from PySide6.QtCore import Qt, QPoint # <--- 修正点：在这里导入 QPoint

def create_icon_from_svg(shape: str) -> QIcon:
    """从SVG文件创建图标"""
    import os
    svg_path = os.path.abspath(f"medimager/icons/{shape}.svg")
    return QIcon(svg_path)


def _on_roi_tool_selected(main_window, roi_tool_button, action, tool_name):
    """当ROI工具被选中时，更新工具栏按钮并切换工具"""
    # 更新工具栏按钮的默认动作
    roi_tool_button.setDefaultAction(action)
    # 切换工具
    main_window._on_tool_selected(tool_name)


def create_main_toolbar(main_window) -> QToolBar:
    """
    创建并返回主工具栏。
    
    Args:
        main_window: MainWindow的实例，用于连接信号。
        
    Returns:
        配置好的QToolBar实例。
    """
    toolbar = QToolBar(main_window.tr("主工具"), main_window)
    toolbar.setObjectName("MainToolBar")
    # 为了美观，我们只显示图标
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)

    tool_action_group = QActionGroup(main_window)
    tool_action_group.setExclusive(True)

    # 在主窗口存储 actions，以便后续可以更新它们的选中状态
    main_window.tool_actions = {}

    # 1. 默认工具 (指针) - 使用click.svg图标
    import os
    click_icon_path = os.path.abspath("medimager/icons/click.svg")
    default_icon = QIcon(click_icon_path)
    
    action = QAction(default_icon, main_window.tr("指针"), main_window)
    action.setStatusTip(main_window.tr("激活默认的指针、平移、缩放、窗位工具"))
    action.setCheckable(True)
    action.setChecked(True) # 默认选中
    action.triggered.connect(lambda: main_window._on_tool_selected("default"))
    toolbar.addAction(action)
    tool_action_group.addAction(action)
    main_window.tool_actions["default"] = action

    toolbar.addSeparator()

    # 2. 折叠式ROI工具按钮
    roi_tool_button = QToolButton(toolbar)
    roi_tool_button.setPopupMode(QToolButton.MenuButtonPopup)
    # 默认也只显示图标
    roi_tool_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
    
    # 创建 Ellipse Action 并设为按钮的默认动作
    ellipse_action = QAction(create_icon_from_svg('ellipse'), main_window.tr("椭圆"), main_window)
    ellipse_action.setStatusTip(main_window.tr("绘制椭圆ROI"))
    ellipse_action.setCheckable(True)
    ellipse_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_tool_button, ellipse_action, "ellipse_roi"))
    roi_tool_button.setDefaultAction(ellipse_action)
    tool_action_group.addAction(ellipse_action)
    main_window.tool_actions["ellipse_roi"] = ellipse_action

    # 创建弹出菜单
    roi_menu = QMenu(roi_tool_button)
    
    # 将椭圆动作也添加到菜单中
    roi_menu.addAction(ellipse_action)
    
    # 创建 Rectangle Action
    rect_action = QAction(create_icon_from_svg('rectangle'), main_window.tr("矩形"), main_window)
    rect_action.setStatusTip(main_window.tr("绘制矩形ROI"))
    rect_action.setCheckable(True)
    rect_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_tool_button, rect_action, "rectangle_roi"))
    roi_menu.addAction(rect_action)
    tool_action_group.addAction(rect_action)
    main_window.tool_actions["rectangle_roi"] = rect_action

    # 创建 Circle Action
    circle_action = QAction(create_icon_from_svg('circle'), main_window.tr("圆形"), main_window)
    circle_action.setStatusTip(main_window.tr("绘制圆形ROI"))
    circle_action.setCheckable(True)
    circle_action.triggered.connect(lambda: _on_roi_tool_selected(main_window, roi_tool_button, circle_action, "circle_roi"))
    roi_menu.addAction(circle_action)
    tool_action_group.addAction(circle_action)
    main_window.tool_actions["circle_roi"] = circle_action

    roi_tool_button.setMenu(roi_menu)
    toolbar.addWidget(roi_tool_button)

    toolbar.addSeparator()

    # 3. 测量工具
    measure_action = QAction(create_icon_from_svg('ruler'), main_window.tr("测量"), main_window)
    measure_action.setStatusTip(main_window.tr("测量两点间的实际距离"))
    measure_action.setCheckable(True)
    measure_action.triggered.connect(lambda: main_window._on_tool_selected("measurement"))
    toolbar.addAction(measure_action)
    tool_action_group.addAction(measure_action)
    main_window.tool_actions["measurement"] = measure_action

    return toolbar