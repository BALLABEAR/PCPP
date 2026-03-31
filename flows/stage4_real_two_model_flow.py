from typing import Any

from prefect import flow, get_run_logger

from flows.common import execute_pipeline


def build_stage4_real_two_model_steps(
    *,
    completion_mode: str = "model",
    completion_weights_path: str | None = "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
    completion_config_path: str | None = "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
    completion_device: str | None = "cuda",
    meshing_repo_path: str = "external_models/ShapeAsPoints",
    meshing_config_path: str = "configs/optim_based/teaser.yaml",
    meshing_total_epochs: int = 200,
    meshing_grid_res: int = 128,
    meshing_no_cuda: bool = False,
) -> list[dict[str, Any]]:
    return [
        {
            "name": "01_completion",
            "worker_module": "workers.completion.snowflake_net.worker",
            "worker_class": "SnowflakeWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/completion/snowflake_net/Dockerfile",
            "image_tag": "pcpp-snowflake:gpu",
            "use_gpu": completion_device == "cuda",
            "cli_args": {
                "mode": completion_mode,
                "weights": completion_weights_path,
                "config": completion_config_path,
                "device": completion_device,
            },
        },
        {
            "name": "02_meshing",
            "worker_module": "workers.meshing.shape_as_points.worker",
            "worker_class": "ShapeAsPointsOptimWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/meshing/shape_as_points/Dockerfile",
            "image_tag": "pcpp-meshing-shape_as_points:gpu",
            "use_gpu": not meshing_no_cuda,
            "cli_args": {
                "repo-path": meshing_repo_path,
                "config": meshing_config_path,
                "total-epochs": meshing_total_epochs,
                "grid-res": meshing_grid_res,
                "no-cuda": meshing_no_cuda,
            },
        },
    ]


@flow(name="stage4-real-two-model-flow", log_prints=True)
def stage4_real_two_model_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    completion_mode: str = "model",
    completion_weights_path: str | None = "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
    completion_config_path: str | None = "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
    completion_device: str | None = "cuda",
    meshing_repo_path: str = "external_models/ShapeAsPoints",
    meshing_config_path: str = "configs/optim_based/teaser.yaml",
    meshing_total_epochs: int = 200,
    meshing_grid_res: int = 128,
    meshing_no_cuda: bool = False,
    pipeline_steps: list[dict] | None = None,
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 real flow started for task %s", task_id)
    if pipeline_steps is None:
        pipeline_steps = build_stage4_real_two_model_steps(
            completion_mode=completion_mode,
            completion_weights_path=completion_weights_path,
            completion_config_path=completion_config_path,
            completion_device=completion_device,
            meshing_repo_path=meshing_repo_path,
            meshing_config_path=meshing_config_path,
            meshing_total_epochs=meshing_total_epochs,
            meshing_grid_res=meshing_grid_res,
            meshing_no_cuda=meshing_no_cuda,
        )

    result_key = execute_pipeline(
        flow_id="stage4_real_two_model_flow",
        task_id=task_id,
        input_bucket=input_bucket,
        input_key=input_key,
        input_keys=input_keys,
        result_bucket=result_bucket,
        pipeline_steps=pipeline_steps,
        task_created_at_utc=task_created_at_utc,
    )
    logger.info("Stage4 real flow completed for task %s", task_id)
    return result_key
