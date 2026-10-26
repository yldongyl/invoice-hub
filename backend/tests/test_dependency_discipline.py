# -*- coding: utf-8 -*-
"""依赖纪律自查（P00 §4 第 1 条 / P02 验收⑥：backend 确定性核心无大模型框架依赖）。

等价复现 P02 §4 验收⑥ 的三个关键词 grep 命令（全文小写子串、大小写不敏感从严）并要求零命中；
违禁词以「相邻字符串字面量编译期拼接」构造，本文件源码不含原词，扫描器不自误报；
范围覆盖 backend/ 全部文本文件（.py/.toml/.md/.json/.txt/.yaml/.yml，不含 __pycache__ 字节码）。
另校验不得 import agent/mcp 包（依赖纪律第 1/2 条的反向约束）。
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 违禁词 = 运行时 join 构造（编译期拼接会被 CPython 折叠成完整词常量并落入 .pyc 字节码，
# 导致验收 grep 扫到二进制缓存误报；运行时 join 不产生完整词常量）。
# CI 组大小写不敏感扫描（这些词不可能出现在合法中文文案）；
# CS 组仅小写子串精确匹配——镜像验收 grep 命令的大小写敏感语义；
# 大写治理文案（FN-0-08 复选框原文「…/ LLM 建议不自动执行」）为清单字面口径，非依赖或调用。
def _w(*parts):
    return "".join(parts)


_FORBIDDEN_CI = (_w("lan", "graph"), _w("open", "ai"), _w("anth", "ropic"), _w("litell", "m"))
_FORBIDDEN_CS = (_w("ll", "m"),)
_SCAN_SUFFIXES = {".py", ".toml", ".md", ".json", ".txt", ".yaml", ".yml"}
# 扫描边界=本仓自研源码（P02 验收⑥ grep 语义）；安装产物与字节码不属于 backend 源码面：
# venv 内第三方 wheel 源码含携带 CS 违禁词子串的常见标识符（R5「匹配函数名含子串」同源问题），
# 必须排除——P07 引入 .venv 后暴露。注：本行注释亦须避开违禁词字面（自误报纪律）。
_EXCLUDE_DIRS = {"__pycache__", ".venv", "venv"}


def _iter_text_files():
    for p in BACKEND_ROOT.rglob("*"):
        if p.is_file() and p.suffix in _SCAN_SUFFIXES and not (_EXCLUDE_DIRS & set(p.parts)):
            yield p


def _find_forbidden(text: str):
    hits = [t for t in _FORBIDDEN_CI if t in text.lower()]
    hits += [t for t in _FORBIDDEN_CS if t in text]   # 小写精确（镜像 grep）
    return hits


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
        if _EXCLUDE_DIRS & set(p.parts):
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
