"""业务路由汇总：专用漂移接口先注册，通用资源路由最后兜底。"""
from __future__ import annotations

from app.routers import drift, resource

ROUTERS = [drift, resource]
