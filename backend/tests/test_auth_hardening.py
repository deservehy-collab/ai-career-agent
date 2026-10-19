"""认证加固的回归测试：限速、token 与账号存活的绑定、注册触发迁移。

三组行为
--------
1. **登录限速**：同一 IP+用户名 的**失败**次数在窗口内达到上限 → 429；
   成功登录清零计数（正常用户输错一两次不受影响）；不同用户名互不影响。
2. **注册限速**：同一 IP 的**成功建号**数超上限 → 429（422/409 不消耗额度）。
3. **token 绑定账号存活**：用户被删除后，未过期的 token 也要被
   ``get_current_user`` 拒掉（401），业务接口与 ``/api/auth/me`` 同口径。

隔离策略与 tests/test_auth_api.py 相同：数据库与 JWT 密钥都指到临时目录，
全程不碰项目 runs/。限速器是进程级单例，每个用例先 ``reset()``。
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import backend.auth as auth  # noqa: E402
from backend import config, db  # noqa: E402
from backend.app import app  # noqa: E402
from backend.auth import get_current_user  # noqa: E402


class SlidingWindowLimiterTest(unittest.TestCase):
    """限速器本体的单元行为（窗口过期 / clear / reset）。"""

    def test_limited_until_window_passes(self):
        limiter = auth._SlidingWindowLimiter(limit=3, window_seconds=0.05)
        for _ in range(3):
            limiter.record("k")
        self.assertTrue(limiter.limited("k"))
        self.assertFalse(limiter.limited("other"), "不同键互不影响")
        import time as _time
        _time.sleep(0.06)
        self.assertFalse(limiter.limited("k"), "窗口滑过后应放行")

    def test_limited_does_not_record(self):
        limiter = auth._SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.record("k")
        self.assertTrue(limiter.limited("k"))
        self.assertTrue(limiter.limited("k"), "limited() 是只读判断，不得自动解除")

    def test_clear_and_reset(self):
        limiter = auth._SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.record("k")
        limiter.clear("k")
        self.assertFalse(limiter.limited("k"))
        limiter.record("k")
        limiter.reset()
        self.assertFalse(limiter.limited("k"))


class _AuthIsolatedCase(unittest.TestCase):
    """公共装置：临时库 + 摘掉鉴权覆盖（走真实鉴权路径）+ 限速器清零。"""

    def setUp(self):
        auth._login_limiter.reset()
        self.addCleanup(auth._login_limiter.reset)
        auth._register_limiter.reset()
        self.addCleanup(auth._register_limiter.reset)

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            mock.patch("backend.config.AUTH_DB_PATH", root / "app.db"),
            mock.patch("backend.config.JWT_SECRET_PATH", root / "jwt.key"),
            mock.patch.object(auth, "_secret_cache", None),
        ]
        for p in self._patches:
            p.start()

        self._saved_override = app.dependency_overrides.pop(get_current_user, None)
        self.client = TestClient(app)

        self.addCleanup(self._restore)

    def _restore(self):
        for p in self._patches:
            p.stop()
        if self._saved_override is not None:
            app.dependency_overrides[get_current_user] = self._saved_override
        try:
            self._tmp.cleanup()
        except PermissionError:
            pass


class LoginRateLimitTest(_AuthIsolatedCase):
    """登录失败限速：只数失败、按用户名隔离、成功清零。"""

    def test_too_many_failures_get_429(self):
        for _ in range(config.AUTH_FAILURE_LIMIT):
            response = self.client.post(
                "/api/auth/login", json={"username": "ghost", "password": "wrong"})
            self.assertEqual(response.status_code, 401)
        blocked = self.client.post(
            "/api/auth/login", json={"username": "ghost", "password": "wrong"})
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("稍后再试", blocked.json()["detail"])

    def test_failures_are_counted_per_username(self):
        for _ in range(config.AUTH_FAILURE_LIMIT):
            self.client.post("/api/auth/login", json={"username": "ghost", "password": "wrong"})
        other = self.client.post(
            "/api/auth/login", json={"username": "someone_else", "password": "wrong"})
        self.assertEqual(other.status_code, 401, "别的用户名不应被连带限速")

    def test_successful_login_clears_failures(self):
        self.client.post("/api/auth/register",
                         json={"username": "real_user", "password": "pw123456"})
        for _ in range(config.AUTH_FAILURE_LIMIT - 1):
            self.client.post("/api/auth/login", json={"username": "real_user", "password": "nope"})
        ok = self.client.post("/api/auth/login",
                              json={"username": "real_user", "password": "pw123456"})
        self.assertEqual(ok.status_code, 200)
        again = self.client.post("/api/auth/login", json={"username": "real_user", "password": "nope"})
        self.assertEqual(again.status_code, 401, "成功登录清零后，再错一次只是 401 不是 429")


class RegisterRateLimitTest(_AuthIsolatedCase):
    """注册限速只数成功建号；用小阈值的替身限速器，避免真跑几十次 PBKDF2。"""

    def test_validation_failures_do_not_consume_quota(self):
        tight = auth._SlidingWindowLimiter(limit=3, window_seconds=3600)
        with mock.patch.object(auth, "_register_limiter", tight):
            for _ in range(5):
                response = self.client.post(
                    "/api/auth/register", json={"username": "bad name!", "password": "pw123456"})
                self.assertEqual(response.status_code, 422)
            ok = self.client.post(
                "/api/auth/register", json={"username": "fine_1", "password": "pw123456"})
            self.assertEqual(ok.status_code, 201, "被 422 拒掉的注册不应消耗额度")

    def test_successes_trip_the_limit(self):
        tight = auth._SlidingWindowLimiter(limit=3, window_seconds=3600)
        with mock.patch.object(auth, "_register_limiter", tight):
            for i in range(3):
                response = self.client.post(
                    "/api/auth/register", json={"username": f"user_{i}", "password": "pw123456"})
                self.assertEqual(response.status_code, 201)
            blocked = self.client.post(
                "/api/auth/register", json={"username": "user_x", "password": "pw123456"})
            self.assertEqual(blocked.status_code, 429)


class TokenBoundToExistingUserTest(_AuthIsolatedCase):
    """用户被删除后，有效期内 token 也必须失效（401）。"""

    def test_deleted_user_token_rejected_everywhere(self):
        token = self.client.post(
            "/api/auth/register", json={"username": "gone_soon", "password": "pw123456"}
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 200)

        with db.session_for(Path(config.AUTH_DB_PATH)) as session:
            user = session.query(db.User).filter_by(username="gone_soon").one()
            session.delete(user)
            session.commit()

        me = self.client.get("/api/auth/me", headers=headers)
        self.assertEqual(me.status_code, 401)
        self.assertIn("不存在", me.json()["detail"])
        # 业务接口同口径：router 级鉴权依赖也要查库
        self.assertEqual(
            self.client.get("/api/knowledge/jds", headers=headers).status_code, 401)


class RegisterTriggersMigrationTest(_AuthIsolatedCase):
    """首个账号注册成功时，旧数据根目录的业务文件应被认领迁移。"""

    def test_first_register_claims_legacy_files(self):
        root = Path(config.AUTH_DB_PATH).parent
        (root / "loop.json").write_text('{"schema_version": 1, "rounds": []}', encoding="utf-8")
        (root / "growth.json").write_text('{"schema_version": 1, "history": []}', encoding="utf-8")

        response = self.client.post(
            "/api/auth/register", json={"username": "first_mover", "password": "pw123456"})
        self.assertEqual(response.status_code, 201)

        # 找到刚注册的用户 id（注册顺序即迁移归属）
        with db.session_for(Path(config.AUTH_DB_PATH)) as session:
            user = session.query(db.User).filter_by(username="first_mover").one()
            user_id = user.id

        target = config.user_data_dir(user_id)
        self.assertTrue((target / "loop.json").exists(), "首个注册应认领旧 loop.json")
        self.assertTrue((target / "growth.json").exists(), "首个注册应认领旧 growth.json")
        self.assertFalse((root / "loop.json").exists(), "旧文件应已改名留档")

    def test_migration_without_users_is_deferred(self):
        (Path(config.AUTH_DB_PATH).parent / "loop.json").write_text("{}", encoding="utf-8")
        response = self.client.post(
            "/api/auth/register", json={"username": "someone", "password": "pw123456"})
        self.assertEqual(response.status_code, 201)
        # 注册后存在用户了 → 这次注册本身就触发了迁移
        self.assertFalse((Path(config.AUTH_DB_PATH).parent / "loop.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
