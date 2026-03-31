from prefect import flow, get_run_logger

from flows.common import execute_pipeline


@flow(name="stage4-segmentation-completion-flow", log_prints=True)
def stage4_segmentation_completion_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    completion_mode: str = "passthrough",
    weights_path: str | None = None,
    config_path: str | None = None,
    device: str | None = None,
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 segmentation+completion flow started for task %s", task_id)
    # Keep historical step names/paths for compatibility with existing tests.
    steps = [
        {
            "name": "segmented",
            "worker_module": "workers.segmentation.fake_segmentation.worker",
            "worker_class": "FakeSegmentationWorker",
            "execution_mode": "local",
        },
        {
            "name": "completed",
            "worker_module": "workers.completion.snowflake_net.worker",
            "worker_class": "SnowflakeWorker",
            "execution_mode": "local",
            "worker_kwargs": {
                "mode": completion_mode,
                "weights_path": weights_path,
                "config_path": config_path,
                "device": device,
            },
        },
    ]
    return execute_pipeline(
        flow_id="stage4_segmentation_completion_flow",
        task_id=task_id,
        input_bucket=input_bucket,
        input_key=input_key,
        input_keys=input_keys,
        result_bucket=result_bucket,
        pipeline_steps=steps,
        task_created_at_utc=task_created_at_utc,
    )
