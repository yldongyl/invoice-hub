# -*- coding: utf-8 -*-
"""蓝图 §13.2 八大 Demo 场景自动化测试（WP5.7 · L2 演示闭环验证）。"""

import subprocess
import sys
from pathlib import Path


def test_blueprint_eight_demo_scenarios():
    """断言蓝图 §13.2 八大 Demo 场景全部回放通过。"""
    demo_script = Path(__file__).resolve().parents[1] / "scripts" / "demo_replay.py"
    res = subprocess.run([sys.executable, str(demo_script)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Demo 场景回放失败:\n{res.stderr}\n{res.stdout}"
    assert "8 / 8 场景全部通过" in res.stdout
