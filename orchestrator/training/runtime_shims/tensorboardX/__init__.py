from __future__ import annotations

from orchestrator.training.runtime_shims.metrics_capture import build_writer_class


SummaryWriter = build_writer_class(None, "tensorboardX")
FileWriter = build_writer_class(None, "tensorboardX")
