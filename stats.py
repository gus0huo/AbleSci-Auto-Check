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
        "total": total,          # ✅ 网站累计积分快照
        "timestamp": datetime.now().isoformat(),
    })
    return history
