import json

import numpy as np
import pytest
from PySide6.QtCore import QPointF

from medimager.core.annotation_persistence import (
    export_annotations,
    import_annotations,
    save_annotations,
)
from medimager.core.image_data_model import AngleMeasurementData, ImageDataModel, MeasurementData
from medimager.core.roi import CircleROI, EllipseROI, RectangleROI


def make_model() -> ImageDataModel:
    model = ImageDataModel()
    assert model.load_single_image(
        np.zeros((4, 8, 8), dtype=np.float32),
        {
            "PatientID": "TEST-001",
            "StudyInstanceUID": "1.2.3",
            "SeriesInstanceUID": "1.2.3.4",
            "SeriesDescription": "Synthetic annotations",
        },
    )
    return model


def add_annotations(model: ImageDataModel) -> None:
    rectangle = RectangleROI((1, 2), (3, 4), 0)
    rectangle.id = "roi-rect"
    rectangle.show_stats = False
    model.add_roi(rectangle)

    circle = CircleROI((4, 5), 2, 1)
    circle.id = "roi-circle"
    model.add_roi(circle)

    ellipse = EllipseROI((5, 6), 3, 2, 2)
    ellipse.id = "roi-ellipse"
    model.add_roi(ellipse)

    model.add_measurement(
        MeasurementData(
            id="measurement-1",
            slice_index=1,
            start_point=QPointF(1.5, 2.5),
            end_point=QPointF(7.5, 2.5),
            distance=6.0,
            unit="mm",
        )
    )
    model.add_angle_measurement(
        AngleMeasurementData(
            id="angle-1",
            slice_index=2,
            point1=QPointF(1, 1),
            vertex=QPointF(2, 2),
            point3=QPointF(3, 1),
            angle_degrees=90.0,
        )
    )


def test_annotation_document_contains_series_identity():
    model = make_model()
    add_annotations(model)

    document = export_annotations(model)

    assert document["schema"] == "medimager.annotations"
    assert document["schema_version"] == 1
    assert document["series"]["patient_id"] == "TEST-001"
    assert document["series"]["slice_count"] == 4
    assert len(document["annotations"]["rois"]) == 3
    assert len(document["annotations"]["measurements"]) == 1
    assert len(document["annotations"]["angle_measurements"]) == 1


def test_save_and_import_annotations_roundtrip(tmp_path):
    source = make_model()
    add_annotations(source)
    file_path = tmp_path / "annotations.json"

    save_annotations(source, file_path)

    target = make_model()
    counts = import_annotations(target, file_path)

    assert counts == {"rois": 3, "measurements": 1, "angle_measurements": 1}
    assert [roi.id for roi in target.rois] == ["roi-rect", "roi-circle", "roi-ellipse"]
    assert target.rois[0].top_left == (1, 2)
    assert target.rois[0].bottom_right == (3, 4)
    assert target.rois[0].show_stats is False
    assert target.rois[1].center == (4, 5)
    assert target.rois[1].radius == 2
    assert target.rois[2].radius_x == 3
    assert target.rois[2].radius_y == 2
    assert target.measurements[0].start_point == QPointF(1.5, 2.5)
    assert target.measurements[0].end_point == QPointF(7.5, 2.5)
    assert target.angle_measurements[0].angle_degrees == 90.0


def test_import_replace_clears_existing_annotations():
    source = make_model()
    add_annotations(source)
    target = make_model()
    target.add_roi(RectangleROI((0, 0), (1, 1), 0))
    target.add_measurement(
        MeasurementData("old", 0, QPointF(0, 0), QPointF(1, 1), 1.0)
    )

    import_annotations(target, export_annotations(source), replace=True)

    assert len(target.rois) == 3
    assert [measurement.id for measurement in target.measurements] == ["measurement-1"]


def test_import_can_append_annotations():
    source = make_model()
    add_annotations(source)
    target = make_model()
    target.add_roi(RectangleROI((0, 0), (1, 1), 0))

    import_annotations(target, export_annotations(source), replace=False)

    assert len(target.rois) == 4


def test_import_rejects_unknown_schema():
    target = make_model()

    with pytest.raises(ValueError, match="Not a MedImager annotation file"):
        import_annotations(target, {"schema": "other", "schema_version": 1})


def test_import_rejects_unknown_roi_type(tmp_path):
    document = {
        "schema": "medimager.annotations",
        "schema_version": 1,
        "annotations": {
            "rois": [{"id": "bad", "type": "Polygon", "slice_index": 0}],
            "measurements": [],
            "angle_measurements": [],
        },
    }
    file_path = tmp_path / "bad.json"
    file_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported ROI type"):
        import_annotations(make_model(), file_path)
