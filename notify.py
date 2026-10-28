"""
通知推送模块
支持渠道（全部可选，配置哪个就推哪个，可同时多个）：
  1. 微信 - Server酱   : PUSH_SERVERCHAN_KEY
  2. Telegram Bot      : PUSH_TELEGRAM_BOT_TOKEN + PUSH_TELEGRAM_CHAT_ID
  3. 飞书自定义机器人   : PUSH_FEISHU_WEBHOOK
  4. 钉钉自定义机器人   : PUSH_DINGTALK_WEBHOOK
"""

import os
import logging
import requests

log = logging.getLogger("notify")


def _post(url: str, **kwargs) -> bool:
    try:
        r = requests.post(url, timeout=15, **kwargs)
        r.raise_for_status()
        return True
    except requests.RequestException as e:
        log.warning("推送失败: %s | %s", url.split("?")[0], type(e).__name__)
        return False


def push_serverchan(title: str, content: str) -> bool:
    """微信推送 —— Server酱 (https://sct.ftqq.com)"""
    key = os.environ.get("PUSH_SERVERCHAN_KEY", "").strip()
    if not key:
        return False
    url = f"https://sctapi.ftqq.com/{key}.send"
    return _post(url, data={"title": title, "desp": content})


def push_telegram(title: str, content: str) -> bool:
    """Telegram Bot 推送"""
    token = os.environ.get("PUSH_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("PUSH_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"*{title}*\n{content}"
    return _post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })


def push_feishu(title: str, content: str) -> bool:
    """飞书自定义机器人推送"""
    webhook = os.environ.get("PUSH_FEISHU_WEBHOOK", "").strip()
    if not webhook:
        return False
    return _post(webhook, json={
        "msg_type": "text",
        "content": {"text": f"{title}\n{content}"},
    })


def push_dingtalk(title: str, content: str) -> bool:
    """钉钉自定义机器人推送"""
    webhook = os.environ.get("PUSH_DINGTALK_WEBHOOK", "").strip()
    if not webhook:
        return False
    return _post(webhook, json={
        "msgtype": "text",
        "text": {"content": f"{title}\n{content}"},
    })


def notify(title: str, content: str) -> None:
    """统一推送入口：依次尝试所有已配置的渠道"""
    sent = []
    if push_serverchan(title, content):
        sent.append("Server酱(微信)")
    if push_telegram(title, content):
        sent.append("Telegram")
    if push_feishu(title, content):
        sent.append("飞书")
    if push_dingtalk(title, content):
        sent.append("钉钉")

    if sent:
        log.info("📨 通知已推送至: %s", "、".join(sent))
    else:
        log.info("ℹ️  未配置任何通知渠道或推送失败")
