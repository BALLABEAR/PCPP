from prefect import flow, get_run_logger

from flows.stage4_real_two_model_flow import build_stage4_real_two_model_steps, stage4_real_two_model_flow


@flow(name="stage4-snowflake-only-flow", log_prints=True)
def stage4_snowflake_only_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    completion_mode: str = "model",
    completion_weights_path: str | None = "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
    completion_config_path: str | None = "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
    completion_device: str | None = "cuda",
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 snowflake-only flow started for task %s", task_id)
    steps = build_stage4_real_two_model_steps(
        completion_mode=completion_mode,
        completion_weights_path=completion_weights_path,
        completion_config_path=completion_config_path,
        completion_device=completion_device,
    )[:1]
    return stage4_real_two_model_flow(
        task_id=task_id,
        input_bucket=input_bucket,
        input_key=input_key,
        result_bucket=result_bucket,
        completion_mode=completion_mode,
        completion_weights_path=completion_weights_path,
        completion_config_path=completion_config_path,
        completion_device=completion_device,
        pipeline_steps=steps,
        input_keys=input_keys,
        task_created_at_utc=task_created_at_utc,
    )
