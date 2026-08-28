# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata


decoder_metadata = []
for distribution in (
    'pylibjpeg',
    'pylibjpeg-libjpeg',
    'pylibjpeg-openjpeg',
    'pyjpegls',
):
    decoder_metadata += copy_metadata(distribution)

decoder_hiddenimports = [
    'pydicom.pixels.decoders.pylibjpeg',
    'pydicom.pixels.decoders.pyjpegls',
    'pylibjpeg',
    'pylibjpeg.utils',
    'libjpeg',
    'libjpeg.utils',
    'openjpeg',
    'openjpeg.utils',
    'jpeg_ls',
    'jpeg_ls.CharLS',
    '_libjpeg',
    '_openjpeg',
    '_CharLS',
]

# Package every vector icon registered by the UI; legacy bitmaps stay excluded.
runtime_icons = sorted(path.name for path in Path('medimager/icons').glob('*.svg'))

runtime_datas = [
    *decoder_metadata,
    *[(f'medimager\\icons\\{name}', 'medimager/icons') for name in runtime_icons],
    ('medimager\\icons\\logo.png', 'medimager/icons'),
    ('medimager\\themes', 'medimager/themes'),
    ('medimager\\i18n\\compiled', 'medimager/i18n/compiled'),
    ('medimager\\i18n\\manifest.yml', 'medimager/i18n'),
    ('pyproject.toml', '.'),
    ('CHANGELOG.md', '.'),
]


a = Analysis(
    ['medimager\\main.py'],
    pathex=[],
    binaries=[],
    datas=runtime_datas,
    hiddenimports=decoder_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MedImager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['medimager\\icons\\favicon.ico'],
)
