# -*- coding: utf-8 -*-
"""原件对象存储（ADR-0002 PoC 口径：本地目录可切 MinIO）。

演示边界（P00 §6）：runtime/objects/ 下按内容寻址（sha256 前缀分桶）落盘——受理即存原件，
任何替换可被摘要检测（FN-1-05④）。oss:// 引用解析：oss://{bucket}/... 仅取尾段文件名在
对象库按 sha256 反查（演示口径：recognize JSON 引用形态须先经 multipart/信箱/DOX 落盘）。
"""

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]          # backend/app/services -> invoice-hub/（与 domain/registry.py 同基准）
OBJECTS_DIR = REPO_ROOT / "runtime" / "objects"


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save(content: bytes, *, subdir: str = "intake") -> tuple[str, str]:
    """内容寻址落盘：返回 (sha256, 本地路径)。同内容重复落盘幂等（同路径）。

    路径记录：对象库位于 REPO_ROOT 下时存相对路径（演示库可读性），
    否则（测试 monkeypatch tmp 目录）存绝对路径——read 兼容两者。
    """
    digest = sha256_of(content)
    path = OBJECTS_DIR / subdir / digest[:2] / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(content)
    try:
        stored = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        stored = str(path).replace("\\", "/")
    return digest, stored


def read(local_path: str) -> bytes:
    p = Path(local_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    if not p.exists():
        raise FileNotFoundError(f"对象缺失：{local_path}（原件必须经受理落盘）")
    return p.read_bytes()


def find_by_digest(digest: str) -> str | None:
    """按 64hex 摘要在对象库查找本地路径（recognize JSON 引用快速路径）。"""
    p = OBJECTS_DIR / "intake" / digest[:2] / digest
    if not p.exists():
        return None
    try:
        return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")
