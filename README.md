# 过敏原溯源服务（共线生产食品批次）

基于 **Python + FastAPI + SQLite** 的过敏原溯源服务，面向共线（共享设备）生产场景：

- 登记**原料批次**的过敏原集合或**待确认**状态（声明可更正，保留版本历史）；
- 登记**加工批次**：设备、UTC 起止时间、投入批次、产出批次；
  已登记加工的**投入登记错误可纠正**（整表替换投入列表，加工号/设备/时段/产出不变，
  同事务校验、随后按现有规则实时重算并仅为实际变化批次记录事件）；
- 产出继承投入的过敏原/待确认状态，并继承**设备上一次加工的残留**；
  只有两次加工之间**已验证且未撤销**的清洗才清除残留；
- 查询任一批次，返回**每项过敏原与待确认状态的来源路径**及当前有效依据；
- 原料声明更正、清洗撤销正式落库前可先**预演（不落库）**：返回确有差异的下游
  批次（过敏原、待确认状态、来源路径及依据的前后变化，设备残留传播同样计入）、
  这些批次**已签发标签**相对变更前后实时结论的差异，以及一次性提交凭据；
  提交时若影响差异的记录已变化则拒绝（需重新预演），无关记录更新不使凭据失效；
- 原料声明更正、清洗撤销后，**未签发结论按当前有效记录实时重算**；
- **签发标签**冻结签发时刻的结论与依据，后续变更不改旧标签，
  可签发关联旧版（`supersedes_id`）的新标签；
  标签签发纳入**可审计审批环节**：质控提交“批次号 + 申请人 + 审批理由 +
  拟签发标签备注 + 当前溯源游标”的签发申请，系统冻结申请时结论并返回实时
  过敏原/待确认/封存状态与依据摘要；审核人仅在申请仍对应同一批次结论且未封存
  时批准（或驳回），批准后签发必须绑定批准记录并冻结**申请时**结论，
  驳回或结论/封存变化禁止签发并要求重新申请；
- **变更事件订阅**：下游按游标增量同步——初始化读取返回同一状态下的现存批次
  实时结论与游标，之后分页读取事件（全局递增序号、触发操作、批次号、变更前后
  完整结论与依据）；业务写入与事件同事务，失败/预演/无实际变化不产事件；
- 无效时序、来源环、设备时间重叠、批次来源冲突一律**拒绝并保持原状态**
  （校验与写入在同一事务内，失败即回滚）。
- **疑似交叉接触调查封存**：质控以批次号、唯一调查号、原因登记调查；系统沿**加工投入链**
  及**同设备相邻加工的残留链**（有效清洗截断残留传播）实时计算受影响批次；
  **封存与过敏原声明是否为空无关**。按批次可查询放行状态、仍生效调查号与各自传播路径；
  多调查叠加时解除其中一个只移除该调查自身的影响。封存批次**不得签发新标签、不得
  作为新加工投入**；若设备残留会使新加工产出受封存影响，加工登记同样拒绝，失败不留
  加工或标签。投入纠正、清洗登记/撤销、调查登记/解除后同步重算封存状态，
  并沿用游标事件流发布实际变化；旧标签快照不变，既有溯源结论字段保持兼容。
- **过敏原代码并码**：质控以“旧代码 + 目标代码 + 必填原因”登记同义代码合并，
  并码**可串接**；查询代码返回最终规范代码与沿革。目标须非空且当前不是别名，
  自映射/成环/同一旧代码生效中改指其他目标一律**拒绝且不留记录**，同向重试幂等
  返回原结果（**仅对生效关系幂等**）。并码登记有误可凭**并码记录号 + 必填原因
  撤销单条关系**：撤销行保留可查原登记及撤销原因/时间，代码查询仅按**生效链**
  给出规范码与沿革；串接链按仍生效的关系解析（A→B→C 中撤销 B→C 后 A 归 B，
  撤销 A→B 后 B 仍归 C）；同一旧代码撤销后可**重新并入**当前非别名目标（新登记
  为新记录）。原料声明版本与已签发标签快照**保留原始代码**；实时溯源按最终规范
  代码**合并同义项并去重**，同时保留每条原始来源路径、声明版本，待确认状态
  不变。并码登记/撤销后重算受影响批次（含设备残留下游），沿用既有事件字段与
  全局顺序，仅为实际变化记录事件（撤销 `op` = `allergen_code_merge_revocation`）；
  业务写入与事件同事务、历史事件不可改写，并码登记/撤销使未提交预演凭据失效。
  新原料登记、声明更正与预演均按当前并码关系解释代码，既有接口字段与路径
  结构保持兼容。

## 快速启动

### Docker Compose（推荐，一键启动）

```bash
docker compose up --build
```

依赖安装与数据库初始化（建表）均在容器启动时自动完成，无需额外步骤。

### 本地运行

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 运行测试

```bash
pip install -r requirements-dev.txt
pytest tests/ -q
```

## 地址与端口

| 项目 | 地址 |
|---|---|
| 服务地址 | http://localhost:8000 |
| 交互式 API 文档 (Swagger) | http://localhost:8000/docs |
| OpenAPI 规格 | http://localhost:8000/openapi.json |
| 健康检查 | http://localhost:8000/health |

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_PORT` | `8000` | 服务监听端口（Compose 下同时作为宿主机映射端口） |
| `DB_PATH` | 容器内 `/data/allergen.db`，本地 `app.db` | SQLite 数据库文件路径 |

修改宿主机端口：`APP_PORT=9000 docker compose up --build`，然后访问 http://localhost:9000 。

## 数据与规则模型

- **原料批次**：当前有效声明 = 最新版本声明（过敏原集合 + 是否待确认）。
- **批次可用时间**：原料 = 首次登记时间；加工产出 = 产出加工的结束时间。
  投入批次的可用时间必须 ≤ 加工开始时间。
- **设备残留**：加工开始时，若同一设备存在上一次加工（`end_utc ≤ 本次 start_utc`），
  且两次加工之间没有 `verified=true 且未撤销` 的清洗
  （`上次 end_utc ≤ cleaned_at ≤ 本次 start_utc`），
  则上一次加工产出的全部过敏原/待确认状态作为残留继承。
- **标签**：签发时将结论（每项过敏原/待确认的来源路径）与依据
  （命中的原料声明版本、赖以清除残留的清洗记录）整体冻结为快照，永不可变。
- **过敏原代码并码**：`allergen_code_merges` 记录 `旧代码 -> 目标代码`（必填
  原因），每个旧代码至多一条**生效中**的记录（部分唯一索引）；目标自身可再被
  并码形成串接链。记录可凭记录号**撤销**（`revoked=1` + 必填撤销原因 + 撤销
  时间，行保留不删）；登记与读取（含撤销）**不改写**任何已存储的声明版本或
  标签快照；实时溯源时沿**生效**并码链把声明代码解析到最终规范代码，同义项
  合并、按完整路径去重，仅在该代码确为别名时于声明步骤附加 `allergen_code`
  （原始代码）/ `canonical_code`（规范代码），无并码时步骤结构与历史完全一致。
  旧版库（`old_code` 列级 UNIQUE、无撤销列）在服务启动时**自动幂等迁移**：
  重建表结构并搬移既有行（`merge_id` 保持不变），无需人工干预。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/materials` | 登记原料批次（过敏原集合或待确认状态） |
| GET | `/materials` / `/materials/{batch_id}` | 查询原料批次及当前有效声明 |
| POST | `/materials/{batch_id}/declarations` | 更正声明（追加新版本） |
| POST | `/materials/{batch_id}/declarations/preview` | 声明更正预演（不落库），返回差异报告 + 提交凭据 |
| POST | `/processings` | 登记加工批次（含全部校验） |
| POST | `/processings/{id}/inputs/correction` | 纠正加工投入（整表替换，加工号/设备/时段/产出不变） |
| GET | `/processings` / `/processings/{id}` | 查询加工批次 |
| POST | `/cleanings` | 登记设备清洗（`verified` 标记是否已验证） |
| GET | `/cleanings` / `/cleanings/{id}` | 查询清洗记录（可按 `?equipment_id=` 过滤） |
| POST | `/cleanings/{id}/revoke` | 撤销清洗验证 |
| POST | `/cleanings/{id}/revoke/preview` | 清洗撤销预演（不落库），返回差异报告 + 提交凭据 |
| POST | `/previews/{preview_id}/commit` | 凭预演凭据原子应用变更（一次性） |
| GET | `/batches/{batch_id}/trace` | 实时溯源：每项过敏原/待确认的来源路径 + 依据 + 封存状态 |
| GET | `/batches/{batch_id}/release` | 按批次查询放行状态：封存状态、仍生效调查号与各自传播路径 |
| POST | `/investigations` | 登记疑似交叉接触调查封存（批次号 + 唯一调查号 + 原因） |
| GET | `/investigations` / `/investigations/{id}` | 查询调查（可按 `?status=open/lifted` 过滤）及受影响批次/路径 |
| POST | `/investigations/{id}/lift` | 解除调查封存（仅移除该调查自身的影响；重复解除报错） |
| POST | `/batches/{batch_id}/labels` | 签发标签（封存批次拒绝；可带 `supersedes_id`；带 `approval_id` 走审批签发） |
| GET | `/batches/{batch_id}/labels` / `/labels/{id}` | 查询标签 |
| POST | `/label-applications` | 提交标签签发申请（批次/申请人/理由/备注/游标；重复未决申请幂等） |
| GET | `/label-applications` / `/label-applications/{id}` | 查询签发申请（可按 `?status=&batch_id=` 过滤；单条含冻结结论与当前对比） |
| POST | `/label-applications/{id}/decision` | 审核批准 `approve` / 驳回 `reject`（审核人必填；驳回必填原因） |
| GET | `/changes/snapshot` | 初始化读取：同一状态下的现存批次实时结论 + 游标 |
| GET | `/changes/events` | 按游标分页读取变更事件（固定上界，无效游标拒绝） |
| POST | `/allergen-merges` | 登记过敏原代码并码（旧代码 + 目标代码 + 必填原因；同向重试幂等，撤销后可重新并码） |
| GET | `/allergen-merges` | 列出全部并码登记（按登记顺序；撤销行保留，带撤销原因/时间） |
| GET | `/allergen-merges/{merge_id}` | 查询单条并码登记（含原登记信息及撤销原因/时间） |
| POST | `/allergen-merges/{merge_id}/revoke` | 撤销单条并码关系（必填撤销原因；仅该行失效，可重新并码） |
| GET | `/allergen-codes/{code}` | 查询代码：按**生效链**给出最终规范代码 `canonical_code` 与并码沿革 `history` |

错误约定：`400` 无效时序/参数（如投入批次在加工开始前不可用、无效游标、
登记调查时批次未知、非法 `status` 过滤、并码旧代码未在任何现存声明中出现、
签发申请批次未知、申请游标越界、审批签发跨批次）；
`404` 资源不存在（含未知签发申请/批准记录、未知标签）；
`409` 冲突（设备时间重叠、来源环、批次号占用、重复撤销、
重复调查号、重复解除、对封存批次签发标签或以封存批次/受封存残留登记新加工、
预演凭据不存在/已使用/已过期，或影响差异的记录已变化需重新预演；并码自映射、
目标当前为别名、同一旧代码生效中改指其他目标、并码记录重复撤销；
同一（批次, 申请人）不同内容的未决签发申请重复提交、已处理申请重复审批、
未批准/已驳回/结论或封存已变化的申请签发标签、同一批准记录重复签发）；
`422` 请求格式错误（如时间缺少时区、调查字段为空白、并码/撤销原因为空白、
申请理由/审核人为空白、驳回缺少原因、游标为负数）。所有时间必须为带时区的 ISO8601（建议 UTC `Z`）。

## 变更预演（dry-run）与凭据提交

在**原料声明更正**或**清洗撤销**正式落库前，可先对“拟变更”进行预演。预演只在
内存中叠加假设状态重算，**不写库**；已有更正、撤销与标签查询接口完全兼容，
已签发标签永不改写。

预演响应（`dry_run=true, applied=false`）包含：

- `preview_id`：提交凭据（进程内一次性令牌，服务重启后失效，需重新预演）；
- `change`：拟应用的变更（类型、目标、新版本号/清洗记录等）；
- `affected_batches[]`：仅列**变更前后确有差异**的批次（含原料目标本身；
  设备残留传播的下游批次同样计入），每项含：
  - `before` / `after`：完整实时结论（过敏原集合、待确认、逐项来源路径）与依据
    （命中的原料声明版本、赖以清除残留的清洗）；
  - `diff`：结论差异（过敏原 `added/removed`、`pending` 翻转、来源路径前后对照）
    与依据差异（声明版本、清洗依据的前后对照）；
  - `issued_labels[]`：该批次每张已签发标签的冻结结论，以及
    `diff_vs_before` / `diff_vs_after`（标签相对变更前、变更后实时结论的差异，
    无差异为 `null`）；
- `commit`：提交方法与路径。

提交 `POST /previews/{preview_id}/commit` 在单个 `BEGIN IMMEDIATE` 事务内重新核对
指纹并写入：若**影响本次差异**的记录（目标/路径上的原料声明版本、相关加工及其
残留窗口内有效的清洗、受影响批次的已签发标签）与预演时一致，则原子应用并返回
实际影响报告（`dry_run=false, applied=true`，结构与预演相同）；否则 `409` 拒绝、
不落库并要求重新预演。无关记录（其他原料/设备上的加工、窗口内未验证或已撤销的
清洗、不受影响批次的标签等）的新增更新**不会**使凭据失效。

```bash
BASE=http://localhost:8000

# 预演声明更正（过敏原 + 待确认），不落库
curl -s $BASE/materials/RM-OAT/declarations/preview -X POST \
  -H 'Content-Type: application/json' \
  -d '{"allergens": ["gluten", "sesame"], "pending": false}'

# 预演清洗撤销（设备残留恢复计入下游批次）
curl -s $BASE/cleanings/1/revoke/preview -X POST

# 用上一步返回的 preview_id 原子提交（返回实际影响）
curl -s $BASE/previews/<preview_id>/commit -X POST
```

## 加工投入纠正

加工已登记后若发现**投入批次登记错误**，可用加工号 + **完整的正确投入列表**
纠正记录：

```
POST /processings/{processing_id}/inputs/correction
{"inputs": ["RM-A", "RM-B"]}
```

规则：

- 请求体为**整表替换**（不是增量补丁），须提交完整的正确投入列表；
- **原加工号、设备、起止时段、产出批次保持原值**，只替换投入边；
- 投入须**非空、无重复、均已登记且在加工开始前可用**（可用时间口径与登记一致：
  原料=首次登记时间，加工产出=产出加工结束时间）；纠正后的来源关系**不得成环**
  （本加工产出不得是新投入，且其下游不得间接到达任一新投入）；
- **校验与替换在同一 `BEGIN IMMEDIATE` 事务内完成**，任一校验失败即回滚，
  记录与事件均保持原状；加工号不存在返回 `404`，未登记/开工前不可用 `400`，
  成环 `409`，空列表/重复 `422`；
- 替换后按现有规则**实时重算相关批次**的过敏原、待确认状态、来源路径与依据，
  包括沿同设备**后续加工的残留传播**；已签发标签**保留原快照**不受影响；
- 变更沿用既有变更订阅事件的字段与全局递增序号：`op` =
  `processing_input_correction`，`op_ref` = `{"processing_id": "..."}`，
  同次纠错**仅为实际变化的批次按批次号顺序**记录事件（固定上界分页等约定不变）；
  **投入集合未变时不替换、不产生事件**（按集合比较，顺序不同视为未变）。

```bash
BASE=http://localhost:8000

# 纠正 P2 的投入（原误登为 RM-MILK，实际为 RM-OAT）；设备/时段/产出不变
curl -s $BASE/processings/P2/inputs/correction -X POST \
  -H 'Content-Type: application/json' \
  -d '{"inputs": ["RM-OAT"]}'

# 多投入的完整正确列表
curl -s $BASE/processings/P2/inputs/correction -X POST \
  -H 'Content-Type: application/json' \
  -d '{"inputs": ["RM-OAT", "RM-SOY"]}'

# 实时溯源随之重算（含后续设备残留下游）；已签发标签仍是签发时快照
curl -s $BASE/batches/OUT-OAT-1/trace
```

## 变更事件订阅（游标增量同步）

下游系统按“**初始化快照 + 游标增量事件**”两阶段同步溯源变化：

1. **初始化读取** `GET /changes/snapshot`：在一致快照（读事务）内返回
   `cursor` 与现存全部批次的实时结论（`conclusion`：过敏原/待确认/来源路径）
   与依据（`basis`：命中的声明版本、清除残留的清洗），按批次号排序。
2. **增量读取** `GET /changes/events?cursor=<c>&limit=<n>[&upper=<u>]`：
   从快照游标（或上一页 `next_cursor`）起，按 `seq` 升序分页拉取事件，
   逐条应用到本地副本即可与线上结论保持一致。

每条事件：

```json
{
  "seq": 14,                                  // 全局递增序号
  "op": "declaration_correction",             // 触发操作
  "op_ref": {"batch_id": "RM-OAT", "new_version": 4, "via": "direct"},
  "batch_id": "OUT-OAT-1",                    // 批次号
  "kind": "product",
  "before": {"conclusion": {...}, "basis": {...}},   // 变更前完整结论与依据
  "after":  {"conclusion": {...}, "basis": {...}},   // 变更后完整结论与依据
  "recorded_at": "2026-09-30T08:00:00Z"
}
```

事件生成规则：

- **触发操作**（`op`）：`material_register`（原料登记）、`declaration_correction`
  （原料更正，含预演提交，`op_ref.via` 区分 `direct` / `preview_commit`）、
  `processing_register`（加工登记）、`processing_input_correction`（加工投入纠正，
  `op_ref` 为 `{"processing_id": ...}`）、`cleaning_register`（清洗登记）、
  `cleaning_revocation`（清洗撤销，含预演提交）、`investigation_open`
  （调查封存登记）、`investigation_lift`（调查封存解除）、
  `allergen_code_merge`（过敏原代码并码登记，
  `op_ref` 为 `{"merge_id", "old_code", "target_code"}`；事件 after 中过敏原
  按最终规范代码合并、路径步骤保留原始代码）、
  `allergen_code_merge_revocation`（过敏原代码并码撤销，
  `op_ref` 为 `{"merge_id", "old_code", "target_code", "reason"}`；仅单条关系
  失效，按仍生效链重算，事件追加写入、历史事件不可改写）。
  封存类事件的视图在既有 `conclusion`/`basis` 外新增 `release` 字段
  （`held` + 生效调查及传播路径）；旧字段结构不变，事件重放与快照保持兼容。
- **新批次**（原料登记、加工产出）`before` 为 `null`（前态为空）。
- 仅为**结论、来源路径或依据确有变化**的批次生成事件；同次操作的多条事件
  按批次号排序（`seq` 升序即批次号序）。
- 业务写入与事件在**同一事务**落库：校验失败回滚、预演（dry-run）均不产事件；
  未验证清洗、窗口外清洗、标签签发等不改变实时溯源的操作也不产事件，
  已签发标签永远不改写。
- 乱序补登加工（插入到同设备两次加工之间）会改变后续批次的残留来源，
  这类既有批次的结论/路径变化同样产生事件。

分页与游标约定：

- 首页可不传 `upper`，服务端固定本次分页会话的上界为当前最大 `seq` 并在
  响应中返回；**翻页时原样回传 `upper`**，分页期间的新写入（`seq > upper`）
  不会进入已开始的读取。
- 响应字段：`events`、`next_cursor`（下一页游标）、`upper`（固定上界）、
  `has_more`（`next_cursor < upper`）、`latest`（当前最大序号；
  `latest > upper` 表示分页期间有新写入，本轮读完后可开启新一轮）。
- 无效游标（负数、超过当前最大序号、`upper < cursor` 或 `upper` 超界）
  返回 `400`；非整数参数返回 `422`。

```bash
BASE=http://localhost:8000

# 1) 初始化：拿到游标与现存批次实时结论
CURSOR=$(curl -s $BASE/changes/snapshot | python3 -c 'import sys,json;print(json.load(sys.stdin)["cursor"])')

# 2) 增量：首页（服务端固定上界 upper）
curl -s "$BASE/changes/events?cursor=$CURSOR&limit=100"
# -> {"events":[...], "next_cursor":N, "upper":U, "has_more":true, "latest":L}

# 3) 翻页：回传固定上界，直到 has_more=false
curl -s "$BASE/changes/events?cursor=N&limit=100&upper=U"

# 4) 本轮读完后，用 next_cursor 开启新一轮（重新固定上界）
curl -s "$BASE/changes/events?cursor=U&limit=100"
```

## 调用示例（curl）

完整演示脚本（覆盖下述全部流程）：`./examples/demo.sh`

```bash
BASE=http://localhost:8000

# 1. 登记原料批次
curl -s $BASE/materials -X POST -H 'Content-Type: application/json' -d '{
  "batch_id": "RM-MILK", "allergens": ["milk"],
  "declared_at": "2026-01-02T06:00:00Z"}'
curl -s $BASE/materials -X POST -H 'Content-Type: application/json' -d '{
  "batch_id": "RM-MYST", "pending": true,
  "declared_at": "2026-01-02T06:00:00Z"}'   # 待确认状态

# 2. 登记加工批次（同一设备 EQ-1 先后两批）
curl -s $BASE/processings -X POST -H 'Content-Type: application/json' -d '{
  "processing_id": "P1", "equipment_id": "EQ-1",
  "start_utc": "2026-01-02T08:00:00Z", "end_utc": "2026-01-02T09:00:00Z",
  "inputs": ["RM-MILK"], "outputs": ["OUT-MILK-1"]}'
curl -s $BASE/processings -X POST -H 'Content-Type: application/json' -d '{
  "processing_id": "P2", "equipment_id": "EQ-1",
  "start_utc": "2026-01-02T10:00:00Z", "end_utc": "2026-01-02T11:00:00Z",
  "inputs": ["RM-OAT"], "outputs": ["OUT-OAT-1"]}'

# 3. 溯源：milk 经设备残留进入 OUT-OAT-1，路径逐步可见
curl -s $BASE/batches/OUT-OAT-1/trace
# -> allergen_paths.milk: RM-MILK --(P1, input)--> OUT-MILK-1
#    --(P2, equipment_residue, EQ-1)--> OUT-OAT-1

# 4. 两次加工之间的已验证清洗 -> 残留清除
curl -s $BASE/cleanings -X POST -H 'Content-Type: application/json' -d '{
  "equipment_id": "EQ-1", "cleaned_at": "2026-01-02T09:30:00Z", "verified": true}'

# 5. 撤销清洗 -> 未签发结论实时重算，milk 残留恢复
curl -s $BASE/cleanings/1/revoke -X POST

# 6. 原料声明更正（追加版本，实时结论随之更新）
curl -s $BASE/materials/RM-OAT/declarations -X POST \
  -H 'Content-Type: application/json' \
  -d '{"allergens": ["gluten", "sesame"]}'

# 6b. 也可以先预演再凭凭据提交（预演不落库；示例见上节“变更预演”）
curl -s $BASE/materials/RM-OAT/declarations/preview -X POST \
  -H 'Content-Type: application/json' \
  -d '{"allergens": ["gluten", "sesame", "soy"]}'
# -> 返回 preview_id 后：curl -s $BASE/previews/<preview_id>/commit -X POST

# 7. 签发标签（冻结当前结论）；变更后签发关联旧版的新标签
curl -s $BASE/batches/OUT-OAT-1/labels -X POST \
  -H 'Content-Type: application/json' -d '{}'
curl -s $BASE/batches/OUT-OAT-1/labels -X POST \
  -H 'Content-Type: application/json' -d '{"supersedes_id": 1}'
curl -s $BASE/labels/1   # 旧标签保持签发时的结论不变
```

## 过敏原代码并码（同义代码合并）

质控发现声明中沿用了**旧过敏原代码**时，以“旧代码 + 目标代码 + 必填原因”
登记并码：

```
POST /allergen-merges
{"old_code": "casein", "target_code": "milk", "reason": "供应商代码勘误：酪蛋白并入 milk"}
```

规则：

- **登记校验（校验与写入同一 `BEGIN IMMEDIATE` 事务，失败回滚不留任何记录或
  事件）**：
  - 旧代码、目标代码、原因均非空（空白 `422`）；旧代码与目标代码相同的
    **自映射** `409`；
  - **目标代码当前不能是别名**（即不能存在以其为旧代码的**生效**并码，`409`）。
    要串接时以当前规范代码为目标（先 `casein -> dairy` 再 `dairy -> milk`），
    因此生效并码只能“接长”规范代码，生效链上不可能成环；
  - 旧代码须在**现存原料声明（含历史版本）**中出现，否则 `400`；
  - 每个旧代码同一时间至多一条**生效**并码（部分唯一索引）：生效中
    **改指其他目标** `409` 拒绝（错误信息提示先撤销原并码）；
  - **同向重试**（生效记录的 `old_code/target_code` 完全相同，原因可不同）
    幂等返回原登记，HTTP `200`、响应附 `"replayed": true`，不重复写、不产事件；
    新登记返回 `201`。**同向重试仅对生效关系幂等**——旧关系已撤销后再次提交
    相同请求是**重新登记**（`201`、新的 `merge_id`）。
- **撤销单条关系**：质控复核发现登记有误时，凭**并码记录号 + 必填撤销原因**
  撤销（`POST /allergen-merges/{merge_id}/revoke`）：
  - 只使**该单条关系**失效，撤销行保留（`status=revoked`、`revoked_reason`、
    `revoked_at`），可经 `GET /allergen-merges`（列表）或
    `GET /allergen-merges/{merge_id}`（单条）查原登记与撤销原因、时间；
  - 未知记录 `404`、重复撤销 `409`、空白原因 `422`，失败不留记录或事件；
  - **串接链按仍生效的关系解析**：A→B→C 中撤销 B→C 后 A 归 B（B 不再归 C），
    撤销 A→B 后 B 仍归 C；代码查询的 `history` 仅含仍生效的跳，已撤销的跳
    不出现在沿革中（撤销后该代码 `is_alias=false`，以自身为规范代码）；
  - **撤销后可重新并码**：同一旧代码可重新并入**当前非别名**目标（新登记为
    新记录）；撤销后并入当前别名目标、生效中改指等非法再并码一律 `409`
    拒绝且不留记录。
- **串接与查询**：`GET /allergen-codes/{code}` 返回
  `canonical_code`（沿**生效链**解析到的最终规范代码）、`is_alias` 与
  `history`（生效链上每一跳的
  `merge_id/old_code/target_code/reason/merged_at` 及状态字段）；
  未知代码以其自身为规范代码、沿革为空。`GET /allergen-merges` 列出全部登记
  （含撤销行，按登记顺序）。
- **历史不改写**：原料声明各版本与已签发标签快照中的原始代码**原样保留**
  （`GET /materials` 的 `allergens` 与标签 `conclusion` 不变；`allergens`
  之外附加 `allergens_canonical` 给出当前规范代码）。
- **实时溯源**：`/batches/{id}/trace`、事件视图与初始化快照按最终规范代码
  **合并同义项**（多个旧代码归到同一过敏原键）并**按完整路径去重**；
  每条来源路径仍逐步保留，别名声明步骤附 `allergen_code`/`canonical_code`
  （规范代码自身与无并码场景步骤结构不变），依据中的声明版本号不变；
  **待确认状态与代码无关，不受并码登记/撤销影响**；封存传播同样与代码无关、
  不变。
- **重算与事件**：登记或撤销后全量重算受影响批次（含沿同设备后续加工的
  **设备残留下游**），初始化快照反映新结论；沿用既有事件字段与全局递增序号，
  登记 `op` = `allergen_code_merge`（`op_ref` =
  `{"merge_id", "old_code", "target_code"}`），撤销 `op` =
  `allergen_code_merge_revocation`（`op_ref` 多一个撤销 `reason`）。
  **仅结论/路径/依据实际变化的批次按批次号顺序在同一事务**落事件；与该变动
  无关的过敏原（步骤逐字节未变）不产事件；校验失败、幂等重试不产事件；
  事件只追加、**历史事件不可改写**。
- **并发与预演**：并码登记/撤销与事件在同一事务原子提交（`BEGIN IMMEDIATE`
  串行化并发写）；预演凭据指纹纳入**全部并码行的生效状态与撤销信息**，预演
  期间任何并码登记**或撤销**都会使未提交凭据失效（提交 `409` 需重新预演），
  杜绝并码变动与声明更正并发提交出现混合状态。
- **新登记/更正按当前关系解释**：并码（含撤销、重新并码）后登记新原料、追加
  声明更正、声明更正预演中的过敏原代码均按当前生效并码关系解析（存储原始
  代码，实时出规范代码）。
- 既有接口的字段与路径结构保持兼容：变更仅为**新增键**（`allergens_canonical`、
  别名步骤上的两个代码字段、并码行上的状态/撤销字段、撤销与单条查询接口），
  无并码时所有响应与历史一致。

```bash
BASE=http://localhost:8000

# 登记并码（必填原因）；可串接
curl -s $BASE/allergen-merges -X POST -H 'Content-Type: application/json' \
  -d '{"old_code":"casein","target_code":"dairy","reason":"供应商代码勘误"}'
curl -s $BASE/allergen-merges -X POST -H 'Content-Type: application/json' \
  -d '{"old_code":"dairy","target_code":"milk","reason":"标准代码统一"}'

# 查询最终规范代码与并码沿革（仅生效链）
curl -s $BASE/allergen-codes/casein   # -> canonical_code=milk, history 两跳
curl -s $BASE/allergen-merges         # 撤销行也在列表中，带撤销原因/时间

# 实时溯源：同义项合并为 milk 并去重，路径步骤保留 allergen_code/canonical_code
curl -s $BASE/batches/OUT-9/trace

# 质控复核发现登记有误：凭并码记录号 + 必填原因撤销单条关系
curl -s $BASE/allergen-merges/2/revoke -X POST \
  -H 'Content-Type: application/json' \
  -d '{"reason":"复核：dairy->milk 登记有误，撤销"}'
# 撤销后：casein 沿剩余生效链归 dairy；撤销行保留可查
curl -s $BASE/allergen-codes/casein   # -> canonical_code=dairy, history 一跳
curl -s $BASE/allergen-merges/2       # -> status=revoked + 撤销原因/时间

# 同一旧代码撤销后可重新并入当前非别名目标（新记录，非幂等重试）
curl -s $BASE/allergen-merges -X POST -H 'Content-Type: application/json' \
  -d '{"old_code":"dairy","target_code":"whey","reason":"复核后改并 whey"}'
```

完整专项演示脚本：`./examples/demo_merges.sh`

## 调查封存（疑似交叉接触）

质控人员发现疑似交叉接触时，以**批次号、唯一调查号、原因**登记调查：

```
POST /investigations
{"investigation_id": "INV-2026-001", "batch_id": "RM-MILK",
 "reason": "共线生产疑似奶残留交叉接触"}
```

规则：

- **封存传播与过敏原内容无关**：无论批次过敏原声明/待确认状态是否为空，传播只按
  批次关系图计算。从疑似批次出发，沿两类边闭包传播：
  - **加工投入链**：投入批次 → 同加工的产出（路径步骤 `via=input`）；
  - **同设备相邻加工残留链**：上一次同设备加工产出 → 本次加工产出
    （`via=equipment_residue` 并带 `equipment_id`）；两次加工之间存在
    **已验证且未撤销**的清洗（端点时刻包含）时，该残留边被**截断**。
- 登记响应的 `affected_batches[]` 给出当前全部受影响批次及**各自传播路径**
  （根步骤 `via=investigation_root`，含调查号）；`GET /investigations?status=open`
  可过滤，已解除调查 `affected_batches` 为空。
- `GET /batches/{id}/release` 返回：
  - `release_status`：`held` / `releasable`；
  - `active_investigations[]`：**仍生效**的调查号、根批次、原因、开启时间与
    各自传播路径；实时溯源 `/batches/{id}/trace` 同步附 `release` 字段。
- **多调查叠加**：批次可同时被多个调查封存（调查号与路径分别保留）；
  `POST /investigations/{id}/lift` 解除时**只移除该调查自身的影响**，
  其他调查仍封存的批次保持封存。重复调查号 `409`、未知调查号解除 `404`、
  重复解除 `409`、登记时未知批次 `400`、空白字段 `422`。
- **封存约束（校验与写入同一事务，失败回滚不留痕）**：
  - 封存批次**不得签发新标签**（`409`）；旧标签快照不变，解除后可再签；
  - 封存批次**不得作为新加工投入**（`409`）；
  - 新加工在同设备上会继承到封存批次的残留、且两次加工间无有效清洗截断时，
    **登记同样拒绝**（`409`，错误信息指明封存残留批次），不留下加工或标签。
- **同步重算**：投入纠正（允许以封存批次作为纠正后投入）、清洗登记/撤销、
  调查登记/解除后，封存状态沿当前记录实时重算——有效清洗可解除下游封存，
  撤销清洗会恢复封存。
- **事件流**：封存状态变化沿用既有游标事件：`op` = `investigation_open` /
  `investigation_lift`，`op_ref` = `{"investigation_id": ...}`；事件 `before/after`
  为完整视图（既有 `conclusion`/`basis` 字段不变，新增 `release` 字段），
  仅封存状态实际变化的批次按批次号顺序落事件，分页/固定上界约定不变。
  初始化快照 `/changes/snapshot` 的每个批次也带 `release`。
- 封存状态对下游为**附加字段**：既有溯源结论字段、标签快照结构
  （仅 `conclusion`/`basis`）、事件重放语义完全兼容。

```bash
BASE=http://localhost:8000

# 登记调查封存（批次号 + 唯一调查号 + 原因）
curl -s $BASE/investigations -X POST -H 'Content-Type: application/json' -d '{
  "investigation_id": "INV-2026-001",
  "batch_id": "RM-MILK",
  "reason": "共线生产疑似奶残留交叉接触"}'

# 按批次查询放行状态、仍生效调查号与传播路径
curl -s $BASE/batches/OUT-OAT-1/release

# 封存批次的标签/新加工被拒绝（409，原子失败不留痕）
curl -i -s $BASE/batches/OUT-OAT-1/labels -X POST -H 'Content-Type: application/json' -d '{}'

# 登记有效清洗截断残留（同步重算，可能解除下游封存）或解除调查（只移除该调查影响）
curl -s $BASE/investigations/INV-2026-001/lift -X POST
```

## 标签签发审批（可审计）

标签签发前必须经过可审计的“**申请 → 审核 → 签发**”环节（也保留不带审批的
直接签发兼容路径，见末段）。所有申请、审核人与审核时间、驳回原因、冻结结论、
签发绑定关系均落库保留，可按申请号、批次与状态检索。

### 1. 质控提交签发申请

`POST /label-applications`，请求体：

```json
{
  "batch_id": "OUT-1",
  "applicant": "qc-zhang",
  "reason": "2026W40 出厂批次标签签发",
  "label_note": "共线复核通过，含奶残留提示",
  "cursor": 14
}
```

- 字段：批次号、申请人、**审批理由（必填）**、拟签发标签备注（可空）、
  **当前溯源游标**（即调用方已同步到的 `/changes/events` 游标）。
- 系统在受理事务内冻结申请时的完整视图并返回：
  - `allergens` / `pending` / `held_at_request`：申请时实时过敏原、待确认、
    封存状态；
  - `frozen_conclusion`、`basis`：申请时冻结的结论（含来源路径）与依据
    （命中的原料声明版本、残留清洗）；
  - `basis_summary`：依据摘要（过敏原/待确认/封存、生效调查号、命中的
    声明版本、清洗依据），供审核人快速判读；
  - `current`：当前实时过敏原/待确认/封存、最新游标；
  - `conclusion_stale`：当前结论是否已与申请冻结结论不一致；
    `cursor_behind`：受理后是否已有新事件。
- **幂等**：同一（批次, 申请人）存在 `pending` 申请时，以**完全相同**的理由与
  备注重复提交返回原申请（HTTP `200`、`"replayed": true`，不重复写）；
  不同内容重复提交 `409`。不同申请人各自独立。
- 未知批次 `400`；理由/申请人空白 `422`；游标负数/缺字段 `422`；
  游标超过当前最大事件序号（过期/未同步）`400`，需先按变更订阅同步后再申请。
- **封存不阻止申请**：封存批次的申请照常受理并如实返回 `held_at_request=true`，
  但审核批准与签发会被拒绝。

### 2. 审核人批准或驳回

`POST /label-applications/{id}/decision`：

```json
{"decision": "approve", "reviewer": "reviewer-li", "note": "依据齐全，同意签发"}
{"decision": "reject",  "reviewer": "reviewer-li", "reject_reason": "依据不完整，退回"}
```

- 审核人 `reviewer` 必填；**驳回必填 `reject_reason`**（空白 `422`），
  `note` 为可选审核备注。
- 批准仅在以下条件同时满足时成功（同一写事务内复核，失败不改状态）：
  1. 申请仍为 `pending`（已驳回/已签发为终态，重复审批 `409`）；
  2. 批次**当前结论与申请冻结结论完全一致**（过敏原、待确认、来源路径、依据，
     经规范化逐字节比对）——申请后声明更正、投入纠正、清洗登记/撤销、并码等
     任一使结论或依据变化，均不能按过期结论批准；
  3. 批次当前**未封存**（申请后新增封存、或申请时封存的状态发生变化，均拒绝）。
- 已 `approved` 但尚未签发的申请若在签发前过期（结论/封存变化），审核人可
  **撤销批准并驳回**（`reject`，驳回不校验新鲜度），申请人随后以当前结论
  重新申请；`rejected` / `issued` 为终态，不可再审批。
- 批准后申请状态为 `approved`，记录 `reviewer` / `reviewed_at` / `review_note`；
  驳回记录 `reject_reason`。未知申请 `404`。

### 3. 凭批准记录签发标签

批准后调用签发接口并绑定批准记录：

```
POST /batches/OUT-1/labels
{"approval_id": 7, "supersedes_id": 3}
```

- 仅当申请属于该批次、状态为 `approved`、且**冻结结论与当前实时结论仍一致、
  批次未封存**时才签发；标签快照冻结的是**申请时结论**（不是签发时刻结论），
  并通过 `labels.approval_id` **绑定批准记录**；申请同步置为 `issued`
  （`issued_label_id` 指向新标签）。
- 任一条件不满足均 `409`：未批准 / 已驳回 / 已签发（批准记录不可重复签发，
  库层唯一约束兜底）/ 结论或封存已变化——错误信息要求重新申请。
- 未知申请 `404`；申请属于其他批次 `400`；未知旧标签、旧标签跨批次沿用原
  `404`/`400` 约定。`supersedes_id` 可选，关联被替代旧版。

### 4. 审计查询

| 接口 | 说明 |
|---|---|
| `GET /label-applications/{id}` | 单条申请：申请字段、审核人/时间/备注/驳回原因、冻结结论、依据摘要、当前实时对比（`conclusion_stale`/`cursor_behind`）、签发标签号 |
| `GET /label-applications?status=pending\|approved\|rejected\|issued` | 按状态过滤（非法值 `400`） |
| `GET /label-applications?batch_id=OUT-1` | 按批次过滤（可与 status 组合） |
| `GET /labels/{id}` / `GET /batches/{batch_id}/labels` | 标签查询保持兼容：原有 `conclusion`/`basis` 快照不变，新增 `approval_id`（审批签发时为申请号，历史直接签发标签为 `null`） |

申请/审批/签发均**不改变实时溯源结论**，不产生变更事件；标签快照结构与既有
查询兼容。旧版数据库（`labels` 无 `approval_id` 列）启动时**自动幂等迁移**
补列，历史标签该列为空。

> **兼容路径**：不带 `approval_id` 的 `POST /batches/{batch_id}/labels`
> 沿用历史行为（冻结签发时刻实时结论；封存批次仍 `409` 拒绝），既有脚本与
> 集成无需改动；新业务应走上述审批流程。

```bash
BASE=http://localhost:8000

# 1) 取当前游标并提交签发申请
CURSOR=$(curl -s $BASE/changes/snapshot | python3 -c 'import sys,json;print(json.load(sys.stdin)["cursor"])')
AID=$(curl -s $BASE/label-applications -X POST -H 'Content-Type: application/json' -d "{
  \"batch_id\":\"OUT-1\",\"applicant\":\"qc-zhang\",
  \"reason\":\"2026W40 出厂批次标签签发\",\"label_note\":\"含奶提示\",\"cursor\":$CURSOR}" \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["application_id"])')

# 2) 审核人批准（驳回用 {"decision":"reject","reviewer":"...","reject_reason":"..."}）
curl -s $BASE/label-applications/$AID/decision -X POST -H 'Content-Type: application/json' \
  -d '{"decision":"approve","reviewer":"reviewer-li"}'

# 3) 凭批准记录签发（冻结申请时结论、绑定批准记录）
curl -s $BASE/batches/OUT-1/labels -X POST -H 'Content-Type: application/json' \
  -d "{\"approval_id\":$AID}"

# 4) 结论变化后旧申请签发被拒（409，需重新申请）；可先驳回过期申请
curl -s $BASE/label-applications/$AID   # -> conclusion_stale=true
```

完整专项演示脚本：`./examples/demo_label_approvals.sh`

## 项目结构

```
app/
  main.py      # FastAPI 路由与错误映射
  service.py   # 业务规则：校验、溯源计算、代码并码规范化与撤销、调查封存传播、标签签发、签发审批工作流、变更预演、变更事件流
  db.py        # SQLite 连接、建表与旧结构幂等迁移、写/读事务
  schemas.py   # 请求模型（强制时区感知时间）
tests/test_app.py            # 45 个端到端测试（溯源/清洗/纠正/预演/标签/事件流）
tests/test_investigations.py # 19 个调查封存端到端测试（传播/截断/叠加/约束/事件/乱序补登）
tests/test_allergen_merges.py # 19 个并码端到端测试（校验/幂等/串接/规范化/去重/快照/事件/并发）
tests/test_allergen_merge_revocation.py # 21 个并码撤销端到端测试（生效链/重并码/重算/事件/预演失效/旧库迁移）
tests/test_label_approvals.py # 35 个标签签发审批端到端测试（申请冻结/幂等/批准驳回/结论与封存变化拦截/绑定签发/审计查询/兼容）
examples/demo.sh    # 全流程 curl 演示（含变更订阅）
examples/demo_investigations.sh  # 调查封存专项 curl 演示
examples/demo_merges.sh          # 过敏原代码并码专项 curl 演示
examples/demo_label_approvals.sh # 标签签发审批专项 curl 演示
Dockerfile / docker-compose.yml / requirements*.txt
```
