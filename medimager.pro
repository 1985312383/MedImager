# ----------------------------------------------------
# MedImager Project File
# ----------------------------------------------------

# 指定源码文件
SOURCES += \
    medimager/main.py \
    medimager/core/dicom_parser.py \
    medimager/core/image_data_model.py \
    medimager/core/roi.py \
    medimager/ui/main_window.py \
    medimager/ui/image_viewer.py \
    medimager/ui/viewport.py \
    medimager/ui/main_toolbar.py \
    medimager/ui/panels/series_panel.py \
    medimager/ui/panels/dicom_tag_panel.py \
    medimager/ui/dialogs/settings_dialog.py \
    medimager/ui/dialogs/custom_wl_dialog.py \
    medimager/ui/tools/base_tool.py \
    medimager/ui/tools/default_tool.py \
    medimager/ui/tools/roi_tool.py \
    medimager/ui/tools/measurement_tool.py

# 指定翻译文件
TRANSLATIONS += \
    medimager/translations/zh_CN.ts \
    medimager/translations/en_US.ts

# lupdate 工具选项
# -locations none: 不在.ts文件中记录行号，使翻译更稳定
LUPDATE_OPTIONS = -locations none -no-obsolete

CODECFORTR = UTF-8 