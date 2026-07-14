"""
新闻批量入库模块

两阶段策略：
1. 批量 INSERT OR IGNORE — 单条 SQL，O(1) 次 DB 交互
2. 需要合并的记录 — 按 title 集合查出并更新
"""
import json
import structlog
from datetime import datetime
from typing import List

log = structlog.get_logger("news_storage")


def upsert_batch(news_items: List[dict]) -> int:
    """
    批量写入新闻，title 唯一索引去重。
    冲突时合并 related_codes（取并集）并补充空的 publish_time。

    Returns:
        新插入的条数
    """
    if not news_items:
        return 0

    from core.database import db_session
    from models.quant_data import StockNews
    from sqlalchemy import text

    inserted = 0

    with db_session() as db:
        # ── 阶段 1：批量 INSERT OR IGNORE ──
        # SQLite 原生语法，跳过已存在的标题
        now = datetime.now()
        for item in news_items:
            stmt = text("""
                INSERT OR IGNORE INTO stock_news
                (title, summary, source, url, publish_time, market_type, related_codes, sentiment_score, sentiment_label, event_type, nlp_reason, code, created_at)
                VALUES (:title, :summary, :source, :url, :pub_time, :market_type, :related_codes, :score, :label, :event_type, :nlp_reason, :code, :created_at)
            """)
            result = db.execute(stmt, {
                "title": item["title"],
                "summary": item.get("summary", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
                "pub_time": item.get("publish_time"),
                "market_type": item.get("market_type", "A股"),
                "related_codes": item.get("related_codes", "[]"),
                "score": item.get("sentiment_score", 0),
                "label": item.get("sentiment_label", "中性"),
                "event_type": item.get("event_type"),
                "nlp_reason": item.get("nlp_reason"),
                "code": item.get("code"),
                "created_at": now,
            })
            inserted += result.rowcount  # INSERT OR IGNORE: 1=插入, 0=跳过

        # ── 阶段 2：合并已存在记录的 related_codes + publish_time ──
        all_titles = [item["title"] for item in news_items]
        title_to_item = {item["title"]: item for item in news_items}

        # 只查需要合并的（已存在的且有 related_codes 或 publish_time 的）
        existing_rows = db.query(StockNews).filter(
            StockNews.title.in_(all_titles)
        ).all()

        for row in existing_rows:
            new_item = title_to_item.get(row.title)
            if not new_item:
                continue
            # 合并 related_codes
            _merge_codes(row, new_item)
            # 补充 publish_time
            if not row.publish_time and new_item.get("publish_time"):
                row.publish_time = new_item["publish_time"]

    log.info("news_upsert_done", total=len(news_items), inserted=inserted)
    return inserted


def _merge_codes(existing, new_item: dict):
    """合并新旧 related_codes（取并集）"""
    try:
        new_codes = json.loads(new_item.get("related_codes", "[]"))
        if not new_codes:
            return
        old_codes = json.loads(existing.related_codes or "[]")
        merged = list(set(old_codes + new_codes))
        if len(merged) > len(old_codes):
            existing.related_codes = json.dumps(merged)
    except Exception as e:
        log.debug("merge_codes_failed", error=str(e))


def cleanup_old_news(days: int = 90) -> int:
    """清理 N 天前的旧新闻（按 created_at）"""
    from core.database import db_session
    from models.quant_data import StockNews
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=days)
    with db_session() as db:
        from sqlalchemy import or_
        count = db.query(StockNews).filter(
            StockNews.created_at < cutoff,
            # 结构化事件（规则注入）永久保留，仅清理普通新闻
            or_(StockNews.nlp_reason.is_(None), ~StockNews.nlp_reason.like("[规则]%")),
        ).delete(synchronize_session=False)

    if count > 0:
        log.info("news_cleanup", deleted=count, older_than=f"{days}d")
    return count
