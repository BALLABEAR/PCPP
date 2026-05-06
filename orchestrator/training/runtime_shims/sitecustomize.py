from __future__ import annotations

try:
    import torch.utils.tensorboard as torch_tensorboard

    from orchestrator.training.runtime_shims.metrics_capture import patch_summary_writer_module

    patch_summary_writer_module(torch_tensorboard, "torch.utils.tensorboard")
except Exception:
    pass
