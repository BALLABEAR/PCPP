from prefect import flow, get_run_logger

from flows.common import run_test_worker


@flow(name="stage2-test-flow", log_prints=True)
def stage2_test_flow(
    task_id: str,
    input_bucket: str,
    input_key: str,
    result_bucket: str,
    input_keys: list[str] | None = None,
    task_created_at_utc: str | None = None,
) -> str:
    logger = get_run_logger()
    logger.info("Stage2 flow started for task %s", task_id)
    # Stage2 keeps single-file behavior by contract.
    result_key = run_test_worker(task_id, input_bucket, input_key, result_bucket)
    logger.info("Stage2 flow completed for task %s", task_id)
    return result_key
