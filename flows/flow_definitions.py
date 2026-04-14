from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable


@dataclass(frozen=True)
class FlowDefinition:
    flow_id: str
    flow_callable_path: str
    step_builder_path: str | None = None
    template: dict[str, Any] | None = None


def _load_symbol(path: str) -> Any:
    module_name, symbol_name = path.rsplit(":", 1)
    module = import_module(module_name)
    return getattr(module, symbol_name)


FLOW_DEFINITIONS: list[FlowDefinition] = [
    FlowDefinition(
        flow_id="pipeline_flow",
        flow_callable_path="flows.common:pipeline_flow",
    ),
]


def get_flow_definitions() -> dict[str, FlowDefinition]:
    return {item.flow_id: item for item in FLOW_DEFINITIONS}


def get_flow_definition(flow_id: str) -> FlowDefinition | None:
    return get_flow_definitions().get(flow_id)


def get_flow_callable(flow_id: str):
    definition = get_flow_definition(flow_id)
    if definition is None:
        return None
    return _load_symbol(definition.flow_callable_path)


def get_flow_step_builder(flow_id: str) -> Callable[[dict[str, Any]], list[dict[str, Any]]] | None:
    definition = get_flow_definition(flow_id)
    if definition is None or not definition.step_builder_path:
        return None
    symbol = _load_symbol(definition.step_builder_path)
    return symbol


def get_pipeline_templates() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for definition in FLOW_DEFINITIONS:
        if definition.template:
            templates.append(definition.template)
    return templates