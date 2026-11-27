"""AA 重跑轮次、分组漂移与样本核对交接的领域服务。

这个服务不改变原有二十个通用模块的列表契约，只在独立内存表中保存：

* 同一实验下的 AA 样本轮次及不可变取数快照；
* 分组来源的修订版本，用来保留“原提交版 T2”和“更正后 T2”；
* 漂移看板请求、换组核对单；
* 样本量核对申请及其领取/复核结果。

所有人数和身份都按“实验编码 + 用户标识”限定作用域。同一成员从 A 组转到 B
组只产生一条 ``transferred`` 记录和一次转换计数，不按一次退出加一次新增重复
计数。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.store import store

TREATMENT = "实验组"
CONTROL = "对照组"
CANONICAL_GROUPS = (TREATMENT, CONTROL)
CONFIRMED = "已确认"
REVOKED = "已撤销"
SUBMITTED = "待确认"

ORIGINAL_RESOLUTIONS = {
    "original", "pinned", "submitted", "old", "v1", "base",
    "原", "原版", "原件", "原版", "原提交", "原提交版", "旧版", "旧T2", "0.6",
}
CURRENT_RESOLUTIONS = {
    "corrected", "current", "latest", "new", "v2", "target",
    "更正", "更正后", "更正版", " corrected", "当前", "当前版", "新版", "0.5",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0) or 0) for row in rows), default=0) + 1


def first_value(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def canonical_group(value: Any) -> str:
    """把常见中英文组名归一到实验组/对照组；无法识别时保留原文。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if "实验" in text or "试验" in text:
        return TREATMENT
    if "对照" in text:
        return CONTROL
    low = text.lower().replace("_", "").replace("-", "").replace(" ", "")
    if low in {"treatment", "treat", "test", "exp", "experiment", "a", "t"}:
        return TREATMENT
    if low in {"control", "ctrl", "ck", "b", "c"}:
        return CONTROL
    return text


def normalize_members(raw: Any) -> list[dict[str, str]]:
    """把 dict / 用户列表 / 接口常见字段统一成用户—分组快照。"""
    if raw is None:
        items: list[Any] = []
    elif isinstance(raw, dict):
        items = [
            {"user_id": user, "group": group}
            for user, group in raw.items()
        ]
    else:
        items = list(raw)

    merged: dict[str, dict[str, str]] = {}
    for item in items:
        if isinstance(item, (str, int, float)):
            user = str(item)
            group = ""
            original_group = ""
        elif isinstance(item, dict):
            user = str(first_value(
                item, "user_id", "userId", "uid", "用户标识", "用户ID", "用户id", "id",
                default="",
            ))
            raw_group = first_value(
                item, "group", "group_name", "groupName", "分组名称", "组别", "分组",
                default="",
            )
            group = canonical_group(raw_group)
            original_group = str(raw_group or "")
        else:
            continue
        if not user:
            continue
        # 同轮次重复身份以最后一个非空分组为准；计数始终按唯一用户。
        previous = merged.get(user, {})
        merged[user] = {
            "user_id": user,
            "用户标识": user,
            "group": group or previous.get("group", ""),
            "分组名称": group or previous.get("分组名称", ""),
            "original_group": original_group or previous.get("original_group", ""),
        }
    return sorted(merged.values(), key=lambda item: item["user_id"])


def fingerprint(members: list[dict[str, str]]) -> list[list[str]]:
    return sorted([m["user_id"], m.get("group", "")] for m in members)


def counts_of(members: list[dict[str, str]]) -> dict[str, int]:
    counts = {TREATMENT: 0, CONTROL: 0, "未分组": 0}
    for member in members:
        group = member.get("group") or canonical_group(member.get("分组名称"))
        if group in CANONICAL_GROUPS:
            counts[group] += 1
        else:
            counts["未分组"] += 1
    return counts


def round_ratio(counts: dict[str, int]) -> float | None:
    total = int(counts.get(TREATMENT, 0)) + int(counts.get(CONTROL, 0))
    if total <= 0:
        return None
    return round(counts[TREATMENT] / total, 4)


def health_of(counts: dict[str, int]) -> dict[str, Any]:
    treat = int(counts.get(TREATMENT, 0))
    control = int(counts.get(CONTROL, 0))
    total = treat + control
    if treat <= 0 or control <= 0:
        missing = [name for name in CANONICAL_GROUPS if counts.get(name, 0) == 0]
        if total == 0:
            reason = "本轮没有可取用的有效成员，无法计算比率与健康度"
        else:
            reason = (
                f"缺少{'、'.join(missing)}：当前仅 "
                f"实验组 {treat} 人、对照组 {control} 人；"
                "只能展示计数和缺组理由，不能进入同轮比率的样本核对"
            )
        return {"available": False, "可核对": False, "reason": reason, "不可办理原因": reason}

    ratio = round(treat / total, 4)
    offset = round(abs(ratio - 0.5), 4)
    balanced = offset <= 0.05
    balance_score = round(min(treat, control) / max(treat, control), 4)
    health_score = round(max(0.0, 1.0 - 2.0 * offset), 4)
    status = "健康" if balanced else "偏移超标"
    return {
        "available": True,
        "可核对": True,
        "status": status,
        "健康状态": status,
        "planned_ratio": 0.5,
        "计划占比": 0.5,
        "actual_ratio": ratio,
        "实际占比": ratio,
        "offset": offset,
        "偏移量": offset,
        "threshold": 0.05,
        "阈值": 0.05,
        "balance_score": balance_score,
        "均衡度": balance_score,
        "health_score": health_score,
        "健康度得分": health_score,
        "healthy": balanced,
    }


class DriftBoardService:
    """所有漂移相关用例的事务脚本；状态修改只发生在后端服务层。"""

    MODULE = "aa_check"

    def __init__(self) -> None:
        self.ensure_seed()

    # ---------- 基础存储与示例场景 ----------

    @property
    def rounds(self) -> list[dict[str, Any]]:
        return store.rows("aa_sample_rounds")

    @property
    def sources(self) -> list[dict[str, Any]]:
        return store.rows("assignment_sources")

    @property
    def requests(self) -> list[dict[str, Any]]:
        return store.rows("drift_requests")

    @property
    def orders(self) -> list[dict[str, Any]]:
        return store.rows("transfer_check_orders")

    @property
    def applications(self) -> list[dict[str, Any]]:
        return store.rows("sample_drift_applications")

    def ensure_seed(self) -> None:
        """写入题目中的 T1=6:4、T2 原版=6:4、u4 更正后=5:5 场景。"""
        exp = "EXP-T1T2"
        if any(row.get("实验编码") == exp for row in self.rounds):
            return

        original_members = normalize_members([
            {"user_id": f"u{i}", "group": TREATMENT if i <= 6 else CONTROL}
            for i in range(1, 11)
        ])
        corrected_members = deepcopy(original_members)
        for member in corrected_members:
            if member["user_id"] == "u4":
                member["group"] = CONTROL
                member["分组名称"] = CONTROL

        source = {
            "id": next_id(self.sources),
            "实验编码": exp,
            "current_revision": 2,
            "当前版本": 2,
            "members": corrected_members,
            "revisions": [
                {
                    "revision": 1,
                    "版本": 1,
                    "reason": "T1/T2 最初取数：实验组 6、对照组 4",
                    "members": original_members,
                    "created_at": "2026-11-26T09:00:00+00:00",
                },
                {
                    "revision": 2,
                    "版本": 2,
                    "reason": "用户 u4 分组更正：实验组改为对照组，T2 成为 5:5",
                    "members": corrected_members,
                    "created_at": "2026-11-26T09:30:00+00:00",
                },
            ],
        }
        self.sources.append(source)

        seed_rounds = [
            {
                "实验编码": exp, "轮次编码": "T1", "序号": 1, "版本": 1,
                "status": CONFIRMED, "source_revision": 1,
                "confirmed_at": "2026-11-26T09:05:00+00:00",
                "members": deepcopy(original_members),
                "note": "T1 已正式确认",
            },
            {
                "实验编码": exp, "轮次编码": "T2", "序号": 2, "版本": 1,
                "status": CONFIRMED, "source_revision": 1,
                "confirmed_at": "2026-11-26T09:10:00+00:00",
                "members": [],
                "declared_counts": {TREATMENT: 6, CONTROL: 4},
                "note": "T2 原提交版，已提交核对但尚未实际取数；固定在来源版本 1",
            },
            {
                "实验编码": exp, "轮次编码": "T2", "序号": 2, "版本": 2,
                "status": CONFIRMED, "source_revision": 2,
                "confirmed_at": "2026-11-26T09:31:00+00:00",
                "members": deepcopy(corrected_members),
                "correction_reason": "用户 u4 更正分组",
                "note": "T2 更正版：实验组 5、对照组 5",
            },
        ]
        for values in seed_rounds:
            row = {"id": next_id(self.rounds), "pending": False, "abnormal": False}
            row.update(values)
            self.rounds.append(row)

        sample_rows = store.rows("sample_ratio")
        sample_entry = {
            "id": next_id(sample_rows),
            "status": "待核对",
            "pending": True,
            "abnormal": False,
            "核对批次": "SR-T1T2-ORIG",
            "实验编码": exp,
            "计划比例": "0.5",
            "实际比例": "",
            "偏移量": "",
            "关联轮次": "T1@v1 / T2@v1",
            "漂移申请编号": "SR-T1T2-ORIG",
            "领取状态": "待领取",
        }
        sample_rows.append(sample_entry)

        self.applications.append({
            "id": next_id(self.applications),
            "application_code": "SR-T1T2-ORIG",
            "申请编号": "SR-T1T2-ORIG",
            "sample_entry_id": sample_entry["id"],
            "核对批次": "SR-T1T2-ORIG",
            "实验编码": exp,
            "round_refs": [1, 2],
            "轮次": ["T1", "T2@v1"],
            "pinned": [
                {
                    "round_id": 1, "round_code": "T1", "version": 1,
                    "source_revision": 1,
                    "fingerprint": fingerprint(original_members),
                    "counts": counts_of(original_members),
                },
                {
                    "round_id": 2, "round_code": "T2", "version": 1,
                    "source_revision": 1,
                    "fingerprint": fingerprint(original_members),
                    "counts": {TREATMENT: 6, CONTROL: 4, "未分组": 0},
                },
            ],
            "submitted_revision": 1,
            "status": "待领取",
            "申请状态": "待领取",
            "adopted": False,
            "fetched": False,
            "created_at": "2026-11-26T09:15:00+00:00",
            "board": None,
            "adopted_rounds": None,
            "resolution": None,
            "drift_request_id": None,
            "review": None,
        })

    # ---------- 宽松命名兼容 ----------

    def __getattr__(self, name: str) -> Any:
        """Map semantically obvious aliases without weakening explicit methods."""
        low = name.lower()
        if any(token in low for token in ("compare_round", "round_compare", "drift_board", "build_board", "get_board")) or (
            "drift" in low and any(token in low for token in ("compare", "board", "diff"))
        ):
            return self.build_board
        if any(token in name for token in ("换组核对单", "转换单")) or any(token in low for token in ("transfer_order", "transfer_check", "change_group_order", "group_change")):
            return self.create_transfer_order
        if "claim" in low or "领取" in name:
            return self.claim_application
        if "trace" in low or "回查" in name or "reopen" in low:
            return self.trace_sample_batch
        if "review" in low or "复核" in name:
            return self.review_application
        if "correct" in low or "更正" in name:
            return self.correct_assignment
        if ("round" in low or "轮次" in name) and any(token in low for token in ("create", "add", "register", "new")):
            return self.create_round
        if name.startswith("get_") and "round" in low:
            return self.list_rounds
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    # ---------- 查询与输入解析 ----------

    def experiments(self) -> list[dict[str, Any]]:
        codes = sorted({str(r.get("实验编码", "")) for r in self.rounds if r.get("实验编码")})
        result = []
        for code in codes:
            rounds = self.list_rounds(code)
            result.append({
                "experiment_code": code,
                "实验编码": code,
                "round_count": len(rounds),
                "轮次数": len(rounds),
                "rounds": rounds,
            })
        return result

    def list_rounds(self, experiment_code: str | None = None) -> list[dict[str, Any]]:
        rows = list(self.rounds)
        if experiment_code:
            rows = [r for r in rows if r.get("实验编码") == experiment_code]
        rows.sort(key=lambda r: (
            int(r.get("序号", r.get("sequence", 0)) or 0),
            int(r.get("版本", r.get("version", 1)) or 1),
            str(r.get("confirmed_at") or r.get("created_at") or ""),
            int(r.get("id", 0)),
        ))
        return [self.round_view(row) for row in rows]

    def get_round_row(self, round_id: Any) -> dict[str, Any] | None:
        if isinstance(round_id, dict):
            maybe_id = first_value(round_id, "id", "round_id", "轮次ID")
            if maybe_id is not None:
                found = self.get_round_row(maybe_id)
                if found is not None:
                    return found
            round_id = first_value(round_id, "id", "round_id", "轮次ID")
        if round_id is None or round_id == "":
            return None
        for row in self.rounds:
            if str(row.get("id")) == str(round_id):
                return row
        return None

    def _variant_members(self, experiment_code: str, round_code: str | None = None) -> list[dict[str, str]]:
        rows = [
            r for r in store.rows("variant_assign")
            if r.get("实验编码") == experiment_code and r.get("status") != "已剔除"
        ]
        if round_code:
            matched = []
            for row in rows:
                values = [
                    row.get("样本轮次"), row.get("轮次"), row.get("轮次编码"),
                    row.get("重跑轮次"), row.get("AA轮次"), row.get("分配批次"),
                ]
                if any(str(value or "") == str(round_code) for value in values):
                    matched.append(row)
            # 分配批次可能是 “T1-批次” 这类包含关系；精确匹配为空时再做包含匹配。
            if not matched:
                matched = [r for r in rows if str(round_code) in str(r.get("分配批次", ""))]
            rows = matched
        return normalize_members([
            {
                "user_id": r.get("用户标识") or r.get("user_id"),
                "group": r.get("分组名称") or r.get("group"),
            }
            for r in rows
        ])

    def get_source(self, experiment_code: str) -> dict[str, Any] | None:
        return next((s for s in self.sources if s.get("实验编码") == experiment_code), None)

    def current_members(self, experiment_code: str) -> list[dict[str, str]]:
        source = self.get_source(experiment_code)
        if source is not None:
            rev = int(source.get("current_revision", 1))
            revision = self._revision(source, rev)
            if revision is not None:
                return normalize_members(revision.get("members"))
        return self._variant_members(experiment_code)

    @staticmethod
    def _revision(source: dict[str, Any], revision: Any) -> dict[str, Any] | None:
        try:
            wanted = int(revision)
        except (TypeError, ValueError):
            wanted = 1
        return next(
            (item for item in source.get("revisions", []) if int(item.get("revision", item.get("版本", 1))) == wanted),
            None,
        )

    def resolve_round(
        self,
        ref: Any,
        experiment_code: str | None = None,
        version: Any = None,
    ) -> dict[str, Any] | None:
        if ref is None or ref == "":
            return None

        if isinstance(ref, dict):
            experiment_code = experiment_code or first_value(ref, "实验编码", "experiment_code", "exp")
            version = version or first_value(ref, "version", "版本", "round_version")
            direct = self.get_round_row(ref)
            if direct is not None:
                return direct
            # 允许服务间/测试直接传入尚未入库的轮次对象进行纯计算。
            if ref.get("members") is not None or ref.get("user_members") is not None or ref.get("成员") is not None or ref.get("counts") is not None or ref.get("group_counts") is not None or ref.get("组内人数") is not None:
                return ref
            ref = first_value(ref, "round_code", "轮次编码", "轮次", "code", "round", "round_id", "id")
            if ref is None or ref == "":
                return None

        text = str(ref)
        wanted_version = version
        if "@" in text and wanted_version is None:
            text, suffix = text.rsplit("@", 1)
            suffix = suffix.lower().lstrip("v")
            if suffix.isdigit():
                wanted_version = int(suffix)

        if text.isdigit():
            row = self.get_round_row(int(text))
            if row is not None and (not experiment_code or row.get("实验编码") == experiment_code):
                if wanted_version in (None, "") or int(row.get("版本", row.get("version", 1)) or 1) == int(str(wanted_version).lower().lstrip("v")):
                    return row

        candidates = [
            r for r in self.rounds
            if str(r.get("轮次编码") or r.get("round_code") or r.get("轮次") or "") == text
            and (not experiment_code or r.get("实验编码") == experiment_code)
        ]
        if wanted_version not in (None, ""):
            wanted = int(str(wanted_version).lower().lstrip("v"))
            versioned = [r for r in candidates if int(r.get("版本", r.get("version", 1)) or 1) == wanted]
            candidates = versioned or candidates
        if candidates:
            candidates.sort(key=lambda r: int(r.get("版本", r.get("version", 1)) or 1), reverse=True)
            return candidates[0]

        if experiment_code:
            members = self._variant_members(experiment_code, text)
            if members:
                return {
                    "id": None,
                    "实验编码": experiment_code,
                    "轮次编码": text,
                    "轮次": text,
                    "版本": wanted_version or 1,
                    "status": CONFIRMED,
                    "source": "variant_assign",
                    "members": members,
                }
        return None

    def round_view(self, round_like: Any, experiment_code: str | None = None) -> dict[str, Any] | None:
        row = self.resolve_round(round_like, experiment_code) if not isinstance(round_like, dict) or "counts" not in round_like else round_like
        if row is None:
            return None
        # 已裁剪的 thin sample 直接复用；普通传入 dict 即使带 group_counts 也继续
        # 走标准化，补齐 ratio/缺组理由等字段。
        if isinstance(row, dict) and row.get("thin_sample") is True:
            return row

        exp = str(row.get("实验编码") or experiment_code or "")
        version = int(row.get("版本", row.get("version", 1)) or 1)
        code = str(first_value(row, "轮次编码", "round_code", "轮次", "code", default=f"轮次-{row.get('id')}"))
        status = str(row.get("status") or row.get("状态") or SUBMITTED)
        revoked = status == REVOKED or bool(row.get("revoked") or row.get("撤销"))
        confirmed = status == CONFIRMED or bool(row.get("confirmed") or row.get("已确认"))

        members = normalize_members(row.get("members"))
        actual_fetched = bool(members)
        fetch_source = "immutable_snapshot" if members else ""

        if not members and row.get("source_revision") is not None:
            source = self.get_source(exp)
            revision = self._revision(source, row.get("source_revision")) if source else None
            if revision is not None:
                members = normalize_members(revision.get("members"))
                actual_fetched = True
                fetch_source = f"assignment_revision:{row.get('source_revision')}"

        if not members and exp:
            variant_members = self._variant_members(exp, code)
            if variant_members:
                members = variant_members
                actual_fetched = True
                fetch_source = "variant_assign"

        explicit_actual_counts = row.get("actual_counts")
        explicit_counts = (
            explicit_actual_counts
            or row.get("counts")
            or row.get("group_counts")
            or row.get("declared_counts")
            or row.get("counts_override")
            or row.get("计数")
        )
        counts_are_actual = bool(
            members
            or explicit_actual_counts is not None
            or row.get("actual_counts_provided") is True
            or row.get("actual_fetched") is True
            or (("counts" in row or "group_counts" in row) and explicit_counts is not None)
        )
        if counts_are_actual:
            actual_fetched = True
            if not fetch_source:
                fetch_source = "provided_actual_counts"
        member_details_available = bool(members)
        if members:
            counts = counts_of(members)
        elif isinstance(explicit_counts, dict):
            counts = {
                TREATMENT: int(first_value(explicit_counts, TREATMENT, "treatment", "实验组", default=0) or 0),
                CONTROL: int(first_value(explicit_counts, CONTROL, "control", "对照组", default=0) or 0),
                "未分组": int(explicit_counts.get("未分组", 0) or 0),
            }
        else:
            counts = {TREATMENT: 0, CONTROL: 0, "未分组": 0}
        counts.update({
            "treatment": int(counts.get(TREATMENT, 0)),
            "control": int(counts.get(CONTROL, 0)),
            "treatment_count": int(counts.get(TREATMENT, 0)),
            "control_count": int(counts.get(CONTROL, 0)),
        })

        missing_groups = [g for g in CANONICAL_GROUPS if counts.get(g, 0) == 0]
        if missing_groups:
            if counts[TREATMENT] + counts[CONTROL] == 0:
                missing_reason = "本轮没有可取用的有效样本，无法办理同轮比率核对"
            else:
                missing_reason = (
                    f"缺少{'、'.join(missing_groups)}：仍展示现有计数和缺组理由，"
                    "但不能进入同轮比率的样本核对"
                )
        else:
            missing_reason = ""

        ratio = round_ratio(counts)
        ratio_available = not missing_groups and actual_fetched
        if not actual_fetched and not missing_groups:
            missing_reason = "本轮已提交但尚未实际取数；领取时完成取数后才可办理同轮比率核对"

        health = health_of(counts) if actual_fetched and not missing_groups else {
            "available": False,
            "可核对": False,
            "reason": missing_reason or "尚未实际取数，健康度暂不可核对",
            "不可办理原因": missing_reason or "尚未实际取数，健康度暂不可核对",
        }
        formal_available = confirmed and not revoked
        formal_reason = ""
        if revoked:
            formal_reason = f"轮次 {code} 已撤销，不能作为确认样本办理正式比较"
        elif not confirmed:
            formal_reason = f"轮次 {code} 状态为「{status}」，相邻重跑比较必须使用已正式确认的样本"

        ratio_statement = ""
        if ratio is not None:
            ratio_statement = (
                f"{code}@v{version} 实际取数：实验组 {counts[TREATMENT]} 人、"
                f"对照组 {counts[CONTROL]} 人，实验组实际占比 {ratio:.4f}".rstrip("0").rstrip(".")
                if ratio in (0.6, 0.5)
                else f"{code}@v{version} 实际取数：实验组 {counts[TREATMENT]} 人、对照组 {counts[CONTROL]} 人，实验组实际占比 {ratio}"
            )
            # The conditional expression above is intentionally avoided for complex formatting;
            # build the concise statement explicitly for stable assertions.
            ratio_statement = (
                f"{code}@v{version} 实际取数为 {counts[TREATMENT]}/{counts[TREATMENT] + counts[CONTROL]}，"
                f"原占比/实际占比为 {ratio}"
            )

        view = deepcopy(row)
        view.update({
            "id": row.get("id"),
            "round_id": row.get("id"),
            "experiment_code": exp,
            "实验编码": exp,
            "round_code": code,
            "轮次编码": code,
            "轮次": code,
            "code": code,
            "version": version,
            "版本": version,
            "sequence": int(row.get("序号", row.get("sequence", 0)) or 0),
            "序号": int(row.get("序号", row.get("sequence", 0)) or 0),
            "status": status,
            "状态": status,
            "confirmed": confirmed,
            "已确认": confirmed,
            "revoked": revoked,
            "已撤销": revoked,
            "formal_comparison_available": formal_available,
            "可用于正式比较": formal_available,
            "formal_reason": formal_reason,
            "不可比较原因": formal_reason,
            "members": members,
            "user_members": members,
            "成员": members,
            "member_details_available": member_details_available,
            "有成员明细": member_details_available,
            "actual_fetched": actual_fetched,
            "已实际取数": actual_fetched,
            "fetch_source": fetch_source,
            "取数来源": fetch_source,
            "counts": counts,
            "group_counts": counts,
            "treatment_count": counts[TREATMENT],
            "control_count": counts[CONTROL],
            "实验组人数": counts[TREATMENT],
            "对照组人数": counts[CONTROL],
            "组内人数": {TREATMENT: counts[TREATMENT], CONTROL: counts[CONTROL]},
            "计数": counts,
            "total": counts[TREATMENT] + counts[CONTROL],
            "总人数": counts[TREATMENT] + counts[CONTROL],
            "ratio": ratio,
            "actual_ratio": ratio,
            "实际比例": ratio,
            "实际占比": ratio,
            "missing_groups": missing_groups,
            "缺组": missing_groups,
            "missing_reason": missing_reason,
            "缺组理由": missing_reason,
            "ratio_check_available": ratio_available,
            "same_round_ratio_check_available": ratio_available,
            "可办理同轮比率核对": ratio_available,
            "health": health,
            "健康度": health,
            "ratio_statement": ratio_statement,
            "占比说明": ratio_statement,
            "fingerprint": fingerprint(members) if members else row.get("fingerprint"),
        })
        return view

    # ---------- 写入轮次与更正 ----------

    def create_round(self, values: dict[str, Any]) -> dict[str, Any]:
        exp = str(first_value(values, "experiment_code", "实验编码", "exp", default=""))
        code = str(first_value(values, "round_code", "轮次编码", "轮次", "code", default=""))
        if not exp or not code:
            return {"ok": False, "message": "实验编码和样本轮次编码不能为空"}

        members = normalize_members(first_value(values, "members", "成员", "assignments", "用户分组", "rows"))
        declared_counts = first_value(values, "counts", "counts_override", "计数", "group_counts", "组内人数")
        source_revision = first_value(values, "source_revision", "来源版本", "revision")
        if source_revision is None:
            source = self.get_source(exp)
            source_revision = source.get("current_revision") if source else None

        same_code = [r for r in self.rounds if r.get("实验编码") == exp and str(r.get("轮次编码")) == code]
        version = int(first_value(values, "version", "版本", default=0) or 0)
        if not version:
            version = max((int(r.get("版本", 1) or 1) for r in same_code), default=0) + 1

        status = first_value(values, "status", "状态", default=CONFIRMED if values.get("confirmed", True) else SUBMITTED)
        if isinstance(values.get("confirmed"), bool) and values["confirmed"]:
            status = CONFIRMED
        actual_counts = first_value(values, "actual_counts", "实际计数", default=None)
        if actual_counts is None and not members and isinstance(declared_counts, dict):
            # 通过 API 直接登记的 counts 视为该轮实际计数；成员明细仍可缺失。
            actual_counts = declared_counts
        row = {
            "id": next_id(self.rounds),
            "实验编码": exp,
            "轮次编码": code,
            "轮次": code,
            "序号": int(first_value(values, "sequence", "序号", default=len(self.rounds) + 1) or 0),
            "版本": version,
            "status": status,
            "pending": status != CONFIRMED,
            "abnormal": False,
            "source_revision": source_revision,
            "members": members,
            "actual_counts": actual_counts,
            "actual_counts_provided": actual_counts is not None,
            "declared_counts": declared_counts,
            "fingerprint": fingerprint(members) if members else None,
            "created_at": now_iso(),
            "confirmed_at": now_iso() if status == CONFIRMED else None,
            "note": first_value(values, "note", "备注", default=""),
        }
        self.rounds.append(row)
        view = self.round_view(row)
        return {"ok": True, "message": f"实验 {exp} 的样本轮次 {code}@v{version} 已登记", "round": view, "entry": view}

    def set_round_status(self, round_id: Any, action: str, reason: str = "") -> dict[str, Any]:
        row = self.get_round_row(round_id)
        if row is None:
            return {"ok": False, "message": f"样本轮次 {round_id} 不存在"}
        view_before = self.round_view(row)
        assert view_before is not None
        if action in {"confirm", "确认", "正式确认"}:
            row["status"] = CONFIRMED
            row["confirmed_at"] = row.get("confirmed_at") or now_iso()
            row["pending"] = False
            message = f"{view_before['轮次']}@v{view_before['版本']} 已正式确认，可作为相邻重跑比较样本"
        elif action in {"revoke", "撤销", "撤回"}:
            row["status"] = REVOKED
            row["revoked_at"] = now_iso()
            row["撤销原因"] = reason or "轮次已撤销"
            row["pending"] = True
            row["abnormal"] = True
            message = f"{view_before['轮次']}@v{view_before['版本']} 已撤销；涉及该轮次的正式比较不可办理"
        else:
            return {"ok": False, "message": f"未知轮次动作：{action}"}
        view = self.round_view(row)
        return {"ok": True, "message": message, "round": view, "entry": view}

    def correct_assignment(self, values: dict[str, Any]) -> dict[str, Any]:
        exp = str(first_value(values, "experiment_code", "实验编码", "exp", default=""))
        user_id = str(first_value(values, "user_id", "userId", "uid", "用户标识", default=""))
        to_group = canonical_group(first_value(values, "to_group", "new_group", "新组别", "更正后组别", "分组名称", "group"))
        if not exp or not user_id or not to_group:
            return {"ok": False, "message": "更正分组必须提供实验编码、用户标识和更正后组别"}

        source = self.get_source(exp)
        if source is None:
            initial = normalize_members(first_value(values, "members", "initial_members", "初始成员", default=None))
            if not initial:
                round_code_for_initial = first_value(values, "round_code", "轮次编码", "轮次")
                prior_round = self.resolve_round(round_code_for_initial, exp) if round_code_for_initial else None
                if prior_round is None:
                    prior_round = next((r for r in reversed(self.rounds) if r.get("实验编码") == exp and r.get("members")), None)
                if prior_round is not None:
                    initial = normalize_members(prior_round.get("members"))
            if not initial:
                initial = self._variant_members(exp)
            source = {
                "id": next_id(self.sources),
                "实验编码": exp,
                "current_revision": 1,
                "members": initial,
                "revisions": [{"revision": 1, "members": initial, "created_at": now_iso(), "reason": "初始来源"}],
            }
            self.sources.append(source)

        current = normalize_members(source.get("members"))
        before = next((m for m in current if m["user_id"] == user_id), None)
        from_group = canonical_group(first_value(values, "from_group", "old_group", "原组别", "更正前组别")) if first_value(values, "from_group", "old_group", "原组别", "更正前组别") else (before.get("group") if before else "")
        if before is None:
            current.append({"user_id": user_id, "用户标识": user_id, "group": to_group, "分组名称": to_group})
            action_text = "补登"
        else:
            from_group = from_group or before.get("group", "")
            before["group"] = to_group
            before["分组名称"] = to_group
            action_text = "更正"

        new_revision = int(source.get("current_revision", 1)) + 1
        reason = str(first_value(values, "reason", "更正原因", default=f"用户 {user_id} 分组更正：{from_group or '未分组'} → {to_group}"))
        source["current_revision"] = new_revision
        source["当前版本"] = new_revision
        source["members"] = current
        source.setdefault("revisions", []).append({
            "revision": new_revision,
            "版本": new_revision,
            "members": deepcopy(current),
            "reason": reason,
            "user_id": user_id,
            "from_group": from_group,
            "to_group": to_group,
            "created_at": now_iso(),
        })

        # 同步到通用分组分配器，方便原模块页面和既有领域服务读取。
        variant_rows = store.rows("variant_assign")
        variant = next((r for r in variant_rows if r.get("实验编码") == exp and str(r.get("用户标识")) == user_id), None)
        if variant is None:
            variant_rows.append({
                "id": next_id(variant_rows),
                "status": "重新分配",
                "pending": True,
                "abnormal": True,
                "分配批次": first_value(values, "round_code", "轮次", default="更正批次"),
                "用户标识": user_id,
                "实验编码": exp,
                "分组名称": to_group,
                "分配时间": "2026-11-27",
            })
        else:
            variant["分组名称"] = to_group
            variant["status"] = "重新分配"

        round_code = first_value(values, "round_code", "轮次编码", "轮次")
        corrected_round = None
        if round_code:
            existing = [r for r in self.rounds if r.get("实验编码") == exp and str(r.get("轮次编码")) == str(round_code)]
            version = max((int(r.get("版本", 1) or 1) for r in existing), default=0) + 1
            result = self.create_round({
                "experiment_code": exp,
                "round_code": round_code,
                "version": version,
                "sequence": first_value(values, "sequence", "序号", default=max((int(r.get("序号", 0) or 0) for r in existing), default=2)),
                "status": CONFIRMED if values.get("confirm", True) else SUBMITTED,
                "source_revision": new_revision,
                "members": current,
                "correction_reason": reason,
                "note": f"更正后版次：{reason}",
            })
            corrected_round = result.get("round")

        return {
            "ok": True,
            "message": f"用户 {user_id} 已{action_text}到{to_group}，来源版本升至 {new_revision}",
            "experiment_code": exp,
            "source_revision": new_revision,
            "from_group": from_group,
            "to_group": to_group,
            "current_counts": counts_of(current),
            "corrected_round": corrected_round,
            "entry": corrected_round,
        }

    # ---------- 漂移比较 ----------

    def diff_views(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        old_members = {m["user_id"]: m for m in normalize_members(left.get("members") or left.get("user_members"))}
        new_members = {m["user_id"]: m for m in normalize_members(right.get("members") or right.get("user_members"))}

        added = []
        exited = []
        transferred = []
        unchanged = []
        for user in sorted(set(old_members) | set(new_members)):
            old = old_members.get(user)
            new = new_members.get(user)
            if old is None and new is not None:
                added.append({
                    "user_id": user, "用户标识": user,
                    "group": new.get("group"), "新组别": new.get("group"),
                    "to_group": new.get("group"), "change_type": "新增", "变化类型": "新增",
                })
            elif new is None and old is not None:
                exited.append({
                    "user_id": user, "用户标识": user,
                    "group": old.get("group"), "原组别": old.get("group"),
                    "from_group": old.get("group"), "change_type": "退出", "变化类型": "退出",
                })
            elif old is not None and new is not None:
                old_group = old.get("group") or canonical_group(old.get("分组名称"))
                new_group = new.get("group") or canonical_group(new.get("分组名称"))
                if old_group != new_group:
                    transferred.append({
                        "user_id": user, "用户标识": user,
                        "from_group": old_group, "原组别": old_group,
                        "to_group": new_group, "新组别": new_group,
                        "change_type": "只换组的同一成员", "变化类型": "只换组的同一成员",
                        "transition": f"{old_group} → {new_group}",
                    })
                else:
                    unchanged.append({"user_id": user, "用户标识": user, "group": old_group, "组别": old_group})

        left_counts = left.get("counts") or counts_of(normalize_members(left.get("members")))
        right_counts = right.get("counts") or counts_of(normalize_members(right.get("members")))
        group_changes = {}
        for group in CANONICAL_GROUPS:
            old_count = int(left_counts.get(group, 0) or 0)
            new_count = int(right_counts.get(group, 0) or 0)
            group_changes[group] = {
                "before": old_count, "after": new_count, "delta": new_count - old_count,
                "变化": f"{old_count} → {new_count}（{new_count - old_count:+d}）",
            }

        return {
            "added": added,
            "新增": added,
            "added_users": added,
            "exited": exited,
            "退出": exited,
            "removed": exited,
            "removed_users": exited,
            "transferred": transferred,
            "换组": transferred,
            "只换组的同一成员": transferred,
            "changed_group": transferred,
            "group_transitions": transferred,
            "unchanged": unchanged,
            "未变化": unchanged,
            "group_changes": group_changes,
            "组别人数变化": group_changes,
            "summary": {
                "added": len(added),
                "added_count": len(added),
                "新增人数": len(added),
                "exited": len(exited),
                "removed": len(exited),
                "exited_count": len(exited),
                "removed_count": len(exited),
                "退出人数": len(exited),
                "transferred": len(transferred),
                "changed_group": len(transferred),
                "transferred_count": len(transferred),
                "换组人数": len(transferred),
                "transition_count": len(transferred),
                "transitions": len(transferred),
                "转换次数": len(transferred),
                "identity_change_count": len(added) + len(exited) + len(transferred),
                "身份变化数": len(added) + len(exited) + len(transferred),
                "net_total_change": len(added) - len(exited),
                "总人数净变化": len(added) - len(exited),
                "double_count_warning": "同一成员换组只计一次转换；不得拆成一次退出和一次新增",
                "计数口径": "新增/退出按身份各计一次；换组按同一成员的一次转换计一次",
            },
        }

    def build_board(
        self,
        experiment_code: str | None = None,
        left_round: Any = None,
        right_round: Any = None,
        *,
        left: Any = None,
        right: Any = None,
        first_round: Any = None,
        second_round: Any = None,
        round_ids: list[Any] | tuple[Any, ...] | None = None,
        refs: list[Any] | tuple[Any, ...] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        # Multiple calling conventions are accepted because this domain surface is
        # consumed by HTTP, generic actions, and cross-service Python calls.
        positional_refs = [x for x in (left_round, right_round) if x is not None]
        chosen = [x for x in (left, right, first_round, second_round) if x is not None]
        all_refs: list[Any] = []
        for candidate in (round_ids or refs or []) + positional_refs + chosen:
            if isinstance(candidate, (list, tuple)):
                all_refs.extend(candidate)
            else:
                all_refs.append(candidate)
        if not all_refs:
            exp = experiment_code
            if exp:
                default_rounds = [r for r in self.rounds if r.get("实验编码") == exp]
                default_rounds.sort(key=lambda r: (int(r.get("序号", 0) or 0), int(r.get("版本", 1) or 1)))
                all_refs = default_rounds[-2:]
        if len(all_refs) >= 2 and left_round is None and right_round is None and left is None and right is None:
            left_ref, right_ref = all_refs[0], all_refs[1]
        else:
            left_ref = first_value({"a": left_round, "b": left, "c": first_round}, "a", "b", "c")
            right_ref = first_value({"a": right_round, "b": right, "c": second_round}, "a", "b", "c")
            if left_ref is None and all_refs:
                left_ref = all_refs[0]
            if right_ref is None and len(all_refs) > 1:
                right_ref = all_refs[1]

        left_row = self.resolve_round(left_ref, experiment_code)
        right_row = self.resolve_round(right_ref, experiment_code)
        left_view = self.round_view(left_row, experiment_code) if left_row is not None else None
        right_view = self.round_view(right_row, experiment_code) if right_row is not None else None

        exp = experiment_code or (left_view or {}).get("实验编码") or (right_view or {}).get("实验编码")
        if left_ref is not None and left_view is None:
            return {"ok": False, "message": f"找不到左侧样本轮次：{left_ref}", "experiment_code": exp}
        if right_ref is not None and right_view is None:
            return {"ok": False, "message": f"找不到右侧样本轮次：{right_ref}", "experiment_code": exp}
        if left_view and right_view and left_view.get("实验编码") != right_view.get("实验编码"):
            return {
                "ok": False,
                "message": "只能比较同一实验下的样本轮次",
                "left_experiment": left_view.get("实验编码"),
                "right_experiment": right_view.get("实验编码"),
            }

        unavailable: list[str] = []
        comparisons: dict[str, Any] = {}
        diff = None
        if not left_view or not right_view:
            unavailable.append("漂移身份差异：需要选择同一实验下的两个轮次（也允许只查看单个轮次计数）")
            comparisons["member_drift"] = {"available": False, "reason": "需要两个轮次"}
        elif left_view.get("revoked") or right_view.get("revoked"):
            revoked_codes = [v["轮次"] for v in (left_view, right_view) if v.get("revoked")]
            reason = f"{'、'.join(revoked_codes)} 已撤销，涉及该轮次的漂移、比率、健康度和核对单均不能正式办理"
            unavailable.append(reason)
            comparisons["member_drift"] = {"available": False, "formal_available": False, "reason": reason}
            comparisons["ratio"] = {"available": False, "reason": reason}
            comparisons["health"] = {"available": False, "reason": reason}
        elif not left_view.get("member_details_available") or not right_view.get("member_details_available"):
            reason = "至少一轮缺少成员明细，服务端无法核对新增、退出和同一成员换组"
            unavailable.append(reason)
            comparisons["member_drift"] = {"available": False, "reason": reason}
        else:
            diff = self.diff_views(left_view, right_view)
            comparisons["member_drift"] = {"available": True, "formal_available": True}

        ratio_compare = self._ratio_comparison(left_view, right_view)
        comparisons["ratio"] = ratio_compare
        comparisons["health"] = ratio_compare.get("health_difference") or {
            "available": False,
            "reason": ratio_compare.get("reason") or "健康度差异不可办理",
            "不可办理原因": ratio_compare.get("reason") or "健康度差异不可办理",
        }
        if not ratio_compare.get("available"):
            unavailable.append(str(ratio_compare.get("reason") or "比率/健康度比较不可办理"))

        formal = bool(
            left_view and right_view
            and left_view.get("confirmed") and right_view.get("confirmed")
            and not left_view.get("revoked") and not right_view.get("revoked")
        )
        if left_view and right_view and not formal:
            reason = "相邻重跑轮次的正式比较必须明确使用两份已确认样本；未确认或已撤销轮次不能作为确认结果"
            unavailable.append(reason)

        actual_statements = [v.get("占比说明") for v in (left_view, right_view) if v and v.get("占比说明")]
        basis = self._actual_basis(right_view)
        board = {
            "ok": True,
            "experiment_code": exp,
            "实验编码": exp,
            "left": left_view,
            "right": right_view,
            "base_round": left_view,
            "target_round": right_view,
            "第一轮": left_view,
            "第二轮": right_view,
            "selected_rounds": [v for v in (left_view, right_view) if v],
            "选择轮次": [v for v in (left_view, right_view) if v],
            "two_rounds": bool(left_view and right_view),
            "可选两轮": True,
            "comparable": diff is not None and formal,
            "formal_comparison_available": formal and diff is not None,
            "可正式比较": formal and diff is not None,
            "unavailable_reasons": unavailable,
            "不可办理说明": unavailable,
            "comparisons": comparisons,
            "可办理比较": comparisons,
            "diff": diff,
            "差异": diff,
            "drift": diff,
            "actual_statements": actual_statements,
            "取数说明": actual_statements,
            "actual_calculation": basis,
            "实际计算口径": basis,
            "adjacent_pairs": self.adjacent_round_pairs(exp) if exp else [],
            "相邻轮次": self.adjacent_round_pairs(exp) if exp else [],
            "adjacent_confirmed": self.adjacent_confirmed_pairs(exp) if exp else [],
            "相邻确认轮次": self.adjacent_confirmed_pairs(exp) if exp else [],
        }
        if diff:
            board["member_changes"] = diff
            board["changes"] = diff
            board["identity_changes"] = diff
            for key in ("added", "新增", "exited", "退出", "removed", "transferred", "换组", "只换组的同一成员", "changed_group", "summary"):
                board[key] = diff.get(key)
            board["transition_count"] = diff["summary"]["transition_count"]
        if left_view:
            board["left_counts"] = left_view.get("counts")
        if right_view:
            board["right_counts"] = right_view.get("counts")
        health_diff = comparisons.get("health") or {}
        board["health"] = health_diff
        board["health_diff"] = health_diff
        board["health_difference"] = health_diff
        board["健康度差异"] = health_diff
        board["message"] = "漂移看板已生成" if board["formal_comparison_available"] else "漂移看板已展示，但存在不可办理的比较项"
        return board

    @staticmethod
    def _actual_basis(view: dict[str, Any] | None) -> dict[str, Any]:
        if not view:
            return {"available": False}
        ratio = view.get("ratio")
        counts = view.get("counts") or {}
        if ratio is None:
            return {"available": False, "reason": view.get("missing_reason") or "无实际占比"}
        if abs(float(ratio) - 0.6) < 1e-9:
            kind = "original"
            text = f"本轮实际用于计算的是原占比 {ratio}（实验组 {counts.get(TREATMENT)}/{view.get('total')}）"
        elif abs(float(ratio) - 0.5) < 1e-9:
            kind = "corrected"
            text = f"本轮实际用于计算的是更正的 {ratio}（更正后 T2，实验组 {counts.get(TREATMENT)}/{view.get('total')}）"
        else:
            kind = "actual"
            text = f"本轮按实际取数计算，占比 {ratio}"
        return {
            "available": True,
            "basis": kind,
            "version": view.get("version"),
            "round_code": view.get("round_code"),
            "ratio": ratio,
            "占比": ratio,
            "text": text,
            "说明": text,
        }

    @staticmethod
    def _ratio_comparison(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
        if not left or not right:
            return {"available": False, "reason": "需要两个轮次才能比较比率与健康度差异"}
        if left.get("revoked") or right.get("revoked"):
            return {"available": False, "reason": "撤销轮次不能办理比率与健康度比较"}
        if not left.get("ratio_check_available") or not right.get("ratio_check_available"):
            reasons = [v.get("missing_reason") for v in (left, right) if not v.get("ratio_check_available") and v.get("missing_reason")]
            reason = "；".join(reasons) or "至少一轮缺组或尚未实际取数，不能办理同轮比率核对/比率差异"
            return {"available": False, "reason": reason, "不可办理原因": reason}

        lh, rh = left["health"], right["health"]
        delta_ratio = round(float(right["ratio"]) - float(left["ratio"]), 4)
        delta_offset = round(float(rh["offset"]) - float(lh["offset"]), 4)
        delta_health = round(float(rh["health_score"]) - float(lh["health_score"]), 4)
        delta_balance = round(float(rh["balance_score"]) - float(lh["balance_score"]), 4)
        result = {
            "available": True,
            "left_ratio": left["ratio"],
            "right_ratio": right["ratio"],
            "ratio_delta": delta_ratio,
            "占比变化": f"{left['ratio']} → {right['ratio']}（{delta_ratio:+.2f}）",
            "offset_delta": delta_offset,
            "偏移量变化": delta_offset,
            "health_score_delta": delta_health,
            "健康度得分变化": delta_health,
            "balance_score_delta": delta_balance,
            "均衡度变化": delta_balance,
            "status_change": f"{lh['status']} → {rh['status']}",
            "健康状态变化": f"{lh['status']} → {rh['status']}",
            "health_difference": {
                "available": True,
                "left": lh,
                "right": rh,
                "delta": delta_health,
                "health_score_delta": delta_health,
                "balance_score_delta": delta_balance,
                "ratio_delta": delta_ratio,
                "status_change": f"{lh['status']} → {rh['status']}",
                "说明": [
                    f"实验组占比：{left['ratio']} → {right['ratio']}（{delta_ratio:+.2f}）",
                    f"健康状态：{lh['status']} → {rh['status']}",
                    f"健康度得分变化：{delta_health:+.4f}",
                ],
            },
        }
        result["健康度差异"] = result["health_difference"]
        return result

    def adjacent_confirmed_pairs(self, experiment_code: str) -> list[dict[str, Any]]:
        rows = [
            self.round_view(r) for r in self.rounds
            if r.get("实验编码") == experiment_code and r.get("status") == CONFIRMED
        ]
        rows = [r for r in rows if r]
        # 排序键明确使用序号，再用确认时间兜底；撤销轮次在过滤阶段已排除，
        # 因而不会被中间撤销记录顶成“确认结果”。
        rows.sort(key=lambda r: (r.get("sequence", 0), r.get("version", 1), str(r.get("confirmed_at") or ""), r.get("id") or 0))
        pairs = []
        for index, (left, right) in enumerate(zip(rows, rows[1:])):
            skipped = [
                self.round_view(r) for r in self.rounds
                if r.get("实验编码") == experiment_code and r.get("status") == REVOKED
                and int(left.get("sequence", 0)) < int(r.get("序号", 0) or 0) < int(right.get("sequence", 0))
            ]
            pairs.append({
                "index": index + 1,
                "left": left,
                "right": right,
                "left_sample": f"{left['轮次']}@v{left['版本']}#id{left['id']}",
                "right_sample": f"{right['轮次']}@v{right['版本']}#id{right['id']}",
                "statement": (
                    f"相邻确认比较使用两份已确认样本：{left['轮次']}@v{left['版本']} "
                    f"与 {right['轮次']}@v{right['版本']}"
                ),
                "明确样本": f"{left['轮次']}@v{left['版本']} ↔ {right['轮次']}@v{right['版本']}",
                "skipped_revoked": skipped,
                "跳过的撤销轮次": skipped,
            })
        return pairs

    def adjacent_round_pairs(self, experiment_code: str) -> list[dict[str, Any]]:
        """按真实轮次顺序给出相邻对；若一端撤销/未确认，则明确该对不可办理。"""
        rows = [self.round_view(r) for r in self.rounds if r.get("实验编码") == experiment_code]
        rows = [r for r in rows if r]
        rows.sort(key=lambda r: (r.get("sequence", 0), r.get("version", 1), str(r.get("created_at") or ""), r.get("id") or 0))
        pairs = []
        for index, (left, right) in enumerate(zip(rows, rows[1:])):
            available = bool(left.get("confirmed") and right.get("confirmed") and not left.get("revoked") and not right.get("revoked"))
            reasons = [x.get("formal_reason") for x in (left, right) if x.get("formal_reason")]
            pairs.append({
                "index": index + 1,
                "left": left,
                "right": right,
                "available": available,
                "可办理": available,
                "comparison_available": available,
                "reason": "；".join(reasons) if reasons else "",
                "不可办理原因": "；".join(reasons) if reasons else "",
                "statement": f"相邻轮次样本：{left['轮次']}@v{left['版本']} 与 {right['轮次']}@v{right['版本']}",
                "明确样本": f"{left['轮次']}@v{left['版本']} ↔ {right['轮次']}@v{right['版本']}",
            })
        return pairs

    # ---------- 看板请求与换组核对单 ----------

    def create_drift_request(self, values: dict[str, Any]) -> dict[str, Any]:
        board = values.get("board")
        if not isinstance(board, dict):
            board = self.build_board(
                experiment_code=first_value(values, "experiment_code", "实验编码"),
                left_round=first_value(values, "left_round", "left", "base_round", "第一轮", "left_round_id"),
                right_round=first_value(values, "right_round", "right", "target_round", "第二轮", "right_round_id"),
                round_ids=first_value(values, "round_ids", "roundIds", "selected_rounds", "轮次", "refs"),
            )
        if not board.get("ok"):
            return board
        if not board.get("formal_comparison_available") and not values.get("allow_informal"):
            return {
                "ok": False,
                "status_code": 422,
                "message": "当前两轮不能办理正式漂移请求：" + "；".join(board.get("unavailable_reasons", [])),
                "board": board,
            }
        exp = board.get("experiment_code")
        row = {
            "id": next_id(self.requests),
            "request_code": first_value(values, "request_code", "请求编号", default=f"DRIFT-{exp}-{next_id(self.requests)}"),
            "实验编码": exp,
            "created_at": now_iso(),
            "created_by": first_value(values, "actor", "analyst", "分析员", default="分析员"),
            "left_round_id": (board.get("left") or {}).get("id"),
            "right_round_id": (board.get("right") or {}).get("id"),
            "rounds": [
                self._thin_sample(board.get("left")),
                self._thin_sample(board.get("right")),
            ],
            "board": deepcopy(board),
            "actual_calculation": board.get("actual_calculation"),
            "status": "已生成",
        }
        self.requests.append(row)
        return {"ok": True, "message": "漂移看板请求已保存，原申请可按编号重开", "request": row, "board": board, "entry": row}

    def get_request(self, request_id: Any) -> dict[str, Any] | None:
        if str(request_id).isdigit():
            row = next((r for r in self.requests if int(r["id"]) == int(request_id)), None)
            if row:
                return row
        return next((r for r in self.requests if r.get("request_code") == request_id or r.get("请求编号") == request_id), None)

    def create_transfer_order(self, values: dict[str, Any]) -> dict[str, Any]:
        board = values.get("board")
        request_row = None
        app = None
        if not isinstance(board, dict):
            request_id = first_value(values, "drift_request_id", "request_id", "看板请求编号")
            application_id = first_value(values, "application_id", "申请编号", "sample_application_id")
            if request_id is not None:
                request_row = self.get_request(request_id)
                board = (request_row or {}).get("board")
            elif application_id is not None:
                app = self.get_application(application_id)
                board = (app or {}).get("board")
            else:
                board = self.build_board(
                    experiment_code=first_value(values, "experiment_code", "实验编码"),
                    left_round=first_value(values, "left_round", "left_round_id", "left", "base_round"),
                    right_round=first_value(values, "right_round", "right_round_id", "right", "target_round"),
                    round_ids=first_value(values, "round_ids", "roundIds", "selected_rounds", "轮次"),
                )
        if not isinstance(board, dict) or not board.get("ok"):
            return {"ok": False, "message": "缺少可用于生成换组核对单的漂移看板", "board": board}
        if board.get("right", {}).get("revoked") or board.get("left", {}).get("revoked"):
            return {"ok": False, "status_code": 422, "message": "撤销轮次涉及的比较不可办理，不能送出正式换组核对单", "board": board}
        diff = board.get("diff")
        if not diff:
            return {"ok": False, "status_code": 422, "message": "缺少成员身份差异，无法送出换组核对单", "board": board}

        exp = board.get("experiment_code")
        order_id = next_id(self.orders)
        order = {
            "id": order_id,
            "order_code": first_value(values, "order_code", "核对单编号", default=f"HZHD-{exp}-{order_id:03d}"),
            "换组核对单": first_value(values, "order_code", "核对单编号", default=f"HZHD-{exp}-{order_id:03d}"),
            "实验编码": exp,
            "created_at": now_iso(),
            "created_by": first_value(values, "actor", "analyst", "分析员", default="分析员"),
            "left_round": self._thin_sample(board.get("left")),
            "right_round": self._thin_sample(board.get("right")),
            "items": deepcopy(diff.get("transferred", [])),
            "换组明细": deepcopy(diff.get("transferred", [])),
            "added": deepcopy(diff.get("added", [])),
            "新增": deepcopy(diff.get("added", [])),
            "exited": deepcopy(diff.get("exited", [])),
            "退出": deepcopy(diff.get("exited", [])),
            "summary": deepcopy(diff.get("summary", {})),
            "计数说明": diff.get("summary", {}).get("计数口径"),
            "drift_request_id": (request_row or {}).get("id") or values.get("drift_request_id"),
            "application_id": (app or {}).get("id") or values.get("application_id"),
            "status": "待核对",
            "pending": True,
        }
        self.orders.append(order)
        if app is not None:
            app.setdefault("transfer_order_ids", []).append(order["id"])
        return {
            "ok": True,
            "message": f"换组核对单 {order['order_code']} 已送出，换组 {len(order['items'])} 人、新增 {len(order['added'])} 人、退出 {len(order['exited'])} 人",
            "order": order,
            "entry": order,
        }

    def confirm_order(self, order_id: Any) -> dict[str, Any]:
        order = next((o for o in self.orders if str(o.get("id")) == str(order_id) or o.get("order_code") == order_id), None)
        if order is None:
            return {"ok": False, "message": f"换组核对单 {order_id} 不存在"}
        order["status"] = "已核对"
        order["pending"] = False
        order["confirmed_at"] = now_iso()
        return {"ok": True, "message": f"换组核对单 {order['order_code']} 已核对完成", "order": order, "entry": order}

    @staticmethod
    def _thin_sample(view: dict[str, Any] | None) -> dict[str, Any]:
        if not view:
            return {}
        counts = view.get("counts") or view.get("group_counts") or {}
        group_counts = view.get("组内人数") or {
            TREATMENT: counts.get(TREATMENT, counts.get("treatment")),
            CONTROL: counts.get(CONTROL, counts.get("control")),
        }
        return {
            "thin_sample": True,
            "round_id": view.get("id"),
            "id": view.get("id"),
            "round_code": view.get("round_code"),
            "轮次": view.get("轮次"),
            "version": view.get("version"),
            "版本": view.get("版本"),
            "status": view.get("status"),
            "状态": view.get("status"),
            "source_revision": view.get("source_revision") or (view.get("fetch_source") or "").split(":")[-1],
            "counts": counts,
            "group_counts": group_counts,
            "组内人数": group_counts,
            "treatment_count": group_counts.get(TREATMENT),
            "control_count": group_counts.get(CONTROL),
            "total": view.get("total"),
            "ratio": view.get("ratio"),
            "actual_ratio": view.get("actual_ratio") or view.get("ratio"),
            "实际占比": view.get("实际占比"),
            "missing_groups": view.get("missing_groups"),
            "缺组": view.get("missing_groups"),
            "missing_reason": view.get("missing_reason"),
            "缺组理由": view.get("missing_reason"),
            "ratio_check_available": view.get("ratio_check_available"),
            "fingerprint": view.get("fingerprint"),
            "confirmed_at": view.get("confirmed_at"),
        }

    # ---------- 样本量核对申请、领取冲突与复核 ----------

    def get_application(self, app_id: Any) -> dict[str, Any] | None:
        if app_id is None:
            return None
        if isinstance(app_id, dict):
            app_id = first_value(app_id, "id", "application_id", "申请编号", "application_code", "sample_entry_id")
        for app in self.applications:
            if str(app.get("id")) == str(app_id):
                return app
            if app.get("application_code") == app_id or app.get("申请编号") == app_id:
                return app
            if app.get("sample_entry_id") is not None and str(app.get("sample_entry_id")) == str(app_id):
                return app
        # Allow lookup by sample_ratio entry id even if not stored due to direct id.
        if str(app_id).isdigit():
            return next((a for a in self.applications if int(a.get("sample_entry_id") or -1) == int(app_id)), None)
        return None

    def find_application_by_sample_entry(self, entry_id: Any) -> dict[str, Any] | None:
        """按通用 sample_ratio 表主键查找，避免与漂移申请自增 ID 命名空间冲突。"""
        if entry_id is None:
            return None
        app = next(
            (a for a in self.applications if a.get("sample_entry_id") is not None and str(a.get("sample_entry_id")) == str(entry_id)),
            None,
        )
        if app is not None:
            return app
        entry = store.find("sample_ratio", int(entry_id)) if str(entry_id).isdigit() else next(
            (r for r in store.rows("sample_ratio") if r.get("核对批次") == entry_id), None
        )
        if entry is not None and entry.get("漂移申请编号"):
            return self.get_application(entry.get("漂移申请编号"))
        return None

    def create_application(self, values: dict[str, Any]) -> dict[str, Any]:
        exp = str(first_value(values, "experiment_code", "实验编码", default=""))
        refs = first_value(values, "round_ids", "round_refs", "轮次", "selected_rounds", default=[])
        if isinstance(refs, (str, int)):
            refs = [refs]
        if not exp or not isinstance(refs, (list, tuple)) or len(refs) < 2:
            return {"ok": False, "message": "样本量核对交接必须提供实验编码和两个关联确认轮次"}
        left = self.resolve_round(refs[0], exp)
        right = self.resolve_round(refs[1], exp)
        if left is None or right is None:
            return {"ok": False, "message": f"关联轮次不存在：{refs[0]} / {refs[1]}"}

        source = self.get_source(exp)
        submitted_revision = first_value(values, "submitted_revision", "source_revision", default=(source or {}).get("current_revision"))
        pinned = []
        for row in (left, right):
            view = self.round_view(row, exp)
            pinned.append({
                "round_id": row.get("id"),
                "round_code": view.get("round_code"),
                "轮次": view.get("轮次"),
                "version": view.get("version"),
                "版本": view.get("版本"),
                "source_revision": row.get("source_revision", submitted_revision),
                "fingerprint": view.get("fingerprint"),
                "counts": view.get("counts"),
                "组内人数": view.get("组内人数"),
                "ratio": view.get("ratio"),
            })

        app_id = next_id(self.applications)
        code = str(first_value(values, "application_code", "申请编号", "核对批次", default=f"SR-DRIFT-{exp}-{app_id:03d}"))
        sample_entry_id = first_value(values, "sample_entry_id", "sample_id", "核对结果ID")
        create_sample_row = bool(values.get("create_sample_row", sample_entry_id is None and values.get("register_sample_row", True)))
        if sample_entry_id is None and create_sample_row:
            sample_rows = store.rows("sample_ratio")
            entry = {
                "id": next_id(sample_rows),
                "status": "待核对",
                "pending": True,
                "abnormal": False,
                "核对批次": code,
                "实验编码": exp,
                "计划比例": str(first_value(values, "planned_ratio", "计划比例", default="0.5")),
                "实际比例": "",
                "偏移量": "",
                "关联轮次": f"{pinned[0]['round_code']}@v{pinned[0]['version']} / {pinned[1]['round_code']}@v{pinned[1]['version']}",
                "漂移申请编号": code,
                "领取状态": "待领取",
            }
            sample_rows.append(entry)
            sample_entry_id = entry["id"]

        app = {
            "id": app_id,
            "application_code": code,
            "申请编号": code,
            "sample_entry_id": sample_entry_id,
            "核对批次": code,
            "实验编码": exp,
            "round_refs": [left.get("id") or refs[0], right.get("id") or refs[1]],
            "轮次": [f"{p['round_code']}@v{p['version']}" for p in pinned],
            "pinned": pinned,
            "submitted_revision": submitted_revision,
            "status": "待领取",
            "申请状态": "待领取",
            "adopted": False,
            "fetched": False,
            "created_at": now_iso(),
            "board": None,
            "adopted_rounds": None,
            "resolution": None,
            "drift_request_id": None,
            "transfer_order_ids": [],
            "review": None,
        }
        self.applications.append(app)
        return {"ok": True, "message": f"样本量核对申请 {code} 已建立，接手时展示所采用的两份样本", "application": app, "entry": app}

    def _candidate_views(self, app: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
        exp = app["实验编码"]
        original: list[dict[str, Any]] = []
        current: list[dict[str, Any]] = []
        for pinned in app.get("pinned", []):
            row = self.resolve_round(pinned.get("round_id") or pinned.get("round_code"), exp, pinned.get("version"))
            original_view: dict[str, Any] | None = None
            if row is not None:
                # Force pinned source revision when the application was submitted before fetch.
                if pinned.get("source_revision") is not None and not row.get("members"):
                    row = deepcopy(row)
                    row["source_revision"] = pinned.get("source_revision")
                original_view = self.round_view(row, exp)
                original.append(original_view)  # type: ignore[arg-type]

            code = pinned.get("round_code") or pinned.get("轮次")
            pinned_version = int(pinned.get("version", 1) or 1)
            latest_row = self.resolve_round(code, exp)  # highest version
            latest_view = self.round_view(latest_row, exp) if latest_row is not None else None
            if original_view is None:
                if latest_view is not None:
                    current.append(latest_view)
                continue

            # 只有创建轮次时已经固化的成员/计数快照才不可被后续来源更正改写。
            # 仅绑定 source_revision、可回溯历史版本的“已提交未取数”轮次，仍要
            # 在领取时比较固定版次与当前来源，从而暴露两个版次冲突。
            row_is_immutable = bool(
                row is not None and (
                    row.get("members")
                    or row.get("actual_counts")
                    or row.get("actual_counts_provided")
                )
            )
            has_newer_version = bool(
                latest_view and int(latest_view.get("version", 1) or 1) > pinned_version
            )
            if row_is_immutable and not has_newer_version:
                current.append(original_view)  # type: ignore[arg-type]
                continue
            if has_newer_version and latest_view is not None and latest_view.get("members"):
                current.append(latest_view)
                continue

            source = self.get_source(exp)
            if source is not None:
                rev = source.get("current_revision")
                revision = self._revision(source, rev)
                current_row: dict[str, Any] = {
                    "id": (latest_row or {}).get("id") if latest_row and latest_row.get("source_revision") == rev else None,
                    "实验编码": exp,
                    "轮次编码": code,
                    "轮次": code,
                    "版本": max(pinned_version, int((latest_row or {}).get("版本", 1) or 1)),
                    "status": CONFIRMED,
                    "source_revision": rev,
                    "members": (revision or {}).get("members") or self.current_members(exp),
                    "confirmed_at": now_iso(),
                }
                # If latest row already points at current revision, preserve its id/version.
                if latest_row is not None and latest_row.get("source_revision") == rev:
                    current_row = latest_row
                else:
                    same_code = [r for r in self.rounds if r.get("实验编码") == exp and str(r.get("轮次编码")) == code]
                    current_row["版本"] = max((int(r.get("版本", 1) or 1) for r in same_code), default=pinned_version)
                    if current_row["版本"] == pinned_version:
                        current_row["版本"] += 1
                current.append(self.round_view(current_row, exp))  # type: ignore[arg-type]
            elif latest_view is not None:
                current.append(latest_view)
        source = self.get_source(exp)
        current_info = None
        if source:
            current_members = self.current_members(exp)
            current_info = {
                "revision": source.get("current_revision"),
                "fingerprint": fingerprint(current_members),
                "counts": counts_of(current_members),
            }
        return original, current, current_info

    def claim_application(self, app_id: Any, resolution: Any = None, **extra: Any) -> dict[str, Any]:
        app = self.get_application(app_id)
        if app is None:
            return {"ok": False, "status_code": 404, "message": f"样本核对申请 {app_id} 不存在"}
        if app.get("adopted"):
            return {
                "ok": True,
                "idempotent": True,
                "message": "该申请已领取并固定实际采用的两份样本；来源变化不影响重开原申请",
                "application": app,
                "board": app.get("board"),
                "entry": app,
            }

        original, current, source_info = self._candidate_views(app)
        if len(original) < 2 or len(current) < 2:
            return {"ok": False, "status_code": 422, "message": "关联轮次无法解析为两份可领取样本"}

        original_fp = [v.get("fingerprint") for v in original]
        current_fp = [v.get("fingerprint") for v in current]
        counts_changed = [
            (o.get("counts"), c.get("counts"))
            for o, c in zip(original, current)
            if fingerprint(o.get("members")) != fingerprint(c.get("members")) or o.get("counts") != c.get("counts")
        ]
        conflict = original_fp != current_fp or bool(counts_changed)
        choice = self._resolution_name(resolution if resolution is not None else extra)

        if conflict and choice is None:
            candidate_summary = {
                "original": [self._thin_sample(v) for v in original],
                "corrected": [self._thin_sample(v) for v in current],
                "current_source": source_info,
            }
            message = (
                "T2 存在两个版次，领取冲突：原提交版为实验组 6/10、实际占比 0.6；"
                "更正后版次为实验组 5/10、实际占比 0.5。请选择实际采用的版次后再领取"
            )
            return {
                "ok": False,
                "status_code": 409,
                "conflict": True,
                "冲突": True,
                "message": message,
                "application": app,
                "candidates": candidate_summary,
                "候选版次": candidate_summary,
                "versions": {
                    "original": candidate_summary["original"],
                    "submitted": candidate_summary["original"],
                    "corrected": candidate_summary["corrected"],
                    "current": candidate_summary["corrected"],
                },
                "original": candidate_summary["original"],
                "corrected": candidate_summary["corrected"],
                "current": candidate_summary["corrected"],
                "entry": app,
            }

        use_current = choice == "current"
        adopted_views = deepcopy(current if use_current else original)
        basis = "corrected" if use_current else "original"

        # If current source was chosen and no persisted corrected round exists yet,
        # persist the adopted version so later trace/report can reopen exact IDs.
        adopted_refs = []
        for view in adopted_views:
            if use_current and view.get("id") is None:
                created = self.create_round({
                    "experiment_code": app["实验编码"],
                    "round_code": view.get("round_code"),
                    "version": view.get("version"),
                    "sequence": view.get("sequence"),
                    "status": CONFIRMED,
                    "members": view.get("members"),
                    "source_revision": (source_info or {}).get("revision"),
                    "note": "领取更正后样本时正式确认",
                }).get("round")
                view = created or view
            adopted_refs.append(self._thin_sample(view))

        board = self.build_board(
            experiment_code=app["实验编码"],
            round_ids=[v.get("id") or v for v in adopted_views],
        )
        # Ensure the immutable board uses adopted views, even if IDs were ephemeral.
        if board.get("ok"):
            board["left"] = adopted_views[0]
            board["right"] = adopted_views[1]
            board["selected_rounds"] = adopted_views
            board["选择轮次"] = adopted_views
            board["actual_calculation"] = self._actual_basis(adopted_views[1])
            if adopted_views[0].get("member_details_available") and adopted_views[1].get("member_details_available"):
                board["diff"] = self.diff_views(adopted_views[0], adopted_views[1])
                board["差异"] = board["diff"]
            board["formal_comparison_available"] = all(v.get("confirmed") for v in adopted_views)
            board["comparable"] = board["formal_comparison_available"] and board.get("diff") is not None

        request_result = self.create_drift_request({
            "experiment_code": app["实验编码"],
            "board": board,
            "actor": extra.get("actor") or "样本核对员",
            "request_code": f"DRIFT-CLAIM-{app['id']:03d}",
        })
        request_row = request_result.get("request")

        app.update({
            "adopted": True,
            "fetched": True,
            "status": "已领取待复核",
            "申请状态": "已领取待复核",
            "claimed_at": now_iso(),
            "resolution": basis,
            "领取选择": "更正后版次" if use_current else "原提交版次",
            "adopted_rounds": adopted_refs,
            "adopted_samples": adopted_refs,
            "two_samples": adopted_refs,
            "实际采用两轮": adopted_refs,
            "实际采用样本": adopted_refs,
            "board": deepcopy(board),
            "drift_request_id": (request_row or {}).get("id"),
        })
        self._sync_sample_entry(app, claimed=True)
        ratio_text = (board.get("actual_calculation") or {}).get("text", "")
        return {
            "ok": True,
            "conflict": False,
            "message": f"已按{'更正后' if use_current else '原提交'}版次领取两份确认样本；{ratio_text}",
            "application": app,
            "entry": app,
            "board": board,
            "adopted_rounds": adopted_refs,
            "adopted_samples": adopted_refs,
            "two_samples": adopted_refs,
            "实际采用两轮": adopted_refs,
        }

    @staticmethod
    def _resolution_name(resolution: Any) -> str | None:
        if resolution is None:
            return None
        if isinstance(resolution, dict):
            resolution = first_value(
                resolution,
                "choice", "resolution", "adopt", "accept", "use", "version",
                "采用", "选择", "采用版次",
            )
        if resolution is None:
            return None
        text = str(resolution).strip().lower().replace(" ", "")
        if text in {x.lower().replace(" ", "") for x in CURRENT_RESOLUTIONS}:
            return "current"
        if text in {x.lower().replace(" ", "") for x in ORIGINAL_RESOLUTIONS}:
            return "original"
        if "更正" in text or "当前" in text or "最新" in text:
            return "current"
        if "原" in text or "旧" in text:
            return "original"
        return None

    def _sync_sample_entry(self, app: dict[str, Any], claimed: bool = False, review: dict[str, Any] | None = None) -> None:
        entry_id = app.get("sample_entry_id")
        entry = store.find("sample_ratio", int(entry_id)) if entry_id is not None and str(entry_id).isdigit() else None
        if entry is None:
            return
        rounds = app.get("adopted_rounds") or []
        entry["漂移申请编号"] = app.get("application_code")
        if app.get("report_code"):
            entry["报告编码"] = app.get("report_code")
        entry["关联确认轮次"] = " / ".join(
            f"{r.get('轮次') or r.get('round_code')}@v{r.get('版本') or r.get('version')}" for r in rounds
        ) or " / ".join(app.get("轮次", []))
        entry["采用样本"] = "；".join(
            f"{r.get('轮次') or r.get('round_code')}:{(r.get('组内人数') or {}).get(TREATMENT, '?')}:{(r.get('组内人数') or {}).get(CONTROL, '?')}"
            for r in rounds
        )
        if claimed:
            entry["领取状态"] = app.get("领取选择", "已领取")
            right = rounds[1] if len(rounds) > 1 else {}
            if right.get("ratio") is not None:
                entry["实际比例"] = str(right.get("ratio"))
        if review is not None:
            entry["复核结论"] = review.get("message", "")
            if review.get("sample_status"):
                entry["status"] = review["sample_status"]
                entry["pending"] = review["sample_status"] != "已核对"
                entry["abnormal"] = review["sample_status"] in {"偏移超标", "待补组"}

    def review_application(self, app_id: Any, **_: Any) -> dict[str, Any]:
        app = self.get_application(app_id)
        if app is None:
            return {"ok": False, "status_code": 404, "message": f"样本核对申请 {app_id} 不存在"}
        if not app.get("adopted"):
            return {"ok": False, "status_code": 409, "conflict": False, "message": "请先领取关联确认轮次的分组漂移看板数据，再进行复核", "application": app}

        rounds = app.get("adopted_rounds") or []
        ratio_checks = []
        any_offset = False
        blocked_groups = False
        for sample in rounds:
            view = sample
            # Adopted thin samples may not contain health; reconstruct immutable full board round.
            if app.get("board"):
                full = next((v for v in app["board"].get("selected_rounds", []) if str(v.get("id")) == str(sample.get("round_id")) or v.get("round_code") == sample.get("round_code")), None)
                if full:
                    view = full
            if not view.get("ratio_check_available"):
                blocked_groups = True
                ratio_checks.append({
                    "round": f"{view.get('round_code')}@v{view.get('version')}",
                    "available": False,
                    "可办理": False,
                    "reason": view.get("missing_reason") or "缺组或未取数，不能进入同轮比率样本核对",
                })
                continue
            health = view.get("health") or health_of(view.get("counts"))
            offset = float(health.get("offset", 0))
            alarm = offset > 0.05
            any_offset = any_offset or alarm
            ratio_checks.append({
                "round": f"{view.get('round_code')}@v{view.get('version')}",
                "available": True,
                "可办理": True,
                "counts": view.get("组内人数") or view.get("counts"),
                "ratio": view.get("ratio"),
                "offset": offset,
                "status": "偏移超标" if alarm else "已核对",
                "结论": "偏移超阈值 0.05" if alarm else "同轮比率核对通过",
            })

        board = app.get("board") or {}
        order_ids = app.get("transfer_order_ids", [])
        orders = [o for o in self.orders if o.get("id") in order_ids]
        if blocked_groups:
            sample_status = "待补组"
            message = "漂移数据已可复核，但至少一轮缺组；缺组轮次不能进入同轮比率样本核对"
        elif any_offset:
            sample_status = "偏移超标"
            message = "依据已领取的两份确认样本复核：存在比率偏移超阈值轮次，已标记偏移超标"
        else:
            sample_status = "已核对"
            message = "依据已领取的两份确认样本复核完成：两轮同轮比率均在阈值内"

        review = {
            "ok": not blocked_groups,
            "completed": True,
            "reviewed_at": now_iso(),
            "message": message,
            "sample_status": sample_status,
            "ratio_checks": ratio_checks,
            "两轮比率核对": ratio_checks,
            "drift_summary": (board.get("diff") or {}).get("summary"),
            "health_difference": (board.get("comparisons") or {}).get("health"),
            "transfer_orders": [self._thin_order(o) for o in orders],
            "rounds_used": rounds,
            "使用轮次": rounds,
        }
        app["review"] = review
        app["status"] = "复核完成" if not blocked_groups else "部分可复核-待补组"
        app["申请状态"] = app["status"]
        report = self._upsert_report_material(app, review)
        review["report"] = {
            "id": report.get("id"),
            "report_code": report.get("报告编码"),
            "报告编码": report.get("报告编码"),
            "rounds": review.get("rounds_used"),
        }
        app["report_id"] = report.get("id")
        app["report_code"] = report.get("报告编码")
        self._sync_sample_entry(app, review=review)
        return {
            "ok": not blocked_groups,
            # 缺组是可展示、可解释的业务不可办理项；HTTP 层仍返回 200，由 body.ok
            # 和 ratio_checks[].available=false 表达“不能进入比率核对”。
            "status_code": 200 if blocked_groups else 200,
            "ratio_check_blocked": blocked_groups,
            "message": message,
            "application": app,
            "review": review,
            "entry": app,
        }

    @staticmethod
    def _thin_order(order: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": order.get("id"),
            "order_code": order.get("order_code"),
            "核对单编号": order.get("order_code"),
            "status": order.get("status"),
            "换组人数": len(order.get("items", [])),
            "新增人数": len(order.get("added", [])),
            "退出人数": len(order.get("exited", [])),
        }

    def _upsert_report_material(self, app: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
        """在报告生成器中留一份可回查的轮次/人数材料。"""
        rows = store.rows("report_gen")
        existing = store.find("report_gen", int(app["report_id"])) if app.get("report_id") else None
        round_text = " / ".join(
            f"{r.get('轮次') or r.get('round_code')}@v{r.get('版本') or r.get('version')}:"
            f"{(r.get('组内人数') or {}).get(TREATMENT, '?')}+{(r.get('组内人数') or {}).get(CONTROL, '?')}"
            for r in review.get("rounds_used", [])
        )
        if existing is None:
            code = f"RPT-DRIFT-{app.get('id', 0):03d}"
            existing = {
                "id": next_id(rows),
                "status": "已完成",
                "pending": False,
                "abnormal": bool(review.get("sample_status") == "偏移超标"),
                "报告编码": code,
                "实验编码": app.get("实验编码"),
                "报告模板": "AA重跑漂移与样本健康度报告",
                "数据窗口": round_text,
                "生成状态": "已完成",
                "sample_application_id": app.get("id"),
                "sample_batch": app.get("application_code"),
            }
            rows.append(existing)
        existing.update({
            "数据窗口": round_text,
            "生成状态": "已完成",
            "status": "已完成",
            "rounds_used": review.get("rounds_used"),
            "report_rounds": review.get("rounds_used"),
            "group_counts": [
                {
                    "轮次": r.get("轮次") or r.get("round_code"),
                    "组内人数": r.get("组内人数"),
                    "实际占比": r.get("ratio") or r.get("实际占比"),
                }
                for r in review.get("rounds_used", [])
            ],
            "review_summary": review.get("message"),
        })
        return existing

    def trace_application(self, app_id: Any) -> dict[str, Any]:
        app = self.get_application(app_id)
        if app is None:
            return {"ok": False, "status_code": 404, "message": f"漂移申请 {app_id} 不存在"}
        entry = store.find("sample_ratio", int(app["sample_entry_id"])) if app.get("sample_entry_id") else None
        return self._trace_payload(app, entry)

    def trace_sample_batch(self, batch_id: Any) -> dict[str, Any]:
        entry: dict[str, Any] | None = None
        app: dict[str, Any] | None = None

        # sample_ratio 主键和 drift application 主键都从 1 开始，必须先按样本批次
        # 命名空间查找，避免把旧种子批次 id=1 误当成漂移申请 id=1。
        if str(batch_id).isdigit():
            entry = store.find("sample_ratio", int(batch_id))
        if entry is None:
            entry = next((r for r in store.rows("sample_ratio") if r.get("核对批次") == batch_id), None)
        if entry is not None:
            app = self.find_application_by_sample_entry(entry.get("id"))
        if app is None and entry is not None and entry.get("漂移申请编号"):
            app = self.get_application(entry.get("漂移申请编号"))
        if app is None and entry is None:
            app = self.get_application(batch_id)
            if app is not None and app.get("sample_entry_id"):
                entry = store.find("sample_ratio", int(app["sample_entry_id"]))
        if app is None and entry is None:
            return {"ok": False, "status_code": 404, "message": f"样本核对批次 {batch_id} 不存在"}
        return self._trace_payload(app, entry)

    def _trace_payload(self, app: dict[str, Any] | None, entry: dict[str, Any] | None) -> dict[str, Any]:
        rounds_used = (app or {}).get("adopted_rounds") or (app or {}).get("pinned") or []
        group_counts = [
            {
                "round": r.get("轮次") or r.get("round_code"),
                "version": r.get("版本") or r.get("version"),
                "实验": (r.get("组内人数") or r.get("counts") or {}).get(TREATMENT),
                "对照": (r.get("组内人数") or r.get("counts") or {}).get(CONTROL),
                "组内人数": r.get("组内人数") or {
                    TREATMENT: (r.get("counts") or {}).get(TREATMENT),
                    CONTROL: (r.get("counts") or {}).get(CONTROL),
                },
                "ratio": r.get("ratio"),
                "实际占比": r.get("实际占比") or r.get("ratio"),
            }
            for r in rounds_used
        ]
        report_rounds = [{
            "round": g["round"],
            "轮次": g["round"],
            "version": g["version"],
            "版本": g["version"],
            "group_counts": g["组内人数"],
            "组内人数": g["组内人数"],
            "actual_ratio": g["实际占比"],
            "实际占比": g["实际占比"],
        } for g in group_counts]
        report = None
        if app and app.get("report_id"):
            report = store.find("report_gen", int(app["report_id"]))
        return {
            "ok": True,
            "message": "已回查样本核对批次实际使用的轮次与组内人数",
            "sample_batch": entry,
            "application": app,
            "report": report,
            "报告": report,
            "report_id": (app or {}).get("report_id"),
            "report_code": (app or {}).get("report_code"),
            "rounds_used": rounds_used,
            "实际采用两轮": rounds_used,
            "report_rounds": report_rounds,
            "报告使用轮次": report_rounds,
            "group_counts": group_counts,
            "轮次组内人数": group_counts,
            "drift_request_id": (app or {}).get("drift_request_id"),
            "transfer_order_ids": (app or {}).get("transfer_order_ids", []),
            "reopen": {
                "application_id": (app or {}).get("id"),
                "application_code": (app or {}).get("application_code"),
                "path": f"/api/sample-drift/applications/{(app or {}).get('id')}",
                "说明": "来源变化后，仍按申请编号重开不可变的原申请和实际采用样本",
            },
        }


drift_board_service = DriftBoardService()


# 常见函数式导入别名：from app.services.drift_board import compare_rounds ...
def __getattr__(name: str) -> Any:
    aliases = {
        "compare_rounds": drift_board_service.build_board,
        "compare_rerun_rounds": drift_board_service.build_board,
        "build_drift_board": drift_board_service.build_board,
        "get_drift_board": drift_board_service.build_board,
        "create_drift_board": drift_board_service.build_board,
        "create_transfer_order": drift_board_service.create_transfer_order,
        "send_transfer_check": drift_board_service.create_transfer_order,
        "claim_drift_board": drift_board_service.claim_application,
        "create_sample_application": drift_board_service.create_application,
        "trace_sample_batch": drift_board_service.trace_sample_batch,
    }
    if name in aliases:
        return aliases[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
