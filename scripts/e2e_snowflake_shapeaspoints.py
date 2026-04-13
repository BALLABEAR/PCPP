from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:8000"
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _wait_run(run_id: str, label: str, timeout_sec: int = 7200, poll_sec: int = 8) -> dict:
    end = time.time() + timeout_sec
    last: dict = {}
    while time.time() < end:
        r = requests.get(f"{BASE}/onboarding/models/runs/{run_id}", timeout=60)
        r.raise_for_status()
        payload = r.json()
        last = payload
        status = payload.get("status")
        if status in {"completed", "failed"}:
            print(f"[{label}] final={status} exit={payload.get('exit_code')}")
            return payload
        print(f"[{label}] status={status}")
        time.sleep(poll_sec)
    raise TimeoutError(f"{label} run timeout. last={last}")


def _wait_task(task_id: str, label: str, timeout_sec: int = 7200, poll_sec: int = 8) -> dict:
    end = time.time() + timeout_sec
    last: dict = {}
    while time.time() < end:
        r = requests.get(f"{BASE}/tasks/{task_id}", timeout=60)
        r.raise_for_status()
        payload = r.json()
        last = payload
        status = payload.get("status")
        if status in {"completed", "failed", "cancelled"}:
            print(f"[{label}] task_final={status}")
            return payload
        print(f"[{label}] task_status={status}")
        time.sleep(poll_sec)
    raise TimeoutError(f"{label} task timeout. last={last}")


def _scaffold_build_smoke(payload: dict, smoke_body: dict) -> None:
    sid = payload["model_id"]
    print(f"\n=== MODEL {sid} ===")
    sc = requests.post(f"{BASE}/onboarding/models/scaffold", json=payload, timeout=180)
    print("scaffold", sid, sc.status_code)
    if sc.status_code != 200:
        raise RuntimeError(sc.text)

    br = requests.post(
        f"{BASE}/onboarding/models/build",
        json={"task_type": payload["task_type"], "model_id": sid, "no_cache": False},
        timeout=120,
    )
    print("build_request", sid, br.status_code)
    if br.status_code != 200:
        raise RuntimeError(br.text)
    build_run = _wait_run(br.json()["run_id"], f"build:{sid}")
    if build_run.get("status") != "completed":
        raise RuntimeError((build_run.get("logs") or "")[-4000:])

    sm = requests.post(f"{BASE}/onboarding/models/smoke-run", json=smoke_body, timeout=120)
    print("smoke_request", sid, sm.status_code)
    if sm.status_code != 200:
        raise RuntimeError(sm.text)
    smoke_run = _wait_run(sm.json()["run_id"], f"smoke:{sid}", timeout_sec=5400, poll_sec=5)
    if smoke_run.get("status") != "completed":
        raise RuntimeError((smoke_run.get("logs") or "")[-6000:])

    rc = requests.post(f"{BASE}/onboarding/models/registry-check", json={"model_id": sid}, timeout=60)
    print("registry_check", sid, rc.status_code, rc.text[:300])


def main() -> None:
    skip_snowflake = os.getenv("SKIP_SNOWFLAKE", "").strip() == "1"
    # Ensure clean slate.
    for model_id in (["shape_as_points"] if skip_snowflake else ["snowflake", "shape_as_points"]):
        r = requests.delete(f"{BASE}/registry/models/{model_id}", timeout=30)
        print("delete", model_id, r.status_code)

    airplane_pcd = ROOT / "data/benchmark_inputs/airplane.pcd"
    airplane_ply = ROOT / "data/benchmark_inputs/airplane_for_shapeaspoints_smoke.ply"
    if not airplane_ply.exists():
        from workers.base.format_converter import FormatConverter

        conv = FormatConverter()
        converted = conv.convert(airplane_pcd, ".ply", ROOT / "data/benchmark_inputs/_tmp_conv")
        airplane_ply.write_bytes(Path(converted).read_bytes())
        print("created_smoke_input_ply", airplane_ply)

    snowflake_entry = (
        "python -c \"import sys,torch,yaml,numpy as np,pathlib,collections; "
        "sys.path.insert(0,'{repo_path}'); "
        "from models.model_completion import SnowflakeNet; "
        "from workers.base.format_converter import FormatConverter; "
        "from workers.base.point_cloud_io import load_points; "
        "cfg=yaml.safe_load(open('{config_path}','r',encoding='utf-8')); "
        "cfg=cfg if isinstance(cfg,dict) else dict(); "
        "mcfg=cfg.get('model'); mcfg=mcfg if isinstance(mcfg,dict) else dict(); "
        "device_str='{device}'; device_str=device_str if device_str else 'cuda:0'; "
        "dev=torch.device(device_str if torch.cuda.is_available() else 'cpu'); "
        "model=SnowflakeNet(dim_feat=mcfg.get('dim_feat',512),num_pc=mcfg.get('num_pc',256),"
        "num_p0=mcfg.get('num_p0',512),radius=mcfg.get('radius',1.0),"
        "bounding=mcfg.get('bounding',True),up_factors=mcfg.get('up_factors',[1,2,2])); "
        "ckpt=torch.load('{weights_path}',map_location=dev); "
        "state=ckpt.get('model',ckpt) if hasattr(ckpt,'get') else ckpt; "
        "fixed=collections.OrderedDict((k[7:] if k.startswith('module.') else k,v) for k,v in state.items()); "
        "model.load_state_dict(fixed,strict=False); model.to(dev); model.eval(); "
        "conv=FormatConverter(); "
        "inp_norm=conv.normalize(pathlib.Path('{input}'), pathlib.Path('{output_dir}')/'_norm_input'); "
        "pts=np.asarray(load_points(pathlib.Path(inp_norm)),dtype=np.float32); "
        "pts=pts.reshape(-1,3) if pts.ndim==1 else pts; "
        "pts=pts[:,:3] if pts.shape[1]>3 else pts; "
        "pts=np.repeat(pts,int(np.ceil(32/max(pts.shape[0],1))),axis=0) if pts.shape[0]<32 else pts; "
        "pts=pts[np.linspace(0,pts.shape[0]-1,2048,dtype=np.int64)] if pts.shape[0]>2048 else pts; "
        "inp=torch.from_numpy(pts).unsqueeze(0).to(dev); "
        "out=model(inp)[-1].squeeze(0).detach().cpu().numpy(); "
        "pathlib.Path('{output_dir}').mkdir(parents=True,exist_ok=True); "
        "np.save(str(pathlib.Path('{output_dir}')/'snowflake_out.npy'),out)\""
    )
    snowflake_payload = {
        "model_id": "snowflake",
        "task_type": "completion",
        "repo_path": "./external_models/SnowflakeNet",
        "weights_path": "./external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
        "config_path": "./external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
        "input_data_kind": "point_cloud",
        "output_data_kind": "point_cloud",
        "description": "Generated adapter scaffold. Replace template logic with real inference.",
        "overwrite": False,
        "entry_command": snowflake_entry,
        "extra_pip_packages": [
            "easydict",
            "h5py",
            "scipy",
            "tensorboardX==1.2",
            "transforms3d",
            "einops",
            "munch",
            "termcolor",
            "opencv-python",
            "pyyaml",
        ],
        "pip_requirements_files": ["./external_models/SnowflakeNet/requirements.txt"],
        "pip_extra_args": [],
        "system_packages": [],
        "base_image": "",
        "extra_build_steps": [],
        "env_overrides": {"PYTHONPATH": "/app:/app/external_models/SnowflakeNet"},
    }
    if not skip_snowflake:
        _scaffold_build_smoke(
            snowflake_payload,
            {
                "task_type": "completion",
                "model_id": "snowflake",
                "input_data_kind": "point_cloud",
                "input_path": "./data/benchmark_inputs/airplane_for_shapeaspoints_smoke.ply",
                "use_gpu": True,
                "model_args": ["--device", "cuda:0"],
            },
        )
    else:
        print("skip_snowflake=1, reusing existing snowflake model")

    shape_entry = (
        "python -c \"import pathlib,glob,shutil,subprocess; import open3d as o3d; "
        "from workers.base.format_converter import FormatConverter; "
        "run_dir=pathlib.Path('{output_dir}')/'sap_run'; run_dir.mkdir(parents=True,exist_ok=True); "
        "conv=FormatConverter(); inp_norm=conv.normalize(pathlib.Path('{input}'), pathlib.Path('{output_dir}')/'_norm_input'); "
        "pcd=o3d.io.read_point_cloud(str(inp_norm)); "
        "pcd.estimate_normals(); pcd.orient_normals_consistent_tangent_plane(30); "
        "inp_with_norm=pathlib.Path('{output_dir}')/'_input_with_normals.ply'; "
        "o3d.io.write_point_cloud(str(inp_with_norm), pcd); "
        "cmd=['python','optim.py','{config_path}','--data:data_path',str(inp_with_norm),"
        "'--train:out_dir',str(run_dir),'--train:total_epochs','300','--model:grid_res','128',"
        "'--train:o3d_show','False','--data:object_id','-1','--train:n_workers','0']; "
        "subprocess.run(cmd,cwd='{repo_path}',check=True); "
        "meshes=sorted(glob.glob(str(run_dir/'vis'/'mesh'/'*.ply'))); "
        "shutil.copy(meshes[-1], str(pathlib.Path('{output_dir}')/'shape_as_points_mesh.ply'))\""
    )
    shape_payload = {
        "model_id": "shape_as_points",
        "task_type": "meshing",
        "repo_path": "./external_models/ShapeAsPoints",
        "weights_path": "./external_models/ShapeAsPoints/configs/optim_based/teaser.yaml",
        "config_path": "./external_models/ShapeAsPoints/configs/optim_based/teaser.yaml",
        "input_data_kind": "point_cloud",
        "output_data_kind": "mesh",
        "description": "Generated adapter scaffold. Replace template logic with real inference.",
        "overwrite": False,
        "entry_command": shape_entry,
        "extra_pip_packages": [
            "trimesh",
            "plyfile",
            "scikit-image",
            "open3d",
            "opencv-python",
            "pykdtree",
            "tensorboard",
            "ipdb",
        ],
        "pip_requirements_files": [],
        "pip_extra_args": [],
        "system_packages": ["ffmpeg", "libgl1", "libglib2.0-0", "libx11-6", "libxext6", "libxrender1", "libsm6"],
        "base_image": "",
        "extra_build_steps": [
            "python -m pip install --no-cache-dir --no-build-isolation --timeout 120 --retries 20 torch-scatter==2.1.2",
            "python -m pip install --no-cache-dir --timeout 120 --retries 20 pytorch3d==0.7.5 -f https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu118_pyt211/download.html",
            "python -m pip install --no-cache-dir --timeout 120 --retries 20 libigl==2.5.1 || python -m pip install --no-cache-dir --timeout 120 --retries 20 libigl",
        ],
        "env_overrides": {"MKL_THREADING_LAYER": "GNU"},
    }
    _scaffold_build_smoke(
        shape_payload,
        {
            "task_type": "meshing",
            "model_id": "shape_as_points",
            "input_data_kind": "point_cloud",
            "input_path": "./data/benchmark_inputs/airplane_for_shapeaspoints_smoke.ply",
            "use_gpu": True,
            "model_args": [],
        },
    )

    now = int(time.time())
    pipeline_name = f"e2e_snowflake_shapeaspoints_{now}"
    draft_payload = {
        "name": pipeline_name,
        "steps": [
            {
                "model_id": "snowflake",
                "params": {
                    "weights_path": "./external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
                    "config_path": "./external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
                    "device": "cuda:0",
                },
            },
            {
                "model_id": "shape_as_points",
                "params": {
                    "config_path": "./external_models/ShapeAsPoints/configs/optim_based/teaser.yaml",
                    "repo_path": "./external_models/ShapeAsPoints",
                    "device": "cuda:0",
                },
            },
        ],
    }
    dr = requests.post(f"{BASE}/pipelines/create-draft", json=draft_payload, timeout=120)
    print("create_draft", dr.status_code, dr.text[:700])
    dr.raise_for_status()
    pipeline = dr.json()
    flow = json.loads(pipeline["config_yaml"])

    with (ROOT / "data/benchmark_inputs/airplane.pcd").open("rb") as fh:
        up = requests.post(
            f"{BASE}/files/upload",
            files={"file": ("airplane.pcd", fh, "application/octet-stream")},
            timeout=120,
        )
    print("upload", up.status_code, up.text)
    up.raise_for_status()
    upload = up.json()

    tr = requests.post(
        f"{BASE}/tasks",
        json={
            "input_bucket": upload["bucket"],
            "input_key": upload["key"],
            "flow_id": flow["flow_id"],
            "flow_params": flow["flow_params"],
        },
        timeout=90,
    )
    print("task_create", tr.status_code, tr.text)
    tr.raise_for_status()
    task = tr.json()
    final_task = _wait_task(task["id"], "pipeline", timeout_sec=10800, poll_sec=10)
    print("task_final", json.dumps(final_task, ensure_ascii=False))

    logs = requests.get(f"{BASE}/tasks/{task['id']}/logs", timeout=60)
    print("task_logs_tail", (logs.json().get("logs") or "")[-3000:])


if __name__ == "__main__":
    main()
