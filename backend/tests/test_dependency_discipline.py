# -*- coding: utf-8 -*-
"""依赖纪律自查（P00 §4 第 1 条 / P02 验收⑥：backend 确定性核心无大模型框架依赖）。

等价复现 P02 §4 验收⑥ 的三个关键词 grep 命令（全文小写子串、大小写不敏感从严）并要求零命中；
违禁词以「相邻字符串字面量编译期拼接」构造，本文件源码不含原词，扫描器不自误报；
范围覆盖 backend/ 全部文本文件（.py/.toml/.md/.json/.txt/.yaml/.yml，不含 __pycache__ 字节码）。
另校验不得 import agent/mcp 包（依赖纪律第 1/2 条的反向约束）。
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 违禁词 = 相邻字符串字面量编译期拼接，源码原文不含完整原词
_FORBIDDEN = ("lan" "ggraph", "open" "ai", "ll" "m", "anth" "ropic", "litell" "m")
_SCAN_SUFFIXES = {".py", ".toml", ".md", ".json", ".txt", ".yaml", ".yml"}


def _iter_text_files():
    for p in BACKEND_ROOT.rglob("*"):
        if p.is_file() and p.suffix in _SCAN_SUFFIXES and "__pycache__" not in p.parts:
            yield p


def _find_forbidden(text: str):
    low = text.lower()
    return [t for t in _FORBIDDEN if t in low]


def test_no_model_framework_references():
    hits = []
    for p in _iter_text_files():
        rel = p.relative_to(BACKEND_ROOT).as_posix()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            found = _find_forbidden(line)
            if found:
                hits.append(f"{rel}:{i} 命中 {found}: {line.strip()[:80]}")
    assert not hits, "backend/ 存在大模型框架引用（P00 §4 红线）：\n" + "\n".join(hits)


def test_no_agent_mcp_package_imports():
    import re
    pat = re.compile(r"^\s*(?:from|import)\s+(agent|mcp)\b")
    hits = []
    for p in BACKEND_ROOT.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pat.match(line):
                hits.append(f"{p.relative_to(BACKEND_ROOT).as_posix()}:{i}: {line.strip()}")
    assert not hits, "backend import 了 agent/mcp 包：\n" + "\n".join(hits)


def test_enum_discipline_no_bare_enum_literals_in_services():
    """纪律④抽样：services/domain 不得散落状态六态字面量（须引用 registry）。

    以 case_status 中不在其他业务语境出现的四个大写词做抽样检查（装载校验一律经 registry）。
    """
    import re
    suspects = ("RECOG" "NIZED", "NEEDS_RE" "VIEW", "INVESTIGAT" "ING", "BLOCK" "ED")
    hits = []
    code_dirs = [BACKEND_ROOT / "app"]
    for d in code_dirs:
        for p in d.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            # 允许出现在注释/docstring；允许 registry/seed 数据加载语境——检查是否存在裸比较赋值
            for tok in suspects:
                if re.search(rf'==\s*["\']{tok}["\']', text) or re.search(rf'["\']{tok}["\']\s*==', text):
                    hits.append(f"{p.relative_to(BACKEND_ROOT).as_posix()}: 硬编码状态比较 {tok}")
    assert not hits, "发现散落状态字面量比较（应引用 enum-registry）：\n" + "\n".join(hits)
