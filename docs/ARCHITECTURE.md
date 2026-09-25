# 原力OS 3.0 架构：从第一性原理出发

## 1. 先问：原力OS 到底是什么？

把五个仓库里所有的名词剥掉，剩下的是同一个动作，每天重复：

```
观察现实 → 提出判断 → 人拍板 → 去做 → 看结果 → 学到东西 → 下一次判断更准
 observe     propose     decide    act     settle     learn
```

这就是母机制"每一次输出，都必须成为下一次输入"的字面实现。健康、投研、创业、内容只是**事实从哪里来、什么情况值得提一个判断**不同，闭环本身完全一样。

所以正确的分层只有两层：

```
┌───────────────────────── 领域应用（每个约 100 行）─────────────────────────┐
│  原力健康         原力投研           原力创业            原力内容      原力OS │
│  HRV/睡眠 → 恢复   净值 → 回撤复核     envelope → 停滞/转红  阅读 → 爆款   心跳  │
│  sources · rules · metrics · actions                                     │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │ Emit(fact | proposal | candidate)
┌──────────────────────────────────▼──────────────────────────────────────┐
│ 内核（闭环本身）                                                           │
│  policy ──► ledger.jsonl ──fold──► State（内存）──► brief / 搜索 / 校准 / 导出 │
│  (谁能写)    (唯一真相)              (O(1) 读)       HTTP + SSE + CLI + UI    │
└─────────────────────────────────────────────────────────────────────────┘
```

## 2. 五个原语

| 原语 | 是什么 | 取代了 |
|---|---|---|
| **Event** | 账本中的一行：`seq, id, ts, type, actor, data` | Envelope、RulingPacket、DecisionReceipt、ActionProposal、outbox、receipts、traces、snapshots |
| **Fact** | `key, value, at`，例如 `health.hrv = 47 @ 2026-09-20` | 各仓的指标表、PIT 观测表、心跳、健康汇总 |
| **Item** | 一个需要人拍板的判断，可带概率、到期日和可度量的目标 | 决策队列、Take 卡、项目 decisions_needed、各类"作战卡" |
| **Canon** | 从现实中学到、经人采纳的原则 | brain-kernel 的 canon registry、promotion gate |
| **Actor** | `principal / agent / viewer` + 可见范围 | G0/G1/G2、truth-writer 开关、CSRF、profile、S0–S3 |

全部词汇只有 7 种事件（完整定义见 `yuanli/state.py` 文件头）：

```
fact.observed   item.proposed   item.decided   item.noted   item.settled   canon.proposed   canon.ruled
```

## 3. 为什么是"只追加账本 + 内存折叠"

一个结构同时解决旧系统用十几套机制拼出来的问题：

| 需求 | 旧系统的做法 | 账本如何天然满足 |
|---|---|---|
| 真相源 | JSON + JSONL + outbox + SQLite，靠文件锁对齐 | 只有一个文件 |
| 审计 | receipts + sha256 + 事件账本 | 账本本身就是审计记录；提交到 git 即可防篡改 |
| 历史 / 追踪 | `history` 表 + `runtime_events` 表 + `snapshots.jsonl` | 每个 Item 自带 `trail`（它的全部事件） |
| 幂等 | 9 个字段比较两遍 + glob 全目录 | 事件 id 重复即返回原事件 |
| 并发 | 两把锁 + revision + 内容哈希 + If-Match | 一把 flock；`rev` 乐观并发，不一致返回 409 |
| 多进程 | truth-writer 单写者 + outbox 两阶段 | 写入前在锁内按字节偏移追平其他进程的写入 |
| Point-in-time | 投研单独建 PIT schema（`available_at`、`vintage_id` 等） | 事件 `ts` 就是"何时知道"，重放到任意时刻都诚实 |
| 崩溃恢复 | 事务日志 + 回滚快照 | 最后一行不完整（崩溃时的半截写入）就截掉；其余全部有效 |

**为什么放内存**：个人 OS 的数据量在 10⁵–10⁶ 个事件量级。实测重放 3.1 万事件需 238 ms，JSON 行解析约 5–8 µs/事件。放进内存之后，读取是 dict 查找，不需要数据库服务器、ORM 或迁移脚本。事件超过约 100 万时，加一个"快照 + 增量重放"即可，不需要改架构。

## 4. 治理：一个函数

```python
HUMAN_ONLY   = {"item.decided", "item.settled", "canon.ruled"}      # 只有人能做
AGENT_WRITES = {"fact.observed", "item.proposed", "item.noted", "canon.proposed"}
```

- **人签不可代**：机器可以提议、附证据、给出概率，但拍板和结算必须是人。这是原设计里正确的内核，原样保留。
- **批准即授权**：领域用代码注册执行器（`actions`）。人批准之后，内核在后台执行，结果以 `item.noted` 写回。执行器是经过审查的代码，不是按字符串黑名单放行，所以不再需要 G2 永不执行。
- **可见范围按构造保证**：每条记录自带 scope（默认 private）。brief、搜索、查询、导出都只序列化受众能看到的记录，不需要事后用正则扫描。
- **网络边界**：没有配置 token 时，只允许监听 localhost；对外服务必须配置 `YUANLI_TOKENS`。这是唯一的启动检查。

## 5. 领域应用契约

```python
Domain(
    key="health", title="原力健康",
    sources=[inbox(...), apple_health(export)],   # fetch() -> Emit*，并发执行，失败降级为可见状态
    rules=[recovery, sleep_debt],                 # rule(state, today) -> Emit*，纯函数，id 确定性去重
    metrics=[Metric("health.hrv", "HRV", "ms")],  # 领域页的数值卡片
    actions={"publish": webhook(url)},            # 人批准后执行
)
```

新增一个领域 = 写一个约 100 行的文件，加入 `domains/__init__.py`，不改内核。规则产出的提案 id 包含周或月（例如 `health:recovery:2026-W39`），所以同一周期不会重复打扰；被否决后也不会再次出现。

**通用接入**：
- **收件箱目录**：把 `.csv` 或 `.jsonl` 放进 `~/.yuanli/inbox/<领域>/`，列名别名自动归一（`key|metric`、`value|nav`、`at|date|day`、`code`）。
- **HTTP**：`POST /api/facts`（可批量）。iOS / Watch App、Dify、n8n、定时任务都可以用 agent token 直接推送。

## 6. 体验原则

1. **一屏**：今天 = 待拍板 + 进行中。其余都是下钻。
2. **一键一决定**：`j/k` 移动，`a` 批准，`r` 否决，`d` 推迟，`s` 结算，`n` 备注，`Enter` 看详情和完整轨迹，`/` 搜索或提问。
3. **乐观更新 + 实时同步**：点击后卡片立即淡出，请求在后台完成；账本序号一变化，SSE 会推送给所有打开的端（手机批准，电脑立刻更新）。
4. **结算有建议**：带 `measure` 的判断会显示"建议结算：达成（实测 47 / 目标 45）"，确认只需一次按键。
5. **分享即快照**：`yuanli export --audience public` 生成静态只读页面，只包含公开记录。
6. **诚实**：来源掉线就显示掉线；没有数据就显示"还没有数据"；校准没有样本就显示 n=0。

## 7. 刻意不做的事

- 不做多租户、微服务、数据库服务器、消息队列、schema 注册中心。
- 不做哈希回执、fail-closed 清单、字符串黑名单、双轨流程、版本化文件名。
- 不在运行时扫描密钥：CI 里的 gitleaks 足够。
- 不用 LLM 做判断：规则是确定性的；LLM 只在显式开启 `YUANLI_BRAIN=1` 时，基于检索到的记录写带引用的回答。

## 8. 演进路径

| 触发条件 | 做法 |
|---|---|
| 账本超过约 100 万事件 | 定期把 State 序列化为快照，启动时加载快照再重放增量 |
| 多台设备写入 | 已支持：多进程 flock 串行化写入 + 按偏移追平；远程设备通过 HTTP 写入 |
| 备份 | 账本是 git 友好的 JSONL，可以直接 `git commit`，或同步到 iCloud / NAS |
| 大量原始时序（逐分钟心率等） | 原始流留在来源系统，账本只记录日级聚合事实 |
| 需要复杂分析 | 把账本导出为 Parquet 或 DuckDB 做离线分析；在线路径保持不变 |
