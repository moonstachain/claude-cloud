# 原力OS 板块审查：由外到内，逐层诊断

> 日期：2026-10-08。对象是当前真正在跑的系统：
> **内核** `yuanli-life/yuanli-os`（main@`a4ff383`，TypeScript + Netlify Functions + Postgres RLS，已有受邀用户、学员 MCP、卷卷试点）；
> **领域** 原力创业（内核内 `packages/venture` + 项目工作台）、原力投研（内核内 Gold 工作台 + `moonstachain/yuanli-invest`）、原力健康（`yuanli-life/yuanli-health-app` + 母仓 `yuanli-health-apple`）、原力内容（`moonstachain/yuanli-content-engine-os`）。
> `moonstachain/yuanli-venture-cockpit` 仍是空仓。
>
> 上一版审查（9/25，见 [`prototype/REVIEW-OSMAX.md`](prototype/REVIEW-OSMAX.md)）看的是 `yuanli-os-max` 等旧仓，把已归档的 `moonstachain/yuanli-os` 当成了"空仓"，**漏掉了 `yuanli-life/yuanli-os` 这个真正的内核**。本版补上。
>
> 方法：逐文件阅读 → 在本机复现完整测试（Node 24.14.1、内嵌 PostgreSQL 17、jsdom、MCP client）→ 在内核仓直接做等价重构，每一步都跑完整测试 → 领域仓做取证审查。结论都附 `文件:行号`（main@`a4ff383`）或实测数字。

图例：✅ 已在 [yuanli-life/yuanli-os#81](https://github.com/yuanli-life/yuanli-os/pull/81) 完成 · 🟡 建议，需要你拍板（涉及产品、安全或线上配置）· ⏸ 暂缓（附原因）

---

## 0. 一句话结论

**代码量的主体不是功能，而是"证明自己没做错"的机制。** 内核约 1.56 万行生产代码、1.83 万行测试，另有 122 个流程文件（2.16 万行回执、契约、计划、验收台账）。用户真正的动作只有一条闭环——*带着资料提出一件事 → AI 给建议 → 我判断 → 我接下一步 → 记录发生了什么 → 看结果 → 留下经验，下次复用*——但每一步都套了许可、同意、证据哈希、常量"未证明"标志和多层转发。

最影响体验的三件事都不是代码风格问题，而是设计决策：

1. **生成一次 AI 建议，要运营方先为这一个任务改环境变量。** 生产调用许可来自 `YUANLI_ALPHA_TASK_INVOCATION_PROFILE`（`task-generation-host.mts:114`），并且绑定单个 `taskId` 和输入哈希（`task-generation-policy.mts:96`）。
2. **保存要先"开启任务保存"并确认范围**（`recording-preference.ts:18`）；管理员改了授权范围，用户要重新同意。一个记录型产品默认不记录。
3. **健康摘要要第二次登录。** OS 已登录后，还要在浏览器里用健康账号邮箱验证码再登一次，只为显示最多 3 条睡眠提示（`health-controller.ts:46`，278 行）。

---

## 1. 产品与体验层

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| U1 | AI 建议的生产调用逐任务授权，靠环境变量下发 | `task-generation-host.mts:114`、`task-generation-policy.mts:96` | 🟡 改为按主体的月度预算 + 日上限，存数据库，超额才拦（见 [架构 §6](ARCHITECTURE.md#6-授权一个主体列三种人签事件)） |
| U2 | 默认不保存；先确认"保存范围"；授权范围一变就要重新同意（scope digest） | `recording-preference.ts:18`、`record-permit.mts:125` | 🟡 保存默认开启；同意改为一次性的服务条款确认 |
| U3 | 一个任务的续接是 7 个独立表单、7 个保存按钮：反馈 / 下一步 / 承接 / 执行 / 结果 / 经验 / 经验使用 | `task-panel.ts` 全文（615 行） | 🟡 合并为一条时间线 + 一个"下一步"输入框，状态机不变 |
| U4 | 文案大量免责：每次保存都附"本人报告，尚未独立核验，不能据此认定因果"等 | `task-panel.ts` 的 summary 文案 | 🟡 保留一处说明，删除逐条免责 |
| U5 | 健康摘要需要第二套登录（Supabase 邮箱 OTP），并有跨标签页广播、会话纪元轮换等 443 行前端逻辑 | `health-controller.ts`、`health-panel.ts`、`health-summary.ts`、`health-config.ts` | 🟡 服务端用主体绑定代取摘要，浏览器只调 `/api/health/summary` |
| U6 | 多租户产品的界面里写死了创始人名字：工时字段"其中 RAY 投入" | `project-panel.ts:69` | 🟡 改为"负责人投入"，或删字段 |
| U7 | 新任务必须选 1–2 份已授权资料才能开始 | `task-v2.ts` `validateNewTask` | 🟡 允许 0 份资料先开始，资料可后补 |
| U8 | 生产根路径之外还有 `?debug=1` 的 "G2 PRIVATE PREVIEW" 页面，把任务原样回显为 JSON | `main.ts`（旧） | ✅ 删除 |

## 2. 界面层（Web）

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| W1 | 任务工作台和项目工作台都把"开发用联合验收面板"整块挂进来当续接组件，再隐藏它的导出按钮、搬走它的状态行 | `task-workbench.ts:594-629`、`project-panel.ts:598` | 🟡 抽出独立的续接组件；`legacy-intake` 区域随 v1 退役一起删除 |
| W2 | 同一份生成错误文案在两个面板各写一遍；同一个失权正则写了 7 处 | `task-workbench.ts:28`、`project-panel.ts:121` | ✅ 收敛到 `api-client.ts` |
| W3 | 健康摘要手写闰年校验 | `health-summary.ts:20` | 🟡 随 U5 一起删除 |
| W4 | 两套列表来源：目录 v2（游标分页）和旧列表（最多 50 条），按特性开关切换 | `task-workbench.ts` `restore()`、`project-panel.ts` `refresh()` | 🟡 目录 v2 稳定后删除旧列表分支 |

## 3. 接入面（HTTP / MCP / CLI）

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| S1 | "内核"请求只把输入加上 `authority_ceiling: "A1"`、`persisted: false`、`external_effect: false` 原样返回；A2–A4 一律抛错，而调用方只传 A0/A1 | `packages/kernel/src/index.ts:93` | ✅ 删除，内核只保留 `Principal` 类型 |
| S2 | CLI 只打印上面的回显；"Web × CLI × MCP → One Kernel" 在字面上成立，但三端拿到的是同一个回显 | `cli/yuanli.ts` | ✅ 删除 |
| S3 | MCP 的 `context.compile` / `doctor` / `capability.list` 同样是回显或静态列表 | `netlify/functions/mcp.mts`（旧 80–166 行） | ✅ 删除；MCP 只保留读真实记录的工具，工具发现走协议自带的 `tools/list` |
| S4 | 预览专用的授权路由，"人工闸门"是任何人都能发送的请求头 | `source-grants.mts:21` `x-yuanli-human-gate: approved` | ✅ 删除（连同 `/api/context`、`/api/status`） |
| S5 | 两套运行时配置命名空间 `YUANLI_JOINT_*` / `YUANLI_ALPHA_*`，再用改名垫片互相映射 | `task-runtime.mts:31`、`:95` | ⏸ 预览模式可能是 deploy preview 联合验收的依赖，删除前需确认 |
| S6 | 两套任务 API：v1 `/api/tasks`（PATCH + `operation` 字段）和 v2 `/api/v2/tasks/*` | `task-record.mts`、`tasks-v2.mts` | ⏸ 仓库自己的退役闸门要求满 30 天（最早 10-25）且连续 7 天零流量（`check-legacy-retirement.mjs:17`）。到期后整体退役约 600 行 |
| S7 | 请求体里出现 `principal`、`tenant_id` 等键就直接 400，而服务端本来就不读这些键 | `joint-http.mts:128` | 🟡 删除；身份只来自会话 |
| S8 | 旧候选接口在模型调用前后各做一次来源授权和经验校验，而结果并不落库（保存时还会再验） | `joint-http.mts:254`、`:290` | 🟡 随 v1 退役删除 |
| S9 | 特性开关 8 个以上：`YUANLI_ALPHA_ENABLED`、`YUANLI_RUNTIME_PROFILE`、`…_TASK_WRITE_ENABLED`、`YUANLI_TASK_FLOW_V2`、`YUANLI_CATALOG_V2_ENABLED`、`…_PROVIDER_ENABLED`、`VITE_HEALTH_SUMMARY_ENABLED`、`GOLD_RESEARCH_AI_ENABLED` | `task-runtime.mts`、`tasks-v2.mts` | 🟡 稳定后收敛为"运行环境 + 模型开关"两个 |

## 4. 应用层

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| A1 | 一个 Web 请求依次经过 `executeTaskRequest` → `executeTaskOperation` → 四个子应用之一 → `taskApplicationPorts()` 端口对象 → `PostgresTaskStore` 门面 → 记录类。三个子应用只做转发，四个端口里 `read` 重复三次，且只有一个实现 | `task-application-ports.mts:5`、`session-task-repository.mts:12`、`application/src/{ports,queries,task-request}.ts` | ✅ 合并为一个 `TaskApplication` 类 + 一个 `TaskRepository` 接口 |
| A2 | `permit` 作为显式参数穿过每一层；会话版仓储收到后直接忽略（`_permit`） | `session-task-repository.mts` | ✅ 接口保留参数，会话版注明"每次重新解析许可" ｜ 🟡 目标是许可只存在于事务上下文 |
| A3 | 常量"未证明"字段进入 API：`natural_reuse_proven:false`、`compounding_proven:false`、`attribution_proven:false`、`verification:"SELF_REPORTED_NOT_VERIFIED"`、`causalBenefitProven:false`，以及 handoff 报告的 `customerOutcomeProven:false` 等 | `task-read-batch.mts:386`、`work-progress.ts:44`、`project-delivery.ts:351`、`handoff.ts:14` | ✅ 删除（Web 与 MCP 均不读取）；死函数 `settleObservation`、`projectFingerprint` 一并删除 |
| A4 | 每个响应都盖上 `capability`、`authority_ceiling`、`storage_effect`、`external_effect:false` 戳 | `joint-http.mts`、`task-mcp.mts` | 🟡 保留了响应形状以免影响现有客户端；v1 退役时一起去掉 |

## 5. 领域规则层

`packages/decision-workflow`（决策→工作安排→执行→结果→经验）本身写得干净：纯函数投影、事件追加带幂等和版本检查。问题在外面：

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| D1 | 每读一个任务，都要沿"经验预载"链递归回溯最多 8 层，重新验证每个祖先任务的经验仍然有效 | `task-read-batch.mts:106` `WITH RECURSIVE` | 🟡 预载时记录经验版本即可；祖先被撤回时由事件标记下游，而不是每次读都重算 |
| D2 | 预载令牌、草稿令牌各自做 HMAC 签名 + 5 分钟过期 + 任务文本哈希绑定 | `decision-workflow/src/task-record.ts` `issueDraftToken`、`learning.ts` `issuePreload` | 🟡 v2 流程已改为服务端状态；v1 退役后令牌随之删除 |

## 6. 存储与授权层

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| P1 | 同一份记录许可被校验 4 次：SQL 函数 `yuanli_lock_record_context` → JS 逐列复核数据库刚返回的行 → `assertRecordingIntent` → 每个存储方法里的 `assertRecordPermit`（含 `authority === "A2"` 字面量检查） | `task-session.mts:53`、`record-permit.mts:30`、`:125`、`kernel/src/task-record.ts:27` | ⏸ 预览模式的许可来自环境变量 JSON，`assertRecordPermit` 是它唯一的校验；先退役预览模式，再收敛为"数据库返回即可信" |
| P2 | 主体是 4 元组（tenant、user、node、ecosystem），每条 SQL 过滤 4 列，比较用规范化 JSON；node/ecosystem 来自尚未使用的"联邦个人节点"设想 | `kernel/src/index.ts`、全部 `*-records.mts` | 🟡 迁移为单列 `principal_id` + RLS |
| P3 | 所有业务对象挤在一张 `yuanli_objects` 表里，按 `object_type`（CTX/DEC/EVD/WPK/ACT/OUT/LRN）和 `payload->>'profile'` 区分，事件数组存在 JSON 里，版本号同时写在根和子记录上 | 迁移 `20260918131000_g1-kernel` | 🟡 目标是一张显式的 `events` 表 + `streams` 摘要表（[架构 §5](ARCHITECTURE.md#5-存储一张事件表一张流表)） |
| P4 | 每个事务进入运行时角色后，再查一次 `pg_roles` 确认自己不是超级用户 | `scoped-db.mts:34` | ✅ 改为每个连接校验一次（`SET LOCAL ROLE` 仍每次执行；失败不缓存） |
| P5 | 一次带身份的请求在开始业务查询前约需 7–8 次往返：BEGIN、SET ROLE、角色自检、set_config、锁身份绑定、再 set_config、锁记录许可（偏好写入还有一次 advisory lock）。目录接口实测 **15 次往返/请求**（与条目数无关） | `task-session.mts:43-53`、测试日志 `Alpha HTTP catalog … 15 database round trips` | ✅ 角色自检去掉一次 ｜ 🟡 用一个 `yuanli_begin(subject)` 函数一次完成身份解析与作用域设置，目标 ≤4 次 |
| P6 | 写路径（工作安排 / 执行 / 经验）三次复制同一段"加锁读视图 → 三项守卫 → 插入或更新子记录 → 推进根版本" | `continuation-records.mts` | ✅ 抽出两个私有方法 |
| P7 | 5 份相同的"限长读取请求体/响应体"循环 | `joint-http`、`gold-handler`、`gold-runtime`、`mcp-oauth-http`、`providers/common/bounded-http` | ✅ 合并为 `readBounded()` |

## 7. 外部调用层（模型、检索）

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| X1 | 调用许可要求 `tokenBudgetEvidence.sha256`、`cost.evidence.status: "VERIFIED_UPPER_BOUND"`、`includesRetrievalAndModel: true` 等字段；代码注释承认这些是"运营方断言，不是对远端定价/分词器文档的校验" | `task-generation-policy.mts:12`、`:36`、`:128` | 🟡 保留真实的数值上限（次数、金额、超时），删除无法验证的"证据"字段 |
| X2 | 两套并行的生成宿主：生产用 `task-generation-host`，非生产用 `candidate-host`，各自实现预留、校验、回执 | `task-generation-host.mts`、`candidate-host.mts`、`candidate-pipeline.mts` | 🟡 合并为一个宿主，环境差异只体现在配置 |
| X3 | Ollama `keep_alive=0`、WeKnora 前后元数据核对 | `providers/ollama`、`providers/weknora` | 保留：前者与留存承诺有关，后者能发现读取期间的来源变更 |

## 8. 测试、CI 与流程文件

| # | 发现 | 证据 | 处置 |
|---|---|---|---|
| T1 | CI 闸门脚本先检查一串"证据文件"是否存在，再把 7 个测试文件映射成 identity/data/task 三个闸门字符串，写出带 `NOT_AUTHORIZED` 注释的回执 | `scripts/svc1-g0-acceptance.mjs:11` | ✅ 改为：测试环境齐备时任何测试被跳过即失败（跨仓 Gold 套件除外），CI 直接跑 `npm run test:full` |
| T2 | 用测试去 grep 文档里的字句，例如断言 YAML 里写着 `rollback_seconds_observed: 18` | `tests/svc1-alpha-migration-manifest.test.ts:51` | 🟡 只保留"已应用迁移不可删除/改号"的结构检查 |
| T3 | 结构警察式测试：断言某文件不存在、某文件不含某正则 | `tests/application-boundaries.test.ts` | 保留依赖方向检查；其余随重构调整 |
| T4 | 122 个流程文件（2.16 万行）：`receipts/` 17、`runs/` 9、`evals/` 11、`contracts/` 20、`governance/` 4、`schemas/` 2、`docs/superpowers/` 8、`docs/architecture/evidence/`（单个 9,617 行 JSON）等 | 仓库根目录 | 🟡 批量删除被会话的安全策略拦截（它们是审计记录）。清单与命令见 [迁移 §2](MIGRATION.md#2-yuanli-os流程文件清单需要你执行或授权)，git 历史仍保留全部内容 |
| T5 | 启动器要求 Node 版本恰好是 24.x 且 ≥24.14.1，否则拒绝运行 | `scripts/lib/enterprise-starter.mjs:110` | 🟡 放宽为 ≥22 |
| T6 | 本地 `LANG=C` 时内嵌 PG 会初始化成 SQL_ASCII，`left(taskText,160)` 截断中文后插入 JSONB 报错 | `catalog-store.mts` | 🟡 测试脚本固定 `--encoding=UTF8`；生产不受影响 |

---

## 9. 领域仓

### 原力创业（`packages/venture` + 项目工作台）

- 真实可用：项目资料包 → AI 报价缺项检查 → 本人判断（价格/成本/工时/交期影响）→ 复核与工时 → 续接。规则在 `project-delivery.ts`，写得清楚。
- 问题：`handoff.ts` 的五阶段衔接检查器没有界面或接口入口，只有测试和一份运营说明（由运营者在脚本里导入调用）；`yuanli-venture-cockpit` 仍是空仓。🟡 建议删除空仓；衔接检查器等有入口再接。

### 原力投研（Gold 工作台 + `yuanli-invest`）

- 内核侧：Gold 工作台通过服务端调用独立的研究运行时（`gold-handler.mts`、`gold-runtime.mts`），边界清楚；判断带方向、起止日、中性区间，到期验真。这部分是全板块最接近"闭环"的设计。
- `yuanli-invest`：933 个文件里 238 个文档、220 个事件、220 个 canon 文件，**34 个 `validate_*.py`**，其中多个把文档的 git blob SHA 写死成"不可变哨兵"（例如 `scripts/validate_yios0_canonical_definition.py:22` `IMMUTABLE_CHILD_SENTINELS`）。真正跑研究的是 `ymq_gold2_*` 几个脚本。🟡 研究逻辑（编译、回放、学习）保留为投研域的数据源；校验器与哨兵删除，版本交给 git。

### 原力健康（`yuanli-health-app` + `yuanli-health-apple`）

- Web 端只有 4.9k 行，已做过分层整理；但 **"确认意向"只保存在当前页面，刷新即清除**（README 明示），周计划 → 执行 → 复盘 → 下周调整的闭环尚未形成。
- 治理负担：`governance/` 19 个文件（settlement、reality proof、authority pin、upstream source lock），`scripts/verify_governance.py` 要求 12 个上游来源按 SHA 锁定；`contract1_authority_gate.py`（411 行）与 `contract234_reality_loop.py`（316 行）是一次性证明工具。
- 🟡 健康事实（睡眠、HRV）由 iOS/Watch 推入内核的事实接口；"意向/计划/执行/复盘"复用内核的任务闭环，健康只提供规则和临床升级判断。

### 原力内容（`yuanli-content-engine-os`）

- 内容本身是资产：`series/`、编辑战略、160 题选题库。
- 代码 4.5 万行，主要是"回执治理"：
  - `install_content_engine_workbench_launch_agent.py` **2,348 行、65 个函数**，用于安装一个本机 LaunchAgent，内含事务日志、所有权审计哈希链（创世块为 64 个 0）、单写者接管、原子目录切换与中断事务恢复。一个 LaunchAgent 本身是十几行 plist。
  - `build_campaign_dashboard.py` **5,003 行**，其中 530 行含 `raise` 或 `sha256`；和另外三个构建器（工作台、实验看板、能力运行时）合计约 9,900 行，职责重叠。
  - `artifacts/receipts/` 与 `artifacts/public/` 把生成物提交进仓库。
- 🟡 内容域进入内核后：选题是任务、发布是批准后的执行器（Dify / 小鹅通），24h/72h/7d 阅读数据是事实，看板是查询而不是提交进仓库的 JSON。LaunchAgent 安装器替换为 plist + `launchctl bootstrap`。这些依赖 macOS 和真实发布渠道，本会话无法端到端验证，所以只给方案、没有直接改。

---

## 10. 该保留的：原设计里正确的部分

1. **人签不可代。** AI 只提建议；判断、承接、结算、经验审核必须是本人。
2. **AI 原文与人的判断分开保存。** v2 的 `proposal` 与 `decision` 分离是对的。
3. **证据可追溯。** 每条建议引用来源 ID、版本和定位。
4. **幂等与乐观并发。** 幂等键 + 期望版本，重试不重写、并发不覆盖。
5. **RLS 隔离与运行时降权。** 数据库层按主体隔离，应用连接不能绕过 RLS。
6. **外部调用后的来源复查。** 模型生成期间资料可能被撤权，提交前再查一次。
7. **到期验真。** 投研的"同端点验真"把判断变成可结算的样本。

## 11. 已完成的重构（PR #81）

8 个提交，每个都单独跑过完整测试：

| 提交 | 生产代码净增减（行） | 说明 |
|---|---|---|
| 删除回显内核、CLI、预览路由与预览落地页 | −705 | S1–S4、U8 |
| 用"跳过即失败"替换验收回执闸门 | −167 | T1 |
| 应用层端口压平 | −151 | A1 |
| 共享 `readBounded()` | −30 | P7 |
| 角色自检每连接一次 | +5 | P4（每请求少一次往返） |
| 删除常量"未证明"字段与死函数 | −40 | A3 |
| UI 错误文案与失权判断去重 | +7 | W2 |
| 续接记录写路径抽取 | −14 | P6 |

合计：生产代码 −1,738 / +657 行；测试 −387 / +75 行（删除的测试都只覆盖被删除的代码）。

**验证**：`npm run build` 通过；`npm run test:full` **714 通过 / 3 跳过**（跨仓 Gold 套件，需另外两个仓库的检出）。重构前同环境基线为 767 通过 / 3 跳过，净减少的 53 个测试全部属于被删除的功能：回显内核 5、三端等价 3、预览路由 29、能力清单 1、旧闸门脚本 15、`settleObservation` 1，另新增 1 个角色自检测试。

## 12. 需要你决定的事项（按收益排序）

1. **模型调用改为按主体预算**（U1、X1、X2）。这是目前最大的体验阻塞。
2. **保存默认开启**（U2），去掉范围摘要同意。
3. **健康摘要改为服务端代取**（U5），删除浏览器第二次登录。
4. **10 月 25 日后退役 v1**（S6、S8、W1、D2、A4），按仓库自己的流量闸门执行，约 −600 行。
5. **确认预览/联合模式是否还在用**（S5、P1），不用则删除，许可校验随之收敛为一处。
6. **授权批量删除流程文件**（T4），一条命令，见迁移清单。
7. **主体单列化与事件表**（P2、P3、P5），按 [架构 §11](ARCHITECTURE.md#11-迁移路径每一步都可回退) 分阶段做。
