"""
多渠道 LLM 情绪分析模块

支持多供应商自动降级（SiliconFlow → Anspire → 关键词兜底）：
1. per-stock 独立评分（解决多股票混合新闻误判）
2. 事件分类（重组/业绩/政策/...）
3. 一句话理由

供应商配置：.env LLM_CHANNELS + LLM_{NAME}_URL/KEY/MODEL
降级链：供应商1 → 供应商2 → ... → 关键词评分（sentiment.py）
"""
import json
import time
import threading
from datetime import date as _date
import structlog
import requests
from typing import List, Dict, Optional

import settings
from services.news.sentiment import score_to_label

log = structlog.get_logger("sentiment_llm")

# ── 模型 token 单价 + 月预算控制 ──
import os as _os

# 模型 token 单价（¥/token）— 以各供应商账单为准
_MODEL_PRICING = {
    # SiliconFlow 实际定价（¥/token）
    'deepseek-ai/DeepSeek-V4-Flash': {'input': 1.0e-6, 'output': 2.0e-6},
    'Qwen/Qwen2.5-7B-Instruct': {'input': 0.3e-6, 'output': 0.7e-6},
    # Anspire（模型名不带前缀，需独立条目）
    'deepseek-v4-flash': {'input': 1.0e-6, 'output': 2.0e-6},
}

# 默认定价（未知模型兜底）
_DEFAULT_PRICING = {'input': 1.0e-6, 'output': 2.0e-6}

# 各供应商可选模型列表（前端下拉用）
_PROVIDER_MODELS = {
    'siliconflow': ['deepseek-ai/DeepSeek-V4-Flash', 'Qwen/Qwen2.5-7B-Instruct'],
    'anspire': ['deepseek-v4-flash'],
}


def _load_providers() -> list:
    """
    从 .env 解析供应商列表，按优先级排序。
    LLM_CHANNELS=siliconflow,anspire → 依次尝试
    未配置时向后兼容 ERNIE_* 单供应商模式。
    """
    channels = (_os.environ.get('LLM_CHANNELS', '') or '').strip()
    if not channels:
        # 向后兼容：无 LLM_CHANNELS 时读 ERNIE_* 旧配置
        key = _os.environ.get('ERNIE_API_KEY', '') or settings.ERNIE_API_KEY
        if key:
            return [{
                'name': 'siliconflow',
                'url': _os.environ.get('ERNIE_MODEL_URL', '') or settings.ERNIE_MODEL_URL,
                'key': key,
                'model': _os.environ.get('ERNIE_MODEL_NAME', '') or settings.ERNIE_MODEL_NAME,
            }]
        return []

    providers = []
    for ch in channels.split(','):
        ch = ch.strip().lower()
        if not ch:
            continue
        prefix = f'LLM_{ch.upper()}_'
        url = _os.environ.get(f'{prefix}URL', '')
        key = _os.environ.get(f'{prefix}KEY', '')
        model = _os.environ.get(f'{prefix}MODEL', '')
        if url and key:
            providers.append({'name': ch, 'url': url, 'key': key, 'model': model})
    return providers


def _pricing_for(model_name: str) -> dict:
    """查询指定模型的定价"""
    return _MODEL_PRICING.get(model_name, _DEFAULT_PRICING)


def _is_free_model_by_name(model_name: str) -> bool:
    p = _pricing_for(model_name)
    return p['input'] == 0 and p['output'] == 0


def _is_free_model() -> bool:
    """主供应商是否免费（预算检查用）"""
    providers = _load_providers()
    if not providers:
        return True
    return _is_free_model_by_name(providers[0].get('model', ''))


def _calc_cost(prompt_tokens: int, completion_tokens: int, model_name: str = '') -> float:
    """根据实际 token 用量和模型计算单次费用（¥）"""
    p = _pricing_for(model_name) if model_name else _DEFAULT_PRICING
    return prompt_tokens * p['input'] + completion_tokens * p['output']


def _daily_budget() -> float:
    """日预算（¥），从月预算推导。仅付费模型调用，免费模型无预算概念"""
    monthly = float(_os.environ.get('LLM_MONTHLY_BUDGET', '') or settings.LLM_MONTHLY_BUDGET)
    return monthly / 30


class _DailyCounter:
    """线程安全的日费用计数器，跨天自动重置"""
    def __init__(self):
        self._lock = threading.Lock()
        self._date = _date.today()
        self._count = 0
        self._total_prompt = 0
        self._total_completion = 0
        self._total_cost = 0.0  # ¥
        self._limit_notified = False



    def _reset_if_new_day(self):
        today = _date.today()
        if today != self._date:
            self._date = today
            self._count = 0
            self._total_prompt = 0
            self._total_completion = 0
            self._total_cost = 0.0
            self._limit_notified = False

    def check_budget(self) -> str:
        """检查预算状态。返回 'ok' / 'free_only' / 'exhausted'

        - ok:         有预算，正常使用全部供应商
        - free_only:  付费预算耗尽但存在免费供应商，仅用免费模型
        - exhausted:  预算耗尽且无免费供应商，降级关键词
        """
        if _is_free_model():
            return 'ok'
        with self._lock:
            self._reset_if_new_day()
            if self._total_cost < _daily_budget():
                return 'ok'
        # 付费预算耗尽 → 看有没有免费供应商可用
        free = [p for p in _load_providers() if _is_free_model_by_name(p.get('model', ''))]
        return 'free_only' if free else 'exhausted'

    def record_usage(self, prompt_tokens, completion_tokens, model_name=''):
        cost = _calc_cost(prompt_tokens, completion_tokens, model_name)
        with self._lock:
            self._reset_if_new_day()
            self._count += 1
            self._total_prompt += prompt_tokens
            self._total_completion += completion_tokens
            self._total_cost += cost

    @property
    def stats(self):
        with self._lock:
            return {
                "date": str(self._date),
                "calls": self._count,
                "prompt_tokens": self._total_prompt,
                "completion_tokens": self._total_completion,
                "cost_today": round(self._total_cost, 4),
            }


_daily = _DailyCounter()


def _notify_budget_reached():
    """预算耗尽时推送通知（每日仅一次），告知用户已降级为关键词评分"""
    if _daily._limit_notified:
        return
    _daily._limit_notified = True
    try:
        from services.notifier import send_notification
        stats = _daily.stats
        send_notification(
            f"⚠️ LLM 日预算已耗尽（¥{stats['cost_today']:.3f}）\n"
            f"今日已调用 {stats['calls']} 次，剩余新闻将使用关键词评分。\n"
            f"如需调整，请前往 系统设置 → AI 模型 修改月预算。"
        )
    except Exception as e:
        log.debug("limit_notify_failed", error=str(e))

# 事件类型枚举（prompt 约束 + 前端展示 + 回测分组）
# LLM 可分类的事件类型（prompt 中提供的选项）
LLM_EVENT_TYPES = {"重组", "业绩", "人事", "诉讼", "资金", "分红", "产品", "合作", "政策", "行业", "其他"}
# 结构化事件专用（sync_events 规则注入，LLM 不应返回这些类型，避免重复信号）
STRUCTURED_EVENT_TYPES = {"大宗交易", "解禁", "龙虎榜"}
# 完整枚举（前端展示 + 回测筛选用）
EVENT_TYPES = sorted(LLM_EVENT_TYPES | STRUCTURED_EVENT_TYPES)

_SYSTEM_PROMPT = """你是 A 股金融新闻分析师。对用户给出的每条新闻，针对其关联的每只股票分别做情绪判断。

输出要求：
- 返回 JSON 数组，每个元素对应一条新闻
- 每条新闻包含 news_idx (从1开始) 和 stocks 数组
- 每只股票: code, score (-1.0到+1.0), event (事件类型), reason (≤20字理由)
- event 取值: 重组/业绩/人事/诉讼/资金/分红/产品/合作/政策/行业/其他
- 分类指引: 产品=新品发布/技术突破, 合作=战略合作/签约订单, 政策=监管/补贴/行业政策, 行业=行业趋势/产业链变动
- 尽量使用具体分类，仅在完全不匹配时才用"其他"
- 只返回 JSON，不要 markdown 标记或其他文字"""


def _build_user_prompt(batch: List[dict]) -> str:
    """构造用户 prompt，每条新闻一行"""
    lines = []
    for i, item in enumerate(batch, 1):
        codes_str = ", ".join(item.get("codes", []))
        title = item.get("title", "")
        lines.append(f"{i}. [{title}] 关联: [{codes_str}]")
    return "新闻列表：\n" + "\n".join(lines)


def _call_single_provider(user_prompt: str, provider: dict) -> Optional[str]:
    """调用单个 LLM 供应商，返回原始文本响应"""
    model_name = provider['model']
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {provider['key']}",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        provider['url'], headers=headers,
        json=payload, timeout=getattr(settings, 'ERNIE_TIMEOUT', 30),
    )
    # 模型不支持 response_format 时去掉重试
    if resp.status_code == 400 and "response_format" in resp.text and "not support" in resp.text.lower():
        payload.pop("response_format", None)
        resp = requests.post(
            provider['url'], headers=headers,
            json=payload, timeout=getattr(settings, 'ERNIE_TIMEOUT', 30),
        )
    resp.raise_for_status()
    data = resp.json()

    # 记录 token 用量（按实际模型计费）
    usage = data.get("usage", {})
    p_tok = usage.get("prompt_tokens", 0)
    c_tok = usage.get("completion_tokens", 0)
    _daily.record_usage(p_tok, c_tok, model_name)
    if p_tok or c_tok:
        log.info("llm_usage", provider=provider['name'], model=model_name,
                 prompt_tokens=p_tok, completion_tokens=c_tok, daily=_daily.stats)

    if "choices" in data:
        return data["choices"][0]["message"]["content"]
    if "result" in data:
        return data["result"]

    log.warning("llm_unexpected_response", provider=provider['name'], keys=list(data.keys()))
    return None


def _call_llm(user_prompt: str, free_only: bool = False) -> Optional[str]:
    """按优先级尝试各供应商，第一个成功即返回。全失败返回 None

    Args:
        free_only: True 时仅使用免费模型的供应商（预算耗尽降级模式）
    """
    providers = _load_providers()
    if free_only:
        providers = [p for p in providers if _is_free_model_by_name(p.get('model', ''))]
    if not providers:
        return None
    last_err = None
    for provider in providers:
        try:
            result = _call_single_provider(user_prompt, provider)
            if result:
                return result
        except Exception as e:
            log.warning("llm_provider_failed", provider=provider['name'], error=str(e))
            last_err = e
    if last_err:
        log.error("all_llm_providers_failed", providers=[p['name'] for p in providers],
                  error=str(last_err))
    return None


def _parse_response(raw: str, batch: List[dict]) -> List[dict]:
    """
    解析 LLM JSON 响应 → 类型安全的结构化数据。

    这是 LLM 输出与业务逻辑之间的**唯一类型边界**。
    所有字段在此处完成类型强制转换，下游无需防御。

    Returns:
        [{ "news_idx": int, "stocks": [{"code": str, "score": float, "event": str, "reason": str}] }]
    """
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        parsed = json.loads(text)

        # 如果返回的是 dict 包裹 {"results": [...]}
        if isinstance(parsed, dict):
            for key in ("results", "data", "news"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                parsed = [parsed]

        if not isinstance(parsed, list):
            return []

        # ── 类型强制转换 ──
        cleaned = []
        for entry in parsed:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry.get("news_idx", 0))
            except (TypeError, ValueError):
                continue

            raw_stocks = entry.get("stocks", [])
            if not isinstance(raw_stocks, list):
                continue

            safe_stocks = []
            for s in raw_stocks:
                if not isinstance(s, dict):
                    continue
                # score: 强制 float, clamp [-1, 1], 无效值 → 0
                try:
                    sc = float(s.get("score", 0))
                except (TypeError, ValueError):
                    sc = 0.0
                sc = max(-1.0, min(1.0, sc))

                # event: 强制 str, 不在 LLM 可用枚举内 → "其他"
                # 结构化事件类型（大宗交易/解禁/龙虎榜）由 sync_events 规则注入，LLM 不应产生
                ev = str(s.get("event", "其他"))
                if ev not in LLM_EVENT_TYPES:
                    ev = "其他"

                safe_stocks.append({
                    "code": str(s.get("code", "")),
                    "score": sc,
                    "event": ev,
                    "reason": str(s.get("reason", ""))[:100],
                })

            cleaned.append({"news_idx": idx, "stocks": safe_stocks})

        return cleaned
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        log.warning("ernie_parse_failed", error=str(e), raw=raw[:200])
        return []


def score_batch_llm(news_items: List[dict]) -> Dict[int, dict]:
    """
    批量调 LLM 评分（多供应商自动降级）。

    Args:
        news_items: [{"id": 123, "title": "...", "codes": ["300965.SZ"]}]

    Returns:
        { news_id: {"score": float, "label": str, "event_type": str, "nlp_reason": str} }
        只返回成功评分的记录，失败的不包含（由调用方回退关键词）
    """
    # 检查是否有可用供应商
    providers = _load_providers()
    if not providers:
        log.debug("llm_skipped", reason="no_provider_configured")
        return {}

    # 日预算前置检查
    budget_status = _daily.check_budget()
    if budget_status == 'exhausted':
        log.warning("llm_daily_budget_exhausted", stats=_daily.stats)
        _notify_budget_reached()
        return {}
    free_only = budget_status == 'free_only'
    if free_only:
        log.info("llm_budget_degraded_to_free", stats=_daily.stats)

    results = {}
    batch_size = int(_os.environ.get('ERNIE_BATCH_SIZE', '') or settings.ERNIE_BATCH_SIZE)

    for start in range(0, len(news_items), batch_size):
        # 循环内逐批检查预算
        budget_status = _daily.check_budget()
        if budget_status == 'exhausted':
            log.warning("llm_budget_mid_batch", stats=_daily.stats,
                        processed=start, total=len(news_items))
            break
        if budget_status == 'free_only':
            free_only = True

        batch = news_items[start:start + batch_size]
        prompt = _build_user_prompt(batch)
        raw = _call_llm(prompt, free_only=free_only)

        if not raw:
            continue

        # _parse_response 已保证所有字段类型安全，下游直接使用
        parsed = _parse_response(raw, batch)

        for entry in parsed:
            idx = entry["news_idx"] - 1  # 1-based → 0-based
            if idx < 0 or idx >= len(batch):
                continue

            news_id = batch[idx]["id"]
            stocks = entry["stocks"]

            if not stocks:
                continue

            # 对目标股票取评分（多只取与 related_codes 匹配的）
            target_codes = set(batch[idx].get("codes", []))
            matched = [s for s in stocks if s["code"] in target_codes]
            if not matched:
                matched = stocks

            # 取绝对值最大的评分作为整条新闻的代表分（score 已是 float）
            best = max(matched, key=lambda s: abs(s["score"]))

            results[news_id] = {
                "score": best["score"],
                "label": score_to_label(best["score"]),
                "event_type": best["event"],
                "nlp_reason": best["reason"],
                "per_stock": stocks,
            }

        # 请求间隔，避免触发频率限制
        if start + batch_size < len(news_items):
            time.sleep(0.5)

    log.info("ernie_batch_done", total=len(news_items), scored=len(results))
    return results
