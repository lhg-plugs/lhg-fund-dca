#!/usr/bin/env python3
"""lhg-fund-dca 确定性定投审计：15 条规则，零第三方依赖。

扫描目标目录的定投计划 / 复盘 Markdown 文档，输出 JSON 与人类可读报告；
有 blocker 时以 exit code 2 退出（供 hooks 与 CI 使用）。

用法：
    python3 fund_audit.py --target <目录> [--format json|text] [--fail-on blocker|warning|nit]

规则文案均为本项目原创。本工具是计划完整性检查，不是投资建议。
"""

import argparse
import json
import os
import re
import sys

VERSION = "1.0.0"
TOOL = "lhg-fund-dca/fund-audit"

SKIP_DIRS = {".git", "__pycache__", "node_modules", "dist", "build"}
SCAN_EXTS = {".md", ".markdown", ".txt"}

PLAN_RES = [re.compile(r"定投|dca", re.I), re.compile(r"计划|plan", re.I)]
REVIEW_RES = [re.compile(r"复盘|review|回顾", re.I)]

COMPLIANCE_WORDS = ["非投资建议", "不构成"]
CODE_RE = re.compile(r"(?<![\d.])\d{6}(?!\d)")
PROMISE_WORDS = ["保证收益", "稳赚", "保本高收益", "必达", "一定能赚", "包赚"]


class Finding:
    __slots__ = ("rule_id", "severity", "category", "title", "file", "line", "snippet", "detail")

    def __init__(self, rule_id, severity, category, title, file, line, snippet, detail):
        self.rule_id = rule_id
        self.severity = severity
        self.category = category
        self.title = title
        self.file = file
        self.line = line
        self.snippet = snippet
        self.detail = detail

    def to_dict(self):
        return {
            "rule_id": self.rule_id, "severity": self.severity,
            "category": self.category, "title": self.title,
            "file": self.file, "line": self.line,
            "snippet": self.snippet, "detail": self.detail,
        }


def collect_files(target):
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            _, ext = os.path.splitext(f)
            if ext.lower() in SCAN_EXTS:
                out.append(os.path.join(root, f))
    return sorted(out)


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _match_any(res, text):
    return any(r.search(text) for r in res)


def _parse_amount(s):
    s = s.replace(",", "").replace("，", "").replace("¥", "").replace("元", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- 规则注册表
RULES = []


def rule(rule_id, severity, category, title, detail):
    def deco(fn):
        RULES.append({"id": rule_id, "severity": severity, "category": category,
                      "title": title, "detail": detail, "check": fn})
        return fn
    return deco


def _plan_files(files):
    return [p for p in files
            if _match_any(PLAN_RES, os.path.basename(p))
            and not _match_any(REVIEW_RES, os.path.basename(p))]


def _review_files(files):
    return [p for p in files if _match_any(REVIEW_RES, os.path.basename(p))]


# ---------------- 计划完整性 ----------------

@rule("FD-PLN-001", "blocker", "plan", "计划缺目标金额",
      "定投计划文档里没有“目标金额”。无目标的定投坚持不下去——先写下这笔钱是干什么用的、要攒到多少。")
def _pln001(files, ctx):
    out = []
    for p in _plan_files(files):
        if not re.search(r"目标金额|目标：", ctx[p]):
            out.append(Finding("FD-PLN-001", "blocker", "plan", "计划缺目标金额",
                               p, 1, os.path.basename(p)[:80],
                               "补上“目标金额：X 元”，并写清用途（首付/教育金/养老）。"))
    return out


@rule("FD-PLN-002", "blocker", "plan", "计划缺期限",
      "定投计划文档里没有“期限/期数”。期限决定每期金额和品种框架，没有期限算不出每期投多少。")
def _pln002(files, ctx):
    out = []
    for p in _plan_files(files):
        if not re.search(r"期限|期数", ctx[p]):
            out.append(Finding("FD-PLN-002", "blocker", "plan", "计划缺期限",
                               p, 1, os.path.basename(p)[:80],
                               "补上“期限：X 年（N 期）”；期限 <3 年要提示定投熨平波动需要时间。"))
    return out


@rule("FD-PLN-003", "blocker", "plan", "计划缺每期金额",
      "定投计划文档里没有“每期金额”。没有每期金额，计划无法执行。")
def _pln003(files, ctx):
    out = []
    for p in _plan_files(files):
        if not re.search(r"每期金额|每月定投|每期定投", ctx[p]):
            out.append(Finding("FD-PLN-003", "blocker", "plan", "计划缺每期金额",
                               p, 1, os.path.basename(p)[:80],
                               "用 lhg-dca-plan 情景区间测算每期金额，并检查 ≤月收入 30%。"))
    return out


@rule("FD-PLN-004", "warning", "plan", "计划缺纪律规则",
      "计划文档里没有“止盈/止损/再平衡”中任意关键词。没有纪律规则的定投，市场一波动就会变形。")
def _pln004(files, ctx):
    out = []
    for p in _plan_files(files):
        if not re.search(r"止盈|止损|再平衡", ctx[p]):
            out.append(Finding("FD-PLN-004", "warning", "plan", "计划缺纪律规则",
                               p, 1, "未见纪律规则",
                               "按 lhg-discipline 补上：止盈方法三选一、暂停/加码白名单、再平衡触发条件。"))
    return out


@rule("FD-PLN-005", "warning", "plan", "计划缺合规声明",
      "计划文档里没有合规声明关键词（“非投资建议”/“不构成”）。每次计划输出末尾必须附合规声明，一次都不许漏。")
def _pln005(files, ctx):
    out = []
    for p in _plan_files(files):
        if not any(w in ctx[p] for w in COMPLIANCE_WORDS):
            out.append(Finding("FD-PLN-005", "warning", "plan", "计划缺合规声明",
                               p, 1, "未见合规声明",
                               "末尾补上：本计划为个人财务规划工具输出，非投资建议，不构成投顾服务；投资有风险。"))
    return out


@rule("FD-PLN-006", "warning", "plan", "计划缺应急金说明",
      "计划文档里没有“应急金/备用金”。应急金没留足就定投，市场一跌就要赎回应急——先补应急金，不谈定投。")
def _pln006(files, ctx):
    out = []
    for p in _plan_files(files):
        if not re.search(r"应急金|备用金", ctx[p]):
            out.append(Finding("FD-PLN-006", "warning", "plan", "计划缺应急金说明",
                               p, 1, "未见应急金说明",
                               "确认是否留足 6 个月生活费；没留足则计划标注“暂缓”并先输出应急金补足计划。"))
    return out


# ---------------- 风控规则 ----------------

@rule("FD-INC-001", "blocker", "risk", "定投金额超月收入 30%",
      "每期金额超过月收入的 30%。这是现金流断裂线——市场跌时叠加收入波动，会被迫停扣，定投就死了。")
def _inc001(files, ctx):
    out = []
    for p in _plan_files(files):
        text = ctx[p]
        m_inc = re.search(r"月收入\s*[：:]\s*¥?\s*([\d,，]+)", text)
        m_amt = re.search(r"(?:每期金额|每月定投|每期定投)\s*[：:]\s*¥?\s*([\d,，]+)", text)
        if m_inc and m_amt:
            income = _parse_amount(m_inc.group(1))
            amt = _parse_amount(m_amt.group(1))
            if income and amt and amt > income * 0.30:
                out.append(Finding("FD-INC-001", "blocker", "risk", "定投金额超月收入 30%",
                                   p, 1, "每期 %.0f > 月收入 %.0f × 30%%（%.0f）" % (amt, income, income * 0.30),
                                   "降额到 30% 以内，或延长期限，没有例外。"))
    return out


@rule("FD-CNC-001", "warning", "risk", "单一品种集中度过高",
      "某单一品种占比超过 50%。定投的意义之一是分散，单品种过半等于把鸡蛋放在一个篮子里。")
def _cnc001(files, ctx):
    out = []
    for p in _plan_files(files):
        for i, ln in enumerate(ctx[p].split("\n")):
            m = re.match(r"\s*[-*]\s*([^：:]+?)\s*[：:]\s*(\d+(?:\.\d+)?)\s*[%％]", ln)
            if m and float(m.group(2)) > 50:
                out.append(Finding("FD-CNC-001", "warning", "risk", "单一品种集中度过高",
                                   p, i + 1, ln.strip()[:120],
                                   "单一品种占比降到 50% 以内，或说明集中持有的理由并经用户确认。"))
    return out


@rule("FD-FEE-001", "warning", "risk", "费率过高预警",
      "费率超过警戒线（管理费 >1.5% / 托管费 >0.25% / 申购费 >1%）。费率是唯一确定的收益，省下来的就是赚到的。")
def _fee001(files, ctx):
    out = []
    limits = {"管理费": 1.5, "托管费": 0.25, "申购费": 1.0}
    for p in _plan_files(files):
        for i, ln in enumerate(ctx[p].split("\n")):
            for name, lim in limits.items():
                m = re.search(name + r"[^\d]*(\d+(?:\.\d+)?)\s*[%％]", ln)
                if m and float(m.group(1)) > lim:
                    out.append(Finding("FD-FEE-001", "warning", "risk", "费率过高预警",
                                       p, i + 1, ln.strip()[:120],
                                       "%s %s%% 超过警戒线 %s%%，按 lhg-fund-filter 重新筛选。" % (
                                           name, m.group(1), lim)))
    return out


# ---------------- 合规红线 ----------------

@rule("FD-REC-001", "blocker", "compliance", "疑似具体产品推荐",
      "文档中出现 6 位数字基金代码且上下文含“基金/代码/买入/推荐/申购”。本插件绝不推荐具体产品——这是红线。")
def _rec001(files, ctx):
    out = []
    for p in _plan_files(files) + _review_files(files):
        for i, ln in enumerate(ctx[p].split("\n")):
            if CODE_RE.search(ln) and re.search(r"基金|代码|买入|推荐|申购", ln):
                out.append(Finding("FD-REC-001", "blocker", "compliance", "疑似具体产品推荐",
                                   p, i + 1, ln.strip()[:120],
                                   "删除具体产品名/代码，改用 lhg-fund-filter 的框架维度描述（如“宽基指数类”）。"))
                break
    return out


@rule("FD-RTN-001", "warning", "compliance", "承诺收益表述",
      "文档中出现承诺收益类表述（保证收益/稳赚/保本高收益/必达）。收益不能承诺，看到就改。")
def _rtn001(files, ctx):
    out = []
    for p in _plan_files(files) + _review_files(files):
        for i, ln in enumerate(ctx[p].split("\n")):
            hit = next((w for w in PROMISE_WORDS if w in ln), None)
            if hit:
                out.append(Finding("FD-RTN-001", "warning", "compliance", "承诺收益表述",
                                   p, i + 1, ln.strip()[:120],
                                   "删除“%s”表述，改为情景区间 + “测算≠预测，未来收益不确定”。" % hit))
    return out


# ---------------- 复盘规则 ----------------

@rule("FD-RVW-001", "warning", "review", "复盘缺偏离度",
      "复盘文档里没有“偏离”。复盘的核心问题是“计划被执行了吗”，偏离度是唯一的量化答案。")
def _rvw001(files, ctx):
    out = []
    for p in _review_files(files):
        if not re.search(r"偏离", ctx[p]):
            out.append(Finding("FD-RVW-001", "warning", "review", "复盘缺偏离度",
                               p, 1, "未见偏离度",
                               "补上：投入偏离度 =（实际投入 − 计划投入）/ 计划投入；>5% 标黄，>10% 标红。"))
    return out


@rule("FD-RVW-002", "warning", "review", "复盘缺再平衡提示",
      "复盘文档里没有“再平衡”。涨跌之后类别占比会漂，再平衡是纪律的一部分。")
def _rvw002(files, ctx):
    out = []
    for p in _review_files(files):
        if not re.search(r"再平衡", ctx[p]):
            out.append(Finding("FD-RVW-002", "warning", "review", "复盘缺再平衡提示",
                               p, 1, "未见再平衡",
                               "检查各类别实际占比 vs 目标占比，偏离 ≥5% 触发再平衡提示（只提示，不指令买卖）。"))
    return out


# ---------------- 文档完整性 ----------------

@rule("FD-DOC-001", "warning", "docs", "缺定投计划文档",
      "目标目录里没有“定投/计划”命名的文档。先有计划，再谈执行。")
def _doc001(files, ctx):
    if not any(_match_any(PLAN_RES, os.path.basename(p)) for p in files):
        return [Finding("FD-DOC-001", "warning", "docs", "缺定投计划文档",
                        "(目录)", 0, "未找到定投计划文档",
                        "跑 /lhg-fund-dca:plan 生成定投计划表。")]
    return []


@rule("FD-DOC-002", "nit", "docs", "文档缺标题",
      "定投文档没有 Markdown 一级标题。打印、存档时容易拿错版本。")
def _doc002(files, ctx):
    out = []
    for p in files:
        base = os.path.basename(p)
        if _match_any(PLAN_RES, base) or _match_any(REVIEW_RES, base):
            if not re.search(r"^#\s+\S", ctx[p], re.M):
                out.append(Finding("FD-DOC-002", "nit", "docs", "文档缺标题",
                                   p, 1, "无一级标题",
                                   "首行加“# <文档名> <版本日期>”。"))
    return out


# ---------------------------------------------------------------- 执行引擎

def run_audit(target):
    files = collect_files(target)
    ctx = {p: read_text(p) for p in files}
    findings = []
    for r in RULES:
        try:
            findings.extend(r["check"](files, ctx))
        except Exception as e:  # 单条规则失败不影响整体：fail-open
            findings.append(Finding(r["id"], "nit", r["category"],
                                    "规则执行异常（已跳过）", "(引擎)", 0, str(e)[:120],
                                    "规则内部出错，不计入结论。"))
    sev_rank = {"blocker": 0, "warning": 1, "nit": 2}
    findings.sort(key=lambda f: (sev_rank.get(f.severity, 3), f.file, f.line))
    summary = {
        "tool": TOOL, "version": VERSION, "target": os.path.abspath(target),
        "files_scanned": len(files), "rules_run": len(RULES),
        "blocker": sum(1 for f in findings if f.severity == "blocker"),
        "warning": sum(1 for f in findings if f.severity == "warning"),
        "nit": sum(1 for f in findings if f.severity == "nit"),
    }
    return {"summary": summary, "findings": [f.to_dict() for f in findings]}


def format_text(report):
    s = report["summary"]
    lines = [
        "lhg-fund-dca 定投审计报告",
        "目标：%s（扫描 %d 个文件，运行 %d 条规则）" % (
            s["target"], s["files_scanned"], s["rules_run"]),
        "blocker=%d warning=%d nit=%d" % (s["blocker"], s["warning"], s["nit"]),
        "（本报告是计划完整性检查，非投资建议。）",
        "",
    ]
    for f in report["findings"]:
        lines.append("[%s][%s] %s:%s %s" % (
            f["severity"], f["rule_id"], f["file"], f["line"], f["title"]))
        if f["snippet"]:
            lines.append("    片段：%s" % f["snippet"])
        lines.append("    建议：%s" % f["detail"])
    if not report["findings"]:
        lines.append("全部通过，无发现。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--format", choices=["json", "text"], default="text")
    ap.add_argument("--fail-on", choices=["blocker", "warning", "nit"], default="blocker")
    args = ap.parse_args()

    report = run_audit(args.target)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(format_text(report))

    order = {"blocker": 0, "warning": 1, "nit": 2}
    threshold = order[args.fail_on]
    worst = min([order[f["severity"]] for f in report["findings"]], default=3)
    if worst == 0:
        return 2
    if worst <= threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
