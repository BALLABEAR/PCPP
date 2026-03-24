from collections.abc import Callable

from flows.pipeline_flow import (
    stage2_test_flow,
    stage4_real_two_model_flow,
    stage4_segmentation_completion_flow,
    stage4_shape_as_points_only_flow,
    stage4_snowflake_only_flow,
)


def get_registered_flows() -> dict[str, Callable]:
    """
    Централизованный реестр flow-функций для orchestrator.
    В этапе 2 регистрируется только тестовый flow.
    """
    return {
        "stage2_test_flow": stage2_test_flow,
        "stage4_segmentation_completion_flow": stage4_segmentation_completion_flow,
        "stage4_real_two_model_flow": stage4_real_two_model_flow,
        "stage4_snowflake_only_flow": stage4_snowflake_only_flow,
        "stage4_shape_as_points_only_flow": stage4_shape_as_points_only_flow,
    }

