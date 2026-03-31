import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorHint:
    title: str
    pattern: str
    fix: str


ERROR_HINTS: list[ErrorHint] = [
    ErrorHint(
        title="Путь к файлу не найден",
        pattern=r"(FileNotFoundError|Input file not found|Weights file not found|Repo path not found)",
        fix="Проверьте пути repo/weights/config и убедитесь, что файлы реально существуют в external_models.",
    ),
    ErrorHint(
        title="Несовпадение checkpoint и config",
        pattern=r"(size mismatch|is not in the models registry|state_dict)",
        fix="Проверьте, что checkpoint соответствует config одной и той же архитектуры (например AdaPoinTr -> AdaPoinTr.yaml).",
    ),
    ErrorHint(
        title="Не собран extension",
        pattern=r"(No module named 'emd'|No module named 'pointnet2_ops'|No module named 'gridding')",
        fix="Добавьте сборку нужного extension в runtime.manifest.yaml (build_steps) и пересоберите образ без кэша.",
    ),
    ErrorHint(
        title="Проблема build isolation",
        pattern=r"(Failed to build 'pointnet2_ops'|build wheel)",
        fix="Для pointnet2_ops используйте --no-build-isolation и убедитесь, что torch установлен до сборки extension.",
    ),
    ErrorHint(
        title="Проблема CUDA arch при сборке",
        pattern=r"(IndexError: list index out of range|_get_cuda_arch_flags)",
        fix="Укажите TORCH_CUDA_ARCH_LIST в env runtime.manifest.yaml и пересоберите образ.",
    ),
    ErrorHint(
        title="Проблема версии NumPy",
        pattern=r"(_ARRAY_API not found|Failed to initialize NumPy)",
        fix="Зафиксируйте numpy<2 в runtime.manifest.yaml и пересоберите образ без кэша.",
    ),
    ErrorHint(
        title="Docker daemon недоступен",
        pattern=r"(failed to connect to the docker API|dockerDesktopLinuxEngine|No such file or directory: 'docker')",
        fix="Проверьте, что Docker Desktop запущен и Linux engine активен.",
    ),
]


def classify_error(log_text: str) -> dict[str, str] | None:
    text = log_text or ""
    for hint in ERROR_HINTS:
        if re.search(hint.pattern, text, re.IGNORECASE):
            return {"title": hint.title, "fix": hint.fix}
    return None
