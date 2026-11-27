"""兼容性别名：样本漂移交接领域服务。"""
from app.services.drift_board import (  # noqa: F401
    DriftBoardService,
    drift_board_service,
)

service = drift_board_service


def __getattr__(name: str):
    return getattr(drift_board_service, name)
