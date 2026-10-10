#!/usr/bin/env python3
"""lhg-fund-dca 硬门②（警告级，不拦截）：写入定投计划文档后做合规检查。

触发：PostToolUse / Write|Edit。只做提醒，永远 exit 0、不拦截写入。
检查两件事：
  1. 定投计划类文档缺合规声明（"非投资建议"/"不构成"）→ 警告补上；
  2. 文档中出现具体产品推荐嫌疑（6 位基金代码）→ 警告删除。

逃生方式：LHG_DCA_HOOKS_OFF=1（环境变量）可关闭本提醒；
或 /plugin disable lhg-fund-dca 停用整个插件。
零第三方依赖。
"""

import json
import os
import re
import sys

PLAN_FILE_RES = [
    re.compile(r"定投|dca", re.I),
    re.compile(r"计划|plan", re.I),
    re.compile(r"复盘|review|回顾", re.I),
]
COMPLIANCE_RES = [re.compile(r"非投资建议"), re.compile(r"不构成")]
CODE_RE = re.compile(r"(?<![\d.])\d{6}(?!\d)")


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(200000)
    except OSError:
        return ""


def main() -> int:
    if os.environ.get("LHG_DCA_HOOKS_OFF") == "1":
        return 0

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "") or ""
    if not file_path:
        return 0

    base = os.path.basename(file_path)
    if not any(r.search(base) for r in PLAN_FILE_RES):
        return 0  # 非定投文档：不打扰

    text = read_text(file_path)
    if not text:
        return 0

    warns = []
    if not any(r.search(text) for r in COMPLIANCE_RES):
        warns.append("缺少合规声明（须含“非投资建议 / 不构成投顾服务”字样），请在文档末尾补上。")
    for i, ln in enumerate(text.split("\n")):
        if CODE_RE.search(ln) and re.search(r"基金|代码|买入|推荐|申购", ln):
            warns.append("第 %d 行疑似出现具体基金代码（6 位数字），按合规要求请删除具体产品推荐。" % (i + 1))
            break

    if not warns:
        return 0

    msg = "合规提醒（lhg-fund-dca）：%s\n%s\n关闭本提醒：export LHG_DCA_HOOKS_OFF=1（当前会话有效）。/lhg-fund-dca:check 可做全面自查。" % (
        file_path, "\n".join(" - " + w for w in warns))
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
