# 原力OS：审查、目标架构与参考原型

本仓放两样东西：

1. **对当前原力OS 板块的审查和目标架构**（`docs/`）。对象是正在运行的内核 `yuanli-life/yuanli-os` 和健康、投研、创业、内容四个领域仓。
   - [审查：由外到内，逐层诊断](docs/REVIEW.md)
   - [目标架构：从第一性原理出发](docs/ARCHITECTURE.md)
   - [清理与迁移清单](docs/MIGRATION.md)
   - 已落地的内核重构：[yuanli-life/yuanli-os#81](https://github.com/yuanli-life/yuanli-os/pull/81)
2. **3.0 参考原型**（`yuanli/`）：单机、只追加 JSONL 账本 + 内存折叠，验证"一个闭环、事件 + 折叠"的内核语义。它是参考实现，不是第二个生产内核（见 [架构 §12](docs/ARCHITECTURE.md#12-与-claude-cloud-里-30-原型的关系)）。原型自己的说明在 [`docs/prototype/`](docs/prototype/)。

---

## 3.0 参考原型

> 一个账本，一个闭环，多个领域。
> **观察 → 提议 → 拍板 → 执行 → 结算 → 学习。**

- **账本是唯一真相**：`~/.yuanli/ledger.jsonl`，只追加，对 git 友好。队列、历史、追踪、校准都从它折叠出来。
- **7 种事件，3 种角色**：机器负责观察和提议，拍板与结算只能由人来做。
- **零运行时依赖**：只用 Python 3.11 标准库。热路径都在亚毫秒级（见 [`docs/prototype/REVIEW-OSMAX.md`](docs/prototype/REVIEW-OSMAX.md) §6）。
- **一屏，一键一决定**：`j/k` 移动，`a` 批准，`r` 否决，`d` 推迟，`s` 结算，`/` 提问。多端实时同步。

### 快速开始

```bash
pip install -e .                       # 想用 Claude 作答时装 .[brain]
yuanli import-osmax ~/yuanli-os-max    # 可选：导入旧决策队列和 Take 卡
yuanli serve                           # http://127.0.0.1:8420
```

终端用法：

```bash
yuanli today                                              # 今天要我拍板什么
yuanli propose invest "茅台三年跑赢沪深300" --forecast 0.55 --due 2029-09-24
yuanli decide invest:3f2a approve -m "按计划建仓"
yuanli settle invest:3f2a yes                             # 自动计算 Brier
yuanli ask "凭据轮换到哪了"
yuanli calibration                                        # 我和机器，谁更准？
yuanli export --audience public --out dist                # 静态只读快照
yuanli log -n 20                                          # 查看账本尾部
```

### 领域应用

| 领域 | 事实从哪来 | 规则会提出什么 |
|---|---|---|
| 原力健康 | Apple Health `export.xml`、App 推送、收件箱 CSV | HRV 比 28 天基线低 15% 以上 → 本周降负荷（附可度量目标）；连续 3 晚睡眠不足 6.5 小时 |
| 原力投研 | 净值 CSV / 推送 | 一年内回撤 ≥15% → 复核持仓（≥30% 为 P0）；投资判断带概率和到期日 |
| 原力创业 | `project_evidence_envelope_v1` | envelope 里待拍板的事项；14 天没有进展 → 推进、砍掉或推迟；风险转红 → P0 |
| 原力内容 | 阅读数据 | 7 天阅读达中位数 2 倍 → 做成系列；达 3 倍 → 正典候选；批准的发布交给 Dify / n8n |
| 原力OS | 机器心跳、本地仓库 | 机器静默超过 6 小时；仓库闲置天数 |

新增一个领域：在 `yuanli/domains/` 下写一个 `domain() -> Domain`（sources / rules / metrics / actions），再在 `domains/__init__.py` 里登记。

### 接口

| 方法 | 路径 | 谁能用 |
|---|---|---|
| GET | `/api/brief` · `/api/items` · `/api/items/{id}` · `/api/domains/{key}` · `/api/facts/{key}` · `/api/calibration` · `/api/canon` · `/api/search?q=` · `/api/ask?q=` | 所有人（按可见范围过滤） |
| POST | `/api/items` · `/api/items/{id}/note` · `/api/facts`（可批量） · `/api/canon` | principal、agent |
| POST | `/api/items/{id}/decide` · `/api/items/{id}/settle` · `/api/canon/{id}/rule` · `/api/collect` | 仅 principal |
| GET | `/api/stream`（SSE，账本变化即推送） | 所有人 |
| GET | `/api/events?after=`（原始账本，用于审计和同步） | 仅 principal |

写接口支持 `Idempotency-Key` 请求头；`rev` 字段不一致时返回 409。

### 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `YUANLI_HOME` | `~/.yuanli` | 账本和收件箱所在目录 |
| `YUANLI_TOKENS` | 空（只能监听 localhost） | `token:name:role[:audience],…`，用 `yuanli token` 生成 |
| `YUANLI_PRINCIPAL` | `principal` | 本机 CLI 的签名者名字 |
| `YUANLI_TZ` | `Asia/Shanghai` | "今天"按哪个时区算 |
| `YUANLI_DOMAINS` | 全部 | 例如 `health,invest` |
| `YUANLI_BRAIN` / `YUANLI_MODEL` | 关 / `claude-opus-5` | `=1` 时由 Claude 基于检索结果作答并带引用 |
| `YUANLI_APPLE_HEALTH_EXPORT` · `YUANLI_VENTURE_PROJECTS` · `YUANLI_HEARTBEAT_DIR` · `YUANLI_REPOS` · `YUANLI_CONTENT_PUBLISH_HOOK` | —— | 各领域的数据源和执行器 |

### 开发

```bash
pip install -e ".[dev]" && pytest          # 40 个测试，约 1 秒
python bench/bench.py ../yuanli-os-max 5000
```
