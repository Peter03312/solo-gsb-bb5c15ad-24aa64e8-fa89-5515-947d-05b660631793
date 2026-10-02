#!/usr/bin/env bash
# 标签签发审批（可审计申请-批准/驳回-签发）端到端演示：
#   基础数据 -> 提交签发申请（批次/申请人/理由/备注/游标）-> 审核批准 ->
#   凭批准记录签发（冻结申请时结论、绑定批准记录）->
#   结论变化后旧申请禁止批准/签发（需重新申请）-> 封存拦截 -> 重复提交幂等/错误约定
# 用法：BASE=http://localhost:8000 ./examples/demo_label_approvals.sh
set -euo pipefail
BASE="${BASE:-http://localhost:8000}"

step() { echo -e "\n\033[1;36m== $* ==\033[0m"; }
req() { # METHOD PATH JSON
  local method="$1" path="$2" body="${3:-}"
  if [ -n "$body" ]; then
    curl -sS -X "$method" "$BASE$path" -H 'Content-Type: application/json' -d "$body"
  else
    curl -sS -X "$method" "$BASE$path"
  fi
  echo
}
q() { python3 -c 'import sys,json;d=json.load(sys.stdin);print(json.dumps(d,ensure_ascii=False,indent=2))'; }
jsonf() { python3 -c "import sys,json;print(json.load(sys.stdin)['$1'])"; }

step "0. 基础数据：奶原料 -> P1/EQ-1 -> OUT-1；再取当前溯源游标"
req POST /materials '{"batch_id":"RM-MILK","allergens":["milk"],"declared_at":"2026-01-02T06:00:00Z"}'
req POST /processings '{"processing_id":"P1","equipment_id":"EQ-1","start_utc":"2026-01-02T08:00:00Z","end_utc":"2026-01-02T09:00:00Z","inputs":["RM-MILK"],"outputs":["OUT-1"]}'
CURSOR="$(curl -sS "$BASE/changes/snapshot" | jsonf cursor)"
echo "当前溯源游标 cursor=$CURSOR"

step "1. 质控提交签发申请（批次号 + 申请人 + 审批理由 + 拟签发标签备注 + 当前游标）"
APP_JSON="$(curl -sS "$BASE/label-applications" -H 'Content-Type: application/json' -d "{
  \"batch_id\":\"OUT-1\",\"applicant\":\"qc-zhang\",\"reason\":\"2026W40 出厂批次标签签发\",
  \"label_note\":\"共线复核通过，含奶残留提示\",\"cursor\":$CURSOR}")"
echo "$APP_JSON" | q
APP_ID="$(echo "$APP_JSON" | jsonf application_id)"

step "1b. 重复提交同一未决申请 -> 幂等（200, replayed=true，不产生新记录）"
req POST /label-applications "{
  \"batch_id\":\"OUT-1\",\"applicant\":\"qc-zhang\",\"reason\":\"2026W40 出厂批次标签签发\",
  \"label_note\":\"共线复核通过，含奶残留提示\",\"cursor\":$CURSOR}"

step "1c. 错误约定：未知批次 400 / 缺理由 422 / 游标越界 400 / 同批次同人不同内容 409"
req POST /label-applications '{"batch_id":"GHOST","applicant":"qc-zhang","reason":"x","cursor":0}'
req POST /label-applications '{"batch_id":"OUT-1","applicant":"qc-zhang","reason":"","cursor":0}'
req POST /label-applications '{"batch_id":"OUT-1","applicant":"qc-zhang","reason":"x","cursor":999999}'
req POST /label-applications '{"batch_id":"OUT-1","applicant":"qc-zhang","reason":"另一个理由","cursor":0}'

step "2. 审核人批准（未批准前签发会 409；申请时已封存则不能批准）"
req POST "/label-applications/$APP_ID/decision" '{"decision":"approve","reviewer":"reviewer-li","note":"依据齐全，同意签发"}'
req GET "/label-applications/$APP_ID" | q

step "3. 凭批准记录签发标签：绑定批准记录，快照冻结【申请时】结论"
LABEL_JSON="$(curl -sS "$BASE/batches/OUT-1/labels" -H 'Content-Type: application/json' \
  -d "{\"approval_id\":$APP_ID}")"
echo "$LABEL_JSON" | q
LABEL_ID="$(echo "$LABEL_JSON" | jsonf label_id)"
echo "申请状态 -> issued；批准记录不可重复签发（再次签发 409）"
req POST /batches/OUT-1/labels "{\"approval_id\":$APP_ID}"

step "4. 标签查询兼容：单查/列表均保留 conclusion/basis 快照，新增 approval_id"
req GET "/labels/$LABEL_ID"
req GET /batches/OUT-1/labels

step "5. 结论变化场景：新申请批准后、签发前上游声明更正 -> 禁止签发，要求重新申请"
APP2="$(req POST /label-applications "{
  \"batch_id\":\"OUT-1\",\"applicant\":\"qc-zhang\",\"reason\":\"换版重签\",\"label_note\":\"v2\",
  \"cursor\":$CURSOR}" | jsonf application_id)"
req POST "/label-applications/$APP2/decision" '{"decision":"approve","reviewer":"reviewer-li"}' >/dev/null
# 签发前上游声明变化（增加 sesame）
req POST /materials/RM-MILK/declarations '{"allergens":["milk","sesame"]}'
req GET "/label-applications/$APP2" | q   # conclusion_stale=true
req POST /batches/OUT-1/labels "{\"approval_id\":$APP2}"   # 409：结论已变化，禁止签发

step "6. 审核人驳回过期申请 -> 申请人以当前结论重新申请 -> 批准 -> 签发（新快照含 sesame）"
req POST "/label-applications/$APP2/decision" '{"decision":"reject","reviewer":"reviewer-li","reject_reason":"结论已变化，按当前结论重新申请"}'
NEW_CURSOR="$(curl -sS "$BASE/changes/snapshot" | jsonf cursor)"
APP3="$(req POST /label-applications "{
  \"batch_id\":\"OUT-1\",\"applicant\":\"qc-zhang\",\"reason\":\"换版重签\",\"label_note\":\"v2\",
  \"cursor\":$NEW_CURSOR}" | jsonf application_id)"
req POST "/label-applications/$APP3/decision" '{"decision":"approve","reviewer":"reviewer-li"}' >/dev/null
req POST /batches/OUT-1/labels "{\"approval_id\":$APP3,\"supersedes_id\":$LABEL_ID}" | q

step "7. 封存拦截：对被封存批次提交申请可受理（如实返回 held），但审核批准 409、签发 409"
req POST /investigations '{"investigation_id":"INV-HOLD-1","batch_id":"OUT-1","reason":"成品疑似交叉接触"}'
req POST /label-applications '{"batch_id":"OUT-1","applicant":"qc-wang","reason":"封存期间申请","cursor":0}' | q
APP4="$(req GET '/label-applications?status=pending&batch_id=OUT-1' | python3 -c 'import sys,json;print(json.load(sys.stdin)["applications"][-1]["application_id"])')"
req POST "/label-applications/$APP4/decision" '{"decision":"approve","reviewer":"reviewer-li"}'

step "8. 审计查询：全部申请（含审核人/时间/驳回原因/冻结结论），可按 status、batch_id 过滤"
req GET /label-applications | q
req GET '/label-applications?status=issued&batch_id=OUT-1'
