"""端到端测试：标签签发审批（可审计申请-批准/驳回-签发）。

覆盖：申请冻结结论与依据摘要、游标校验、重复提交幂等/冲突、批准/驳回状态机、
结论或封存变化后禁止批准与签发（需重新申请）、签发绑定批准记录并冻结申请时
结论、已处理申请不可重复审批、未知/跨批次/缺理由等错误，以及与既有标签
快照/查询和直接签发路径的兼容。
"""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# 每个测试会话使用独立数据库文件
_tmp = tempfile.mkdtemp(prefix="allergen-test-")
os.environ["DB_PATH"] = os.path.join(_tmp, "test-approval.db")

from app import db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    # 重置数据库
    db.init_db()
    conn = db.connect()
    for t in ["material_declarations", "material_batches", "processing_inputs",
              "processing_outputs", "processings", "cleanings", "labels",
              "trace_events", "allergen_code_merges", "investigations",
              "label_applications"]:
        conn.execute(f"DELETE FROM {t}")
    conn.execute("DELETE FROM sqlite_sequence WHERE name = 'trace_events'")
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def material(c, batch_id, allergens=None, pending=False,
             declared_at="2026-01-01T00:00:00Z"):
    return c.post("/materials", json={
        "batch_id": batch_id, "allergens": allergens or [],
        "pending": pending, "declared_at": declared_at})


def processing(c, pid, eq, start, end, inputs, outputs):
    return c.post("/processings", json={
        "processing_id": pid, "equipment_id": eq,
        "start_utc": start, "end_utc": end,
        "inputs": inputs, "outputs": outputs})


def apply(c, batch_id, applicant="qc-zhang", reason="出厂批次标签签发",
         note="共线复核通过", cursor=0):
    body = {"batch_id": batch_id, "applicant": applicant, "reason": reason,
            "cursor": cursor}
    if note is not None:
        body["label_note"] = note
    return c.post("/label-applications", json=body)


def decide(c, app_id, decision, reviewer="reviewer-li", **kw):
    body = {"decision": decision, "reviewer": reviewer, **kw}
    return c.post(f"/label-applications/{app_id}/decision", json=body)


def issue(c, batch_id, app_id=None, supersedes_id=None):
    body = {}
    if app_id is not None:
        body["approval_id"] = app_id
    if supersedes_id is not None:
        body["supersedes_id"] = supersedes_id
    return c.post(f"/batches/{batch_id}/labels", json=body)


@pytest.fixture()
def world(client):
    """RM-MILK(milk) --P1/EQ-1--> OUT-1（简单可溯源场景）。"""
    material(client, "RM-MILK", allergens=["milk"])
    processing(client, "P1", "EQ-1",
               "2026-01-02T08:00:00Z", "2026-01-02T09:00:00Z",
               ["RM-MILK"], ["OUT-1"])
    return client


# ---------------------------------------------------------------- 申请受理

def test_application_freezes_conclusion_and_basis_summary(world):
    r = apply(world, "OUT-1", cursor=2)  # 原料登记+加工登记产生 2 条事件
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["replayed"] is False
    assert a["status"] == "pending"
    assert a["allergens"] == ["milk"]
    assert a["pending"] is False
    assert a["held_at_request"] is False
    assert a["frozen_conclusion"]["allergens"] == ["milk"]
    # 依据摘要：命中声明版本 + 实时封存状态
    summary = a["basis_summary"]
    assert summary["allergens"] == ["milk"]
    assert summary["pending"] is False
    assert summary["held"] is False
    assert summary["active_investigations"] == []
    versions = {(v["batch_id"], v["version"]) for v in summary["material_versions"]}
    assert ("RM-MILK", 1) in versions
    # 当前实时视图与申请时一致
    assert a["conclusion_stale"] is False
    assert a["current"]["allergens"] == ["milk"]
    assert a["current"]["held"] is False
    assert a["requested_cursor"] == 2
    assert a["cursor_seq"] == 2
    assert a["reviewer"] is None and a["reviewed_at"] is None


def test_application_pending_material(world):
    material(world, "RM-P", pending=True)
    a = apply(world, "RM-P").json()
    assert a["pending"] is True
    assert a["basis_summary"]["pending"] is True
    assert a["frozen_conclusion"]["pending"] is True


def test_application_without_label_note_ok(world):
    r = world.post("/label-applications", json={
        "batch_id": "OUT-1", "applicant": "qc", "reason": "无备注申请",
        "cursor": 0})
    assert r.status_code == 201, r.text
    assert r.json()["label_note"] == ""


def test_application_unknown_batch_400(world):
    r = apply(world, "GHOST")
    assert r.status_code == 400
    assert "未知批次" in r.json()["detail"]


def test_application_blank_reason_422(world):
    r = world.post("/label-applications", json={
        "batch_id": "OUT-1", "applicant": "qc", "reason": "   ", "cursor": 0})
    assert r.status_code == 422


def test_application_missing_cursor_422(world):
    r = world.post("/label-applications", json={
        "batch_id": "OUT-1", "applicant": "qc", "reason": "x"})
    assert r.status_code == 422


def test_application_cursor_out_of_range_400(world):
    r = apply(world, "OUT-1", cursor=9999)
    assert r.status_code == 400
    assert "游标" in r.json()["detail"]


def test_application_negative_cursor_422(world):
    r = world.post("/label-applications", json={
        "batch_id": "OUT-1", "applicant": "qc", "reason": "x", "cursor": -1})
    assert r.status_code == 422


def test_application_held_state_returned(world):
    world.post("/investigations", json={
        "investigation_id": "INV-1", "batch_id": "RM-MILK",
        "reason": "疑似交叉接触"})
    a = apply(world, "OUT-1").json()
    assert a["held_at_request"] is True
    assert a["basis_summary"]["held"] is True
    assert a["basis_summary"]["active_investigations"] == ["INV-1"]
    assert a["current"]["held"] is True


# ---------------------------------------------------------------- 幂等与冲突

def test_duplicate_pending_application_is_idempotent(world):
    first = apply(world, "OUT-1")
    assert first.status_code == 201
    second = apply(world, "OUT-1")  # 同批次/申请人/理由/备注
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    assert second.json()["application_id"] == first.json()["application_id"]
    rows = world.get("/label-applications").json()["applications"]
    assert len(rows) == 1  # 不重复写


def test_duplicate_pending_application_with_different_note_conflicts(world):
    assert apply(world, "OUT-1", note="备注A").status_code == 201
    r = apply(world, "OUT-1", note="备注B")
    assert r.status_code == 409


def test_duplicate_pending_application_with_different_reason_conflicts(world):
    assert apply(world, "OUT-1", reason="理由一").status_code == 201
    r = apply(world, "OUT-1", reason="理由二")
    assert r.status_code == 409


def test_distinct_applicants_have_separate_applications(world):
    a1 = apply(world, "OUT-1", applicant="qc-zhang").json()
    a2 = apply(world, "OUT-1", applicant="qc-wang").json()
    assert a1["application_id"] != a2["application_id"]


# ---------------------------------------------------------------- 批准与签发

def test_approve_then_issue_binds_approval_and_freezes(world):
    app_id = apply(world, "OUT-1", cursor=2).json()["application_id"]
    r = decide(world, app_id, "approve")
    assert r.status_code == 200, r.text
    approved = r.json()
    assert approved["status"] == "approved"
    assert approved["reviewer"] == "reviewer-li"
    assert approved["reviewed_at"] is not None

    r = issue(world, "OUT-1", app_id=app_id)
    assert r.status_code == 201, r.text
    label = r.json()
    assert label["approval_id"] == app_id
    assert label["conclusion"]["allergens"] == ["milk"]

    # 申请置为 issued 并绑定标签
    got = world.get(f"/label-applications/{app_id}").json()
    assert got["status"] == "issued"
    assert got["issued_label_id"] == label["label_id"]
    assert got["issued_at"] is not None

    # 标签查询（列表/单条）兼容且带 approval_id
    listed = world.get("/batches/OUT-1/labels").json()
    assert [l["label_id"] for l in listed] == [label["label_id"]]
    assert listed[0]["approval_id"] == app_id
    assert world.get(f"/labels/{label['label_id']}").json()["basis"]


def test_issue_requires_approved_application(world):
    app_id = apply(world, "OUT-1").json()["application_id"]
    # pending 状态不能签发
    r = issue(world, "OUT-1", app_id=app_id)
    assert r.status_code == 409
    assert "未批准或已驳回" in r.json()["detail"]


def test_rejected_application_cannot_issue_and_can_reapply(world):
    app_id = apply(world, "OUT-1").json()["application_id"]
    r = decide(world, app_id, "reject", reject_reason="依据不完整，退回")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    assert r.json()["reject_reason"] == "依据不完整，退回"

    # 驳回后禁止签发
    r = issue(world, "OUT-1", app_id=app_id)
    assert r.status_code == 409

    # 已处理申请不可重复审批（再批准/再驳回均冲突）
    assert decide(world, app_id, "approve").status_code == 409
    assert decide(world, app_id, "reject",
                  reject_reason="再次驳回").status_code == 409

    # 驳回后可重新申请（新记录），批准后正常签发
    new_id = apply(world, "OUT-1").json()["application_id"]
    assert new_id != app_id
    assert decide(world, new_id, "approve").status_code == 200
    assert issue(world, "OUT-1", app_id=new_id).status_code == 201


def test_reject_without_reason_422(world):
    app_id = apply(world, "OUT-1").json()["application_id"]
    r = world.post(f"/label-applications/{app_id}/decision", json={
        "decision": "reject", "reviewer": "r"})
    assert r.status_code == 422


def test_decision_unknown_application_404(world):
    assert decide(world, 999, "approve").status_code == 404


def test_decision_blank_reviewer_422(world):
    app_id = apply(world, "OUT-1").json()["application_id"]
    r = world.post(f"/label-applications/{app_id}/decision", json={
        "decision": "approve", "reviewer": "  "})
    assert r.status_code == 422


# ---------------------------------------------------------------- 结论变化

def test_approve_rejected_when_conclusion_changed_after_request(world):
    app_id = apply(world, "OUT-1", cursor=2).json()["application_id"]
    # 申请后上游声明更正：OUT-1 实时结论变化
    world.post("/materials/RM-MILK/declarations", json={
        "allergens": ["milk", "peanut"]})
    a = world.get(f"/label-applications/{app_id}").json()
    assert a["conclusion_stale"] is True
    assert a["current"]["allergens"] == ["milk", "peanut"]
    r = decide(world, app_id, "approve")
    assert r.status_code == 409
    assert "重新提交" in r.json()["detail"]
    # 申请仍为 pending（未被置为批准），但结论过期不能批准；驳回不要求新鲜度
    assert world.get(f"/label-applications/{app_id}").json()["status"] == "pending"


def test_issue_rejected_when_conclusion_changes_after_approval(world):
    app_id = apply(world, "OUT-1", cursor=2).json()["application_id"]
    assert decide(world, app_id, "approve").status_code == 200
    # 批准后、签发前上游声明更正
    world.post("/materials/RM-MILK/declarations", json={
        "allergens": ["milk", "peanut"]})
    r = issue(world, "OUT-1", app_id=app_id)
    assert r.status_code == 409
    assert "结论" in r.json()["detail"] and "重新提交" in r.json()["detail"]
    # 未签发任何标签，申请保持 approved（但已不可用）
    assert world.get("/batches/OUT-1/labels").json() == []
    got = world.get(f"/label-applications/{app_id}").json()
    assert got["status"] == "approved"


def test_label_snapshot_freezes_request_time_conclusion(world):
    """批准后结论变化，重新申请再签发：新标签冻结的是新申请时结论；
    旧的已批准申请按过期结论禁止签发。"""
    first = apply(world, "OUT-1", cursor=2).json()["application_id"]
    assert decide(world, first, "approve").status_code == 200
    world.post("/materials/RM-MILK/declarations", json={
        "allergens": ["milk", "peanut"]})
    assert issue(world, "OUT-1", app_id=first).status_code == 409

    # 以当前结论重新申请 -> 批准 -> 签发，快照为 peanut+milk
    second = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, second, "approve").status_code == 200
    label = issue(world, "OUT-1", app_id=second).json()
    assert label["conclusion"]["allergens"] == ["milk", "peanut"]
    assert label["approval_id"] == second


# ---------------------------------------------------------------- 封存变化

def test_approve_rejected_while_held(world):
    """申请时已封存：不能批准。"""
    app_id = apply(world, "OUT-1").json()["application_id"]
    world.post("/investigations", json={
        "investigation_id": "INV-1", "batch_id": "RM-MILK",
        "reason": "疑似交叉接触"})
    r = decide(world, app_id, "approve")
    assert r.status_code == 409
    assert "封存" in r.json()["detail"]


def test_hold_opened_after_request_blocks_approval_via_stale_release(world):
    """申请后新增封存：release 属于冻结视图一部分，批准被拒（需重新申请）。"""
    app_id = apply(world, "OUT-1").json()["application_id"]
    world.post("/investigations", json={
        "investigation_id": "INV-1", "batch_id": "OUT-1",
        "reason": "成品疑似污染"})
    assert decide(world, app_id, "approve").status_code == 409


def test_hold_lifted_after_request_still_blocks_approval(world):
    """申请时封存、申请后解除：当前 release 与冻结时不同 -> 拒绝批准，
    需以放行后的结论重新申请。"""
    world.post("/investigations", json={
        "investigation_id": "INV-1", "batch_id": "RM-MILK",
        "reason": "疑似交叉接触"})
    app_id = apply(world, "OUT-1").json()["application_id"]
    assert app_id  # 封存期间允许申请
    world.post("/investigations/INV-1/lift")
    r = decide(world, app_id, "approve")
    assert r.status_code == 409
    # 过期的未决申请不能按旧结论批准；审核人驳回后申请人方可重新申请
    assert decide(world, app_id, "reject",
                  reject_reason="封存解除前后结论不一致，退回重报").status_code == 200
    new_id = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, new_id, "approve").status_code == 200
    assert issue(world, "OUT-1", app_id=new_id).status_code == 201


def test_hold_after_approval_blocks_issue(world):
    app_id = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, app_id, "approve").status_code == 200
    world.post("/investigations", json={
        "investigation_id": "INV-1", "batch_id": "OUT-1",
        "reason": "成品疑似污染"})
    r = issue(world, "OUT-1", app_id=app_id)
    assert r.status_code == 409
    assert "封存" in r.json()["detail"]


# ---------------------------------------------------------------- 签发校验

def test_issue_with_unknown_approval_404(world):
    assert issue(world, "OUT-1", app_id=404404).status_code == 404


def test_issue_with_approval_of_other_batch_400(world):
    material(world, "RM-2", allergens=["soy"])
    a1 = apply(world, "OUT-1").json()["application_id"]
    a2 = apply(world, "RM-2").json()["application_id"]
    assert decide(world, a1, "approve").status_code == 200
    assert decide(world, a2, "approve").status_code == 200
    r = issue(world, "OUT-1", app_id=a2)
    assert r.status_code == 400
    assert "属于批次" in r.json()["detail"]


def test_approval_record_cannot_be_reused_for_second_label(world):
    app_id = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, app_id, "approve").status_code == 200
    assert issue(world, "OUT-1", app_id=app_id).status_code == 201
    r = issue(world, "OUT-1", app_id=app_id)
    assert r.status_code == 409
    assert "不可重复签发" in r.json()["detail"]


def test_approved_application_can_be_withdrawn_by_rejection_then_reapply(world):
    """已批准但签发前结论变化：审核人可撤销批准并驳回，申请人重新申请。"""
    app_id = apply(world, "OUT-1", cursor=2).json()["application_id"]
    assert decide(world, app_id, "approve").status_code == 200
    world.post("/materials/RM-MILK/declarations", json={
        "allergens": ["milk", "peanut"]})
    # 不能重复批准
    assert decide(world, app_id, "approve").status_code == 409
    # 撤销批准并驳回（驳回不要求结论新鲜度）
    r = decide(world, app_id, "reject",
               reject_reason="批准后结论变化，撤销批准，退回重报")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    # rejected 终态：再次驳回/批准仍 409
    assert decide(world, app_id, "approve").status_code == 409
    assert decide(world, app_id, "reject",
                  reject_reason="x").status_code == 409
    # 重新申请 -> 批准 -> 签发
    new_id = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, new_id, "approve").status_code == 200
    label = issue(world, "OUT-1", app_id=new_id)
    assert label.status_code == 201
    assert label.json()["conclusion"]["allergens"] == ["milk", "peanut"]


def test_issue_with_supersedes_id_and_approval(world):
    first_app = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, first_app, "approve").status_code == 200
    l1 = issue(world, "OUT-1", app_id=first_app).json()["label_id"]

    second_app = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, second_app, "approve").status_code == 200
    r = issue(world, "OUT-1", app_id=second_app, supersedes_id=l1)
    assert r.status_code == 201
    assert r.json()["supersedes_id"] == l1
    assert r.json()["approval_id"] == second_app


# ---------------------------------------------------------------- 兼容性

def test_direct_issue_path_still_works(world):
    """不带 approval_id 的直接签发路径保持历史行为。"""
    r = issue(world, "OUT-1")
    assert r.status_code == 201
    assert r.json()["approval_id"] is None


def test_direct_issue_blocked_when_held(world):
    world.post("/investigations", json={
        "investigation_id": "INV-1", "batch_id": "OUT-1", "reason": "x"})
    assert issue(world, "OUT-1").status_code == 409


def test_approval_flow_emits_no_trace_events(world):
    before = world.get("/changes/snapshot").json()["cursor"]
    app_id = apply(world, "OUT-1").json()["application_id"]
    assert decide(world, app_id, "approve").status_code == 200
    assert issue(world, "OUT-1", app_id=app_id).status_code == 201
    after = world.get("/changes/snapshot").json()["cursor"]
    assert before == after  # 申请/审批/签发均不改实时溯源，不产事件


def test_idempotent_replay_after_events_still_returns_original(world):
    first = apply(world, "OUT-1", cursor=2)
    assert first.status_code == 201
    # 新写入产生事件后，同一未决申请重放仍返回原记录，并标出落后/过期
    world.post("/materials/RM-MILK/declarations", json={
        "allergens": ["milk", "peanut"]})
    second = apply(world, "OUT-1", cursor=2)
    assert second.status_code == 200
    body = second.json()
    assert body["replayed"] is True
    assert body["application_id"] == first.json()["application_id"]
    assert body["conclusion_stale"] is True
    assert body["cursor_behind"] is True


# ---------------------------------------------------------------- 列表/过滤

def test_list_and_filter_applications(world):
    a1 = apply(world, "OUT-1", applicant="qc-zhang").json()["application_id"]
    a2 = apply(world, "OUT-1", applicant="qc-wang").json()["application_id"]
    decide(world, a1, "reject", reject_reason="退回")

    listing = world.get("/label-applications").json()["applications"]
    assert [a["application_id"] for a in listing] == [a1, a2]

    pending = world.get("/label-applications?status=pending").json()["applications"]
    assert [a["application_id"] for a in pending] == [a2]

    rejected = world.get(
        "/label-applications?status=rejected").json()["applications"]
    assert [a["application_id"] for a in rejected] == [a1]

    by_batch = world.get(
        "/label-applications?batch_id=OUT-1").json()["applications"]
    assert len(by_batch) == 2
    assert world.get(
        "/label-applications?status=bogus").status_code == 400
