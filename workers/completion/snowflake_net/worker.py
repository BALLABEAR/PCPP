import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

from workers.base.base_worker import BaseWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)


class SnowflakeWorker(BaseWorker):
    """
    SnowflakeNet wrapper for PCPP.

    Modes:
    - passthrough: smoke mode, copies input to output (safe default).
    - model: runs SnowflakeNet forward pass if dependencies and weights are ready.
    """

    def __init__(
        self,
        mode: str = "passthrough",
        weights_path: str | None = None,
        config_path: str | None = None,
        device: str | None = None,
    ) -> None:
        super().__init__(model_id="snowflake_net")
        self.mode = mode
        self.weights_path = weights_path
        self.config_path = config_path
        self.device = device or ("cuda" if os.environ.get("CUDA_VISIBLE_DEVICES", "") else "cpu")

    def process(self, input_path: Path, output_dir: Path) -> Path:
        output_path = output_dir / f"{input_path.stem}_snowflake.xyz"
        if self.mode == "passthrough":
            shutil.copy2(input_path, output_path)
            logger.info("Passthrough mode used. Output copied to %s", output_path)
            return output_path
        return self._run_model(input_path=input_path, output_path=output_path)

    def _run_model(self, input_path: Path, output_path: Path) -> Path:
        import numpy as np

        repo_root = Path(os.getenv("SNOWFLAKE_REPO", "external_models/SnowflakeNet")).resolve()
        if not repo_root.exists():
            raise FileNotFoundError(
                f"SnowflakeNet repo not found at {repo_root}. "
                "Clone it to external_models/SnowflakeNet or set SNOWFLAKE_REPO."
            )

        try:
            import torch
        except Exception as exc:
            raise RuntimeError("PyTorch is required for model mode. Install torch first.") from exc

        sys.path.insert(0, str(repo_root))
        try:
            from models.model_completion import SnowflakeNet  # type: ignore
        except ModuleNotFoundError as exc:
            if "pointnet2_ops" in str(exc):
                raise RuntimeError(
                    "SnowflakeNet extension pointnet2_ops is missing. "
                    "Build extensions from external_models/SnowflakeNet README "
                    "(models/pointnet2_ops_lib, loss_functions/Chamfer3D, loss_functions/emd)."
                ) from exc
            raise

        config_path = (
            Path(self.config_path).resolve()
            if self.config_path
            else repo_root / "completion" / "configs" / "pcn_cd1.yaml"
        )
        config = _read_yaml(config_path)
        model_cfg = config.get("model", {})
        model = SnowflakeNet(
            dim_feat=model_cfg.get("dim_feat", 512),
            num_pc=model_cfg.get("num_pc", 256),
            num_p0=model_cfg.get("num_p0", 512),
            radius=model_cfg.get("radius", 1),
            bounding=model_cfg.get("bounding", True),
            up_factors=model_cfg.get("up_factors", [1, 2, 2]),
        )

        if not self.weights_path:
            raise ValueError(
                "weights_path is required in model mode. "
                "Pass --weights <path-to-ckpt-best.pth>."
            )

        ckpt_path = Path(self.weights_path).resolve()
        if not ckpt_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")

        checkpoint = torch.load(str(ckpt_path), map_location="cpu")
        state = checkpoint.get("model", checkpoint)
        if any(k.startswith("module.") for k in state.keys()):
            state = {k.replace("module.", "", 1): v for k, v in state.items()}
        model.load_state_dict(state, strict=False)
        model.eval()
        model.to(self.device)

        points = _load_points(input_path)
        points = _normalize_point_count(points, target_n=max(model_cfg.get("num_p0", 512), 512))
        tensor = torch.from_numpy(points.astype(np.float32)).unsqueeze(0).to(self.device)

        with torch.no_grad():
            pred_list = model(tensor)
            pred = pred_list[-1][0].detach().cpu().numpy()

        _save_xyz(output_path, pred)
        logger.info("Snowflake model mode completed: %s", output_path)
        return output_path


def _read_yaml(path: Path) -> dict:
    import yaml

    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_points(path: Path):
    import numpy as np

    suffix = path.suffix.lower()
    if suffix in {".pcd", ".ply"}:
        try:
            import open3d as o3d
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize open3d for {suffix}: {exc}. "
                "Usually this means missing system libs (libX11/libGL) inside container."
            ) from exc

        cloud = o3d.io.read_point_cloud(str(path))
        arr = np.asarray(cloud.points, dtype=np.float32)
        if arr.size == 0:
            raise ValueError(f"Failed to read points from file: {path}")
        if arr.ndim == 1:
            arr = arr.reshape(-1, 3)
        return arr
    if suffix == ".npy":
        arr = np.load(path)
    else:
        arr = np.loadtxt(path, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 3)
    if arr.shape[1] > 3:
        arr = arr[:, :3]
    if arr.shape[1] != 3:
        raise ValueError(f"Input must have XYZ columns. got shape={arr.shape}")
    return arr.astype(np.float32)


def _normalize_point_count(points, target_n: int):
    import numpy as np

    n = points.shape[0]
    if n == target_n:
        return points
    if n > target_n:
        idx = np.random.choice(n, target_n, replace=False)
        return points[idx]
    pad_idx = np.random.choice(n, target_n - n, replace=True)
    return np.vstack([points, points[pad_idx]])


def _save_xyz(path: Path, points) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(path, points, fmt="%.6f %.6f %.6f")


def main() -> None:
    parser = argparse.ArgumentParser(description="PCPP SnowflakeNet wrapper")
    parser.add_argument("--input", required=True, help="Input point cloud (.xyz/.txt/.npy)")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--mode", choices=["passthrough", "model"], default="passthrough")
    parser.add_argument("--weights", default=None, help="Path to SnowflakeNet checkpoint")
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to Snowflake completion config yaml (e.g. c3d_cd2.yaml)",
    )
    parser.add_argument("--device", default=None, help="cuda or cpu")
    args = parser.parse_args()

    worker = SnowflakeWorker(
        mode=args.mode,
        weights_path=args.weights,
        config_path=args.config,
        device=args.device,
    )
    result = worker.run(input_path=args.input, output_dir=args.output_dir)
    print(result)


if __name__ == "__main__":
    main()
