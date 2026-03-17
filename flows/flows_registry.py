from collections.abc import Callable

from flows.pipeline_flow import stage2_test_flow


def get_registered_flows() -> dict[str, Callable]:
    """
    Централизованный реестр flow-функций для orchestrator.
    В этапе 2 регистрируется только тестовый flow.
    """
    return {
        "stage2_test_flow": stage2_test_flow,
    }

