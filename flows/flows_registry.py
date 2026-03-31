from collections.abc import Callable

from flows.flow_definitions import FLOW_DEFINITIONS, get_flow_callable


def get_registered_flows() -> dict[str, Callable]:
    registered: dict[str, Callable] = {}
    for definition in FLOW_DEFINITIONS:
        flow_callable = get_flow_callable(definition.flow_id)
        if flow_callable is None:
            continue
        registered[definition.flow_id] = flow_callable
    return registered

