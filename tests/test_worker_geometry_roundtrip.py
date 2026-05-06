from pathlib import Path

import numpy as np

from workers.base.base_worker import BaseWorker
from workers.base.format_converter import FormatConverter
from workers.base.point_cloud_io import load_points, save_points


class DummyWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(model_id="dummy")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        normalized = self._converter.normalize(input_path, output_dir / "_norm_input")
        points = load_points(normalized)
        output_path = output_dir / "dummy_out.npy"
        np.save(output_path, np.asarray(points, dtype=np.float32))
        return output_path


def test_format_converter_geometry_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "input.ply"
    points = [
        (10.0, 5.0, -2.0),
        (14.0, 9.0, 2.0),
        (12.0, 7.0, 0.0),
    ]
    save_points(source, points)

    converter = FormatConverter()
    normalized = converter.normalize(
        source,
        tmp_path / "_norm_input",
        geometry_normalization=True,
    )

    restored_input = tmp_path / "restored.npy"
    np.save(restored_input, np.asarray(load_points(normalized), dtype=np.float32))
    restored = converter.convert_model_output_to_point_cloud(
        output_path=restored_input,
        work_dir=tmp_path / "_restored",
        source_context_dir=tmp_path / "_norm_input",
    )

    roundtrip = np.asarray(load_points(restored), dtype=np.float32)
    assert np.allclose(roundtrip, np.asarray(points, dtype=np.float32), atol=1e-5)


def test_format_converter_geometry_roundtrip_for_ascii_pcd(tmp_path: Path) -> None:
    source = tmp_path / "input.pcd"
    source.write_text(
        "\n".join(
            [
                "# .PCD v0.7 - Point Cloud Data file format",
                "VERSION 0.7",
                "FIELDS x y z",
                "SIZE 4 4 4",
                "TYPE F F F",
                "COUNT 1 1 1",
                "WIDTH 3",
                "HEIGHT 1",
                "VIEWPOINT 0 0 0 1 0 0 0",
                "POINTS 3",
                "DATA ascii",
                "10 5 -2",
                "14 9 2",
                "12 7 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    converter = FormatConverter()
    normalized = converter.normalize(
        source,
        tmp_path / "_norm_input",
        geometry_normalization=True,
    )

    restored_input = tmp_path / "restored.npy"
    np.save(restored_input, np.asarray(load_points(normalized), dtype=np.float32))
    restored = converter.convert_model_output_to_point_cloud(
        output_path=restored_input,
        work_dir=tmp_path / "_restored",
        source_context_dir=tmp_path / "_norm_input",
    )

    roundtrip = np.asarray(load_points(restored), dtype=np.float32)
    assert np.allclose(
        roundtrip,
        np.asarray([(10.0, 5.0, -2.0), (14.0, 9.0, 2.0), (12.0, 7.0, 0.0)], dtype=np.float32),
        atol=1e-5,
    )


def test_base_worker_converts_npy_output_without_geometry_restore(tmp_path: Path) -> None:
    source = tmp_path / "input.ply"
    points = [
        (100.0, 200.0, 300.0),
        (101.5, 199.0, 299.5),
        (98.5, 201.0, 302.0),
    ]
    save_points(source, points)

    worker = DummyWorker()
    worker._runtime.accepted_input_formats = [".ply"]
    result = Path(worker.run(str(source), str(tmp_path / "out")))

    restored = np.asarray(load_points(result), dtype=np.float32)
    assert result.suffix.lower() == ".ply"
    assert np.allclose(restored, np.asarray(points, dtype=np.float32), atol=1e-5)
