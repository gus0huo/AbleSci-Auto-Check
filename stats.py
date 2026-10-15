"""
签到积分统计模块
- 记录每日每个账号的签到结果
- 生成汇总摘要（用于推送）
- 生成 STATS.md 报表（提交回仓库）
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


# ================== 数据读写 ==================
def load_history() -> list:
    """读取历史记录"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log.warning("历史数据读取失败，重新初始化")
    return []


def save_history(history: list):
    """保存历史记录"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    log.info("📊 历史数据已保存: %s 条记录", len(history))


def add_record(history: list, email: str, status: str, points: int,
               signcount: int, total: int = None) -> list:
    """添加记录（同一天同一账号去重），total 为网站累计积分"""
    today = date.today().isoformat()
    history = [r for r in history if not (r["date"] == today and r["email"] == email)]
    history.append({
        "date": today,
        "email": email,
        "status": status,
        "points": points,
        "signcount": signcount,
        "total": total,
        "timestamp": datetime.now().isoformat(),
    })
    return history


# ================== 统计计算 ==================
def _account_stats(history: list) -> dict:
    """按账号汇总"""
    accounts = {}
    for r in history:
        email = r.get("email", "?")
        if email not in accounts:
            accounts[email] = {"points": 0, "days": 0, "max_streak": 0, "last_streak": 0}
        accounts[email]["points"] += r.get("points", 0)
        accounts[email]["days"] += 1
        streak = r.get("signcount", 0)
        accounts[email]["max_streak"] = max(accounts[email]["max_streak"], streak)
        if r["date"] == max(x["date"] for x in history if x["email"] == email):
            accounts[email]["last_streak"] = streak
    return accounts


def summary_text(history: list) -> str:
    """生成推送用的简短摘要"""
    if not history:
        return "📊 暂无统计数据"

    total_points = sum(r.get("points", 0) for r in history)
    total_records = len(history)
    today = date.today().isoformat()
    today_points = sum(r.get("points", 0) for r in history if r["date"] == today)

    lines = [f"📊 累计获得 {total_points} 分 | 今日 +{today_points} 分 | 共 {total_records} 天次"]
    accounts = _account_stats(history)
    for email, s in accounts.items():
        lines.append(
            f"  {email}: {s['points']}分 | {s['days']}天 | "
            f"连续{s['last_streak']}天(最长{s['max_streak']})"
        )
    return "\n".join(lines)


# ================== 报表生成 ==================
def write_report(history: list):
    """生成 STATS.md 统计报表"""
    if not history:
        return

    total_points = sum(r.get("points", 0) for r in history)
    total_records = len(history)
    accounts = _account_stats(history)

    lines = [
        "# 📊 AbleSci 签到统计报表",
        "",
        f"> 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## 总览",
        "",
        f"- 累计获得积分: **{total_points}**",
        f"- 总签到天次: **{total_records}**",
        f"- 账号数量: **{len(accounts)}**",
        "",
        "## 各账号统计",
        "",
        "| 账号 | 累计获得 | 签到天数 | 当前连续 | 最长连续 |",
        "|------|:-------:|:-------:|:-------:|:-------:|",
    ]
    for email, s in accounts.items():
        lines.append(
            f"| {email} | {s['points']} | {s['days']} | "
            f"{s['last_streak']} 天 | {s['max_streak']} 天 |"
        )

    lines += [
        "",
        "## 最近 30 条记录",
        "",
        "| 日期 | 账号 | 状态 | 积分 | 连续天数 | 累计积分 |",
        "|------|------|------|:----:|:-------:|:-------:|",
    ]
    recent = sorted(history, key=lambda x: x.get("date", ""), reverse=True)[:30]
    for r in recent:
        status = STATUS_LABEL.get(r["status"], r["status"])
        total = r.get("total")
        lines.append(
            f"| {r['date']} | {r['email']} | {status} | "
            f"+{r.get('points', 0)} | {r.get('signcount', 0)} | "
            f"{total if total is not None else '-'} |"
        )

    with open("STATS.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    log.info("📊 报表已生成: STATS.md")
