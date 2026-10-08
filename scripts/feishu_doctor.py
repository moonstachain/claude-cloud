#!/usr/bin/env python3
"""Check that the Feishu CLI (lark-cli) can talk to Feishu as the app's bot.

Runs four checks in order and stops at the first failure, printing what to fix:
  1. lark-cli is installed
  2. app credentials are present (LARKSUITE_CLI_APP_ID / LARKSUITE_CLI_APP_SECRET,
     or a profile from `lark-cli config init`)
  3. open.feishu.cn is reachable through the network policy
  4. a read-only call (GET /open-apis/bot/v3/info) succeeds as the bot

Exit 0 when all pass, 1 otherwise. Never prints the app secret.
Usage: python3 scripts/feishu_doctor.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

OPEN_API = "https://open.feishu.cn"
SETTINGS = "云环境设置（会话标题栏的云环境菜单 → Edit）"


def ok(msg: str) -> None:
    print(f"[feishu] ✅ {msg}")


def fail(msg: str, fix: str) -> int:
    print(f"[feishu] ❌ {msg}")
    print(f"[feishu]    → {fix}")
    return 1


def run(args: list[str], timeout: int = 30) -> tuple[int, dict | None, str]:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, None, "timeout"
    for text in (p.stdout, p.stderr):
        try:
            return p.returncode, json.loads(text), ""
        except ValueError:
            continue
    return p.returncode, None, (p.stderr or p.stdout).strip()


def find(obj, key: str):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            hit = find(v, key)
            if hit is not None:
                return hit
    return None


def check_cli() -> int:
    exe = shutil.which("lark-cli")
    if not exe:
        return fail("没有安装 lark-cli", "npm install -g @larksuite/cli")
    _, _, out = run([exe, "--version"], timeout=10)
    ok(out or "lark-cli 已安装")
    return 0


def check_credentials() -> int:
    app_id = os.environ.get("LARKSUITE_CLI_APP_ID", "").strip()
    has_secret = bool(os.environ.get("LARKSUITE_CLI_APP_SECRET", "").strip())
    if app_id and has_secret:
        ok(f"凭证来自环境变量：App ID {app_id[:8]}…，App Secret 已设置")
        return 0
    if app_id or has_secret:
        missing = "LARKSUITE_CLI_APP_SECRET" if app_id else "LARKSUITE_CLI_APP_ID"
        return fail(f"缺少环境变量 {missing}", f"在{SETTINGS}的环境变量里补上，然后开新会话")
    code, cfg, _ = run(["lark-cli", "config", "show"], timeout=10)
    if code == 0 and cfg and cfg.get("ok", True):
        ok("凭证来自本机 lark-cli 配置（config init）")
        return 0
    return fail(
        "没有找到飞书应用凭证",
        f"在{SETTINGS}的环境变量里加 LARKSUITE_CLI_APP_ID 和 LARKSUITE_CLI_APP_SECRET，然后开新会话",
    )


def check_network() -> int:
    try:
        urllib.request.urlopen(OPEN_API + "/open-apis/", timeout=10)
    except urllib.error.HTTPError:
        pass  # any HTTP answer from Feishu means the host is reachable
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        return fail(
            f"连不上 open.feishu.cn（{reason}）",
            f"在{SETTINGS}的 Network access → Allowed domains 里加 open.feishu.cn",
        )
    ok("open.feishu.cn 网络可达")
    return 0


def check_bot() -> int:
    code, res, raw = run(["lark-cli", "api", "GET", "/open-apis/bot/v3/info", "--as", "bot"])
    if code == 0 and res and res.get("ok", True) and res.get("code", 0) == 0:
        name = find(res, "app_name") or "（未返回名称）"
        status = find(res, "activate_status")
        note = "" if status in (None, 2) else f"，机器人激活状态 {status}（2 为已激活）"
        ok(f"机器人可用：{name}{note}")
        return 0
    err = (res or {}).get("error") or {}
    msg = err.get("message") or (res or {}).get("msg") or raw or f"exit {code}"
    hint = err.get("hint") or "检查 App ID / App Secret 是否正确，应用是否已在开放平台发布版本"
    return fail(f"机器人调用失败：{msg}", hint)


def main() -> int:
    for check in (check_cli, check_credentials, check_network, check_bot):
        if check():
            return 1
    print("[feishu] 飞书已连通，可以用 `lark-cli <domain> --help` 开始操作（机器人身份加 --as bot）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
