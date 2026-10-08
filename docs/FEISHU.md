# 接入飞书 CLI

用飞书官方 CLI [`@larksuite/cli`](https://github.com/larksuite/cli)（命令 `lark-cli`），以**应用机器人**身份操作国内飞书：发消息、读写授权给应用的文档和多维表格。

云端会话启动时，`.claude/hooks/session-start.sh` 会自动安装 `lark-cli` 和它的 Agent Skills（`lark-im`、`lark-base` 等，相当于官方的 `npx @larksuite/cli@latest install`），并运行 `scripts/feishu_doctor.py` 检查连通性。检查结果会出现在会话开头，缺什么就提示补什么。

## 一次性设置

### 1. 飞书开放平台（open.feishu.cn/app）

1. 创建**企业自建应用**，在"凭证与基础信息"里拿到 App ID（`cli_` 开头）和 App Secret。
2. 添加应用能力 → **机器人**。
3. 权限管理里开通要用的权限，例如：

   | 用途 | 权限 |
   |---|---|
   | 以机器人身份发消息 | `im:message:send_as_bot` |
   | 多维表格 | `bitable:app` |
   | 文档 | `docx:document` |
   | 云空间文件 | `drive:drive` |

4. 版本管理与发布 → 创建版本并发布。权限在发布后才生效。
5. 机器人只能访问别人给它的东西：文档、多维表格里要"添加文档应用"，群聊里要先把机器人拉进群。

### 2. 云环境设置（会话标题栏的云环境菜单 → Edit）

| 位置 | 填什么 |
|---|---|
| Network access → Allowed domains | `open.feishu.cn`（保持 "Allow package managers" 勾选） |
| 环境变量 | `LARKSUITE_CLI_APP_ID=cli_xxx`、`LARKSUITE_CLI_APP_SECRET=…` |

App Secret 只放在环境变量里，不要写进仓库，也不要贴到聊天里。改完后开一个新会话。

## 检查与使用

```bash
python3 scripts/feishu_doctor.py      # 依次检查：CLI、凭证、网络、机器人调用
lark-cli im --help                    # 每个业务域的命令；机器人身份加 --as bot
lark-cli api GET /open-apis/bot/v3/info --as bot
```

`feishu_doctor.py` 全部通过时退出码为 0，不会打印 App Secret。

本地使用：`npm install -g @larksuite/cli` 后运行 `lark-cli config init`，凭证会存进系统钥匙串，doctor 同样能识别。
