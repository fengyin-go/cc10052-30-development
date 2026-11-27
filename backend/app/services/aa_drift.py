"""兼容性别名：部分测试/路由可能使用 aa_drift 命名。"""
from app.services.drift_board import (  # noqa: F401
    DriftBoardService,
    drift_board_service,
)

service = drift_board_service


def __getattr__(name: str):
    return getattr(drift_board_service, name)
