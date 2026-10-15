import os
import re
import sys
import time
import json
import shutil
import logging
import subprocess
import requests

from notify import notify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("checkin")

BASE = "https://www.ablesci.com"
CHECKIN_URL = f"{BASE}/user/sign"
LOGIN_URL = f"{BASE}/site/login"
COOKIE_SECRET_NAME = "ABLESCI_COOKIE"


class AbleSciClient:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Referer": LOGIN_URL,
            "Origin": BASE,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })

    # ---------- Cookie ----------
    def set_cookie(self, cookie_str: str):
        """把 Cookie 字符串解析进 Session"""
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                self.s.cookies.set(k.strip(), v.strip(), domain=".ablesci.com", path="/")

    def get_cookie_string(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.s.cookies.get_dict().items())

    # ---------- 登录 ----------
    def login(self, email: str, password: str) -> bool:
        try:
            self.s.cookies.clear()          # 清掉旧 Cookie，避免干扰
            r = self.s.get(LOGIN_URL, timeout=20)

            m = re.search(r'name="_csrf"\s+value="([^"]+)"', r.text) or \
                re.search(r'value="([^"]+)"\s+name="_csrf"', r.text)
            csrf = m.group(1) if m else ""

            payload = {"email": email, "password": password, "remember": "1"}
            if csrf:
                payload["_csrf"] = csrf

            self.s.post(LOGIN_URL, data=payload, timeout=20)

            if "_identity-frontend" in self.s.cookies.get_dict():
                log.info("✅ 账号登录成功，已获取新的 30 天凭据")
                return True
            log.error("❌ 登录失败：未获取到 _identity-frontend")
            return False
        except requests.RequestException as e:
            log.error("❌ 登录请求异常: %s", e)
            return False

    # ---------- 签到 ----------
    def checkin(self) -> dict:
        for attempt in range(3):
            try:
                r = self.s.get(CHECKIN_URL, timeout=20)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                log.warning("请求失败(%s/3): %s", attempt + 1, e)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("签到请求多次失败")


# ================== 保存 Cookie 到 GitHub Secret ==================
def save_cookie_to_secret(cookie_str: str) -> bool:
    """登录成功后把新 Cookie 写回 Secret，实现 30 天自动续期"""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        log.info("本地运行，跳过自动保存（请手动更新 Cookie）")
        return False
    if not shutil.which("gh"):
        log.warning("未找到 gh 命令，无法保存 Cookie")
        return False
    if not os.environ.get("GH_TOKEN"):
        log.warning("未配置 GH_TOKEN（PAT），无法保存 Cookie")
        return False

    try:
        # 通过 stdin 传值，兼容所有 gh 版本，且不暴露在命令行参数中
        r = subprocess.run(
            ["gh", "secret", "set", COOKIE_SECRET_NAME],
            input=cookie_str,
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("✅ 新 Cookie 已写回 Secret: %s", COOKIE_SECRET_NAME)
            return True
        log.warning("写回 Secret 失败: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.warning("写回 Secret 异常: %s", e)
        return False


# ================== 响应解析 ==================
def parse_response(data: dict) -> tuple:
    """返回 (状态, 推送标题, 推送内容)"""
    code = data.get("code")

    if code == 0:
        msg = data.get("msg", "")
        sign_data = data.get("data", {})
        content = (f"{msg}\n"
                   f"连续签到: {sign_data.get('signcount', '?')} 次\n"
                   f"本次积分: {sign_data.get('signpoint', '?')}")
        html = sign_data.get("today_history", "")
        m = re.search(r'color:\s*#ea4335[^>]*>([^<]+)<', html)
        if m:
            content += f"\n今日历史: {m.group(1).strip()}"
        return "success", "AbleSci 签到成功 ✅", content

    msg = data.get("msg", json.dumps(data, ensure_ascii=False))
    if "已" in msg and ("签到" in msg or "打卡" in msg):
        return "already", "AbleSci 今日已签到 ℹ️", msg
    if "登录" in msg or code == -1:
        return "auth_failed", "AbleSci 签到失败 ❌", f"登录态失效: {msg}"
    return "failed", "AbleSci 签到失败 ❌", f"code={code}\n{msg}"


# ================== 主流程 ==================
def main():
    client = AbleSciClient()
    cookie = os.environ.get("ABLESCI_COOKIE", "").strip()
    email = os.environ.get("ABLESCI_EMAIL", "").strip()
    password = os.environ.get("ABLESCI_PASSWORD", "").strip()

    result = title = content = None

    # ---- ① 优先使用已保存的 Cookie ----
    if cookie:
        log.info("① 使用已保存的 Cookie 尝试签到...")
        client.set_cookie(cookie)
        try:
            result, title, content = parse_response(client.checkin())
        except Exception as e:
            result, title, content = "failed", "AbleSci 签到失败 ❌", f"脚本异常: {e}"

    # ---- ② Cookie 缺失或已过期 → 账号密码登录 ----
    if result in (None, "auth_failed"):
        if result == "auth_failed":
            log.info("② Cookie 已过期，改用账号密码登录...")
        else:
            log.info("② 未配置 Cookie，使用账号密码登录...")

        if not (email and password):
            notify("AbleSci 签到失败 ❌", "Cookie 已过期且未配置账号密码，请更新 Secret")
            sys.exit(1)

        if not client.login(email, password):
            notify("AbleSci 签到失败 ❌", "账号密码登录失败，请检查凭据或是否触发验证")
            sys.exit(1)

        # ③ 登录成功 → 把新 Cookie 写回 Secret
        save_cookie_to_secret(client.get_cookie_string())

        # ④ 用新会话签到
        try:
            result, title, content = parse_response(client.checkin())
        except Exception as e:
            result, title, content = "failed", "AbleSci 签到失败 ❌", f"脚本异常: {e}"

    # ---- 推送结果 ----
    notify(title, content)
    if result in ("auth_failed", "failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
