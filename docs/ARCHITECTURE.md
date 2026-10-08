# 原力OS 目标架构：从第一性原理出发

> 适用于 `yuanli-life/yuanli-os` 内核及健康、投研、创业、内容四个领域。现状诊断见 [REVIEW.md](REVIEW.md)，清理与迁移清单见 [MIGRATION.md](MIGRATION.md)。

## 1. 先问：这个板块到底在做什么

把所有名词（CTX/DEC/WPK/ACT/OUT/LRN、G0R、SVC1、FED0、A0–A4、Contract1–4……）剥掉，四个领域做的是同一件事：

```
事实进来 → 提出一个判断 → 本人拍板 → 承接下一步 → 记录发生了什么 → 看结果 → 留下经验 → 下一次带着经验开始
```

| 领域 | 事实从哪来 | 提出什么 | 结果怎么看 |
|---|---|---|---|
| 通用任务 | 本人授权的资料 | AI 给出备选、理由、判断条件 | 本人记录执行与观察 |
| 原力创业 | 项目资料包（需求、报价、变更） | 报价缺项检查 | 交付与复核、实际工时 |
| 原力投研 | 黄金行情快照 | 方向判断（起止日、中性区间） | 到期按同一端点结算 |
| 原力健康 | 睡眠、HRV 等观测 | 本周调整建议 | 下周观测对比 |
| 原力内容 | 选题库、阅读数据 | 选题与草稿 | 24h / 72h / 7d 阅读 |

现在的代码里，这条闭环被实现了不止一次：v1 任务、v2 任务、项目任务、Gold 判断、健康 Today、内容 Campaign 各有各的状态机、存储和校验。目标是**一个闭环、一种存储、多个领域插件**。

## 2. 设计目标（可度量）

| 目标 | 现状 | 目标值 |
|---|---|---|
| 登录次数 | OS 一次 + 健康再一次 | 1 |
| 开始记录前的步骤 | 先"开启任务保存"并确认范围 | 0（默认保存） |
| 生成一次 AI 建议的前置 | 运营方为该任务写环境变量 | 0（在月度预算内） |
| 每个请求的数据库往返 | 目录实测 15 次；一次续接写入按代码路径约 15 次 | ≤ 4 |
| 读一个任务的成本 | 递归回溯经验链最多 8 层并重新校验 | 只读本任务的事件 |
| 新增一个领域 | 改内核、加表单、加闸门 | 加一个目录，不改内核 |
| 治理 | 回执、契约 YAML、证据哈希、闸门脚本 | 代码里的一张写入规则表 + git 历史 + 测试 |

不变的安全承诺（来自原设计里正确的部分）：人签不可代；AI 原文与人的判断分开保存；证据可追溯；幂等与乐观并发；按主体的 RLS；模型调用前后复查来源权限；到期验真。

## 3. 总体结构

```
┌──────────────────────── 领域模块（每个一个目录）────────────────────────┐
│  task      venture        invest          health          content     │
│  通用任务   报价→交付       判断→到期结算     观测→本周调整     选题→发布→阅读 │
│  schema · project(events) · rules(facts) · actions · panel           │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │ append(event) / read(stream)
┌──────────────────────────────────▼────────────────────────────────────┐
│ 内核                                                                    │
│  身份 → 主体 ── policy(谁能写哪种事件) ── events 表（只追加）               │
│                                          └─ streams 表（列表摘要，同事务更新）│
│  facts / sources / grants        budget（模型月度预算）                      │
│  接入面：Web（一个 SPA）· HTTP /api/v1 · MCP（读 + 提议）· agent token 推事实 │
└───────────────────────────────────────────────────────────────────────┘
```

方框是代码职责，不是部署单元：仍然是一个 Netlify 站点、一个 Postgres。

## 4. 五个原语

| 原语 | 是什么 | 取代 |
|---|---|---|
| **Principal** | 一个人（`principal_id`），身份系统里的账号绑定到它 | tenant/user/node/ecosystem 四元组、personal node、A0–A4 |
| **Fact** | 带来源和时间的观测：`source_id, key, value, observed_at, revision` | 资料授权快照、健康投影、行情快照、阅读回执 |
| **Stream** | 一件需要本人判断的事（一个任务、一个项目、一个投研判断、一个选题） | CTX 根对象、Gold claim、内容 Campaign 节点 |
| **Event** | Stream 上的一条只追加记录：`type, actor, data, idempotency_key` | DEC/WPK/ACT/OUT/LRN 子对象、payload 里的事件数组、回执 |
| **Projection** | 对事件的纯函数折叠，得到界面上的视图 | TaskReadBatch、各种 `*View` 拼装、提交进仓库的看板 JSON |

事件类型是一个封闭词表，现有能力都能映射过去：

| 事件 | 谁能写 | 现在对应 |
|---|---|---|
| `opened` | 本人 / 规则 | 新建任务、选定项目资料包、登记投研判断 |
| `proposal.generated` | AI | v2 `proposal`、报价检查 `complete_check` |
| `proposal.failed` | 系统 | `generation.state=FAILED/UNKNOWN`、`fail_check` |
| `decided` | **本人** | v2 `humanDecision`、v1 feedback、项目 `decide` |
| `step.proposed` / `step.committed` | 本人 / **本人** | WPK `propose` / `accept` |
| `executed` | **本人** | ACT `record_execution` |
| `observed` | **本人** / 系统（行情、阅读数） | OUT `observe_outcome`、Gold 到期数据 |
| `settled` | 系统按规则 | Gold 结算、带概率判断的 Brier |
| `learning.proposed` / `learning.reviewed` | 本人 / **本人** | LRN `propose` / `review` |
| `learning.applied` | **本人** | learning_use、预载 |
| `deleted` | **本人** | 删除墓碑 |

加粗的是人签事件。领域可以在 `data` 里带自己的字段（例如项目的价格/工时影响、投研的方向和中性区间），由领域的 schema 校验。

## 5. 存储：一张事件表，一张流表

```sql
create table streams (
  stream_id    uuid primary key,
  principal_id uuid not null,
  domain       text not null,          -- task | venture | invest | health | content
  version      int  not null,
  title        text not null,
  state        text not null,          -- 待判断 / 进行中 / 已结算 / 已删除
  due_at       timestamptz,
  updated_at   timestamptz not null,
  summary      jsonb not null          -- 列表卡片需要的字段，与事件同一事务更新
);
create table events (
  stream_id       uuid not null references streams,
  seq             int  not null,
  principal_id    uuid not null,
  type            text not null,
  actor           text not null,       -- human:<id> | ai:<model> | system:<rule>
  data            jsonb not null,
  idempotency_key text not null,
  at              timestamptz not null default now(),
  primary key (stream_id, seq),
  unique (stream_id, idempotency_key)
);
-- RLS：principal_id = current_setting('yuanli.principal_id')::uuid，两张表各一条策略
```

- **写**：一个 SQL 函数 `yuanli_append(stream, expected_version, key, type, actor, data, summary)`。版本不符返回 `VERSION_CONFLICT`；同一幂等键返回原结果。一次往返完成乐观并发、幂等和列表摘要更新，取代现在"锁根 → 读整棵对象树 → 校验 → 插入或更新子对象 → 推进根版本 → 重新读视图"。
- **读一个**：`select … from events where stream_id=$1 order by seq`，再用领域的 `project()` 折叠。现有 `projectWorkPackage`、`projectProgress`、`projectLearning` 已经是这种纯函数，可以直接复用。
- **列表**：只读 `streams`，按 `(updated_at, stream_id)` 游标分页。不再为了列表去读子对象或校验祖先。
- **经验复用**：预载时把来源任务的经验版本写进 `learning.applied` 事件。来源经验被撤回时，追加一条事件即可让下游显示"依据已撤回"，而不是每次读都递归回溯 8 层。
- **事实**：`facts(principal_id, source_id, key, value, observed_at, revision)`，只追加；需要时间点查询就按 `observed_at` 取。

## 6. 授权：一个主体列，三种人签事件

- **身份 → 主体**：`bindings(auth_subject → principal_id, status)`。一个 `SECURITY DEFINER` 函数 `yuanli_begin(auth_subject)` 在同一次调用里解析绑定、`set_config('role', 'yuanli_runtime')`、设置 `yuanli.principal_id`。每个请求：`BEGIN` + `yuanli_begin` + 业务语句 + `COMMIT`，≤ 4 次往返。
- **写入规则**：代码里一张表决定哪些 actor 能写哪些事件类型（§4）。这是唯一的"闸门"，取代 A0–A4、record permit、recording consent、invocation permit 四套机制。
- **资料授权**：`grants(principal_id, source_id, mode, expires_at, revoked_at)`。模型调用前读一次，追加 `proposal.generated` 前在同一事务里再读一次（保留"外部调用后复查"这条不变量）。
- **模型花费**：`budgets(principal_id, month, limit_minor, spent_minor)`。调用前在一个事务里原子预留单次上限，结束后按实际结算；超额返回 `BUDGET_EXHAUSTED`。不再需要逐任务的环境变量许可，也不需要无法验证的"成本证据哈希"。
- **保存**：默认保存。首次使用时确认一次服务条款；用户可以随时导出或删除。

## 7. 领域模块契约

```ts
export interface Domain<View> {
  key: "task" | "venture" | "invest" | "health" | "content";
  title: string;
  /** 本领域在事件 data 里额外携带的字段 */
  schemas: Partial<Record<EventType, ZodType>>;
  /** 纯函数：事件 → 界面视图 */
  project(events: Event[]): View;
  /** 纯函数：新事实 → 建议新开的流（例如 HRV 连续偏低 → 本周降负荷） */
  rules?: (facts: Fact[], now: Date) => Opened[];
  /** 本人批准后执行的动作（发布文章、写回飞书），结果以事件写回 */
  actions?: Record<string, (stream: View) => Promise<EventInput>>;
  /** 懒加载的界面面板 */
  panel: () => Promise<{ mount(root: HTMLElement, api: Api): () => void }>;
}
```

| 领域 | 迁入后是什么 |
|---|---|
| task | 现有 v2 任务：资料 → AI 建议 → 判断 → 下一步 → 执行 → 观察 → 经验 |
| venture | 现有项目工作台：资料包 → 报价检查 → 判断（价格/成本/工时/交期）→ 复核与工时 |
| invest | Gold 判断成为 `domain=invest` 的流；研究运行时继续是外部服务，行情快照与到期数据以 `observed` 写入；结算是规则 |
| health | iOS/Watch 或健康 Supabase 用 agent token 推入日级事实；规则产生"本周调整"流；浏览器不再有第二次登录 |
| content | 选题是流；发布是批准后的 action（Dify / 小鹅通）；24h/72h/7d 阅读是 `observed`；看板是查询 |

## 8. 接入面

- **Web**：一个 SPA，三类页面：`/`（今天）、`/d/:domain`（领域页）、`/s/:id`（一件事的时间线）。
- **HTTP**：`/api/v1/streams`（列表、读、追加事件）、`/api/v1/facts`（批量写事实）、`/api/v1/sources`。一套版本。
- **MCP**：读工具 + "提议"工具（只能写 AI 可写的事件类型，例如 `opened`、`proposal.generated`）。人签事件只能在 Web 完成。
- **Agent token**：给 iOS/Watch、Dify、n8n、定时任务推事实用，只能写 `facts`。

## 9. 体验

1. **今天一屏**：待我判断（按到期日）、我已承接（逾期标红）、新事实触发的建议。四个领域混排，带领域标签。
2. **一件事一条时间线**：AI 原文、我的判断、下一步、执行、观察、经验按时间排列；底部只有一个输入框，根据当前状态提示下一步该写什么。取代现在的 7 个表单和 7 个保存按钮。
3. **键盘优先**：`j/k` 移动、`a` 采用、`m` 调整、`r` 不采用、`n` 记一笔、`/` 搜索。
4. **乐观更新 + 版本冲突合并提示**：保存立即反映；遇到 `VERSION_CONFLICT` 时保留草稿并展示对方的新事件。
5. **少说免责**：每页一处说明"AI 建议需要你判断；记录是你本人的报告"，而不是每次保存都附一段。

## 10. 性能预算

| 路径 | 现在 | 目标 |
|---|---|---|
| 列表（目录） | 15 次往返；为每个任务读子对象并递归校验经验链 | 3 次往返；只读 `streams` |
| 读一件事 | 批量读根与子对象 + 来源授权 + 递归依赖 | 3 次往返；读事件并折叠 |
| 写一个事件 | 进入会话 7 次 + 锁根、读视图、写子对象、推进根版本、重读视图，约 15 次 | 3–4 次往返；一个 `yuanli_append` |
| 生成建议 | 读许可（环境变量）+ 两套宿主的预留与校验 | 预算预留 1 次 + 来源复查 1 次 |

数据量：单个主体在 10⁴ 流、10⁵ 事件量级，事件表按 `(stream_id, seq)` 主键即可；列表按 `(principal_id, updated_at)` 索引。

## 11. 迁移路径：每一步都可回退

| 阶段 | 内容 | 回退方式 |
|---|---|---|
| 0 ✅ | [yuanli-os#81](https://github.com/yuanli-life/yuanli-os/pull/81)：删除回显内核与预览路由、压平应用层、去掉常量标志、简化 CI 闸门 | 回滚 PR |
| 1 | 不改表结构的决策项：默认保存；按主体预算；健康服务端代取；10-25 后退役 v1；确认并删除预览模式；删除流程文件 | 每项一个 PR，各自回滚 |
| 2 | 新建 `streams` / `events` / `facts` / `budgets`；现有写路径**双写**事件；回填脚本把 `yuanli_objects` 转成事件；测试里对每个夹具比较"旧视图 == 新折叠" | 关掉双写开关，新表不被读取 |
| 3 | 读路径切到事件表（开关控制）；删除递归经验校验；主体单列化（`principal_id` 即现在的 `userId`，tenant/node/ecosystem 变成主体表的属性） | 开关切回旧读路径 |
| 4 | 领域迁入：投研判断、健康事实、内容选题依次成为流和事实 | 每个领域独立开关 |
| 5 | 删除 `yuanli_objects` 代码路径；表保留只读归档 | 归档表仍在 |

## 12. 与 `claude-cloud` 里 3.0 原型的关系

`yuanli/` 下的 Python 原型（只追加 JSONL 账本 + 内存折叠，7 种事件、3 种角色）验证的是同一套内核语义，只是面向单个用户、单机。它的价值在两处：

1. 证明"事件 + 折叠"足以承载全部闭环，读取可以与历史规模无关；
2. 领域规则可以直接移植（HRV 低于 28 天基线、回撤复核、项目停滞、阅读异常值）。

它**不应**成长为第二个生产内核——那会重演"多个仓库各自实现同一闭环"的问题。生产内核是 `yuanli-life/yuanli-os`；原型保留为参考实现和离线个人工具，规则移植完成后可以归档。原型自己的设计说明见 [`prototype/ARCHITECTURE.md`](prototype/ARCHITECTURE.md)。
