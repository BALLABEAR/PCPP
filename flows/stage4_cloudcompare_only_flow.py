from prefect import flow, get_run_logger

from flows.common import execute_pipeline


@flow(name="stage4-cloudcompare-only-flow", log_prints=True)
def stage4_cloudcompare_only_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    cloudcompare_exe: str = "CloudCompare",
    strict_cli: bool = False,
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 cloudcompare-only flow started for task %s", task_id)
    steps = [
        {
            "name": "01_cloudcompare",
            "worker_module": "workers.meshing.cloudcompare.worker",
            "worker_class": "CloudCompareMeshingWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/meshing/cloudcompare/Dockerfile",
            "image_tag": "pcpp-meshing-cloudcompare:cpu",
            "use_gpu": False,
            "cli_args": {
                "cloudcompare-exe": cloudcompare_exe,
                "strict-cli": strict_cli,
            },
        }
    ]
    return execute_pipeline(
        flow_id="stage4_cloudcompare_only_flow",
        task_id=task_id,
        input_bucket=input_bucket,
        input_key=input_key,
        input_keys=input_keys,
        result_bucket=result_bucket,
        pipeline_steps=steps,
        task_created_at_utc=task_created_at_utc,
    )
