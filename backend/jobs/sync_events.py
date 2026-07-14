"""
结构化事件同步
============
同步最新交易日（或历史范围）的大宗交易/限售解禁/龙虎榜数据，
写入 StockNews 表复用新闻基础设施（事件回测/K 线标记/推送）。

来源: Tushare Pro block_trade / share_float / top_list（需 2000 积分）
"""

import time
import json
import math
import structlog
from typing import Optional

from jobs.sync_base import write_watermark
from utils.trade_date import resolve_end_date

log = structlog.get_logger("sync_events")


def _safe_float(v, default=0.0):
    """安全转 float，NaN/None/空串 → default"""
    if v is None:
        return default
    try:
        val = float(v)
        return default if math.isnan(val) or math.isinf(val) else val
    except (ValueError, TypeError):
        return default


# ── title 前缀（保证 INSERT OR IGNORE 的唯一性）──
_PREFIX_BLOCK = "[大宗交易]"
_PREFIX_FLOAT = "[解禁]"
_PREFIX_TOP = "[龙虎榜]"


def sync_events(
    ts_source,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    force_refill: bool = False,
) -> dict:
    """
    同步结构化事件 → StockNews。

    日常模式：基于 DB 实际最大事件日期自动回补到最新交易日。
    force_refill 模式：按 start_date~end_date 范围拉取。

    关键设计：
    - 以 DB 实际数据为准回补（不信任水位）
    - 只有实际写入数据时才推进水位（0 条 → 水位不动）
    """
    t_start = time.time()
    total = 0

    if force_refill and start_date and end_date:
        s = start_date.replace("-", "")[:8]
        e = end_date.replace("-", "")[:8]
        total = _sync_range(ts_source, s, e)
        wm_date_raw = e
    else:
        target = resolve_end_date(fmt="%Y%m%d")
        # 基于 DB 实际最大事件日期 +1 回补
        db_next = _get_events_db_max_next()
        if db_next and db_next < target:
            log.info("events_backfill", from_date=db_next, to_date=target)
            total = _sync_range(ts_source, db_next, target)
        else:
            total = _sync_single_day(ts_source, target)
        wm_date_raw = target

    duration = round(time.time() - t_start, 1)

    # 只有实际写入数据时才推进水位
    if total > 0:
        wm_date = f"{wm_date_raw[:4]}-{wm_date_raw[4:6]}-{wm_date_raw[6:]}"
        write_watermark("events", "any", wm_date, t_start, "success")
        # 实时推送：对高分事件触发精选推送
        _push_events(wm_date)
        log.info("sync_events_done", rows=total, watermark=wm_date, duration=duration)
    else:
        log.info("sync_events_done", rows=0, watermark="unchanged", duration=duration)

    return {"rows": total}


# ══════════════════ 内部 ══════════════════


def _get_events_db_max_next() -> str | None:
    """读取 StockNews 中事件类型的最大 publish_time +1 天，返回 YYYYMMDD。"""
    from datetime import timedelta
    from core.database import db_session
    from sqlalchemy import text
    try:
        with db_session() as db:
            r = db.execute(text(
                "SELECT MAX(DATE(publish_time)) FROM stock_news "
                "WHERE event_type IN ('大宗交易', '解禁', '龙虎榜')"
            )).scalar()
            if r:
                import pandas as pd
                max_date = pd.to_datetime(str(r))
                return (max_date + timedelta(days=1)).strftime("%Y%m%d")
    except Exception as e:
        log.debug("events_db_max_error", error=str(e))
    return None


def _push_events(pub_date: str):
    """推送高分结构化事件（逻辑与 pipeline._push_top 一致）"""
    try:
        from services.notifier import load_config, save_config, send_notification, is_push_cooling
        from core.database import db_session
        from models.quant_data import StockNews
        from datetime import datetime

        cfg = load_config()
        if not cfg.get("auto_push_enabled", False):
            return
        if is_push_cooling(cfg):
            return

        threshold = cfg.get("push_threshold", 0.5)
        top_n = cfg.get("push_top_n", 5)

        with db_session() as db:
            rows = db.query(StockNews).filter(
                StockNews.event_type.in_(["大宗交易", "解禁", "龙虎榜"]),
                StockNews.publish_time >= pub_date,
            ).all()

            scored = [r for r in rows if abs(r.sentiment_score or 0) >= threshold]
            scored.sort(key=lambda r: abs(r.sentiment_score or 0), reverse=True)
            top = scored[:top_n]
            if not top:
                return

            push_items = []
            for r in top:
                s = r.sentiment_score or 0
                codes = []
                try:
                    codes = json.loads(r.related_codes or "[]")
                except (json.JSONDecodeError, TypeError):
                    log.debug("push_codes_parse_skip", title=r.title)
                push_items.append({
                    "emoji": "📈" if s > 0 else "📉",
                    "label": "利好" if s > 0 else "利空",
                    "score": f"{s:+.1f}",
                    "title": (r.title or "")[:50],
                    "url": r.url or "",
                    "codes": ", ".join(codes[:3]) if codes else "",
                    "event_type": r.event_type or "",
                    "reason": (r.nlp_reason or "")[:30],
                })

        from utils.template_engine import render
        now = str(datetime.now().replace(microsecond=0))[:16]
        content = render("push_top.j2", items=push_items, now=now)
        ok = send_notification(content)
        cfg["last_push"] = {"time": now, "count": len(top), "success": ok, "source": "events"}
        save_config(cfg)
    except Exception as e:
        log.warning("push_events_error", error=str(e))

def _sync_single_day(ts, target_date: str) -> int:
    """拉取单日三类事件"""
    total = 0
    total += _fetch_block_trade(ts, trade_date=target_date)
    total += _fetch_share_float(ts, float_date=target_date)
    total += _fetch_top_list(ts, trade_date=target_date)
    return total


def _sync_range(ts, start: str, end: str) -> int:
    """force_refill 范围拉取"""
    total = 0
    # block_trade / share_float 原生支持 start_date/end_date
    total += _fetch_block_trade(ts, start_date=start, end_date=end)
    total += _fetch_share_float(ts, start_date=start, end_date=end)

    # top_list 只支持 trade_date 单日查询，需按交易日遍历
    trade_dates = _get_trade_dates_in_range(ts, start, end)
    for td in trade_dates:
        total += _fetch_top_list(ts, trade_date=td)
        time.sleep(0.15)  # 与 TUSHARE_FETCH_SLEEP 对齐
    return total


def _get_trade_dates_in_range(ts, start: str, end: str) -> list:
    """获取范围内的交易日列表"""
    try:
        df = ts.pro.trade_cal(
            start_date=start, end_date=end, is_open="1", fields="cal_date"
        )
        if df is not None and not df.empty:
            return sorted(df["cal_date"].astype(str).tolist())
    except Exception as e:
        log.warning("trade_cal_failed", error=str(e))
    return []


# ── 大宗交易 ──

def _fetch_block_trade(ts, trade_date=None, start_date=None, end_date=None) -> int:
    """拉取大宗交易并写入 StockNews"""
    try:
        import data_sources.tushare_source as tm

        @tm.with_tushare_retry(max_retries=2, delay=2.0)
        def _call():
            kwargs = {"fields": "ts_code,trade_date,price,vol,amount,buyer,seller"}
            if trade_date:
                kwargs["trade_date"] = trade_date
            elif start_date and end_date:
                kwargs["start_date"] = start_date
                kwargs["end_date"] = end_date
            return ts.pro.block_trade(**kwargs)

        df = _call()
        if df is None or df.empty:
            return 0

        rows = []
        for _, r in df.iterrows():
            code = str(r.get("ts_code", ""))
            date_raw = str(r.get("trade_date", ""))
            if not code or len(date_raw) < 8:
                continue
            pub_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
            amount = r.get("amount")
            price = r.get("price")
            vol = r.get("vol")

            # 赋分：基于成交金额（万元）和方向
            amount_val = _safe_float(amount)
            score = 0.2  # 默认轻微利好（有人承接）
            reason_parts = []
            if amount_val > 0:
                reason_parts.append(f"成交{amount_val:.0f}万元")
            if _safe_float(price) > 0:
                reason_parts.append(f"价格{_safe_float(price):.2f}元")
            if _safe_float(vol) > 0:
                reason_parts.append(f"{_safe_float(vol):.0f}万股")

            # 大宗交易默认折价利空（无法精确计算折价率，需收盘价对比，保守赋分）
            if amount_val >= 5000:
                score = -0.5  # 大额交易偏利空
            elif amount_val >= 1000:
                score = -0.3

            title = f"{_PREFIX_BLOCK} {code} {pub_date} {' '.join(reason_parts)}"
            rows.append({
                "title": title[:200],
                "source": "tushare",
                "pub_date": pub_date,
                "related_codes": json.dumps([code]),
                "sentiment_score": score,
                "event_type": "大宗交易",
                "nlp_reason": f"[规则] {' '.join(reason_parts)}",
                "code": code,
            })

        return _upsert_news(rows)

    except Exception as e:
        log.warning("block_trade_failed", error=str(e))
        return 0


# ── 限售解禁 ──

def _fetch_share_float(ts, float_date=None, start_date=None, end_date=None) -> int:
    """拉取限售解禁并写入 StockNews"""
    try:
        import data_sources.tushare_source as tm

        @tm.with_tushare_retry(max_retries=2, delay=2.0)
        def _call():
            kwargs = {"fields": "ts_code,float_date,float_share,float_ratio,holder_name"}
            if float_date:
                kwargs["float_date"] = float_date
            elif start_date and end_date:
                kwargs["start_date"] = start_date
                kwargs["end_date"] = end_date
            return ts.pro.share_float(**kwargs)

        df = _call()
        if df is None or df.empty:
            return 0

        rows = []
        for _, r in df.iterrows():
            code = str(r.get("ts_code", ""))
            date_raw = str(r.get("float_date", ""))
            if not code or len(date_raw) < 8:
                continue
            pub_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
            float_share = r.get("float_share")  # 万股
            float_ratio = r.get("float_ratio")  # %
            holder_raw = r.get("holder_name")
            holder = str(holder_raw)[:20] if holder_raw is not None and str(holder_raw) != "nan" else ""

            reason_parts = []
            if _safe_float(float_share) > 0:
                reason_parts.append(f"解禁{_safe_float(float_share):.0f}万股")
            if _safe_float(float_ratio) > 0:
                reason_parts.append(f"占比{_safe_float(float_ratio):.1f}%")
            if holder:
                reason_parts.append(holder[:20])

            # 赋分：解禁比例越高越利空
            ratio = _safe_float(float_ratio)
            if ratio > 10:
                score = -0.7
            elif ratio > 5:
                score = -0.5
            else:
                score = -0.3

            title = f"{_PREFIX_FLOAT} {code} {pub_date} {' '.join(reason_parts)}"
            rows.append({
                "title": title[:200],
                "source": "tushare",
                "pub_date": pub_date,
                "related_codes": json.dumps([code]),
                "sentiment_score": score,
                "event_type": "解禁",
                "nlp_reason": f"[规则] {' '.join(reason_parts)}",
                "code": code,
            })

        return _upsert_news(rows)

    except Exception as e:
        log.warning("share_float_failed", error=str(e))
        return 0


# ── 龙虎榜 ──

def _fetch_top_list(ts, trade_date=None) -> int:
    """拉取龙虎榜并写入 StockNews"""
    try:
        import data_sources.tushare_source as tm

        @tm.with_tushare_retry(max_retries=2, delay=2.0)
        def _call():
            return ts.pro.top_list(
                trade_date=trade_date,
                fields="ts_code,trade_date,name,close,pct_change,net_amount,reason"
            )

        df = _call()
        if df is None or df.empty:
            return 0

        rows = []
        for _, r in df.iterrows():
            code = str(r.get("ts_code", ""))
            date_raw = str(r.get("trade_date", ""))
            if not code or len(date_raw) < 8:
                continue
            pub_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
            net_amount = r.get("net_amount")  # 万元
            reason_raw = r.get("reason")
            name_raw = r.get("name")
            reason = str(reason_raw)[:30] if reason_raw is not None and str(reason_raw) != "nan" else ""
            name = str(name_raw)[:10] if name_raw is not None and str(name_raw) != "nan" else ""

            net_val = _safe_float(net_amount)
            reason_parts = []
            if name:
                reason_parts.append(name)
            if reason:
                reason_parts.append(reason)
            if net_val != 0:
                reason_parts.append(f"净额{net_val:.0f}万")

            # 赋分：净买入利好，净卖出利空
            if net_val > 0:
                score = 0.6
            elif net_val < 0:
                score = -0.6
            else:
                score = 0.3  # 上榜本身有关注度

            title = f"{_PREFIX_TOP} {code} {pub_date} {' '.join(reason_parts)}"
            rows.append({
                "title": title[:200],
                "source": "tushare",
                "pub_date": pub_date,
                "related_codes": json.dumps([code]),
                "sentiment_score": score,
                "event_type": "龙虎榜",
                "nlp_reason": f"[规则] {' '.join(reason_parts)}",
                "code": code,
            })

        return _upsert_news(rows)

    except Exception as e:
        log.warning("top_list_failed", error=str(e))
        return 0


# ── 写入 StockNews ──

def _upsert_news(rows: list) -> int:
    """批量写入 StockNews，title 唯一索引自动去重"""
    if not rows:
        return 0

    from services.news.storage import upsert_batch
    from services.news.sentiment import score_to_label

    news_dicts = []
    for r in rows:
        score = r["sentiment_score"]
        news_dicts.append({
            "title": r["title"],
            "source": r["source"],
            "url": "",
            "publish_time": r["pub_date"],
            "related_codes": r["related_codes"],
            "sentiment_score": score,
            "sentiment_label": score_to_label(score),
            "event_type": r["event_type"],
            "nlp_reason": r["nlp_reason"],
            "code": r.get("code"),
        })

    inserted = upsert_batch(news_dicts)
    log.info("events_upserted", inserted=inserted, total=len(news_dicts))
    return inserted
