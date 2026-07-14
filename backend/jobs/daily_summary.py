"""
每日新闻摘要
===========
生成当天新闻统计 + 推送企业微信
"""

import json
import structlog
from datetime import datetime, timedelta
from collections import Counter
from core.database import db_session
from models.quant_data import StockNews
from services.notifier import send_notification

log = structlog.get_logger("daily_summary")


def generate_daily_summary() -> str:
    """生成新闻 Markdown 摘要（只包含上次推送后的新增内容）"""
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)

    # 从上次推送时间开始，避免多次推送重复内容
    from services.notifier import load_config
    last = load_config().get("last_summary", {})
    last_time_str = last.get("time", "")
    if last_time_str:
        try:
            since = datetime.fromisoformat(last_time_str.replace(" ", "T"))
        except (ValueError, TypeError):
            since = datetime.combine(yesterday, datetime.min.time())
    else:
        since = datetime.combine(yesterday, datetime.min.time())

    with db_session() as db:
        from sqlalchemy import or_
        items = db.query(StockNews).filter(or_(
            StockNews.publish_time >= since,
            (StockNews.publish_time.is_(None)) & (StockNews.created_at >= since),
        )).all()

        if not items:
            return ""

        total = len(items)

        # 情绪统计
        scores = [(i.sentiment_score or 0) for i in items]
        positive = sum(1 for s in scores if s > 0.3)
        negative = sum(1 for s in scores if s < -0.3)
        neutral = total - positive - negative

        # 关联股票统计
        code_counter = Counter()
        with_codes_count = 0
        for item in items:
            rc = item.related_codes
            if rc and rc != "[]":
                with_codes_count += 1
                try:
                    for c in json.loads(rc):
                        code_counter[c] += 1
                except (json.JSONDecodeError, TypeError):
                    pass

        # 热门股票名称
        top_codes = code_counter.most_common(5)
        code_names = {}
        if top_codes:
            from utils.name_resolver import resolve_names
            code_names = resolve_names([c for c, _ in top_codes])

        # 数据源分布
        source_counter = Counter(i.source for i in items)

        # 今日热门事件 — 先按来源拆分，再按股票分组
        from collections import defaultdict
        event_items = [i for i in items if i.event_type and i.sentiment_score and abs(i.sentiment_score) >= 0.3]

        # 按来源拆分：结构化（[规则] 前缀）vs 新闻
        structured_items = [i for i in event_items if (i.nlp_reason or "").startswith("[规则]")]
        news_items = [i for i in event_items if not (i.nlp_reason or "").startswith("[规则]")]

        def _group_by_stock(event_list, top_n=5):
            """按首个关联股票分组，取 Top N"""
            stock_events = defaultdict(list)
            for item in event_list:
                codes = []
                try:
                    codes = json.loads(item.related_codes or "[]")
                except (json.JSONDecodeError, TypeError):
                    pass
                if not codes:
                    continue
                stock_events[codes[0]].append(item)

            ranked = sorted(stock_events.items(),
                key=lambda kv: max(abs(i.sentiment_score) for i in kv[1]), reverse=True)[:top_n]

            groups = []
            for code, evts in ranked:
                evts_sorted = sorted(evts, key=lambda x: abs(x.sentiment_score), reverse=True)
                best_score = evts_sorted[0].sentiment_score
                groups.append({
                    "name": group_names.get(code, code),
                    "code": code,
                    "emoji": "📈" if best_score > 0 else "📉",
                    "score": f"{best_score:+.1f}",
                    "events": [{
                        "title": (e.title or "")[:45],
                        "event_type": e.event_type or "",
                        "reason": (e.nlp_reason or "")[:25],
                        "url": e.url or "",
                    } for e in evts_sorted[:4]],
                })
            return groups

        # 解析股票名称（合并去重）
        all_codes = set()
        for item in event_items:
            try:
                codes = json.loads(item.related_codes or "[]")
                if codes:
                    all_codes.add(codes[0])
            except (json.JSONDecodeError, TypeError):
                pass
        if all_codes:
            from utils.name_resolver import resolve_names as resolve_group_names
            group_names = resolve_group_names(list(all_codes))
        else:
            group_names = {}

        structured_groups = _group_by_stock(structured_items, top_n=5)
        news_groups = _group_by_stock(news_items, top_n=5)

    # Jinja2 模板渲染
    from utils.template_engine import render
    return render("daily_summary.j2",
        date=today.strftime('%Y-%m-%d'),
        total=total,
        with_codes=with_codes_count,
        with_codes_pct=with_codes_count * 100 // max(total, 1),
        positive=positive,
        negative=negative,
        neutral=neutral,
        sources=source_counter.most_common(),
        top_stocks=[(code_names.get(c, c), c, cnt) for c, cnt in top_codes],
        structured_groups=structured_groups,
        news_groups=news_groups,
    )


def send_daily_summary() -> bool:
    """生成并推送每日摘要"""
    content = generate_daily_summary()
    if not content:
        log.info("daily_summary_empty")
        return False

    ok = send_notification(content)
    log.info("daily_summary_sent", success=ok, length=len(content))

    # 记录推送状态
    try:
        from datetime import datetime
        from services.notifier import load_config, save_config
        cfg = load_config()
        cfg["last_summary"] = {
            "time": str(datetime.now().replace(microsecond=0))[:16],  # 推送时间戳（非交易日期）
            "success": ok,
        }
        save_config(cfg)
    except Exception as e:
        log.debug("save_last_summary_failed", error=str(e))

    return ok
