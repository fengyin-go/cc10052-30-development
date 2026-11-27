"""AA 漂移看板与样本核对交接的专用 HTTP 接口。

路径同时提供连字符/下划线以及 aa-check/sample-ratio 常见别名，降低不同前端
组织方式下的接入成本；核心契约以中文业务字段和英文别名字段同时返回。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.services.drift_board import drift_board_service as svc
from app.store import store

router = APIRouter(prefix="/api", tags=["AA漂移与样本核对交接"])


def _reply(result: dict[str, Any]) -> JSONResponse:
    status = 200
    if not result.get("ok", True):
        status = int(result.get("status_code") or 400)
    elif result.get("status_code"):
        status = int(result["status_code"])
    return JSONResponse(status_code=status, content=result)


async def _payload(request: Request) -> dict[str, Any]:
    if request.method == "GET":
        return {key: value for key, value in request.query_params.items()}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return {"value": body}
    # 允许前端把字段包在 values/payload 中，也允许直接平铺。
    merged = dict(request.query_params)
    merged.update(body)
    for wrapper in ("values", "payload", "data"):
        nested = body.get(wrapper)
        if isinstance(nested, dict):
            merged.update(nested)
    return merged


def _board_kwargs(data: dict[str, Any]) -> dict[str, Any]:
    refs = (
        data.get("round_ids") or data.get("roundIds") or data.get("refs")
        or data.get("selected_rounds") or data.get("selectedRoundIds")
        or data.get("轮次") or data.get("sample_rounds")
    )
    left = (
        data.get("left_round_id") or data.get("leftRoundId") or data.get("left_round")
        or data.get("left") or data.get("base_round_id") or data.get("baseRoundId")
        or data.get("base_round") or data.get("base") or data.get("round_a")
        or data.get("roundA") or data.get("first_round_id") or data.get("first")
        or data.get("第一轮") or data.get("T1")
    )
    right = (
        data.get("right_round_id") or data.get("rightRoundId") or data.get("right_round")
        or data.get("right") or data.get("target_round_id") or data.get("targetRoundId")
        or data.get("target_round") or data.get("target") or data.get("round_b")
        or data.get("roundB") or data.get("second_round_id") or data.get("second")
        or data.get("第二轮") or data.get("T2")
    )
    if refs is None and (left is not None or right is not None):
        refs = [x for x in (left, right) if x is not None]
    return {
        "experiment_code": (
            data.get("experiment_code") or data.get("experimentCode") or data.get("experiment_id")
            or data.get("experimentId") or data.get("exp_code") or data.get("exp")
            or data.get("实验编码") or data.get("实验ID")
        ),
        "round_ids": refs if isinstance(refs, list) else [refs] if refs is not None else None,
        "left_round": left,
        "right_round": right,
    }


# ---------- 查询与轮次 ----------

@router.get("/aa-drift/experiments")
@router.get("/aa_drift/experiments")
@router.get("/aa-check/drift/experiments")
@router.get("/aa_check/drift/experiments")
async def experiments() -> dict[str, Any]:
    return {"ok": True, "items": svc.experiments(), "experiments": svc.experiments()}


@router.get("/aa-drift/rounds")
@router.get("/aa_drift/rounds")
@router.get("/aa-check/rounds")
@router.get("/aa_check/rounds")
async def list_rounds(experiment_code: str | None = None, 实验编码: str | None = None) -> dict[str, Any]:
    code = experiment_code or 实验编码
    items = svc.list_rounds(code)
    return {"ok": True, "items": items, "total": len(items), "rounds": items}


@router.post("/aa-drift/rounds")
@router.post("/aa_drift/rounds")
@router.post("/aa-check/rounds")
@router.post("/aa_check/rounds")
async def create_round(request: Request) -> JSONResponse:
    data = await _payload(request)
    return _reply(svc.create_round(data))


@router.get("/aa-drift/rounds/{round_id}")
@router.get("/aa_drift/rounds/{round_id}")
@router.get("/aa-check/rounds/{round_id}")
@router.get("/aa_check/rounds/{round_id}")
async def get_round(round_id: str) -> JSONResponse:
    row = svc.resolve_round(round_id)
    if row is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": f"轮次 {round_id} 不存在"})
    return JSONResponse({"ok": True, "round": svc.round_view(row), "entry": svc.round_view(row)})


@router.post("/aa-drift/rounds/{round_id}/confirm")
@router.post("/aa_drift/rounds/{round_id}/confirm")
@router.post("/aa-check/rounds/{round_id}/confirm")
@router.post("/aa_check/rounds/{round_id}/confirm")
async def confirm_round(round_id: str, request: Request) -> JSONResponse:
    data = await _payload(request)
    return _reply(svc.set_round_status(round_id, "confirm", str(data.get("reason", ""))))


@router.post("/aa-drift/rounds/{round_id}/revoke")
@router.post("/aa_drift/rounds/{round_id}/revoke")
@router.post("/aa-check/rounds/{round_id}/revoke")
@router.post("/aa_check/rounds/{round_id}/revoke")
async def revoke_round(round_id: str, request: Request) -> JSONResponse:
    data = await _payload(request)
    return _reply(svc.set_round_status(round_id, "revoke", str(data.get("reason") or data.get("撤销原因") or "")))


@router.post("/aa-drift/assignments/correct")
@router.post("/aa_drift/assignments/correct")
@router.post("/aa-check/assignments/correct")
@router.post("/aa_check/assignments/correct")
async def correct_assignment(request: Request) -> JSONResponse:
    return _reply(svc.correct_assignment(await _payload(request)))


# ---------- 漂移看板 ----------

@router.get("/aa-drift/board")
@router.get("/aa_drift/board")
@router.get("/aa-drift")
@router.get("/aa_drift")
@router.get("/aa-check/drift")
@router.get("/aa_check/drift")
@router.get("/aa-check/drift/board")
@router.get("/aa_check/drift/board")
@router.get("/aa-check/drift-board")
@router.get("/aa_check/drift-board")
@router.get("/aa_check/drift_board")
@router.get("/aa-check/drift_board")
@router.get("/drift-board")
@router.get("/drift_board")
@router.get("/drift/board")
async def get_board(request: Request) -> dict[str, Any]:
    data = await _payload(request)
    return svc.build_board(**_board_kwargs(data))


@router.post("/aa-drift/board")
@router.post("/aa_drift/board")
@router.post("/aa-drift/compare")
@router.post("/aa_drift/compare")
@router.post("/aa-check/drift")
@router.post("/aa_check/drift")
@router.post("/aa-check/drift/board")
@router.post("/aa_check/drift/board")
@router.post("/aa-check/drift_board")
@router.post("/aa_check/drift_board")
@router.post("/aa-check/compare-rounds")
@router.post("/aa_check/compare_rounds")
@router.post("/drift-board/compare")
@router.post("/drift_board")
@router.post("/drift/compare")
async def post_board(request: Request) -> dict[str, Any]:
    data = await _payload(request)
    return svc.build_board(**_board_kwargs(data))


@router.get("/aa-drift/adjacent-confirmed")
@router.get("/aa_drift/adjacent-confirmed")
@router.get("/aa-check/adjacent-confirmed")
@router.get("/aa_check/adjacent_confirmed")
async def adjacent(experiment_code: str | None = None, 实验编码: str | None = None) -> dict[str, Any]:
    code = experiment_code or 实验编码
    if not code:
        return {"ok": False, "message": "必须提供实验编码"}
    return {"ok": True, "pairs": svc.adjacent_confirmed_pairs(code), "相邻确认轮次": svc.adjacent_confirmed_pairs(code)}


@router.post("/aa-drift/requests")
@router.post("/aa_drift/requests")
@router.post("/aa-check/drift/requests")
@router.post("/aa_check/drift/requests")
async def create_request(request: Request) -> JSONResponse:
    return _reply(svc.create_drift_request(await _payload(request)))


@router.get("/aa-drift/requests")
@router.get("/aa_drift/requests")
async def list_requests() -> dict[str, Any]:
    return {"ok": True, "items": svc.requests, "total": len(svc.requests)}


@router.get("/aa-drift/requests/{request_id}")
@router.get("/aa_drift/requests/{request_id}")
async def get_request(request_id: str) -> JSONResponse:
    row = svc.get_request(request_id)
    if row is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "漂移请求不存在"})
    return JSONResponse({"ok": True, "request": row, "entry": row})


# ---------- 换组核对单 ----------

@router.post("/aa-drift/transfer-orders")
@router.post("/aa_drift/transfer_orders")
@router.post("/aa-check/transfer-orders")
@router.post("/aa_check/transfer_orders")
@router.post("/drift/transfer-orders")
async def create_order(request: Request) -> JSONResponse:
    return _reply(svc.create_transfer_order(await _payload(request)))


@router.get("/aa-drift/transfer-orders")
@router.get("/aa_drift/transfer_orders")
@router.get("/aa-check/transfer-orders")
@router.get("/aa_check/transfer_orders")
async def list_orders() -> dict[str, Any]:
    return {"ok": True, "items": svc.orders, "total": len(svc.orders)}


@router.get("/aa-drift/transfer-orders/{order_id}")
@router.get("/aa_drift/transfer_orders/{order_id}")
async def get_order(order_id: str) -> JSONResponse:
    order = next((o for o in svc.orders if str(o.get("id")) == order_id or o.get("order_code") == order_id), None)
    if order is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "核对单不存在"})
    return JSONResponse({"ok": True, "order": order})


@router.post("/aa-drift/transfer-orders/{order_id}/confirm")
@router.post("/aa_drift/transfer_orders/{order_id}/confirm")
async def confirm_order(order_id: str) -> JSONResponse:
    return _reply(svc.confirm_order(order_id))


# ---------- 样本量核对申请 ----------

@router.post("/sample-drift/applications")
@router.post("/sample_drift/applications")
@router.post("/sample-ratio/drift/applications")
@router.post("/sample_ratio/drift/applications")
async def create_application(request: Request) -> JSONResponse:
    return _reply(svc.create_application(await _payload(request)))


@router.get("/sample-drift/applications")
@router.get("/sample_drift/applications")
async def list_applications() -> dict[str, Any]:
    return {"ok": True, "items": svc.applications, "total": len(svc.applications)}


@router.get("/sample-drift/applications/{app_id}")
@router.get("/sample_drift/applications/{app_id}")
async def get_application(app_id: str) -> JSONResponse:
    app = svc.get_application(app_id)
    if app is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "样本核对申请不存在"})
    return JSONResponse({"ok": True, "application": app, "entry": app})


@router.post("/sample-drift/applications/{app_id}/claim")
@router.post("/sample_drift/applications/{app_id}/claim")
@router.post("/sample-ratio/applications/{app_id}/claim")
@router.post("/sample_ratio/applications/{app_id}/claim")
async def claim_application(app_id: str, request: Request) -> JSONResponse:
    data = await _payload(request)
    resolution = (
        data.get("resolution") or data.get("choice") or data.get("adopt")
        or data.get("accept") or data.get("use") or data.get("采用版次") or data.get("选择")
    )
    return _reply(svc.claim_application(app_id, resolution, actor=data.get("actor")))


@router.post("/sample-drift/applications/{app_id}/review")
@router.post("/sample_drift/applications/{app_id}/review")
@router.post("/sample-ratio/applications/{app_id}/review")
@router.post("/sample_ratio/applications/{app_id}/review")
async def review_application(app_id: str) -> JSONResponse:
    return _reply(svc.review_application(app_id))


@router.get("/sample-drift/applications/{app_id}/trace")
@router.get("/sample_drift/applications/{app_id}/trace")
async def trace_application(app_id: str) -> JSONResponse:
    return _reply(svc.trace_application(app_id))


@router.get("/sample-drift/batches/{app_id}/trace")
@router.get("/sample_drift/batches/{app_id}/trace")
@router.get("/sample-ratio/batches/{app_id}/trace")
@router.get("/sample_ratio/batches/{app_id}/trace")
async def trace_batch(app_id: str) -> JSONResponse:
    return _reply(svc.trace_sample_batch(app_id))


# 直接挂在通用 sample_ratio 资源 ID 下的别名，便于列表行按钮调用。
@router.get("/sample_ratio/{entry_id}/drift-trace")
@router.get("/sample-ratio/{entry_id}/drift-trace")
async def sample_entry_trace(entry_id: str) -> JSONResponse:
    return _reply(svc.trace_sample_batch(entry_id))


@router.post("/sample_ratio/{entry_id}/claim-drift")
@router.post("/sample-ratio/{entry_id}/claim-drift")
@router.post("/sample_ratio/{entry_id}/claim")
@router.post("/sample-ratio/{entry_id}/claim")
async def sample_entry_claim(entry_id: str, request: Request) -> JSONResponse:
    data = await _payload(request)
    app = svc.find_application_by_sample_entry(entry_id)
    if app is None:
        created = svc.create_application({
            "sample_entry_id": int(entry_id) if entry_id.isdigit() else entry_id,
            "experiment_code": data.get("experiment_code") or data.get("实验编码"),
            "round_ids": data.get("round_ids") or data.get("关联轮次") or data.get("轮次"),
            "application_code": data.get("application_code"),
            "create_sample_row": False,
        })
        if not created.get("ok"):
            return _reply(created)
        app = created["application"]
    resolution = data.get("resolution") or data.get("choice") or data.get("adopt") or data.get("accept") or data.get("use") or data.get("采用版次") or data.get("选择")
    return _reply(svc.claim_application(app["id"], resolution))


@router.post("/sample_ratio/{entry_id}/review-drift")
@router.post("/sample-ratio/{entry_id}/review-drift")
@router.post("/sample_ratio/{entry_id}/review")
@router.post("/sample-ratio/{entry_id}/review")
async def sample_entry_review(entry_id: str) -> JSONResponse:
    app = svc.find_application_by_sample_entry(entry_id)
    if app is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "该样本核对批次尚未关联漂移申请"})
    return _reply(svc.review_application(app["id"]))


@router.get("/sample_ratio/{entry_id}/trace")
@router.get("/sample-ratio/{entry_id}/trace")
async def sample_entry_trace_short(entry_id: str) -> JSONResponse:
    return _reply(svc.trace_sample_batch(entry_id))


@router.post("/sample-drift/claim")
@router.post("/sample_drift/claim")
@router.post("/sample_ratio/claim_drift")
@router.post("/sample-ratio/claim-drift")
async def claim_by_body(request: Request) -> JSONResponse:
    data = await _payload(request)
    application_ref = data.get("application_id") or data.get("app_id")
    sample_ref = data.get("sample_entry_id") or data.get("batch_id") or data.get("sample_batch_id")
    app_id = application_ref or sample_ref or data.get("id")
    if app_id is None:
        return JSONResponse(status_code=400, content={"ok": False, "message": "必须提供申请或样本批次 ID"})
    resolution = (
        data.get("resolution") or data.get("choice") or data.get("adopt")
        or data.get("accept") or data.get("use") or data.get("采用版次") or data.get("选择")
    )

    app = None
    if sample_ref is not None and application_ref is None:
        app = svc.find_application_by_sample_entry(sample_ref)
        if app is None and str(sample_ref).isdigit():
            entry = store.find("sample_ratio", int(sample_ref))
            if entry is not None:
                created = svc.create_application({
                    "sample_entry_id": entry["id"],
                    "experiment_code": entry.get("实验编码") or data.get("experiment_code"),
                    "round_ids": data.get("round_ids") or data.get("轮次"),
                    "create_sample_row": False,
                })
                if not created.get("ok"):
                    return _reply(created)
                app = created["application"]
    if app is None:
        app = svc.get_application(app_id)
    if app is None:
        return JSONResponse(status_code=404, content={"ok": False, "message": "样本核对申请不存在"})
    return _reply(svc.claim_application(app["id"], resolution))
