import os
import re
import sys
import time
import json
import shutil
import logging
import subprocess
from datetime import date
import requests

from notify import notify
from stats import load_history, save_history, add_record, write_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("checkin")

BASE = "https://www.ablesci.com"
CHECKIN_URL = f"{BASE}/user/sign"
LOGIN_URL = f"{BASE}/site/login"
POINT_URL = f"{BASE}/my/point"
ACCOUNTS_SECRET_NAME = "ABLESCI_ACCOUNTS"

# 积分明细表行：时间 + 积分变动 + 说明
ROW_RE = re.compile(
    r'<tr>\s*<td>\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s*</td>\s*'
    r'<td>\s*([+-]?\d+)\s*</td>\s*'
    r'<td>([\s\S]*?)</td>'
)

# 总积分候选正则（首选为精确定稿）
POINT_PATTERNS = [
    r'您当前的总积分为[\s\S]{0,200}?(\d[\d,]*)',   # ✅ 依据真实页面结构
    r"总积分[^0-9]{0,200}(\d[\d,]*)",
    r"累计积分[^0-9]{0,200}(\d[\d,]*)",
    r"当前拥有[^0-9]{0,200}(\d[\d,]*)",
]


def parse_point_rows(html: str) -> list:
    """解析积分明细表 → [{'time','delta','desc'}, ...]"""
    rows = []
    for m in ROW_RE.finditer(html):
        t, delta, desc_html = m.groups()
        desc = re.sub(r'<[^>]+>', '', desc_html)      # 去掉 <a> 等标签
        desc = re.sub(r'\s+', ' ', desc).strip()
        rows.append({"time": t, "delta": int(delta), "desc": desc})
    return rows


class AbleSciClient:
    def __init__(self, email=""):
        self.email = email
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Referer": f"{BASE}/",
            "Origin": BASE,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })

    # ---------- Cookie ----------
    def set_cookie(self, cookie_str: str):
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
            self.s.cookies.clear()
            r = self.s.get(LOGIN_URL, timeout=20)
            m = re.search(r'name="_csrf"\s+value="([^"]+)"', r.text) or \
                re.search(r'value="([^"]+)"\s+name="_csrf"', r.text)
            csrf = m.group(1) if m else ""

            payload = {"email": email, "password": password, "remember": "1"}
            if csrf:
                payload["_csrf"] = csrf
            self.s.post(LOGIN_URL, data=payload, timeout=20)

            if "_identity-frontend" in self.s.cookies.get_dict():
                log.info("✅ [%s] 登录成功", self.email)
                return True
            log.error("❌ [%s] 登录失败：未获取到 _identity-frontend", self.email)
            return False
        except requests.RequestException as e:
            log.error("❌ [%s] 登录异常: %s", self.email, e)
            return False

    # ---------- 签到 ----------
    def checkin(self) -> dict:
        for attempt in range(3):
            try:
                r = self.s.get(CHECKIN_URL, timeout=20)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                log.warning("[%s] 请求失败(%s/3): %s", self.email, attempt + 1, e)
                time.sleep(3 * (attempt + 1))
        raise RuntimeError("签到请求多次失败")

    # ---------- ✅ 读取积分页（总积分 + 今日变动） ----------
    def fetch_point_info(self) -> dict:
        """
        返回:
          total       - 当前总积分（页面"您当前的总积分为"）
          today_points- 今日积分变动合计（积分明细表）
          today_desc  - 今日积分说明，如"签到"
        解析失败的字段为 None / 空
        """
        info = {"total": None, "today_points": None, "today_desc": ""}
        try:
            r = self.s.get(POINT_URL, timeout=20)
            r.raise_for_status()
            html = r.text

            # 1) 总积分
            for pat in POINT_PATTERNS:
                m = re.search(pat, html)
                if m:
                    info["total"] = int(m.group(1).replace(",", ""))
                    break

            # 2) 积分明细表 → 今日变动
            rows = parse_point_rows(html)
            today = date.today().isoformat()
            today_rows = [x for x in rows if x["time"].startswith(today)]
            if rows:
                info["today_points"] = sum(x["delta"] for x in today_rows)
                info["today_desc"] = "、".join(x["desc"] for x in today_rows)

            log.info("[%s] 网站积分: 累计=%s | 今日=%s(%s)",
                     self.email, info["total"],
                     f"{info['today_points']:+d}" if info["today_points"] is not None else "?",
                     info["today_desc"] or "-")

            if info["total"] is None:
                snippet = re.sub(r"\s+", " ", html)
                log.warning("[%s] 总积分解析失败，页面片段: %s", self.email, snippet[:500])
            return info
        except requests.RequestException as e:
            log.warning("[%s] 读取积分页失败: %s", self.email, e)
            return info


# ================== 响应解析 ==================
def parse_response(data: dict) -> dict:
    code = data.get("code")
    if code == 0:
        msg = data.get("msg", "")
        sd = data.get("data", {})
        points = sd.get("signpoint", 0)
        signcount = sd.get("signcount", 0)
        return {"status": "success",
                "desc": f"✅ 签到成功 (连续{signcount}天 +{points}分)",
                "points": points, "signcount": signcount}

    msg = data.get("msg", json.dumps(data, ensure_ascii=False))
    if "已" in msg and ("签到" in msg or "打卡" in msg):
        return {"status": "already", "desc": "ℹ️ 今日已签到", "points": 0, "signcount": 0}
    if "登录" in msg or code == -1:
        return {"status": "auth_failed", "desc": "❌ 登录态失效", "points": 0, "signcount": 0}
    return {"status": "failed", "desc": f"❌ 异常(code={code})", "points": 0, "signcount": 0}


def _attach_point_info(client: AbleSciClient, result: dict) -> dict:
    info = client.fetch_point_info()
    result["total"] = info["total"]
    result["site_today"] = info["today_points"]
    result["site_desc"] = info["today_desc"]
    return result


# ================== 单账号处理 ==================
def run_account(account: dict) -> dict:
    email = account.get("email", "")
    password = account.get("password", "")
    cookie = account.get("cookie", "").strip()
    client = AbleSciClient(email)

    # ① 优先 Cookie
    if cookie:
        client.set_cookie(cookie)
        try:
            result = parse_response(client.checkin())
        except Exception as e:
            result = {"status": "failed", "desc": f"❌ 异常: {e}", "points": 0, "signcount": 0}
        if result["status"] != "auth_failed":
            return _attach_point_info(client, result)
        log.info("[%s] Cookie 过期，尝试密码登录...", email)

    # ② 密码登录
    if not (email and password):
        result = {"status": "failed", "desc": "❌ Cookie过期且无密码", "points": 0, "signcount": 0}
        result.update({"total": None, "site_today": None, "site_desc": ""})
        return result
    if not client.login(email, password):
        result = {"status": "failed", "desc": "❌ 密码登录失败", "points": 0, "signcount": 0}
        result.update({"total": None, "site_today": None, "site_desc": ""})
        return result

    # ③ 更新 Cookie
    account["cookie"] = client.get_cookie_string()

    # ④ 签到 + 读积分
    try:
        result = parse_response(client.checkin())
    except Exception as e:
        result = {"status": "failed", "desc": f"❌ 异常: {e}", "points": 0, "signcount": 0}
    return _attach_point_info(client, result)


# ================== Secret 回写 ==================
def save_accounts_to_secret(accounts: list) -> bool:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        log.info("本地运行，跳过自动保存")
        return False
    if not shutil.which("gh") or not os.environ.get("GH_TOKEN"):
        log.warning("未配置 gh / GH_TOKEN，跳过自动保存")
        return False
    try:
        r = subprocess.run(
            ["gh", "secret", "set", ACCOUNTS_SECRET_NAME],
            input=json.dumps(accounts, ensure_ascii=False),
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            log.info("✅ 账号数据已写回 Secret")
            return True
        log.warning("写回 Secret 失败: %s", r.stderr.strip())
        return False
    except Exception as e:
        log.warning("写回 Secret 异常: %s", e)
        return False


# ================== 账号加载 ==================
def load_accounts() -> list:
    raw = os.environ.get("ABLESCI_ACCOUNTS", "").strip()
    if raw:
        try:
            accounts = json.loads(raw)
            if isinstance(accounts, list) and accounts:
                return accounts
        except json.JSONDecodeError as e:
            log.error("ABLESCI_ACCOUNTS 解析失败: %s", e)
        sys.exit(1)

    email = os.environ.get("ABLESCI_EMAIL", "").strip()
    password = os.environ.get("ABLESCI_PASSWORD", "").strip()
    cookie = os.environ.get("ABLESCI_COOKIE", "").strip()
    if email or cookie:
        return [{"email": email, "password": password, "cookie": cookie}]

    log.error("未配置任何账号凭据")
    sys.exit(1)


# ================== 主流程 ==================
def main():
    accounts = load_accounts()
    log.info("===== 加载 %s 个账号 =====", len(accounts))

    history = load_history()
    cookie_changed = False
    results = []

    for i, account in enumerate(accounts, 1):
        email = account.get("email", "")
        log.info("--- 账号 %s/%s: %s ---", i, len(accounts), email or f"账号{i}")
        old_cookie = account.get("cookie", "")

        try:
            result = run_account(account)
        except Exception as e:
            result = {"status": "failed", "desc": f"❌ 未捕获异常: {e}",
                      "points": 0, "signcount": 0,
                      "total": None, "site_today": None, "site_desc": ""}

        if account.get("cookie", "") != old_cookie:
            cookie_changed = True

        history = add_record(history, email or f"账号{i}", result["status"],
                             result["points"], result["signcount"],
                             result.get("total"), result.get("site_today"))
        results.append((email or f"账号{i}", result))
        time.sleep(2)

    save_history(history)
    write_report(history)

    if cookie_changed:
        save_accounts_to_secret(accounts)

    # ---- 推送：积分来自网站 ----
    lines = []
    for name, r in results:
        parts = [r["desc"]]
        if r.get("total") is not None:
            parts.append(f"累计积分: {r['total']}")
        if r.get("site_today") is not None:
            v = r["site_today"]
            parts.append(f"今日{'+' if v >= 0 else ''}{v}分")
        lines.append(f"{name}: " + " | ".join(parts))

    ok = sum(1 for _, r in results if r["status"] in ("success", "already"))
    today_points = sum(r["points"] for _, r in results)
    title = f"AbleSci 签到 {ok}/{len(accounts)} 成功 | 今日+{today_points}分"
    if ok < len(accounts):
        title += " ⚠️"

    notify(title, "\n".join(lines))
    if ok < len(accounts):
        sys.exit(1)


if __name__ == "__main__":
    main()
