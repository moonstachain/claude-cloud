# 原力OS 全面审查：由外到内，逐层诊断

> 审查对象：`yuanli-os-max`（OS 内核/工作台）、`yuanli-health-apple`（原力健康）、`yuanli-invest-runtime`（原力投研）、`yuanli-content-engine-os`（原力内容）、`yuanli-strategy-soul`（治理根节点）、`yuanli-brain-kernel`（大脑规格）。
> `yuanli-os` / `yuanli-health-app` / `yuanli-venture-cockpit` 为空仓，原力创业目前只存在于 envelope 数据和 soul 文档里。
> 方法：逐仓阅读代码 → 在本机跑通旧测试（os-max 92/92 通过）→ 用真实数据做基准 → 用新内核在同一数据上复现功能。所有结论都附文件位置或实测数字。

---

## 0. 一句话结论

**五个仓库在重复实现同一个闭环，而且每一次都用"再加一道门"来弥补"没有一个统一的真相源"。**

- 同一个闭环被重写了 5 遍，名字各不相同：
  - os-max：`fact → judgment → decision → action → verification → learning`
  - 健康：`CTX → EVD → DEC → WPK → ACT → OUT → LRN`
  - brain-kernel：`Experience → Knowledge Asset → Canon → Decision → Reality Feedback → Learning`
  - 投研：`observation → receipt → learning`
  - 内容：`Evidence → 24h / 72h / 7d → Learning`
- 真相被拆进可变 JSON、JSONL 账本、outbox 目录、SQLite 读模型和各种 receipt 文件，只能靠文件锁、内容哈希、revision、If-Match、幂等键碰撞检测、truth-writer 环境变量去拼一致性。
- 结果是：代码约 **21.4 万行 Python**、**3,400+ 个元文件（md/yaml/json）**、**133 个 CI workflow**。可用户每天真正要做的事只有一件：**看事实，拍板，事后结算。**

新内核用 **1 个只追加账本 + 7 种事件 + 3 种角色**实现同一个闭环（Python 2143 行，含 5 个领域应用；UI 524 行；零运行时依赖），在同一份真实数据上，热路径快 20–18,000 倍，见第 6 节。

---

## 1. 用户体验层：用户每天实际面对什么

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| U1 | **"已批准"是黑洞**：批准之后没有任何机制推动执行和结算 | 真实队列 58 项里：28 项 approved/close_ready，其中 **25 项已逾期**（最早 2026-07-11）；14 项 deferred；只有 11 项 done | 新内核的"进行中"一栏按到期日排序，逾期标红；领域可以注册执行器，批准后立即执行（§4 K3） |
| U2 | **认知负荷**：一屏要同时理解 8 个固定视图 × 6 域 × M0–M6 × C1–C4 × G0/G1/G2 × S0–S3 × 5 种新鲜度 × 3 种置信度 × 3 种可见范围 | `docs/ARCHITECTURE-V2.md`、`osmax/models.py` 的枚举 | 压缩为：两栏（待拍板 / 进行中）+ 每个领域一页 + 校准 + 正典 |
| U3 | **拍板要走两步**：UI 里签字只写 outbox，还要另起进程 `OSMAX_TRUTH_WRITER=1 osmax apply-rulings` 才生效 | `service.py:798` `apply_rulings` | 签字就是事件，一次写入立即生效 |
| U4 | **推迟要填三个字段**（`due_at` + `defer_reason` + `resume_condition`），否则 422 | `models.py` `RulingRequest.validate_defer_contract` | 按 `d` 即可，默认 7 天，理由可选 |
| U5 | **结算要手工判断**：Take 卡需要人工填 outcome，即使数据已经在库里 | `calibration.py`（446 行）| 提案可声明 `measure`，系统预填"建议结算：达成 / 未达成（实测 vs 目标）"，按 `s` 回车确认 |
| U6 | **中文搜索基本失效**：分词只按空格和标点切分，"健康数据最近怎么样"被当成一个整词 | `service.py:597` `re_split` | 中日韩文字按二元组切分，"凭据什么时候轮换完"可以命中"八类凭据轮换" |
| U7 | **首页信息密度被打分，但分数是写死的常量**：`density_audit.baseline/target/acceptance` 硬编码在 API 响应里 | `service.py:418` | 删除 |
| U8 | **校准系统没有产出数据**：446 行 Take 状态机加 Brier 计算，目前 1 张 Take、0 个结算样本 | `data/calibration/takes.json` | 概率挂在任何一个决策上，结算即计分；按"人 / 机器"、按领域分组 |

## 2. 仓库拓扑与法权层

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| R1 | **273 个仓库**，其中大量是"投影 / 镜像 / 备份 / handoff module"。仓库描述里写的是法权声明（"PROJECTION of … Not SSOT"、"Not a second canon"、"P5 quarantine"），而不是它做什么 | GitHub 仓库描述 | 目标拓扑：1 个内核仓 + 少数资产仓（App、内容、方法论正文）；其余归档 |
| R2 | **跨仓法权网**：`repo-contract.yaml` + `authority-ledgers.yaml` + `repository-enrollment-*` 的 r2 版本和 amendment，互相引用 | `yuanli-os-max/repo-contract.yaml`；soul `governance/` 38 项 | 只剩一个运行时之后，"谁是真相"这个问题本身就不存在了 |
| R3 | **把仓库名硬编码进校验器**：配置文件必须等于代码里写死的仓库名和 issue 号，否则无法启动。这是配置对自身的同义反复 | `source_registry.py:16` `FORBIDDEN_ACTIVE_REFERENCES`、`:28` `REQUIRED_CURRENT_AUTHORITIES`、`:135` `"issues/448"` | 删除整个模块（186 行 + 12 个测试） |
| R4 | **版本号写进文件名**：`r2/r3/r4/r5`、`v1..v12`、`V11A`，每一版都是新文件加新测试 | invest `evidence/*.r2..r5.json`；health `docs/` 48 份 v2–v12 文档 | 版本交给 git；每个对象只保留当前形态 |
| R5 | **soul 仓治理元文件过载**：2,874 个文件里有 1,354 md + 710 yaml，另有 114 个 workflow | soul 仓 | 保留方法论正文（这是真正的资产），删除注册表、修正案、回执类治理文件 |

## 3. 治理与流程层

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| G1 | **G0/G1/G2 由字符串子串黑名单判定**，误伤大于保护：`report.execution_summary`（含 `exec`）和 `content.publisher_review`（含 `publish`）都被判为 G2 拒绝（实测） | `service.py:37` `G2_OPERATION_MARKERS` | 改为 3 种角色：只有 principal 能拍板、结算、裁决正典；执行器是仓库里经过审查的代码，不是字符串 |
| G2 | **G2 批准了也永不执行**："只记录授权，不执行"。人已经看过参数并批准，系统仍拒绝执行，于是只能手工执行，然后被遗忘 | `apply_rulings` 结果 `decision_recorded_no_execution` | 批准本身就是闸门。有执行器就执行（Dify / n8n / 飞书 webhook），没有就进入"进行中"栏跟踪 |
| G3 | **SDD 双轨**：spec-kit 四阶段 + superpowers 七阶段 + 宪法检查 + Complexity Tracking，再加 10 个 speckit skill（约 13 万字） | `.specify/`、`.claude/skills/speckit-*`、`docs/管理契约-superpowers映射.md` | 对个人系统是纯开销。保留两条：测试先行，PR 合并 |
| G4 | **fail-closed 泛滥**：清单缺失、schema 不符、清单为空、外部检查器缺失，全部 fail-closed。"门"本身成了主要故障源 | `gates.py`（154 行 + 20 个测试） | 删除。唯一真正要守的门是"谁能写什么"，由 `policy.py` 一处实现 |
| G5 | **哈希当信任**：envelope 自带 `content_hash` 自校验、receipt 带 sha256、安装器审计链（genesis 为 64 个 0）。数据本来就在 git 里，git 已经提供内容寻址 | `collectors.py:446`；内容引擎 `sha256` 出现 1,629 处 | 删除。账本进 git 就是审计 |
| G6 | **安全扫描放在热路径上**：没有扫描回执时，`collect` 会触发 `git log -p --all` 全历史扫描 | `collectors.py:568` → `security.py:75` | 交给 CI 里的 gitleaks（已有）。运行时不扫描 |
| G7 | **隐私靠事后正则**：公开导出之后，再用 email / 私网 IP / `¥` 金额 / `/Users/` 路径正则扫一遍 | `security.py` `PUBLIC_LEAK_PATTERNS` | 隐私按构造保证：每条记录自带 scope，默认 private；导出只序列化受众可见的记录 |

## 4. 架构与数据层

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| K1 | **没有单一真相源**：可变的 `decision-queue.json` + 只追加的 `events/rulings.jsonl` + `var/outbox/*.json` + SQLite 读模型 + `snapshots.jsonl` + `receipts/*.json` | os-max README "目录"表 | **一个只追加 JSONL 账本**。队列、回执、历史、追踪、校准都是从它折叠出来的视图 |
| K2 | **四个并行状态机**：决策 6 态 × 执行 6 态 × 验证 5 态 × 结算 3 态，另有一个 5 态 Take 状态机 | `decision_lifecycle.py`、`calibration.py` | 一个生命周期：`open → approved / rejected / deferred → done`。执行和验证的证据以 `item.noted` 挂在同一条目上 |
| K3 | **幂等和一致性手写两遍**：outbox 写入先在锁里逐字段比较 9 个字段，再在第二把锁里用反向条件再比一遍；另外还要 glob 扫描全部 outbox 检查同 revision | `service.py:621/653`（proposal）、`:704/736/737`（ruling） | 事件 id 即幂等键；`rev` 做乐观并发；账本 flock 串行化写入 |
| K4 | **读模型每次请求都重建**：`current_brief()` 每个请求重新计算整页，还会重读注册表（含修正案合并、别名展开、全量校验）、判断配置和队列哈希；SSE 每 30 秒重算整页，只为推送数据源状态 | `app.py:77`、`service.py:237`、`app.py:298-307` | 内存折叠：每个事件 O(1) 更新，读取 O(1)；SSE 只在账本序号变化时推送 |
| K5 | **单条记录查询是全表扫描**：`get_record` 先 `list_records()` 把整张表 JSON 反序列化，再在 Python 里过滤 | `store.py:174-176` | dict 查找，5 µs |
| K6 | **采集串行，存在 N+1**：10 个来源依次执行（各自 3–12 s 超时）；战略项目对每个项目单独起一个 `gh api` 子进程 | `collectors.py:587`、`:407-436` | 线程池并发；来源失败降级为可见状态，不会阻塞其他来源 |
| K7 | **同一 API 两套版本**：`/api/v1/proposals` 与 `/api/v2/proposals` 等价；`/v1/decisions/{id}/sign` 与 `/v2/decisions/{id}/rulings` 各有一套版本语义（revision / content-hash） | `app.py:198-296` | 一套路由，一张表 |
| K8 | **外部依赖写死本机路径**：`~/AI Project/gbrain/src/cli.ts`，子进程超时 180 s | `service.py:454-473` | 可选的 `brain.py`：默认确定性检索；设置 `YUANLI_BRAIN=1` 后由 Claude 基于命中记录生成回答并带引用 |

## 5. 代码层（跨仓代表性样本）

**os-max（10,411 行 Python）**
- `source_registry.py`、`gates.py`、`security.py`、`nightly.py`、`calibration.py`、`decision_lifecycle.py`、`resolver.py` + `data/resolver-table.json`、14 份 `contracts/*.schema.json`：全部删除，或由新内核的 3 个文件吸收。
- 心跳文件损坏时用正则"抢救"半行 JSON（`collectors.py:220`）→ 改为取最后一行完整的 JSON。
- `mutated()` 未被任何代码调用（`source_registry.py:185`）。
- 根目录下 5 份生成的 HTML、5 张"作战卡"md、`reports/*.xlsx` 都是产物，不应入库。

**内容引擎（41,670 行）**
- 一个**本机 LaunchAgent 安装器有 2,348 行**：包含哈希链审计、事务日志回滚、单写者所有权接管事件。127 处 `raise`，104 处 `sha256`。而一个 LaunchAgent 本身只是一个 15 行的 plist。（`dify/scripts/install_content_engine_workbench_launch_agent.py`）
- `build_campaign_dashboard.py` **5,005 行**，291 处 `raise`，239 处 `sha256`；它和另外 3 个同类构建器（workbench、experiment dashboard、capability runtime）合计 9,854 行，职责重叠。
- 保留：`dify/` 工作流（作为执行器）、`series/` 内容资产、编辑战略文档（这些是内容本身）。

**原力健康（119,155 行）**
- `server/ingest_server.py` 1,580 行，其中约 200 个函数和校验只为接收手表事件。新内核里对应的是 `POST /api/facts` 加一个 agent token。
- `verify_g0_exit_gate.py` 1,484 行、`verify_github_platform_gate.py` 1,740 行：用来验证"治理门是否合规"的代码，比功能代码还多。
- README 首屏是法权状态（"G0 当前为 BLOCKED_ON_PLATFORM_ATTESTATION … PR #98 的自报 ACCEPTED 仍为语义无效"），而不是健康状况。
- 保留：`apps/` 下的 iOS / Watch Swift 代码（真实资产），把上报地址改为 `/api/facts` 即可。

**原力投研（2,482 行，最健康的一个仓）**
- 领域逻辑（管理人实体解析、CTA 回放）是真资产，保留为数据源适配器。
- Supabase 函数把 `program = 'YMQ-GOLD2'`、`battle = 'G6-LIVE-SHADOW'` 写死在 SQL 里；边缘函数把客户端 ID 写死为 `YIOS-TG1-G1R-M4`。→ 改为 `POST /api/facts`。账本的事件时间戳就是"何时知道"，因此天然是 point-in-time 数据。

**测试层**
- os-max 的 92 个测试里，约 **63 个在测防御机制本身**（门 20、注册表 12、fleet 准入 16、模块地图 6、ViewSpec 防注入 4、nightly 3……），只有不到三分之一在测用户可感知的行为。

## 6. 性能层（同机、同数据实测）

基准脚本：旧系统 `bench/bench_osmax.py`（在 os-max 的环境里运行），新系统 `bench/bench.py`。数据为 os-max 真实决策队列；5,000 项是把真实条目克隆扩容，与旧系统基准完全一致。新系统的账本里另外放了 2 万条投研事实，旧系统没有。

| 热路径 | 旧 · 58 项 | 新 · 58 项 | 旧 · 5,000 项 | 新 · 5,000 项 |
|---|---:|---:|---:|---:|
| 首页（整页 brief） | 5.81 ms | **0.25 ms** | 105 ms | **5.2 ms** |
| 单条记录查询 | 1.37 ms | **0.004 ms** | 92 ms | **0.005 ms** |
| 问答"今天只需我拍板什么" | 8.3 ms | **0.02 ms** | 198 ms | **0.19 ms** |
| 自由文本检索 | 10.5 ms | **0.02 ms** | 303 ms | **0.52 ms** |
| 冷启动 / 重建 | collect 164 ms（真实环境还要加网络超时和 `git log -p --all`）| 重放 2 万事件 120 ms | 838 ms | 重放 3.1 万事件 238 ms |
| 写一次（含 fsync） | — | 0.25 ms | — | 0.27 ms |

旧系统的延迟随条目数线性增长（每次请求都要全表反序列化），新系统的查询路径与规模无关。

## 7. 该保留的：原设计里正确的部分

这些不是过度防御，新内核全部保留，只是换成更简单的实现：

1. **证据优先**：每个提案携带 `evidence`，每条事实都带时间和来源。
2. **人签不可代**：只有 principal 能拍板、结算、采纳正典。agent 只能观察、提议、备注（`policy.py` 中 `HUMAN_ONLY`）。
3. **默认私密**：scope 默认 `private`，在读路径统一执行。
4. **校准**：Brier 分数，并且现在区分人和机器。
5. **读模型可重建**：内存状态可以随时从账本重放得到。
6. **现实回灌**：结算 → 校准 → 正典候选 → 人采纳。

## 8. 附录：复现旧系统基准

```bash
cd yuanli-os-max && uv sync --extra dev --locked && uv run pytest -q     # 92 passed
uv run python ../claude-cloud/bench/bench_osmax.py .                      # 旧系统
cd ../claude-cloud && python bench/bench.py ../yuanli-os-max 58           # 新系统，真实队列
python bench/bench.py ../yuanli-os-max 5000                               # 新系统，5,000 项
```
