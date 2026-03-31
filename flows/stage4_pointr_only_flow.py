from prefect import flow, get_run_logger

from flows.common import execute_pipeline


@flow(name="stage4-pointr-only-flow", log_prints=True)
def stage4_pointr_only_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    pointr_mode: str = "model",
    pointr_repo_path: str = "external_models/PoinTr",
    pointr_config_path: str = "cfgs/PCN_models/PoinTr.yaml",
    pointr_weights_path: str | None = None,
    pointr_device: str = "cuda:0",
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 PoinTr-only flow started for task %s", task_id)
    steps = [
        {
            "name": "01_completion",
            "worker_module": "workers.completion.poin_tr.worker",
            "worker_class": "PointrWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/completion/poin_tr/Dockerfile",
            "image_tag": "pcpp-completion-poin_tr:gpu",
            "use_gpu": not pointr_device.startswith("cpu"),
            "cli_args": {
                "mode": pointr_mode,
                "repo-path": pointr_repo_path,
                "config": pointr_config_path,
                "weights": pointr_weights_path,
                "device": pointr_device,
            },
        }
    ]
    return execute_pipeline(
        flow_id="stage4_pointr_only_flow",
        task_id=task_id,
        input_bucket=input_bucket,
        input_key=input_key,
        input_keys=input_keys,
        result_bucket=result_bucket,
        pipeline_steps=steps,
        task_created_at_utc=task_created_at_utc,
    )
