"""
推送通知服务
===========
支持: Telegram Bot / 企业微信 Webhook / 飞书 / PushPlus / Server酱 / 自定义 Webhook
配置持久化到 .notify_config.json，运行时热加载，无需重启。
首次启动自动从 .env 迁移已有配置。
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

import requests
import structlog

log = structlog.get_logger("notifier")

_CONFIG_FILE = Path(__file__).resolve().parent.parent / ".notify_config.json"

# ── 默认配置模板 ──

_DEFAULT_CONFIG = {
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
        "proxy": "",
    },
    "wechat": {
        "enabled": False,
        "webhook_url": "",
    },
    "pushplus": {
        "enabled": False,
        "token": "",
        "topic": "",
    },
    "serverchan": {
        "enabled": False,
        "sendkey": "",
    },
    "feishu": {
        "enabled": False,
        "webhook": "",
    },
    "webhook": {
        "enabled": False,
        "url": "",
    },
    "auto_push_enabled": False,
    "push_top_n": 5,
    "push_threshold": 0.5,
    "push_cooldown_minutes": 10,
    "summary_push_hours": [],
    "last_push": None,
    "last_summary": None,
}

# 渠道 key 列表（用于动态遍历，system_config / news.py 引用此常量）
CHANNEL_KEYS = ("telegram", "wechat", "pushplus", "serverchan", "feishu", "webhook")


# ── 配置读写 ──

def load_config() -> dict:
    """读取推送配置，不存在则从 .env 迁移并生成默认文件"""
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 补全缺失的 key（兼容旧配置文件）
            from copy import deepcopy
            for key, defaults in _DEFAULT_CONFIG.items():
                if key not in cfg:
                    cfg[key] = deepcopy(defaults)
            return cfg
        except (json.JSONDecodeError, IOError):
            pass

    # 首次：从 .env 迁移
    cfg = _migrate_from_env()
    save_config(cfg)
    log.info("notify_config_migrated_from_env")
    return cfg


def save_config(cfg: dict) -> None:
    """持久化配置到 JSON 文件"""
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def _migrate_from_env() -> dict:
    """从 .env 环境变量迁移到 JSON 配置"""
    cfg = json.loads(json.dumps(_DEFAULT_CONFIG))

    # Telegram
    tg_enabled = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("true", "1", "yes")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    tg_proxy = os.getenv("TELEGRAM_PROXY", "")
    if tg_token and tg_chat:
        cfg["telegram"] = {
            "enabled": tg_enabled,
            "bot_token": tg_token,
            "chat_id": tg_chat,
            "proxy": tg_proxy,
        }

    # 企业微信
    wechat_url = os.getenv("WECHAT_WEBHOOK_URL", "")
    if wechat_url:
        cfg["wechat"] = {
            "enabled": True,
            "webhook_url": wechat_url,
        }

    return cfg


# ── 发送函数 ──

def send_telegram(content: str, cfg: Optional[dict] = None) -> bool:
    """发送 Telegram 消息（Markdown 格式）"""
    tg = (cfg or load_config()).get("telegram", {})
    if not tg.get("enabled"):
        return False
    bot_token = tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "")
    if not bot_token or not chat_id:
        log.warning("telegram_not_configured")
        return False

    # Telegram MarkdownV2 转义
    escaped = content
    for ch in r'_[]()~`>#+-=|{}.!':
        escaped = escaped.replace(ch, f'\\{ch}')

    proxies = {"https": tg.get("proxy")} if tg.get("proxy") else None

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": escaped, "parse_mode": "MarkdownV2"},
            timeout=15,
            proxies=proxies,
        )
        data = resp.json()
        if data.get("ok"):
            log.info("telegram_send_ok")
            return True
        # MarkdownV2 失败时回退纯文本
        resp2 = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": content},
            timeout=15,
            proxies=proxies,
        )
        ok = resp2.json().get("ok", False)
        log.info("telegram_send_fallback_text", ok=ok)
        return ok
    except Exception as e:
        log.error("telegram_send_error", error=str(e))
        return False


def send_wechat_work(content: str, cfg: Optional[dict] = None) -> bool:
    """发送企业微信 Markdown 消息"""
    wc = (cfg or load_config()).get("wechat", {})
    if not wc.get("enabled"):
        return False
    url = wc.get("webhook_url", "")
    if not url:
        log.warning("wechat_webhook_not_configured")
        return False

    try:
        resp = requests.post(url, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=10)
        data = resp.json()
        if data.get("errcode") == 0:
            log.info("wechat_send_ok")
            return True
        log.warning("wechat_send_failed", errcode=data.get("errcode"), errmsg=data.get("errmsg"))
        return False
    except Exception as e:
        log.error("wechat_send_error", error=str(e))
        return False


def send_pushplus(content: str, cfg: Optional[dict] = None) -> bool:
    """发送 PushPlus 消息（微信公众号推送）"""
    pp = (cfg or load_config()).get("pushplus", {})
    if not pp.get("enabled"):
        return False
    token = pp.get("token", "")
    if not token:
        log.warning("pushplus_not_configured")
        return False

    try:
        payload = {
            "token": token,
            "title": "量化平台通知",
            "content": content,
            "template": "markdown",
        }
        topic = pp.get("topic", "")
        if topic:
            payload["topic"] = topic

        resp = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        data = resp.json()
        # PushPlus 返回 code==200 表示成功（非 HTTP 状态码）
        if data.get("code") == 200:
            log.info("pushplus_send_ok")
            return True
        log.warning("pushplus_send_failed", code=data.get("code"), msg=data.get("msg"))
        return False
    except Exception as e:
        log.error("pushplus_send_error", error=str(e))
        return False


def send_serverchan(content: str, cfg: Optional[dict] = None) -> bool:
    """发送 Server酱 消息（手机 APP 推送）"""
    sc = (cfg or load_config()).get("serverchan", {})
    if not sc.get("enabled"):
        return False
    sendkey = sc.get("sendkey", "")
    if not sendkey:
        log.warning("serverchan_not_configured")
        return False

    try:
        # sctp 前缀的 sendkey 使用不同域名（DSA 验证经验）
        if sendkey.startswith("sctp"):
            match = re.match(r"sctp(\d+)t", sendkey)
            if match:
                url = f"https://{match.group(1)}.push.ft07.com/send/{sendkey}.send"
            else:
                url = f"https://sctapi.ftqq.com/{sendkey}.send"
        else:
            url = f"https://sctapi.ftqq.com/{sendkey}.send"

        resp = requests.post(
            url,
            json={"title": "量化平台通知", "desp": content},
            headers={"Content-Type": "application/json;charset=utf-8"},
            timeout=10,
        )
        if resp.status_code == 200:
            log.info("serverchan_send_ok")
            return True
        log.warning("serverchan_send_failed", status=resp.status_code)
        return False
    except Exception as e:
        log.error("serverchan_send_error", error=str(e))
        return False


def send_feishu(content: str, cfg: Optional[dict] = None) -> bool:
    """发送飞书消息（lark_md 交互卡片，纯文本回退）"""
    fs = (cfg or load_config()).get("feishu", {})
    if not fs.get("enabled"):
        return False
    webhook = fs.get("webhook", "")
    if not webhook:
        log.warning("feishu_not_configured")
        return False

    try:
        # 飞书文本消息不渲染 Markdown，必须使用 interactive + lark_md 卡片
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "量化平台通知"},
                },
                "elements": [{
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": content},
                }],
            },
        }
        resp = requests.post(webhook, json=payload, timeout=15)
        data = resp.json()
        code = data.get("code", data.get("StatusCode"))
        if code == 0:
            log.info("feishu_send_ok")
            return True

        # 卡片失败时回退纯文本
        log.info("feishu_card_failed_fallback_text", code=code)
        resp2 = requests.post(
            webhook,
            json={"msg_type": "text", "content": {"text": content}},
            timeout=15,
        )
        data2 = resp2.json()
        ok = data2.get("code", data2.get("StatusCode")) == 0
        log.info("feishu_send_fallback_text", ok=ok)
        return ok
    except Exception as e:
        log.error("feishu_send_error", error=str(e))
        return False


def send_webhook(content: str, cfg: Optional[dict] = None) -> bool:
    """发送到自定义 Webhook（自动识别钉钉 URL 切换 payload 格式）"""
    wh = (cfg or load_config()).get("webhook", {})
    if not wh.get("enabled"):
        return False
    url = wh.get("url", "")
    if not url:
        log.warning("webhook_not_configured")
        return False

    try:
        # 钉钉 URL 自动识别，使用 Markdown 格式（DSA 验证经验）
        url_lower = url.lower()
        if "dingtalk" in url_lower or "oapi.dingtalk.com" in url_lower:
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": "量化平台通知", "text": content},
            }
        else:
            payload = {"content": content, "msg_type": "text"}

        resp = requests.post(url, json=payload, timeout=10)
        ok = 200 <= resp.status_code < 300
        log.info("webhook_send", status=resp.status_code, ok=ok)
        return ok
    except Exception as e:
        log.error("webhook_send_error", error=str(e))
        return False


# 渠道名 → 发送函数映射（用于 send_notification 遍历和 notify-test 动态调用）
_CHANNEL_SENDERS = {
    "telegram": send_telegram,
    "wechat": send_wechat_work,
    "pushplus": send_pushplus,
    "serverchan": send_serverchan,
    "feishu": send_feishu,
    "webhook": send_webhook,
}

# 渠道中文名（用于测试推送结果和日志）
CHANNEL_LABELS = {
    "telegram": "Telegram",
    "wechat": "企业微信",
    "pushplus": "PushPlus",
    "serverchan": "Server酱",
    "feishu": "飞书",
    "webhook": "自定义Webhook",
}


def is_push_cooling(cfg: dict) -> bool:
    """检查精选推送是否在冷却期内，防止短时间连推"""
    from datetime import datetime
    last = cfg.get("last_push")
    if not last or not last.get("time"):
        return False
    # 上次未实际发送（count=0 或失败）不启动冷却
    if not last.get("count") or not last.get("success"):
        return False
    cooldown = cfg.get("push_cooldown_minutes", 10)
    try:
        last_time = datetime.strptime(last["time"], "%Y-%m-%d %H:%M")
        elapsed = (datetime.now() - last_time).total_seconds() / 60
        if elapsed < cooldown:
            log.info("push_cooldown_active", elapsed_min=round(elapsed, 1), cooldown=cooldown)
            return True
    except (ValueError, TypeError):
        pass
    return False


def send_notification(content: str) -> bool:
    """向所有已启用渠道发送通知（遍历式，非优先级链）"""
    cfg = load_config()
    any_ok = False

    for name, sender in _CHANNEL_SENDERS.items():
        if cfg.get(name, {}).get("enabled"):
            try:
                ok = sender(content, cfg)
                if ok:
                    any_ok = True
                else:
                    log.warning("channel_send_failed", channel=name)
            except Exception as e:
                log.error("channel_send_error", channel=name, error=str(e))

    if not any_ok:
        log.warning("no_notification_sent")
    return any_ok
