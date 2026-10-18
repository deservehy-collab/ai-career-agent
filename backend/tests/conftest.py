"""``backend/tests/`` 的夹具：把鉴权依赖换成固定测试用户。

为什么这个目录也要一份
----------------------
``tests/conftest.py`` 的全局覆盖**只对 ``tests/`` 目录生效**，而它对
``backend/tests/`` 的影响纯粹是"跑全量时恰好先被导入了"这种收集顺序巧合 ——
单独跑 ``pytest backend/tests/xxx.py`` 时所有请求都会 401。本文件把这份隐式
依赖写明：这里的用例默认就是"已登录"，谁要验证真实鉴权口径，就自己
覆盖/撤掉它（见 test_health_auth.py）。
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app import app  # noqa: E402
from backend.auth import get_current_user  # noqa: E402

app.dependency_overrides[get_current_user] = lambda: {"id": 0, "username": "test-user"}
