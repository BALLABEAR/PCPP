import argparse
import subprocess
import sys
from pathlib import Path

from workers.base.base_worker import BaseWorker


class ShapeAsPointsOptimWorker(BaseWorker):
    """
    Adapter for ShapeAsPoints optimization-based reconstruction.
    Input: .obj (preferred), .ply, .xyz, .txt, .npy.
    Non-mesh inputs are converted to .ply with estimated normals.
    Output: reconstructed .ply mesh.
    """

    def __init__(
        self,
        repo_path: str = "external_models/ShapeAsPoints",
        config_path: str = "configs/optim_based/teaser.yaml",
        total_epochs: int = 200,
        grid_res: int = 128,
        no_cuda: bool = False,
    ) -> None:
        super().__init__(model_id="shape_as_points_optim")
        self.repo_path = Path(repo_path)
        self.config_path = config_path
        self.total_epochs = total_epochs
        self.grid_res = grid_res
        self.no_cuda = no_cuda

    def process(self, input_path: Path, output_dir: Path) -> Path:
        suffix = input_path.suffix.lower()
        if suffix not in {".obj", ".ply", ".xyz", ".txt", ".npy"}:
            raise ValueError("ShapeAsPoints optimization mode supports .obj/.ply/.xyz/.txt/.npy inputs")

        repo = self.repo_path.resolve()
        if not repo.exists():
            raise FileNotFoundError(f"ShapeAsPoints repo not found: {repo}")

        config = (repo / self.config_path).resolve()
        if not config.exists():
            raise FileNotFoundError(f"ShapeAsPoints config not found: {config}")

        run_dir = (output_dir / f"{input_path.stem}_sap_run").resolve()
        run_dir.mkdir(parents=True, exist_ok=True)

        prepared_input = self._prepare_input_for_optim(input_path=input_path, output_dir=output_dir)

        command = [
            sys.executable,
            "optim.py",
            str(config),
            "--data:data_path",
            str(prepared_input.resolve()),
            "--data:object_id",
            "-1",
            "--train:out_dir",
            str(run_dir),
            "--train:total_epochs",
            str(self.total_epochs),
            "--model:grid_res",
            str(self.grid_res),
            "--train:o3d_show",
            "False",
        ]
        if self.no_cuda:
            command.append("--no_cuda")

        subprocess.run(command, cwd=str(repo), check=True)

        mesh_dir = run_dir / "vis" / "mesh"
        mesh_candidates = sorted(mesh_dir.glob("*.ply"))
        if not mesh_candidates:
            raise RuntimeError(f"No mesh output found in {mesh_dir}")

        latest_mesh = mesh_candidates[-1]
        output_path = output_dir / f"{input_path.stem}_sap_mesh.ply"
        output_path.write_bytes(latest_mesh.read_bytes())
        return output_path

    def _prepare_input_for_optim(self, input_path: Path, output_dir: Path) -> Path:
        suffix = input_path.suffix.lower()
        if suffix in {".obj", ".ply"}:
            return input_path

        try:
            import numpy as np
            import open3d as o3d
        except Exception as exc:
            raise RuntimeError(
                "open3d and numpy are required to convert xyz/txt/npy input for ShapeAsPoints"
            ) from exc

        if suffix == ".npy":
            points = np.load(str(input_path))
        else:
            points = np.loadtxt(str(input_path), dtype=np.float32)
        if points.ndim == 1:
            points = points.reshape(-1, 3)
        if points.shape[1] > 3:
            points = points[:, :3]
        if points.shape[1] != 3:
            raise ValueError(f"Expected XYZ points with 3 columns, got shape={points.shape}")

        cloud = o3d.geometry.PointCloud()
        cloud.points = o3d.utility.Vector3dVector(points.astype(np.float64))
        cloud.estimate_normals()
        cloud.orient_normals_consistent_tangent_plane(30)

        converted = output_dir / f"{input_path.stem}_with_normals.ply"
        o3d.io.write_point_cloud(str(converted), cloud)
        return converted


def main() -> None:
    parser = argparse.ArgumentParser(description="PCPP ShapeAsPoints optimization adapter")
    parser.add_argument("--input", required=True, help="Input .obj/.ply/.xyz/.txt/.npy path")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument(
        "--repo-path",
        default="external_models/ShapeAsPoints",
        help="Path to ShapeAsPoints repository",
    )
    parser.add_argument(
        "--config",
        default="configs/optim_based/teaser.yaml",
        help="Relative config path inside ShapeAsPoints repo",
    )
    parser.add_argument("--total-epochs", type=int, default=200, help="Optimization iterations")
    parser.add_argument("--grid-res", type=int, default=128, help="Poisson grid resolution")
    parser.add_argument("--no-cuda", action="store_true", default=False, help="Run on CPU")
    args = parser.parse_args()

    worker = ShapeAsPointsOptimWorker(
        repo_path=args.repo_path,
        config_path=args.config,
        total_epochs=args.total_epochs,
        grid_res=args.grid_res,
        no_cuda=args.no_cuda,
    )
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
