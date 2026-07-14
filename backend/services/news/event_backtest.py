"""
事件回测统计 — L1 统计验证层

按 event_type 聚合历史事件，计算 T+N 收益率和胜率，
验证 NLP 事件分类是否具有预测价值。
"""
import json
from datetime import timedelta
from typing import Optional, List

import structlog

from core.database import db_session
from models.quant_data import StockNews, StockDailyBar

log = structlog.get_logger("event_backtest")

# 默认观察周期：T+1 验证即时反应，T+5 一周趋势，T+10 两周确认
DEFAULT_PERIODS = [1, 5, 10]

# 兜底分类无预测价值，排除
_EXCLUDE_EVENTS = {"其他"}


def extract_event_signals(
    event_type: Optional[str] = None,
    min_score: float = 0.3,
    codes_filter: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> list:
    """
    提取去重后的事件信号列表（L1 统计 + L3 策略共用）。

    逻辑：
    - 排除"其他/技术/政策"兜底分类
    - 排除北交所（.BJ）
    - 按 (code, date, event_type) 去重，保留 |score| 最高的一条

    Returns:
        [{"code", "pub_date"(date), "event", "score", "title", "url"}, ...]
    """
    with db_session() as db:
        query = db.query(StockNews).filter(
            StockNews.event_type.isnot(None),
            StockNews.event_type != "",
            StockNews.event_type.notin_(list(_EXCLUDE_EVENTS)),
            StockNews.publish_time.isnot(None),
        )
        if event_type:
            query = query.filter(StockNews.event_type == event_type)
        if start_date:
            query = query.filter(StockNews.publish_time >= start_date)
        if end_date:
            query = query.filter(StockNews.publish_time <= end_date + " 23:59:59")
        news_rows = [{
            "event_type": r.event_type,
            "sentiment_score": r.sentiment_score,
            "related_codes": r.related_codes,
            "publish_time": r.publish_time,
            "title": r.title,
            "url": r.url,
        } for r in query.all()]

    codes_set = set(codes_filter) if codes_filter else None
    dedup = {}
    for row in news_rows:
        score = row["sentiment_score"] or 0
        if abs(score) < min_score:
            continue
        codes = json.loads(str(row["related_codes"] or "[]"))
        if not codes:
            continue
        code = codes[0]
        if code.endswith(".BJ"):
            continue
        if codes_set and code not in codes_set:
            continue
        pub_date = row["publish_time"].date()
        key = (code, pub_date.isoformat(), row["event_type"])
        if key not in dedup or abs(score) > abs(dedup[key]["score"]):
            dedup[key] = {
                "code": code, "pub_date": pub_date,
                "event": row["event_type"], "score": score,
                "title": row["title"], "url": row["url"],
            }

    return list(dedup.values())


def analyze_events(
    event_type: Optional[str] = None,
    min_score: float = 0.3,
    periods: Optional[list] = None,
) -> dict:
    """
    统计事件发生后 T+N 天的收益表现。

    Args:
        event_type: 筛选事件类型（None=全部）
        min_score: 最低 |sentiment_score| 阈值
        periods: T+N 天列表，如 [1, 3, 5, 10]

    Returns:
        {"summary": {事件类型: 统计}, "details": [逐条明细]}
    """
    if periods is None:
        periods = DEFAULT_PERIODS

    events = extract_event_signals(event_type=event_type, min_score=min_score)
    code_set = {e["code"] for e in events}

    # 批量加载价格数据（单次查询替代 N+1）
    max_period = max(periods)
    price_cache = {}
    if events:
        all_dates = [e["pub_date"] for e in events]
        min_date = min(all_dates)
        max_date = max(all_dates) + timedelta(days=max_period + 5)
        with db_session() as db:
            bars = db.query(
                StockDailyBar.code, StockDailyBar.trade_date, StockDailyBar.close
            ).filter(
                StockDailyBar.code.in_(list(code_set)),
                StockDailyBar.trade_date >= min_date,
                StockDailyBar.trade_date <= max_date,
            ).order_by(StockDailyBar.code, StockDailyBar.trade_date).all()
        for bar in bars:
            price_cache.setdefault(bar.code, []).append((bar.trade_date, bar.close))

    # 逐条计算收益
    details = []
    for item in events:
        code = item["code"]
        pub_date = item["pub_date"]
        all_bars = price_cache.get(code, [])
        future_bars = [(d, c) for d, c in all_bars if d >= pub_date and c and c > 0]
        if len(future_bars) < 2:
            continue

        t0_close = future_bars[0][1]
        returns = {}
        for p in periods:
            if p < len(future_bars):
                returns[f"r{p}d"] = round((future_bars[p][1] / t0_close - 1) * 100, 2)
        if not returns:
            continue

        details.append({
            "date": pub_date.strftime("%Y-%m-%d"),
            "code": code,
            "event": item["event"],
            "score": round(item["score"], 2),
            "title": item["title"],
            "url": item["url"],
            **returns,
        })

    summary = _aggregate(details, periods)
    log.info("event_backtest_done", events=len(details), types=len(summary))
    return {"summary": summary, "details": details}


def _aggregate(details: list, periods: list) -> dict:
    """按 event_type 分组计算均值和胜率"""
    from collections import defaultdict

    groups = defaultdict(list)
    for d in details:
        groups[d["event"]].append(d)

    summary = {}
    for et, items in groups.items():
        stats = {"count": len(items)}
        for p in periods:
            key = f"r{p}d"
            vals = [d[key] for d in items if key in d]
            if vals:
                stats[f"avg_{p}d"] = round(sum(vals) / len(vals), 2)
                stats[f"win_{p}d"] = round(sum(1 for v in vals if v > 0) / len(vals), 2)
                stats[f"samples_{p}d"] = len(vals)
        summary[et] = stats

    return summary
