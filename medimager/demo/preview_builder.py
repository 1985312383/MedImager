"""Deterministically render the tiny bundled example-study preview assets."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image, ImageDraw


PREVIEW_SIZE = (320, 180)
_SCALE = 2


def build_preview_assets(output_dir: str | Path) -> tuple[Path, ...]:
    """Render the three catalog PNGs without depending on source DICOM pixels."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    renderers: tuple[tuple[str, Callable[[], Image.Image]], ...] = (
        ("ct_multiphase.png", _render_ct),
        ("mr_brain.png", _render_mr),
        ("geometry_lab.png", _render_geometry),
    )
    paths: list[Path] = []
    for filename, renderer in renderers:
        path = destination / filename
        renderer().save(path, format="PNG", compress_level=9, optimize=False)
        paths.append(path)
    return tuple(paths)


def _scaled(values: tuple[float, ...]) -> tuple[int, ...]:
    return tuple(round(value * _SCALE) for value in values)


def _canvas(start: str, end: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    width, height = (value * _SCALE for value in PREVIEW_SIZE)
    start_rgb = np.asarray(
        Image.new("RGB", (1, 1), start).getpixel((0, 0)), dtype=np.float64
    )
    end_rgb = np.asarray(
        Image.new("RGB", (1, 1), end).getpixel((0, 0)), dtype=np.float64
    )
    y, x = np.mgrid[0:height, 0:width]
    weight = ((x + y) / max(1, width + height - 2))[..., np.newaxis]
    rgb = np.rint(start_rgb + (end_rgb - start_rgb) * weight).astype(np.uint8)
    alpha = np.full((height, width, 1), 255, dtype=np.uint8)
    gradient = Image.fromarray(np.concatenate((rgb, alpha), axis=2), mode="RGBA")
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=16 * _SCALE,
        fill=255,
    )
    gradient.putalpha(mask)
    return gradient, ImageDraw.Draw(gradient)


def _finish(image: Image.Image) -> Image.Image:
    return image.resize(PREVIEW_SIZE, Image.Resampling.LANCZOS)


def _panel(draw: ImageDraw.ImageDraw, box: tuple[float, ...]) -> None:
    draw.rounded_rectangle(
        _scaled(box),
        radius=10 * _SCALE,
        fill="#06090e",
        outline="#3b4a5d",
        width=1 * _SCALE,
    )


def _render_ct() -> Image.Image:
    image, draw = _canvas("#101722", "#202b3a")
    _panel(draw, (14, 14, 156, 166))
    _panel(draw, (164, 14, 306, 86))
    _panel(draw, (164, 94, 306, 166))

    draw.ellipse(_scaled((26, 23, 144, 157)), fill="#75808c")
    draw.ellipse(_scaled((41, 30, 129, 146)), fill="#8e98a4")
    draw.ellipse(_scaled((38, 44, 76, 118)), fill="#17212b")
    draw.ellipse(_scaled((75, 41, 117, 119)), fill="#17212b")
    draw.ellipse(_scaled((68, 72, 102, 116)), fill="#aab2bc")
    draw.ellipse(_scaled((77, 134, 93, 150)), fill="#e5e9ee")
    draw.ellipse(_scaled((112, 79, 122, 89)), fill="#f2b96b")
    draw.line(_scaled((22, 90, 148, 90)), fill="#e9aa45", width=2 * _SCALE)
    draw.line(_scaled((85, 22, 85, 158)), fill="#e9aa45", width=2 * _SCALE)

    draw.ellipse(_scaled((182, 23, 288, 77)), fill="#77818c")
    draw.ellipse(_scaled((195, 32, 229, 66)), fill="#151e27")
    draw.ellipse(_scaled((239, 31, 277, 67)), fill="#151e27")
    draw.ellipse(_scaled((228, 43, 242, 57)), fill="#f0f3f6")
    draw.ellipse(_scaled((256, 45, 264, 53)), fill="#ff8b5c")

    draw.polygon(
        [
            _scaled(point)
            for point in (
                (200, 157),
                (194, 111),
                (213, 101),
                (257, 102),
                (275, 116),
                (269, 157),
            )
        ],
        fill="#6f7a86",
    )
    draw.line(_scaled((221, 156, 221, 109)), fill="#1b252f", width=16 * _SCALE)
    draw.line(_scaled((252, 156, 252, 108)), fill="#1b252f", width=16 * _SCALE)
    draw.line(_scaled((171, 130, 299, 130)), fill="#49c6d4", width=2 * _SCALE)
    draw.line(_scaled((235, 99, 235, 161)), fill="#49c6d4", width=2 * _SCALE)
    draw.ellipse(_scaled((251, 123, 259, 131)), fill="#ff8b5c")
    return _finish(image)


def _render_mr() -> Image.Image:
    image, draw = _canvas("#111520", "#25283a")
    for box in (
        (14, 14, 156, 86),
        (164, 14, 306, 86),
        (14, 94, 156, 166),
        (164, 94, 306, 166),
    ):
        _panel(draw, box)

    treatments = (
        (85, 50, "#aaa7b1", "#d1ced7", "#32323c", None),
        (235, 50, "#8c8996", "#5d5b68", "#e4e2e8", None),
        (85, 130, "#92909b", "#686673", "#15161c", "#d4c788"),
        (235, 130, "#6f707b", "#80828c", "#2b2c34", "#fff1a6"),
    )
    for cx, cy, outer, inner, ventricle, lesion in treatments:
        draw.ellipse(_scaled((cx - 46, cy - 30, cx + 46, cy + 30)), fill=outer)
        draw.ellipse(_scaled((cx - 33, cy - 22, cx + 33, cy + 22)), fill=inner)
        draw.polygon(
            [
                _scaled(point)
                for point in (
                    (cx - 14, cy - 5),
                    (cx, cy - 17),
                    (cx + 14, cy - 5),
                    (cx + 7, cy + 10),
                    (cx, cy + 12),
                    (cx - 7, cy + 10),
                )
            ],
            fill=ventricle,
        )
        if lesion is not None:
            draw.ellipse(_scaled((cx + 12, cy - 14, cx + 28, cy + 6)), fill=lesion)
    draw.line(_scaled((160, 20, 160, 160)), fill="#50586c", width=_SCALE)
    draw.line(_scaled((20, 90, 300, 90)), fill="#50586c", width=_SCALE)
    return _finish(image)


def _render_geometry() -> Image.Image:
    image, draw = _canvas("#0d1720", "#1d3039")
    draw.rounded_rectangle(
        _scaled((14, 14, 306, 166)),
        radius=10 * _SCALE,
        fill="#17252c",
        outline="#4c6872",
        width=2 * _SCALE,
    )
    for x in range(30, 306, 16):
        draw.line(_scaled((x, 14, x, 166)), fill="#38505a", width=_SCALE)
    for y in range(30, 166, 16):
        draw.line(_scaled((14, y, 306, y)), fill="#38505a", width=_SCALE)

    draw.polygon(
        [_scaled(point) for point in ((34, 127), (120, 145), (138, 63), (52, 46))],
        fill="#617782",
        outline="#a6c2cb",
    )
    draw.ellipse(_scaled((90, 76, 110, 96)), fill="#f4bb61")
    draw.line(_scaled((20, 91, 150, 91)), fill="#4fd0de", width=2 * _SCALE)
    draw.line(_scaled((82, 29, 82, 154)), fill="#4fd0de", width=2 * _SCALE)

    draw.ellipse(
        _scaled((177, 37, 283, 143)),
        fill="#17252c",
        outline="#78919b",
        width=2 * _SCALE,
    )
    draw.line(_scaled((183, 116, 273, 60)), fill="#e3a548", width=3 * _SCALE)
    draw.line(_scaled((192, 52, 274, 126)), fill="#e3a548", width=3 * _SCALE)
    draw.ellipse(_scaled((228, 80, 242, 94)), fill="#f06c61")
    draw.line(_scaled((178, 90, 282, 90)), fill="#66d4df", width=2 * _SCALE)
    draw.line(_scaled((230, 38, 230, 142)), fill="#66d4df", width=2 * _SCALE)
    return _finish(image)


if __name__ == "__main__":
    build_preview_assets(Path(__file__).with_name("previews"))
