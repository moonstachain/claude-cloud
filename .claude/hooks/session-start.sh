#!/bin/bash
# Cloud-session setup: project deps for tests/lint, plus the Feishu CLI and a
# connectivity check whose report lands in the session context.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

pip install -q --root-user-action=ignore -e ".[dev]" ruff

LARK_CLI_VERSION="${LARK_CLI_VERSION:-1.0.97}"
if [ "$(lark-cli --version 2>/dev/null | awk '{print $NF}')" != "$LARK_CLI_VERSION" ]; then
  npm install -g --silent "@larksuite/cli@${LARK_CLI_VERSION}" >/dev/null
fi

# Agent skills (lark-im, lark-base, ...), same as `npx @larksuite/cli install` step 2.
if [ ! -e "$HOME/.claude/skills/lark-shared" ]; then
  npx -y skills add larksuite/cli -y -g >/dev/null 2>&1 \
    || echo "[feishu] ⚠️ Skills 安装失败，可手动运行：npx skills add larksuite/cli -y -g"
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  # The image ships a standalone pytest (own venv, can't import yuanli) earlier on PATH.
  echo "export PATH=\"$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts"))'):\$PATH\"" >> "$CLAUDE_ENV_FILE"
  echo 'export LARKSUITE_CLI_NO_UPDATE_NOTIFIER=1' >> "$CLAUDE_ENV_FILE"
  echo 'export LARKSUITE_CLI_NO_SKILLS_NOTIFIER=1' >> "$CLAUDE_ENV_FILE"
fi

# Report only; a missing secret or blocked host must not fail session start.
timeout 60 python3 scripts/feishu_doctor.py || true
