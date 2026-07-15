from __future__ import annotations

import os


# Возвращает DSN для подключения к PostgreSQL.
def get_database_url() -> str:
    return os.getenv("DATABASE_URL", "postgresql://pcpp_new:pcpp_new@postgres:5432/pcpp_new")


# Возвращает корень workspace, где лежат workers и артефакты.
def get_workspace_root() -> str:
    return os.getenv("WORKSPACE_ROOT", "/workspace")
