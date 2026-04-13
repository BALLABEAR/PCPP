"""Full E2E: scaffold -> build -> smoke (GPU) -> 2 pipelines -> upload -> 2 tasks."""
from __future__ import annotations

import json
import pathlib
import shutil
import time

import requests

BASE = "http://localhost:8000"
ROOT = pathlib.Path(__file__).resolve().parents[1]


def rel_posix(p: pathlib.Path) -> str:
    rel = p.relative_to(ROOT).as_posix()
    return f"./{rel}" if not rel.startswith(".") else rel


def wait_run(url: str, rid: str, label: str, interval: float, max_wait: float) -> dict:
    deadline = time.time() + max_wait
    last = {}
    while time.time() < deadline:
        r = requests.get(f"{url}/onboarding/models/runs/{rid}", timeout=60)
        r.raise_for_status()
        st = r.json()
        last = st
        s = st.get("status")
        if s in ("completed", "failed"):
            return st
        print(f"  [{label}] {s} ...")
        time.sleep(interval)
    raise TimeoutError(f"{label} run {rid} did not finish: last={last}")


def wait_task(tid: str, label: str, interval: float, max_wait: float) -> dict:
    deadline = time.time() + max_wait
    last = {}
    while time.time() < deadline:
        r = requests.get(f"{BASE}/tasks/{tid}", timeout=60)
        r.raise_for_status()
        st = r.json()
        last = st
        s = st.get("status")
        if s in ("completed", "failed", "cancelled"):
            return st
        print(f"  [{label}] task status={s}")
        time.sleep(interval)
    raise TimeoutError(f"{label} task {tid} did not finish: last={last}")


def main() -> None:
    pretrained = ROOT / "external_models/PoinTr/pretrained"
    pths = sorted(pretrained.glob("*.pth")) if pretrained.is_dir() else []
    if len(pths) >= 2:
        w1, w2 = pths[0], pths[1]
    else:
        w1 = pretrained / "AdaPoinTr_PCN.pth"
        w2 = pretrained / "PCNnew.pth"

    cfg_ada = ROOT / "external_models/PoinTr/cfgs/PCN_models/AdaPoinTr.yaml"
    cfg_pcn = ROOT / "external_models/PoinTr/cfgs/PCN_models/PoinTr.yaml"

    print("Weights:", w1.name, w2.name)

    shutil.rmtree(ROOT / "workers/completion/poin_tr", ignore_errors=True)
    r = requests.delete(f"{BASE}/registry/models/poin_tr", timeout=60)
    print("delete registry", r.status_code)

    extra_build = [
        "cd /app/external_models/PoinTr/extensions/chamfer_dist && python setup.py build_ext --inplace",
        "cd /app/external_models/PoinTr/extensions/cubic_feature_sampling && python setup.py build_ext --inplace",
        "cd /app/external_models/PoinTr/extensions/emd && python setup.py build_ext --inplace",
        "cd /app/external_models/PoinTr/extensions/gridding && python setup.py build_ext --inplace",
        "cd /app/external_models/PoinTr/extensions/gridding_loss && python setup.py build_ext --inplace",
        "python -m pip install --no-cache-dir --no-build-isolation "
        "git+https://github.com/erikwijmans/Pointnet2_PyTorch.git#subdirectory=pointnet2_ops_lib",
    ]

    payload = {
        "model_id": "poin_tr",
        "task_type": "completion",
        "repo_path": "./external_models/PoinTr",
        "weights_path": rel_posix(w1),
        "config_path": rel_posix(cfg_ada),
        "input_data_kind": "point_cloud",
        "output_data_kind": "point_cloud",
        "entry_command": "",
        "extra_pip_packages": ["numpy<2"],
        "pip_requirements_files": [],
        "pip_extra_args": [],
        "system_packages": [],
        "base_image": "",
        "extra_build_steps": extra_build,
        "env_overrides": {},
        "overwrite": False,
        "description": "Generated adapter scaffold. Replace template logic with real inference.",
    }
    sc = requests.post(f"{BASE}/onboarding/models/scaffold", json=payload, timeout=180)
    print("scaffold", sc.status_code, sc.text[:500] if sc.status_code != 200 else "ok")
    sc.raise_for_status()

    br = requests.post(
        f"{BASE}/onboarding/models/build",
        json={"task_type": "completion", "model_id": "poin_tr", "no_cache": False},
        timeout=120,
    )
    print("build req", br.status_code)
    br.raise_for_status()
    rid = br.json()["run_id"]
    bst = wait_run(BASE, rid, "build", interval=15.0, max_wait=7200.0)
    print("build final", bst.get("status"), bst.get("exit_code"))
    if bst.get("status") != "completed":
        print((bst.get("logs") or "")[-2500:])
        raise SystemExit(1)

    sr = requests.post(
        f"{BASE}/onboarding/models/smoke-run",
        json={
            "task_type": "completion",
            "model_id": "poin_tr",
            "input_data_kind": "point_cloud",
            "use_gpu": True,
            "model_args": ["--device", "cuda:0"],
        },
        timeout=120,
    )
    print("smoke req", sr.status_code, sr.text[:300])
    sr.raise_for_status()
    sid = sr.json()["run_id"]
    sst = wait_run(BASE, sid, "smoke", interval=5.0, max_wait=1800.0)
    print("smoke final", sst.get("status"), sst.get("exit_code"))
    if sst.get("status") != "completed":
        print((sst.get("logs") or "")[-2500:])
        raise SystemExit(1)

    rc = requests.post(f"{BASE}/onboarding/models/registry-check", json={"model_id": "poin_tr"}, timeout=60)
    print("registry-check", rc.status_code, rc.text[:400])

    ts = int(time.time())
    name_a = f"e2e_pointr_{ts}_ada"
    name_b = f"e2e_pointr_{ts}_pcn"

    def create_pl(name: str, wp: pathlib.Path, cp: pathlib.Path) -> dict:
        body = {
            "name": name,
            "steps": [
                {
                    "model_id": "poin_tr",
                    "params": {
                        "weights_path": rel_posix(wp),
                        "config_path": rel_posix(cp),
                        "device": "cuda:0",
                        "mode": "model",
                    },
                }
            ],
        }
        pr = requests.post(f"{BASE}/pipelines/create-draft", json=body, timeout=120)
        print(f"create-draft {name}", pr.status_code, pr.text[:400])
        pr.raise_for_status()
        return pr.json()

    pa = create_pl(name_a, w1, cfg_ada)
    pb = create_pl(name_b, w2, cfg_pcn)

    plane = ROOT / "data/benchmark_inputs/airplane.pcd"
    if not plane.is_file():
        raise FileNotFoundError(plane)

    with plane.open("rb") as fh:
        up = requests.post(
            f"{BASE}/files/upload",
            files={"file": ("airplane.pcd", fh, "application/octet-stream")},
            timeout=120,
        )
    print("upload", up.status_code, up.text)
    up.raise_for_status()
    bucket = up.json()["bucket"]
    key = up.json()["key"]

    def run_task(pl_resp: dict, label: str) -> dict:
        cfg = json.loads(pl_resp["config_yaml"])
        fp = cfg["flow_params"]
        tr = requests.post(
            f"{BASE}/tasks",
            json={
                "input_bucket": bucket,
                "input_key": key,
                "flow_id": cfg["flow_id"],
                "flow_params": fp,
            },
            timeout=60,
        )
        print(f"task {label}", tr.status_code, tr.text[:500])
        tr.raise_for_status()
        tid = tr.json()["id"]
        return wait_task(tid, label, interval=10.0, max_wait=3600.0)

    ta = run_task(pa, "pipeline_a")
    print("task A", ta)
    logs_a = requests.get(f"{BASE}/tasks/{ta['id']}/logs", timeout=60)
    print("logs A tail:\n", (logs_a.json().get("logs") or "")[-2000:])

    tb = run_task(pb, "pipeline_b")
    print("task B", tb)
    logs_b = requests.get(f"{BASE}/tasks/{tb['id']}/logs", timeout=60)
    print("logs B tail:\n", (logs_b.json().get("logs") or "")[-2000:])

    print("E2E done.")


if __name__ == "__main__":
    main()
