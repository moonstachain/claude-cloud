# 清理与迁移清单

> 配合 [REVIEW.md](REVIEW.md)（为什么）与 [ARCHITECTURE.md](ARCHITECTURE.md)（去哪里）。这里只列"做什么"，按仓库分组，每项标明是否改变线上行为。

## 1. `yuanli-life/yuanli-os`：已完成

[yuanli-life/yuanli-os#81](https://github.com/yuanli-life/yuanli-os/pull/81)（草稿），8 个提交，线上用户可见的变化只有两处：

- MCP 工具列表里不再有 `yuanli.context.compile`、`yuanli.doctor`、`yuanli.capability.list`（三者都是回显或静态列表）。
- 任务视图的 JSON 里不再有常量字段 `natural_reuse_proven`、`compounding_proven`、`attribution_proven`、`verification`、`causalBenefitProven`。Web 与 MCP 都不读取它们。

其余是删除仅在 dev/deploy-preview 生效的路由、删除 CLI、压平内部分层，以及 CI 改为 `npm run test:full`。

## 2. `yuanli-os`：流程文件清单（需要你执行或授权）

本会话尝试批量删除这些审计/流程记录时被安全策略拦截，所以留给你决定。git 历史保留全部内容。

**可以直接删除**（没有代码或测试引用）：

```bash
git rm -r receipts runs preloads schemas .yuanli \
  docs/superpowers docs/architecture/evidence \
  evals
git rm docs/architecture/2026-09-2*.md \
  docs/delivery/2026-09-27-*.md docs/delivery/2026-10-01-*.md \
  docs/operations/2026-09-30-FIRST-TASK-CANDIDATE.md \
  docs/product/GOLD-UI-REVIEW-20260925.md HANDOFF.md
```

- `scripts/rehearse-pilot-restore.mjs` 会在运行时重新创建 `evals/service/` 并写报告，不受影响。
- `docs/architecture/SVC1-SEED-ALPHA-OPERATIONS-RUNBOOK.md` 是运维手册，建议移到 `docs/runbooks/` 而不是删除。
- 其余 `docs/architecture/*.md`（CAPABILITY-FABRIC、FEDERATED-PERSONAL-OS、G1/G2、NETLIFY-NATIVE-KERNEL、PERSONAL-HARNESS、THREE-SURFACES-ONE-KERNEL）描述的多是未实现的设想，四元组主体和"三端一个内核"的回显就来自这里。采纳新架构后用一份当前架构说明替换它们。

**先改一处再删**：

- `contracts/`：`tests/svc1-alpha-migration-manifest.test.ts` 在 grep 其中一份 YAML 的字句（如 `rollback_seconds_observed: 18`）。把这个测试改成只检查"已应用的迁移目录存在、种子迁移不在自动迁移目录里、清理迁移不含 INSERT"，然后 `git rm -r contracts`。
- `governance/`、`repo-contract.yaml`：`AGENTS.md` 和 `README.md` 引用它们；`yuanli-strategy-soul` 可能有跨仓的登记检查。确认 soul 仓不再检查后，删除并把 `AGENTS.md` 缩成"人签不可代、不提交密钥、生产发布需人工确认"三条。

**保留**：`docs/adr/`、`docs/runbooks/`、`docs/product/`（产品思考本身）、`docs/delivery/enterprise-*.md` 与 `templates/`、`skills/`（启动器打包依赖）、`docs/operations/2026-09-25-TASK-V2-ROLLOUT.md`（v1 退役流程，退役完成后再删）、`operations/alpha-applied-migrations/`。

## 3. `yuanli-os`：后续 PR（按收益排序）

| # | PR | 改变线上行为 | 预估 |
|---|---|---|---|
| 1 | 模型调用改为按主体月度预算：新表 `budgets`，删除 `YUANLI_ALPHA_TASK_INVOCATION_PROFILE`、证据字段校验，合并 `task-generation-host` 与 `candidate-host` | 是：用户不再需要等运营方逐任务开通 | −600 行 |
| 2 | 保存默认开启：删除 recording consent 与 scope digest，保留"暂停保存"开关 | 是 | −250 行 |
| 3 | 健康摘要服务端代取：OS 服务端用主体绑定调健康投影；删除浏览器 Supabase 会话与 `HealthController` | 是：少一次登录 | −400 行 |
| 4 | 10-25 之后按流量闸门退役 v1：`/api/tasks/candidate`、`learning-preload`、签名保存、草稿/预载令牌、`legacy-intake` 面板、响应戳 | 否（届时已零流量） | −600 行 |
| 5 | 确认预览/联合模式后删除：`YUANLI_JOINT_*`、预览 Bearer、`principal.mts`、`auth.mts`；许可校验收敛为数据库一处 | 仅影响 deploy preview | −300 行 |
| 6 | 续接组件独立：从 `task-panel.ts` 拆出时间线组件，任务与项目工作台直接使用 | 是：7 个表单合为 1 条时间线 | −300 行 |
| 7 | ✅ 已在 [#81](https://github.com/yuanli-life/yuanli-os/pull/81) 完成：事务开头合成一条语句 + `yuanli_enter_subject` 一次完成身份解析与作用域设置 | 否（新增一个函数的迁移） | 每请求少 3 次往返（实测） |
| 8 | 事件表双写与回填（[架构 §11](ARCHITECTURE.md#11-迁移路径每一步都可回退) 阶段 2–5） | 分阶段，开关控制 | 存储层预计 −1,000 行 |

小项：`project-panel.ts:69` 的"其中 RAY 投入"改为通用字段；启动器的 Node 版本要求放宽到 ≥22；测试脚本初始化内嵌 PG 时固定 UTF8 编码。

## 4. 领域仓

### `moonstachain/yuanli-content-engine-os`

- 保留：`series/`、`reports/` 的编辑战略与选题库、`dify/workflows/`（作为发布执行器）、`dify/prompts/`。
- 替换：`dify/scripts/install_*_launch_agent.py`（5 个，合计 2,992 行）→ 每个服务一份 plist + `launchctl bootstrap gui/$UID <plist>`。需要在 macOS 上验证。
- 合并：`build_campaign_dashboard.py`（5,003 行）、`build_content_engine_workbench.py`（2,147 行）、`build_experiment_dashboard.py`、`capability_runtime.py` → 内容域迁入内核后，看板就是查询；迁入前至少停止把 `artifacts/public/`、`artifacts/receipts/` 提交进仓库。
- 删除：`governance/privacy_scan.py` 与事后正则扫描（改为发布前只序列化公开字段）。

### `yuanli-life/yuanli-health-app`

- 保留：`src/domain`（纯规则）、`src/runtime`（输入校验）、Today 与健康进展页面。
- 补齐：意向确认要持久化（现在刷新即清除）——迁入内核后它就是一个 `step.committed` 事件。
- 删除：`governance/` 19 个 settlement/proof/pin 文件、`scripts/verify_governance.py`（12 个上游来源按 SHA 锁定）、`scripts/contract1_authority_gate.py`、`scripts/contract234_reality_loop.py`（一次性证明工具，README 已注明不应例行执行）。

### `moonstachain/yuanli-invest`

- 保留：研究方法论正文、`ymq_gold2_*` 研究编译/回放/学习脚本（作为投研域的数据源）。
- 删除：34 个 `validate_*.py`、文档 blob SHA 哨兵（如 `validate_yios0_canonical_definition.py:22`）、`receipts/`；版本交给 git。

### `moonstachain/yuanli-venture-cockpit`

空仓。删除或归档；创业域在内核的 `packages/venture` 与项目工作台里。

### `moonstachain/claude-cloud`（本仓）

- `yuanli/` 下的 Python 原型保留为参考实现；把它的领域规则移植进内核的领域模块后归档。
- 原型针对 `yuanli-os-max` 等旧仓的导入与处置清单见 [`prototype/MIGRATION-FROM-OSMAX.md`](prototype/MIGRATION-FROM-OSMAX.md)。
