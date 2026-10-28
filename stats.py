"""
签到积分统计模块
- 记录每日签到结果（邮箱完全打码存储）
- 生成汇总摘要与 STATS.md 报表
"""

import os
import json
import logging
from datetime import date, datetime

log = logging.getLogger("stats")

DATA_DIR = "data"
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")

STATUS_LABEL = {
    "success": "✅ 成功",
    "already": "ℹ️ 已签到",
    "failed": "❌ 失败",
    "auth_failed": "❌ 登录失效",
}


def mask_email(email: str) -> str:
    """邮箱完全打码：user@example.com → ***@***"""
    if not email:
        return "***"
    return "***@***"


# ================== 数据读写 ==================
def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("历史数据读取失败，重新初始化")
    return []


def save_history(history: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    log.info("📊 历史数据已保存: %s 条记录", len(history))


def add_record(history: list, email: str, status: str, points: int,
               signcount: int, total: int = None, site_today: int = None) -> list:
    """添加记录（同一天同一账号去重）
    email      - 已打码的邮箱标识
    total      - 网站当前总积分快照
    site_today - 网站积分明细中今日变动合计
    """
    today = date.today().isoformat()
    history = [r for r in history if not (r["date"] == today and r["email"] == email)]
    history.append({
        "date": today,
        "email": email,
        "status": status,
        "points": points,
        "signcount": signcount,
        "total": total,
        "site_today": site_today,
        "timestamp": datetime.now().isoformat(),
    })
    return history


# ================== 统计计算 ==================
def _account_stats(history: list) -> dict:
    accounts = {}
    for r in history:
        email = r.get("email", "?")
        if email not in accounts:
            accounts[email] = {"points": 0, "days": 0, "max_streak": 0,
                               "last_streak": 0, "last_total": None}
        accounts[email]["points"] += r.get("points", 0)
        accounts[email]["days"] += 1
        streak = r.get("signcount", 0)
        accounts[email]["max_streak"] = max(accounts[email]["max_streak"], streak)
        if r.get("total") is not None:
            accounts[email]["last_total"] = r["total"]
        if r["date"] == max(x["date"] for x in history if x["email"] == email):
            accounts[email]["last_streak"] = streak
    return accounts


def summary_text(history: list) -> str:
    if not history:
        return "📊 暂无统计数据"
    total_points = sum(r.get("points", 0) for r in history)
    lines = [f"📊 累计获得 {total_points} 分 | 共 {len(history)} 天次"]
    for email, s in _account_stats(history).items():
        total = s["last_total"] if s["last_total"] is not None else "-"
        lines.append(f"  {email}: 网站总积分 {total} | 签到{s['days']}天 | 连续{s['last_streak']}天")
    return "\n".join(lines)


# ================== 报表生成 ==================
def write_report(history: list):
    if not history:
        return

    total_points = sum(r.get("points", 0) for r in history)
    accounts = _account_stats(history)

    lines = [
        "# 📊 AbleSci 签到统计报表",
        "",
        f"> 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 总览",
        "",
        f"- 签到累计获得积分: **{total_points}**",
        f"- 总签到天次: **{len(history)}**",
        f"- 账号数量: **{len(accounts)}**",
        "",
        "## 各账号统计",
        "",
        "| 账号 | 网站总积分 | 签到累计获得 | 签到天数 | 当前连续 | 最长连续 |",
        "|------|:---------:|:----------:|:-------:|:-------:|:-------:|",
    ]
    for email, s in accounts.items():
        total = s["last_total"] if s["last_total"] is not None else "-"
        lines.append(
            f"| {email} | {total} | {s['points']} | {s['days']} | "
            f"{s['last_streak']} 天 | {s['max_streak']} 天 |"
        )

    lines += [
        "",
        "## 最近 30 条记录",
        "",
        "| 日期 | 账号 | 状态 | 签到积分 | 连续天数 | 今日变动 | 网站总积分 |",
        "|------|------|------|:------:|:-------:|:------:|:--------:|",
    ]
    recent = sorted(history, key=lambda x: x.get("date", ""), reverse=True)[:30]
    for r in recent:
        status = STATUS_LABEL.get(r["status"], r["status"])
        total = r.get("total")
        site_today = r.get("site_today")
        lines.append(
            f"| {r['date']} | {r['email']} | {status} | "
            f"+{r.get('points', 0)} | {r.get('signcount', 0)} | "
            f"{'+' if (site_today or 0) >= 0 else ''}{site_today if site_today is not None else '-'} | "
            f"{total if total is not None else '-'} |"
        )

    with open("STATS.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log.info("📊 报表已生成: STATS.md")
