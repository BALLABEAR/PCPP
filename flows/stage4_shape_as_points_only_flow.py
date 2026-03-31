from prefect import flow, get_run_logger

from flows.stage4_real_two_model_flow import build_stage4_real_two_model_steps, stage4_real_two_model_flow


@flow(name="stage4-shape-as-points-only-flow", log_prints=True)
def stage4_shape_as_points_only_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    meshing_repo_path: str = "external_models/ShapeAsPoints",
    meshing_config_path: str = "configs/optim_based/teaser.yaml",
    meshing_total_epochs: int = 200,
    meshing_grid_res: int = 128,
    meshing_no_cuda: bool = False,
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage4 shape-as-points-only flow started for task %s", task_id)
    steps = build_stage4_real_two_model_steps(
        meshing_repo_path=meshing_repo_path,
        meshing_config_path=meshing_config_path,
        meshing_total_epochs=meshing_total_epochs,
        meshing_grid_res=meshing_grid_res,
        meshing_no_cuda=meshing_no_cuda,
    )[1:]
    return stage4_real_two_model_flow(
        task_id=task_id,
        input_bucket=input_bucket,
        input_key=input_key,
        result_bucket=result_bucket,
        meshing_repo_path=meshing_repo_path,
        meshing_config_path=meshing_config_path,
        meshing_total_epochs=meshing_total_epochs,
        meshing_grid_res=meshing_grid_res,
        meshing_no_cuda=meshing_no_cuda,
        pipeline_steps=steps,
        input_keys=input_keys,
        task_created_at_utc=task_created_at_utc,
    )
