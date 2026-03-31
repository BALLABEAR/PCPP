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


def _value(params: dict[str, Any], key: str, default: Any) -> Any:
    value = params.get(key, default)
    return default if value is None else value


def build_stage4_real_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    completion_mode = _value(params, "completion_mode", "model")
    completion_weights_path = _value(
        params,
        "completion_weights_path",
        "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
    )
    completion_config_path = _value(
        params,
        "completion_config_path",
        "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
    )
    completion_device = _value(params, "completion_device", "cuda")
    meshing_repo_path = _value(params, "meshing_repo_path", "external_models/ShapeAsPoints")
    meshing_config_path = _value(params, "meshing_config_path", "configs/optim_based/teaser.yaml")
    meshing_total_epochs = int(_value(params, "meshing_total_epochs", 200))
    meshing_grid_res = int(_value(params, "meshing_grid_res", 128))
    meshing_no_cuda = bool(_value(params, "meshing_no_cuda", False))
    return [
        {
            "name": "01_completion",
            "worker_module": "workers.completion.snowflake_net.worker",
            "worker_class": "SnowflakeWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/completion/snowflake_net/Dockerfile",
            "image_tag": "pcpp-snowflake:gpu",
            "use_gpu": completion_device == "cuda",
            "cli_args": {
                "mode": completion_mode,
                "weights": completion_weights_path,
                "config": completion_config_path,
                "device": completion_device,
            },
        },
        {
            "name": "02_meshing",
            "worker_module": "workers.meshing.shape_as_points.worker",
            "worker_class": "ShapeAsPointsOptimWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/meshing/shape_as_points/Dockerfile",
            "image_tag": "pcpp-meshing-shape_as_points:gpu",
            "use_gpu": not meshing_no_cuda,
            "cli_args": {
                "repo-path": meshing_repo_path,
                "config": meshing_config_path,
                "total-epochs": meshing_total_epochs,
                "grid-res": meshing_grid_res,
                "no-cuda": meshing_no_cuda,
            },
        },
    ]


def build_stage4_snowflake_only_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    return build_stage4_real_steps(params)[:1]


def build_stage4_shape_as_points_only_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    return build_stage4_real_steps(params)[1:]


def build_stage4_segmentation_completion_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    return [
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
                "mode": _value(params, "completion_mode", "passthrough"),
                "weights_path": params.get("weights_path"),
                "config_path": params.get("config_path"),
                "device": params.get("device"),
            },
        },
    ]


def build_stage4_cloudcompare_only_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "01_cloudcompare",
            "worker_module": "workers.meshing.cloudcompare.worker",
            "worker_class": "CloudCompareMeshingWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/meshing/cloudcompare/Dockerfile",
            "image_tag": "pcpp-meshing-cloudcompare:cpu",
            "use_gpu": False,
            "cli_args": {
                "cloudcompare-exe": _value(params, "cloudcompare_exe", "CloudCompare"),
                "strict-cli": bool(_value(params, "strict_cli", False)),
            },
        }
    ]


def build_stage4_pointr_only_steps(params: dict[str, Any]) -> list[dict[str, Any]]:
    pointr_mode = _value(params, "pointr_mode", "model")
    pointr_repo_path = _value(params, "pointr_repo_path", "external_models/PoinTr")
    pointr_config_path = _value(params, "pointr_config_path", "cfgs/PCN_models/PoinTr.yaml")
    pointr_weights_path = params.get("pointr_weights_path")
    pointr_device = _value(params, "pointr_device", "cuda:0")
    return [
        {
            "name": "01_completion",
            "worker_module": "workers.completion.poin_tr.worker",
            "worker_class": "PointrWorker",
            "execution_mode": "docker",
            "dockerfile_path": "/app/workers/completion/poin_tr/Dockerfile",
            "image_tag": "pcpp-completion-poin_tr:gpu",
            "use_gpu": not str(pointr_device).startswith("cpu"),
            "cli_args": {
                "mode": pointr_mode,
                "repo-path": pointr_repo_path,
                "config": pointr_config_path,
                "weights": pointr_weights_path,
                "device": pointr_device,
            },
        }
    ]


FLOW_DEFINITIONS: list[FlowDefinition] = [
    FlowDefinition(
        flow_id="stage2_test_flow",
        flow_callable_path="flows.stage2_test_flow:stage2_test_flow",
        template={
            "id": "stage2_test",
            "name": "Stage 2 Test Flow",
            "flow_id": "stage2_test_flow",
            "description": "MinIO -> fake worker -> MinIO result",
            "flow_params": {},
        },
    ),
    FlowDefinition(
        flow_id="stage4_segmentation_completion_flow",
        flow_callable_path="flows.stage4_segmentation_completion_flow:stage4_segmentation_completion_flow",
        step_builder_path="flows.flow_definitions:build_stage4_segmentation_completion_steps",
    ),
    FlowDefinition(
        flow_id="stage4_real_two_model_flow",
        flow_callable_path="flows.stage4_real_two_model_flow:stage4_real_two_model_flow",
        step_builder_path="flows.flow_definitions:build_stage4_real_steps",
        template={
            "id": "stage4_real_two_model",
            "name": "Stage 4 Real (Completion -> Meshing)",
            "flow_id": "stage4_real_two_model_flow",
            "description": "SnowflakeNet completion + ShapeAsPoints meshing",
            "flow_params": {
                "completion_mode": "model",
                "completion_weights_path": "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
                "completion_config_path": "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
                "completion_device": "cuda",
                "meshing_repo_path": "external_models/ShapeAsPoints",
                "meshing_config_path": "configs/optim_based/teaser.yaml",
                "meshing_total_epochs": 200,
                "meshing_grid_res": 128,
                "meshing_no_cuda": False,
            },
        },
    ),
    FlowDefinition(
        flow_id="stage4_snowflake_only_flow",
        flow_callable_path="flows.stage4_snowflake_only_flow:stage4_snowflake_only_flow",
        step_builder_path="flows.flow_definitions:build_stage4_snowflake_only_steps",
        template={
            "id": "stage4_snowflake_only",
            "name": "Stage 4 Snowflake Only",
            "flow_id": "stage4_snowflake_only_flow",
            "description": "Single-step completion flow with SnowflakeNet only",
            "flow_params": {
                "completion_mode": "model",
                "completion_weights_path": "external_models/SnowflakeNet/pretrained_completion/ckpt-best-c3d-cd_l2.pth",
                "completion_config_path": "external_models/SnowflakeNet/completion/configs/c3d_cd2.yaml",
                "completion_device": "cuda",
            },
        },
    ),
    FlowDefinition(
        flow_id="stage4_shape_as_points_only_flow",
        flow_callable_path="flows.stage4_shape_as_points_only_flow:stage4_shape_as_points_only_flow",
        step_builder_path="flows.flow_definitions:build_stage4_shape_as_points_only_steps",
        template={
            "id": "stage4_shape_as_points_only",
            "name": "Stage 4 ShapeAsPoints Only",
            "flow_id": "stage4_shape_as_points_only_flow",
            "description": "Single-step meshing flow with ShapeAsPoints only",
            "flow_params": {
                "meshing_repo_path": "external_models/ShapeAsPoints",
                "meshing_config_path": "configs/optim_based/teaser.yaml",
                "meshing_total_epochs": 20,
                "meshing_grid_res": 64,
                "meshing_no_cuda": False,
            },
        },
    ),
    FlowDefinition(
        flow_id="stage4_cloudcompare_only_flow",
        flow_callable_path="flows.stage4_cloudcompare_only_flow:stage4_cloudcompare_only_flow",
        step_builder_path="flows.flow_definitions:build_stage4_cloudcompare_only_steps",
        template={
            "id": "stage4_cloudcompare_only",
            "name": "Stage 4 CloudCompare Only",
            "flow_id": "stage4_cloudcompare_only_flow",
            "description": "Single-step meshing flow with CloudCompare adapter",
            "flow_params": {
                "cloudcompare_exe": "CloudCompare",
                "strict_cli": False,
            },
        },
    ),
    FlowDefinition(
        flow_id="stage4_pointr_adapointr_pcn_flow",
        flow_callable_path="flows.stage4_pointr_only_flow:stage4_pointr_only_flow",
        step_builder_path="flows.flow_definitions:build_stage4_pointr_only_steps",
        template={
            "id": "stage4_pointr_adapointr_pcn",
            "name": "PoinTr AdaPoinTrPCN",
            "flow_id": "stage4_pointr_adapointr_pcn_flow",
            "description": "Single-step completion flow with PoinTr",
            "flow_params": {
                "pointr_mode": "model",
                "pointr_repo_path": "external_models/PoinTr",
                "pointr_config_path": "cfgs/PCN_models/AdaPoinTr.yaml",
                "pointr_weights_path": "external_models/PoinTr/pretrained/AdaPoinTr_PCN.pth",
                "pointr_device": "cuda:0",
            },
        },
    ),
    FlowDefinition(
        flow_id="stage4_pointr_pcnnew_flow",
        flow_callable_path="flows.stage4_pointr_only_flow:stage4_pointr_only_flow",
        step_builder_path="flows.flow_definitions:build_stage4_pointr_only_steps",
        template={
            "id": "stage4_pointr_pcnnew",
            "name": "PoinTr PCNnew",
            "flow_id": "stage4_pointr_pcnnew_flow",
            "description": "Single-step completion flow with PoinTr",
            "flow_params": {
                "pointr_mode": "model",
                "pointr_repo_path": "external_models/PoinTr",
                "pointr_config_path": "cfgs/PCN_models/PoinTr.yaml",
                "pointr_weights_path": "external_models/PoinTr/pretrained/PCNnew.pth",
                "pointr_device": "cuda:0",
            },
        },
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
