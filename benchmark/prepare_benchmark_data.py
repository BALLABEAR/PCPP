import argparse
import hashlib
import json
import tempfile
import urllib.request
from pathlib import Path


SOURCE_FILES = [
    {
        "name": "table_scene_lms400",
        "url": "https://raw.githubusercontent.com/PointCloudLibrary/data/master/tutorials/table_scene_lms400.pcd",
        "sha256": "e285d415641e0d9de695b611db874cc8fe995e8089b77a50d6056d24d8cbcc58",
    },
    {
        "name": "table_scene_mug_stereo_textured",
        "url": "https://raw.githubusercontent.com/PointCloudLibrary/data/master/tutorials/table_scene_mug_stereo_textured.pcd",
        "sha256": "1a79fe07ce50023699f2b7a1bae37f18174b2495619bf7839d962ac282249334",
    },
    {
        "name": "room_scan1",
        "url": "https://raw.githubusercontent.com/PointCloudLibrary/data/master/tutorials/room_scan1.pcd",
        "sha256": "52c373a67d8beaa318b5e8c024f06e219f14acc1db28fa7333ff5dc73840428b",
    },
]

TARGET_SIZES = [100_000, 500_000, 1_000_000]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_with_checksum(url: str, destination: Path, expected_sha: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        with urllib.request.urlopen(url, timeout=60) as response, tmp_path.open("wb") as out:
            out.write(response.read())

        actual_sha = sha256_file(tmp_path)
        if actual_sha != expected_sha:
            raise ValueError(
                f"Checksum mismatch for {url}. expected={expected_sha}, actual={actual_sha}"
            )
        tmp_path.replace(destination)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def load_point_cloud(path: Path):
    import numpy as np

    try:
        import open3d as o3d
    except Exception as exc:
        raise RuntimeError(
            "open3d is required to prepare benchmark data. Install with: pip install open3d"
        ) from exc

    cloud = o3d.io.read_point_cloud(str(path))
    points = np.asarray(cloud.points, dtype=np.float32)
    if points.size == 0:
        raise ValueError(f"No points loaded from {path}")
    return points


def resample_points(points, target_size: int, seed: int):
    import numpy as np

    rng = np.random.default_rng(seed)
    n_points = points.shape[0]
    if n_points == target_size:
        return points
    if n_points > target_size:
        idx = rng.choice(n_points, target_size, replace=False)
        return points[idx]
    idx = rng.choice(n_points, target_size - n_points, replace=True)
    return np.vstack([points, points[idx]])


def save_xyz(path: Path, points) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(path, points, fmt="%.6f %.6f %.6f")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and prepare benchmark datasets (100K/500K/1M)")
    parser.add_argument("--raw-dir", default="data/raw_benchmark")
    parser.add_argument("--prepared-dir", default="data/benchmark_inputs")
    parser.add_argument("--manifest-dir", default="data/benchmark_manifests")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force-download", action="store_true")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    prepared_dir = Path(args.prepared_dir)
    manifest_dir = Path(args.manifest_dir)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    downloaded_manifest: list[dict] = []
    prepared_manifest: list[dict] = []

    for source in SOURCE_FILES:
        raw_file = raw_dir / f"{source['name']}.pcd"
        if args.force_download or not raw_file.exists():
            download_with_checksum(source["url"], raw_file, source["sha256"])

        actual_sha = sha256_file(raw_file)
        if actual_sha != source["sha256"]:
            raise ValueError(f"Raw file checksum mismatch for {raw_file}")

        downloaded_manifest.append(
            {
                "name": source["name"],
                "path": str(raw_file),
                "sha256": actual_sha,
            }
        )

        points = load_point_cloud(raw_file)
        for target_size in TARGET_SIZES:
            size_label = f"{target_size // 1000}k" if target_size < 1_000_000 else "1m"
            output_file = prepared_dir / size_label / f"{source['name']}_{size_label}.xyz"
            points_resampled = resample_points(
                points,
                target_size=target_size,
                seed=args.seed + hash((source["name"], target_size)) % 10_000,
            )
            save_xyz(output_file, points_resampled)

            # Integrity checks: exact point count + file checksum
            import numpy as np

            loaded = np.loadtxt(output_file, dtype=np.float32)
            if loaded.ndim == 1:
                loaded = loaded.reshape(-1, 3)
            if loaded.shape[0] != target_size:
                raise ValueError(f"Point count mismatch in {output_file}: {loaded.shape[0]} != {target_size}")

            prepared_manifest.append(
                {
                    "source_name": source["name"],
                    "size_label": size_label,
                    "target_size": target_size,
                    "path": str(output_file),
                    "sha256": sha256_file(output_file),
                    "point_count": int(loaded.shape[0]),
                }
            )

    (manifest_dir / "raw_sources.json").write_text(
        json.dumps(downloaded_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (manifest_dir / "prepared_files.json").write_text(
        json.dumps(prepared_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Prepared {len(prepared_manifest)} benchmark files in {prepared_dir}")


if __name__ == "__main__":
    main()
