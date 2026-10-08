# 迁移：从 os-max 与各领域仓到原力OS 3.0

## 1. 功能对照（os-max → 新内核）

| os-max 功能 | 新内核 | 状态 |
|---|---|---|
| `GET /api/v1/snapshot`、`/api/v2/brief` | `GET /api/brief` | ✅ 覆盖 |
| `GET /api/v2/queue`、`/ui/queue` | `GET /api/items?status=&domain=` | ✅ 覆盖 |
| `POST /api/v1/decisions/{id}/sign`、`/api/v2/decisions/{id}/rulings` + `apply-rulings` | `POST /api/items/{id}/decide`（`rev` 乐观并发，立即生效） | ✅ 合并为一步 |
| defer 三字段契约 | `verdict: defer`，`until` 默认 +7 天，理由写在 `note` | ✅ 简化 |
| `close_ready → done`、执行/验证/结算三态 | `item.noted`（执行和验证证据）+ `item.settled`（结果） | ✅ 合并为一个生命周期 |
| Take 卡 + Brier（`calibration.py`） | 任意 Item 都可以带 `forecast`；结算自动计 Brier；按人和机器、按领域分组，并给出可靠性分箱 | ✅ 覆盖并扩展 |
| `POST /api/v1/proposals`（G1 outbox） | `POST /api/items`（agent 或 principal 提议） | ✅ 覆盖 |
| G2 人工操作卡 | Item 的 `manual: true` 标记；没有执行器就在"进行中"栏跟踪 | ✅ 覆盖 |
| `GET /api/v1/traces/{trace_id}` | `GET /api/items/{id}` 返回完整 `trail` | ✅ 覆盖 |
| `GET /api/v2/history/{object_id}` | `GET /api/facts/{key}` | ✅ 覆盖 |
| `GET /api/v2/evidence/{ref}`（读仓内文件） | `evidence` 字段 + 事实序列 | ⚠️ 不再从 HTTP 读取服务器文件（这本身就是攻击面） |
| `POST /api/v2/chat`（SSE）+ resolver 表 + 20 条黄金意图 | `GET /api/ask`：中文二元组检索；可选 Claude 带引用作答 | ✅ 覆盖，中文可用 |
| `POST /api/v2/views/{id}/pin` | —— | ❌ 删除：固定一张临时卡片，不如直接提一个 Item |
| `/api/v2/events` SSE（每 30 秒重算整页） | `/api/stream`（账本变化时推送序号） | ✅ 事件驱动 |
| `osmax export --profile public/private` | `yuanli export --audience public/team/private` | ✅ 覆盖 |
| `osmax verify`、`scan-secrets` | `pytest` + CI 里的 gitleaks | ❌ 运行时不再扫描 |
| `nightly-improve`（技能改进提案 + 三道门） | 校准分组显示哪个领域、谁的判断更差 | ❌ 删除提案机器；改进依据来自校准 |
| 采集器：决策队列 / 验证 md / gbrain / 心跳 / 夜航日志 / 大脑指标 / 指针 / 战略项目 / 安全回执 | 一次性导入队列；心跳 → `os` 领域；战略项目 envelope → `venture` 领域；其余 → 收件箱或 `/api/facts` | ✅ 数据面覆盖 |
| Fleet 控制面（GitHub self-hosted runner、准入、策略门） | 心跳 + 静默主机规则 | ❌ 删除：个人三台机器不需要 CI 编排层 |
| 304 模块能力地图、HTML 蓝图 / 作战图生成器 | —— | ❌ 删除：这些是产物，不是系统 |

## 2. 一次性迁移步骤

```bash
pip install -e .                               # 零运行时依赖；想用 Claude 回答时装 .[brain]
yuanli import-osmax ~/yuanli-os-max            # 58 个决策 + Take 卡 → 账本；可以重复执行，不会重复写入
yuanli today                                   # 终端里先看一眼
yuanli token mingge principal                  # 为每个端生成 token
yuanli token ios agent
export YUANLI_TOKENS="<上面两行，用逗号连接>"
yuanli serve --host 0.0.0.0                    # 建议放在 Tailscale 或 nginx 后面
```

各领域接入（全部可选，缺失的来源会显示为"未采集"，不影响其他部分）：

| 领域 | 做法 |
|---|---|
| 原力健康 | iOS / Watch App 的上报地址改为 `POST /api/facts`（agent token）；或者把 Apple Health 的 `export.xml` 放进 `~/.yuanli/inbox/health/` |
| 原力投研 | 净值 CSV（`date,code,nav`）放进 `~/.yuanli/inbox/invest/`；runtime 仓的实体解析和回放脚本改为向 `/api/facts` 推送；投资判断用"新判断"表单录入（概率 + 到期日） |
| 原力创业 | `YUANLI_VENTURE_PROJECTS` 指向现有 `project_evidence_envelope_v1` 目录，格式原样读取 |
| 原力内容 | 阅读数据（`key=reads:<文章>,value,at,label`）放进 `~/.yuanli/inbox/content/`；`YUANLI_CONTENT_PUBLISH_HOOK` 指向 Dify 或 n8n 的发布工作流 |
| 原力OS | `YUANLI_HEARTBEAT_DIR` 指向现有心跳目录（格式兼容）；`YUANLI_REPOS` 列出要盯住的本地仓库 |

## 3. 各仓处置清单（建议，由你执行）

> 这些仓库不在本次 PR 的写入范围内，这里只给出清单。建议先导入、并行运行一周，确认无误后再删除。

**yuanli-os-max**：导入后归档。
- 删除：`osmax/` 全部（由本仓取代）、`contracts/`（14 份 schema → 7 种事件）、`data/source-registry*.json`、`data/frozen/`、`data/resolver-table.json`、`data/judgment-config.json`、`scripts/fleet/`、`scripts/secret_executor/`、`build_*.py`、根目录下生成的 HTML 和作战卡、`reports/*.xlsx`、`.specify/`、`.claude/skills/speckit-*`
- 保留：`data/decision-queue.json`、`data/events/`、`data/calibration/`（作为历史，已导入）

**yuanli-content-engine-os**
- 删除：`dify/scripts/install_*_launch_agent.py`（5 个安装器，合计约 11 万字节）→ `yuanli serve` 配一个 15 行的 launchd plist；`build_campaign_dashboard.py`、`build_content_engine_workbench.py`、`build_experiment_dashboard.py`、`capability_runtime.py`（合计 9,854 行）→ `content` 领域 + UI；`governance/privacy_scan.py` → 按 scope 构造隐私
- 保留：`dify/` 工作流（作为执行器）、`series/`、编辑战略和选题库（这些是内容资产）

**yuanli-health-apple**
- 保留：`apps/`（Swift iOS / Watch），只改上报地址
- 删除：`server/ingest_server.py`、`server/health_mcp_local/`、`scripts/verify_*gate*.py`、`docs/canon/*.json` 状态机、v2–v12 版本文档（留当前一份）
- 迁移：`scripts/health_os_db.py` 中的私有 SQLite 数据按日聚合后推送到 `/api/facts`

**yuanli-invest-runtime**
- 保留：`src/`（管理人实体解析、CTA 回放）作为数据源适配器
- 删除：`evidence/*.r2..r5.json`、`governance/shared-spec/*receipt*`、Supabase 摄取函数和写死 program/battle 的 SQL → `/api/facts`

**yuanli-strategy-soul**
- 保留：方法论正文（三部曲、手稿、本体）——这是知识资产
- 删除：`governance/repository-enrollment-*`、修正案、回执、`authority-ledgers`；114 个 workflow 收敛到不超过 3 个

**yuanli-brain-kernel**：它的闭环已经被本内核的事件模型完整实现，可以归档。

**空仓** `yuanli-os`、`yuanli-health-app`、`yuanli-venture-cockpit`：删除，或者把本仓作为 `yuanli-os` 的内容推过去。
