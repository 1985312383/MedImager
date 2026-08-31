import pydicom
import pytest
from PySide6.QtCore import QPointF

from medimager.core.sync_manager import SyncMode
from tests.test_sync_view_integration import _bind_two_series, _model_with_geometry


def test_orthogonal_series_emit_a_clipped_patient_plane_intersection():
    frame_uid = pydicom.uid.generate_uid()
    source = _model_with_geometry([(0, 0, 10)], frame_uid=frame_uid)
    target = _model_with_geometry(
        [(0, 0, 0)],
        orientation=(0, 1, 0, 0, 0, 1),
        frame_uid=frame_uid,
    )
    _, sync = _bind_two_series(source, target)
    lines = []
    sync.cross_reference_line_updated.connect(
        lambda view_id, start, end: lines.append(
            (view_id, QPointF(start), QPointF(end))
        )
    )
    sync.set_sync_mode(SyncMode.CROSS_REFERENCE)

    sync.update_cross_reference("view_0_0", QPointF(5, 5))

    assert len(lines) == 1
    view_id, start, end = lines[0]
    assert view_id == "view_0_1"
    assert sorted((start.x(), end.x())) == pytest.approx([0.0, 31.0])
    assert start.y() == pytest.approx(10.0)
    assert end.y() == pytest.approx(10.0)


def test_reference_line_requires_the_same_frame_of_reference():
    source = _model_with_geometry(
        [(0, 0, 10)], frame_uid=pydicom.uid.generate_uid()
    )
    target = _model_with_geometry(
        [(0, 0, 0)],
        orientation=(0, 1, 0, 0, 0, 1),
        frame_uid=pydicom.uid.generate_uid(),
    )
    _, sync = _bind_two_series(source, target)
    lines = []
    sync.cross_reference_line_updated.connect(lambda *args: lines.append(args))
    sync.set_sync_mode(SyncMode.CROSS_REFERENCE)

    sync.update_cross_reference("view_0_0", QPointF(5, 5))

    assert lines == []


def test_reference_lines_and_shared_cursor_can_be_toggled_independently():
    frame_uid = pydicom.uid.generate_uid()
    source = _model_with_geometry([(0, 0, 10)], frame_uid=frame_uid)
    target = _model_with_geometry(
        [(0, 0, 0)],
        orientation=(0, 1, 0, 0, 0, 1),
        frame_uid=frame_uid,
    )
    _, sync = _bind_two_series(source, target)
    sync.set_sync_mode(SyncMode.CROSS_REFERENCE)
    lines = []
    cursors = []
    sync.cross_reference_line_updated.connect(lambda *args: lines.append(args))
    sync.patient_cursor_updated.connect(lambda *args: cursors.append(args))

    sync.set_cross_reference_visibility(
        reference_lines=True,
        shared_cursor=False,
    )
    sync.update_cross_reference("view_0_0", QPointF(5, 5))
    assert lines
    assert not cursors

    lines.clear()
    sync.set_cross_reference_visibility(
        reference_lines=False,
        shared_cursor=True,
    )
    sync.update_cross_reference("view_0_0", QPointF(5, 5))
    assert not lines
    assert cursors
