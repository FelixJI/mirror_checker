"""测试包引导：把仓库 python/ 目录加入 sys.path。

这样 ``python -m unittest discover -s tests`` 与 pytest 都能在不安装
包的前提下导入 mirror_core / mirror_cli。
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_DIR = REPO_ROOT / "python"
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))
