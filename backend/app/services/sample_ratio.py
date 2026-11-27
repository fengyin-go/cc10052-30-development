"""样本量核对领域服务：管理实验分组比例的计划与实际核对、偏移告警与阈值判定。

数据链路位置：样本治理层，消费分组分配器的实际分配结果与实验设计的计划比例，
核对偏移量并告警，保证实验分组的统计有效性。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.drift_board import drift_board_service
from app.store import store


class SampleRatioService(BaseModuleService):
    MODULE = "sample_ratio"
    ENTITY = "核对结果"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["核对批次", "实验编码", "计划比例", "实际比例", "偏移量"]
    REQUIRED_FIELDS = ["核对批次", "实验编码", "计划比例"]
    STATUS_ORDER = ["待核对", "已核对", "偏移超标"]
    ACTION_RULES = {"执行核对": "已核对", "告警偏移": "偏移超标"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：比例核对与偏移告警 ----

    def run_check(self, entry_id: int) -> dict[str, Any]:
        """执行比例核对：重算实际比例并按阈值判定偏移状态。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "待核对":
            return {"ok": False, "message": "仅待核对批次可执行"}

        linked_app = drift_board_service.find_application_by_sample_entry(entry_id)
        if linked_app is None and entry.get("漂移申请编号"):
            linked_app = drift_board_service.get_application(entry.get("漂移申请编号"))
        if linked_app is not None:
            if not linked_app.get("adopted"):
                claim = drift_board_service.claim_application(linked_app.get("id"))
                if not claim.get("ok"):
                    entry["领取状态"] = "领取冲突，待选择版次"
                    return claim
            review = drift_board_service.review_application(linked_app.get("id"))
            return {"ok": review.get("ok", False), "message": review.get("message", "漂移复核完成"), "review": review}

        exp_code = str(entry.get("实验编码", ""))
        assign_rows = [
            r for r in store.rows("variant_assign")
            if r.get("实验编码") == exp_code and r.get("status") != "已剔除"
        ]
        if not assign_rows:
            entry["status"] = "偏移超标"
            entry["abnormal"] = True
            return {"ok": False, "message": "实验无有效分组，核对失败"}
        exp_count = sum(1 for r in assign_rows if r.get("分组名称") == "实验组")
        actual = round(exp_count / len(assign_rows), 4)
        try:
            planned = float(entry.get("计划比例", "0.5"))
        except ValueError:
            planned = 0.5
        offset = round(abs(actual - planned), 4)
        entry["实际比例"] = str(actual)
        entry["偏移量"] = str(offset)
        entry["核对时间"] = datetime.now(timezone.utc).isoformat()
        if offset > 0.05:
            entry["status"] = "偏移超标"
            entry["pending"] = True
            entry["abnormal"] = True
            return {"ok": True, "message": f"偏移 {offset} 超阈值 0.05，已告警"}
        entry["status"] = "已核对"
        entry["pending"] = False
        return {"ok": True, "message": f"核对通过，偏移 {offset} 在阈值内"}

    def alert_offset(self, entry_id: int) -> dict[str, Any]:
        """把偏移超标批次登记为异常事件，进入质量处置流程。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "偏移超标":
            return {"ok": False, "message": "仅偏移超标批次可告警"}
        anomaly_rows = store.rows("anomaly_metric")
        anomaly_rows.append({
            "id": max((int(r.get("id", 0)) for r in anomaly_rows), default=0) + 1,
            "异常编号": f"AN-SR-{entry_id}",
            "指标编码": str(entry.get("实验编码", "")),
            "基线区间": str(entry.get("计划比例", "")),
            "观测值": str(entry.get("实际比例", "")),
            "异常评分": "0.7",
            "status": "待确认",
            "pending": True,
            "abnormal": False,
        })
        entry["pending"] = True
        return {"ok": True, "message": f"偏移告警已登记（偏移量 {entry.get('偏移量', '0')}）"}

    def batch_run_pending(self) -> dict[str, Any]:
        """批量执行待核对批次。"""
        pending = [r for r in store.rows(self.MODULE) if r.get("status") == "待核对"]
        passed, alarmed = 0, 0
        for row in pending:
            result = self.run_check(int(row.get("id", 0)))
            if result.get("ok"):
                if "超阈值" in str(result.get("message", "")):
                    alarmed += 1
                else:
                    passed += 1
        return {"ok": True, "message": f"批量核对完成：通过 {passed}，告警 {alarmed}"}

    def consume_from_variant_assign(self, exp_code: str) -> dict[str, Any]:
        """读取分组分配器的分布统计，作为核对输入。"""
        rows = [r for r in store.rows("variant_assign") if r.get("实验编码") == exp_code]
        if not rows:
            return {"ok": False, "message": "实验无分组数据"}
        valid = [r for r in rows if r.get("status") != "已剔除"]
        return {
            "ok": True,
            "总分配数": len(rows),
            "有效分配数": len(valid),
            "实验组占比": round(sum(1 for r in valid if r.get("分组名称") == "实验组") / max(len(valid), 1), 4),
        }

    def consume_from_exp_design(self, exp_code: str) -> dict[str, Any]:
        """读取实验设计层流量比例作为计划比例。"""
        exp = next((r for r in store.rows("exp_design") if r.get("实验编码") == exp_code), None)
        if exp is None:
            return {"ok": False, "message": "实验方案不存在"}
        ratio = str(exp.get("流量比例", "0.5"))
        try:
            planned = float(ratio) / 100.0 if float(ratio) > 1 else float(ratio)
        except ValueError:
            planned = 0.5
        return {"ok": True, "计划比例": str(planned), "分组策略": exp.get("分组策略", "")}

    def export_offset_trend(self, exp_code: str) -> list[dict[str, Any]]:
        """导出实验偏移趋势，供报告生成器写入样本健康度章节。"""
        return [
            {
                "核对批次": r.get("核对批次", ""),
                "计划比例": r.get("计划比例", ""),
                "实际比例": r.get("实际比例", ""),
                "偏移量": r.get("偏移量", ""),
            }
            for r in store.rows(self.MODULE) if r.get("实验编码") == exp_code
        ]

    # ---- 分组漂移看板领取、两轮样本复核与报告回查 ----

    def create_drift_application(self, values: dict[str, Any]) -> dict[str, Any]:
        return drift_board_service.create_application(values)

    def claim_drift_board(self, batch_or_app_id: Any, resolution: Any = None, **kwargs: Any) -> dict[str, Any]:
        entry = store.find(self.MODULE, int(batch_or_app_id)) if str(batch_or_app_id).isdigit() else None
        if entry is not None:
            app = drift_board_service.find_application_by_sample_entry(entry["id"])
            if app is None and entry.get("漂移申请编号"):
                app = drift_board_service.get_application(entry.get("漂移申请编号"))
            if app is None:
                round_refs = (
                    kwargs.get("round_ids") or kwargs.get("roundIds") or kwargs.get("selected_rounds")
                    or [part.strip() for part in str(entry.get("关联轮次", "")).replace("／", "/").split("/") if part.strip()]
                )
                created = drift_board_service.create_application({
                    "sample_entry_id": entry["id"],
                    "experiment_code": entry.get("实验编码") or kwargs.get("experiment_code"),
                    "round_ids": round_refs,
                    "create_sample_row": False,
                })
                if not created.get("ok"):
                    return created
                app = created["application"]
            return drift_board_service.claim_application(app["id"], resolution, **kwargs)

        app = drift_board_service.get_application(batch_or_app_id)
        if app is None:
            return {"ok": False, "status_code": 404, "message": f"样本核对批次/申请 {batch_or_app_id} 不存在"}
        return drift_board_service.claim_application(app["id"], resolution, **kwargs)

    def review_with_drift(self, batch_or_app_id: Any) -> dict[str, Any]:
        app = drift_board_service.find_application_by_sample_entry(batch_or_app_id)
        if app is None:
            app = drift_board_service.get_application(batch_or_app_id)
        if app is None:
            return {"ok": False, "status_code": 404, "message": f"样本核对申请 {batch_or_app_id} 不存在"}
        return drift_board_service.review_application(app["id"])

    def trace_report_rounds(self, batch_or_app_id: Any) -> dict[str, Any]:
        return drift_board_service.trace_sample_batch(batch_or_app_id)

    reopen_application = trace_report_rounds

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(drift_board_service, name)

    def run_action_detailed(
        self,
        entry_id: int,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = payload or {}
        values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
        merged = {**payload, **values}
        entry = store.find(self.MODULE, entry_id)

        if action in {
            "领取漂移看板数据", "领取分组漂移看板", "领取分组漂移看板数据",
            "领取漂移数据", "处理领取冲突", "claim_drift", "claim-drift",
        } or ("领取" in action and ("漂移" in action or "看板" in action)):
            result = self.claim_drift_board(
                entry_id,
                merged.get("resolution") or merged.get("choice") or merged.get("adopt")
                or merged.get("accept") or merged.get("use") or merged.get("采用版次") or merged.get("选择"),
                actor=merged.get("actor"),
                round_ids=merged.get("round_ids") or merged.get("roundIds") or merged.get("selected_rounds"),
            )
            result["entry"] = result.get("application") or result.get("entry") or entry
            return result

        if action in {
            "漂移复核", "使用漂移看板复核", "完成漂移复核",
            "根据漂移看板复核", "根据两份确认样本复核", "样本核对复核",
        } or ("复核" in action and "漂移" in action):
            result = self.review_with_drift(entry_id)
            result["entry"] = result.get("application") or entry
            return result

        if action in {
            "回查轮次人数", "回查报告轮次", "回查报告使用的轮次与组内人数",
            "复查实际采用两轮", "重开原申请", "trace",
        } or ("回查" in action and ("轮次" in action or "报告" in action)) or ("重开" in action and "申请" in action):
            result = self.trace_report_rounds(entry_id)
            result["entry"] = result.get("application") or entry
            return result

        if action == "执行核对":
            linked_app = drift_board_service.find_application_by_sample_entry(entry_id)
            if linked_app is not None or entry.get("漂移申请编号"):
                result = self.run_check(entry_id)
                result["entry"] = store.find(self.MODULE, entry_id)
                return result
            # 未接入漂移看板的旧通用批次保持脚手架原有的状态流转契约。
            return super().run_action_detailed(entry_id, action, payload)

        return super().run_action_detailed(entry_id, action, payload)
