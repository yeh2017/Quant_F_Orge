"""
system_config.py
================
系统配置统一管理：读写 .env + .notify_config.json，供前端设置面板使用。
Token 类字段脱敏返回，PUT 时脱敏字段自动跳过。
"""
import os
import re

import settings as _settings
from pathlib import Path

import structlog
from fastapi import APIRouter, Request

_log = structlog.get_logger("system_config")

router = APIRouter(prefix="/api/system", tags=["system"])

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


# .env 中需要管理的 key（顺序即前端展示顺序，按分组排列）
_ENV_KEYS = [
    # 数据源
    "TUSHARE_TOKEN", "TUSHARE_POINTS", "TAVILY_API_KEY",
    # AI 模型（多渠道）
    "LLM_CHANNELS", "ERNIE_BATCH_SIZE", "LLM_MONTHLY_BUDGET",
    "LLM_SILICONFLOW_URL", "LLM_SILICONFLOW_KEY", "LLM_SILICONFLOW_MODEL",
    "LLM_ANSPIRE_URL", "LLM_ANSPIRE_KEY", "LLM_ANSPIRE_MODEL",
    # 向后兼容旧配置
    "ERNIE_API_KEY", "ERNIE_MODEL_NAME",
    # 服务配置
    "API_HOST", "API_PORT",
    # 数据限速（秒/请求）
    "TUSHARE_FETCH_SLEEP", "BOND_FETCH_SLEEP", "FINANCIAL_SLEEP",
    "MONEYFLOW_SLEEP", "SW_INDUSTRY_SLEEP", "AKSHARE_NEWS_SLEEP",

    # 并发 & 写入
    "FINANCIAL_WORKERS", "WRITE_BATCH_SIZE",
    # 熔断保护
    "TUSHARE_RATE_LIMIT_PER_MIN", "TUSHARE_BREAKER_FAIL_THRESHOLD", "TUSHARE_BREAKER_COOLDOWN",
    # 数据保留
    "NEWS_RETAIN_DAYS", "BACKTEST_RESULT_RETAIN_DAYS",
    "DB_RETAIN_YEARS", "CACHE_RETAIN_DAYS", "LOG_RETAIN_DAYS",
]

# 需要脱敏的 key
_SENSITIVE_KEYS = {"TUSHARE_TOKEN", "TAVILY_API_KEY", "ERNIE_API_KEY",
                   "LLM_SILICONFLOW_KEY", "LLM_ANSPIRE_KEY"}

_MASK_PATTERN = re.compile(r"\*{4}")


def _mask(value: str) -> str:
    """脱敏：保留前 4 位 + 后 4 位"""
    if not value or len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def _is_masked(value: str) -> bool:
    """判断值是否为脱敏后的占位符"""
    return bool(_MASK_PATTERN.search(value))


# env key → settings.py 默认值映射（单一真相来源）
_ENV_DEFAULTS = {
    "TUSHARE_POINTS": str(_settings.TUSHARE_POINTS),
    "TUSHARE_FETCH_SLEEP": str(_settings.TUSHARE_FETCH_SLEEP),
    "BOND_FETCH_SLEEP": str(_settings.BOND_FETCH_SLEEP),
    "FINANCIAL_SLEEP": str(_settings.FINANCIAL_SLEEP),
    "MONEYFLOW_SLEEP": str(_settings.MONEYFLOW_SLEEP),
    "SW_INDUSTRY_SLEEP": str(_settings.SW_INDUSTRY_SLEEP),
    "AKSHARE_NEWS_SLEEP": str(_settings.AKSHARE_NEWS_SLEEP),

    "FINANCIAL_WORKERS": str(_settings.FINANCIAL_WORKERS),
    "WRITE_BATCH_SIZE": str(_settings.WRITE_BATCH_SIZE),
    "TUSHARE_RATE_LIMIT_PER_MIN": str(_settings.TUSHARE_RATE_LIMIT_PER_MIN),
    "TUSHARE_BREAKER_FAIL_THRESHOLD": str(_settings.TUSHARE_BREAKER_FAIL_THRESHOLD),
    "TUSHARE_BREAKER_COOLDOWN": str(_settings.TUSHARE_BREAKER_COOLDOWN),
    "NEWS_RETAIN_DAYS": str(_settings.NEWS_RETAIN_DAYS),
    "BACKTEST_RESULT_RETAIN_DAYS": str(_settings.BACKTEST_RESULT_RETAIN_DAYS),
    "DB_RETAIN_YEARS": str(_settings.DB_RETAIN_YEARS),
    "CACHE_RETAIN_DAYS": str(_settings.CACHE_RETAIN_DAYS),
    "LOG_RETAIN_DAYS": str(_settings.LOG_RETAIN_DAYS),
    "ERNIE_MODEL_NAME": _settings.ERNIE_MODEL_NAME,
    "ERNIE_BATCH_SIZE": str(_settings.ERNIE_BATCH_SIZE),
    "LLM_MONTHLY_BUDGET": str(int(_settings.LLM_MONTHLY_BUDGET)),
    # LLM 多渠道默认值
    "LLM_CHANNELS": "siliconflow,anspire",
    "LLM_SILICONFLOW_URL": _settings.ERNIE_MODEL_URL,
    "LLM_SILICONFLOW_MODEL": _settings.ERNIE_MODEL_NAME,
    "LLM_ANSPIRE_URL": "https://open-gateway.anspire.cn/v6/chat/completions",
    "LLM_ANSPIRE_MODEL": "deepseek-v4-flash",
    "API_HOST": "0.0.0.0",
    "API_PORT": "8000",
}


def _read_env() -> dict:
    """解析 .env 文件为 dict（只读取有值的行）"""
    result = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            value = value.strip()
            if value:
                result[key.strip()] = value
    return result


def _write_env(updates: dict):
    """写入 .env：有值=更新/新增，空值=删除该行（重置为默认值）"""
    lines = []
    if _ENV_PATH.exists():
        lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

    to_write = {k: v for k, v in updates.items() if v}   # 有值的
    to_delete = {k for k, v in updates.items() if not v}  # 空值=删除

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in to_delete:
                updated_keys.add(key)
                continue  # 删除该行
            if key in to_write:
                new_lines.append(f"{key}={to_write[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # 新增不存在的 key（仅有值的）
    for key, value in to_write.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 热更新 os.environ
    for key, value in to_write.items():
        os.environ[key] = value
    for key in to_delete:
        os.environ.pop(key, None)


@router.get("/config")
async def get_config():
    """合并返回 .env 配置 + 推送配置"""
    env_data = _read_env()

    # 构造 env 部分：.env 值优先，缺失用 settings.py 默认值填充（脱敏）
    env_config = {}
    for key in _ENV_KEYS:
        value = env_data.get(key, "") or _ENV_DEFAULTS.get(key, "")
        if key in _SENSITIVE_KEYS and value:
            env_config[key] = _mask(value)
        else:
            env_config[key] = value

    # 构造 notify 部分（脱敏敏感字段）
    from services.notifier import load_config as _load_notify
    notify_config = _load_notify()

    # 各渠道敏感字段统一脱敏
    _NOTIFY_SENSITIVE = {
        "telegram": ("bot_token", "chat_id"),
        "pushplus": ("token",),
        "serverchan": ("sendkey",),
    }
    for channel, fields in _NOTIFY_SENSITIVE.items():
        for field in fields:
            val = notify_config.get(channel, {}).get(field, "")
            if val and len(val) >= 8:
                notify_config.setdefault(channel, {})[field] = _mask(val)

    # 模型价格表（前端单一数据源）
    from services.news.sentiment_llm import _MODEL_PRICING, _daily
    model_pricing = {k: v for k, v in _MODEL_PRICING.items()}

    # 近 7 天日均需 LLM 评分的新闻条数（有关联股票的）
    avg_daily_llm_news = 0
    try:
        from core.database import db_session
        from sqlalchemy import text as _text
        with db_session() as db:
            row = db.execute(_text(
                "SELECT COUNT(*) as c, COUNT(DISTINCT DATE(publish_time)) as d "
                "FROM stock_news "
                "WHERE publish_time >= DATE('now', '-7 days') "
                "AND related_codes IS NOT NULL AND related_codes != '[]'"
            )).fetchone()
            if row and row[1] and row[1] > 0:
                avg_daily_llm_news = round(row[0] / row[1])
    except Exception as e:
        _log.debug("avg_daily_llm_news_query_failed", error=str(e))

    # LLM 供应商状态列表（前端展示用）
    from services.news.sentiment_llm import _load_providers, _PROVIDER_MODELS, _MODEL_PRICING
    import os as _os
    llm_providers = []
    # 始终从 LLM_CHANNELS 构建完整列表，Key 为空也展示（前端才有输入框）
    channels = (_os.environ.get('LLM_CHANNELS', '') or env_config.get('LLM_CHANNELS', '')).strip()
    configured_map = {p['name']: p for p in _load_providers()}
    for ch in (channels.split(',') if channels else []):
        ch = ch.strip().lower()
        if not ch:
            continue
        prefix = f'LLM_{ch.upper()}_'
        p = configured_map.get(ch, {})
        models = _PROVIDER_MODELS.get(ch, [])
        llm_providers.append({
            'name': ch,
            'model': p.get('model') or _os.environ.get(f'{prefix}MODEL', ''),
            'configured': bool(p.get('key')),
            'models': [{'name': m, 'free': _MODEL_PRICING.get(m, {}).get('input', 1) == 0} for m in models],
        })

    return {
        "env": env_config, "notify": notify_config,
        "model_pricing": model_pricing,
        "avg_daily_llm_news": avg_daily_llm_news,
        "llm_stats": _daily.stats,
        "llm_providers": llm_providers,
    }


@router.put("/config")
async def update_config(request: Request):
    """接收 partial update，拆分写回 .env 和 .notify_config.json"""
    body = await request.json()

    # 处理 env 部分
    env_updates = body.get("env", {})
    if env_updates:
        # 过滤掉脱敏值（用户未修改的字段）
        real_updates = {}
        for key, value in env_updates.items():
            if key in _SENSITIVE_KEYS and _is_masked(str(value)):
                continue  # 跳过脱敏占位符
            real_updates[key] = str(value)
        if real_updates:
            _write_env(real_updates)  # 空值由 _write_env 处理为删除行

    # 处理 notify 部分
    notify_updates = body.get("notify")
    if notify_updates is not None:
        from services.notifier import load_config as _load_notify, save_config as _save_notify, CHANNEL_KEYS
        current = _load_notify()
        for channel in CHANNEL_KEYS:
            if channel in notify_updates:
                incoming = notify_updates[channel]
                merged = {**current.get(channel, {})}
                for k, v in incoming.items():
                    if isinstance(v, str) and "****" in v:
                        continue
                    merged[k] = v
                current[channel] = merged
        # 顶层非渠道字段（auto_push_enabled, summary_push_hours, push_top_n, push_threshold）
        for key in ("auto_push_enabled", "summary_push_hours", "push_top_n", "push_threshold"):
            if key in notify_updates:
                val = notify_updates[key]
                # 边界校验
                try:
                    if key == "push_top_n":
                        val = max(1, min(20, int(val)))
                    elif key == "push_threshold":
                        val = max(0.1, min(1.0, float(val)))
                except (ValueError, TypeError):
                    continue
                current[key] = val
        _save_notify(current)

    return {"ok": True}


@router.get("/status")
async def get_status():
    """系统状态：DB 大小"""
    db_path = Path(__file__).resolve().parent.parent / "quant_data.db"
    db_size_mb = round(db_path.stat().st_size / 1024 / 1024, 1) if db_path.exists() else 0
    return {"db_size_mb": db_size_mb}


@router.post("/test-llm")
async def test_llm_connectivity():
    """轻量级 LLM 连通性测试：对每个已配置供应商发送最小 prompt，返回各自状态"""
    import requests as _req
    from services.news.sentiment_llm import _load_providers

    providers = _load_providers()
    if not providers:
        return {"results": [], "summary": "未配置任何 LLM 供应商"}

    results = []
    for p in providers:
        entry = {"name": p["name"], "model": p["model"], "status": "unknown", "detail": ""}
        try:
            resp = _req.post(
                p["url"],
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {p['key']}",
                },
                json={
                    "model": p["model"],
                    "messages": [{"role": "user", "content": "回复OK"}],
                    "max_tokens": 5,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                entry["status"] = "ok"
                entry["detail"] = "连通正常"
            elif resp.status_code in (401, 403):
                entry["status"] = "auth_error"
                entry["detail"] = "API Key 无效或无权限"
            elif resp.status_code == 402:
                entry["status"] = "no_balance"
                entry["detail"] = "账户余额不足"
            elif resp.status_code == 429:
                entry["status"] = "rate_limit"
                entry["detail"] = "请求频率超限（但连通正常）"
            else:
                entry["status"] = "error"
                entry["detail"] = f"HTTP {resp.status_code}: {resp.text[:100]}"
        except _req.Timeout:
            entry["status"] = "timeout"
            entry["detail"] = "请求超时（>10s）"
        except _req.ConnectionError:
            entry["status"] = "unreachable"
            entry["detail"] = "无法连接服务器"
        except Exception as e:
            entry["status"] = "error"
            entry["detail"] = str(e)[:100]
        results.append(entry)

    ok_count = sum(1 for r in results if r["status"] == "ok")
    summary = f"{ok_count}/{len(results)} 个供应商可用"
    return {"results": results, "summary": summary}
