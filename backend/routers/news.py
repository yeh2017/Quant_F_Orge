"""
新闻 API 路由
GET  /api/news               — 新闻列表
POST /api/news/refresh       — 手动触发抓取
POST /api/news/search        — 全网搜索
GET  /api/news/event-stats   — 事件回测统计
"""
import threading
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from typing import List
from sqlalchemy.orm import Session
from core.database import get_db
from models.quant_data import StockNews
from datetime import datetime, timedelta
from sqlalchemy import func
import json
from services.news.sentiment import STRONG_THRESHOLD
from services.news.sentiment_llm import _load_providers
from utils.template_engine import clean_reason as _clean_reason


def _safe_loads_codes(raw: str) -> list:
    """安全解析 related_codes JSON，脏数据时返回空列表"""
    try:
        return json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []

router = APIRouter(prefix="/news", tags=["News"])

# ── Pipeline 单例 ──
from services.news.pipeline import get_pipeline
_pipeline = get_pipeline()


@router.get("")
async def get_news(
    market: str = Query("all", description="A股/全球/all"),
    code: str = Query(None, description="按关联股票代码过滤"),
    days: int = Query(3, ge=1, le=365, description="最近几天"),
    search: str = Query(None, description="搜索关键词（不受天数限制）"),
    limit: int = Query(30, ge=1, le=1000, description="最大条数"),
    include_events: bool = Query(False, description="是否包含结构化事件（K线可视化用）"),
    db: Session = Depends(get_db),
):
    """获取新闻列表"""
    q = db.query(StockNews)
    effective_time = func.coalesce(StockNews.publish_time, StockNews.created_at)

    # 默认排除结构化事件（大宗/解禁/龙虎榜），K线可视化需要时传 include_events=true
    if not include_events:
        from sqlalchemy import or_ as _or
        q = q.filter(_or(StockNews.nlp_reason.is_(None), ~StockNews.nlp_reason.like("[规则]%")))

    if search:
        # 搜索模式：全字段匹配，不受天数限制
        kw = f"%{search}%"
        from sqlalchemy import or_

        # ── 构建匹配条件 ──
        resolved_codes = _pipeline._resolver.search_codes(search.strip())
        code_filters = [StockNews.related_codes.ilike(f"%{c}%") for c in resolved_codes]

        filters = [
            StockNews.title.ilike(kw),
            StockNews.source.ilike(kw),
            StockNews.related_codes.ilike(kw),
        ] + code_filters
        q = q.filter(or_(*filters))
    else:
        # 默认模式：按天数过滤
        since = datetime.now() - timedelta(days=days)
        q = q.filter(effective_time >= since)

    if market != "all":
        q = q.filter(StockNews.market_type == market)
    if code:
        q = q.filter(StockNews.related_codes.contains(code))

    total = q.count()
    items = q.order_by(effective_time.desc()).limit(limit).all()

    # 收集关联代码，查名称和涨跌幅
    all_codes = set()
    for n in items:
        for c in _safe_loads_codes(n.related_codes):
            all_codes.add(c)

    code_name_map = {}
    code_change_map = {}
    if all_codes:
        from utils.name_resolver import resolve_names
        from models.quant_data import StockDailyBar
        code_name_map = resolve_names(list(all_codes))

        subq = db.query(
            StockDailyBar.code,
            func.max(StockDailyBar.trade_date).label("max_date")
        ).filter(StockDailyBar.code.in_(all_codes)).group_by(StockDailyBar.code).subquery()

        rows = db.query(StockDailyBar.code, StockDailyBar.pct_chg).join(
            subq, (StockDailyBar.code == subq.c.code) & (StockDailyBar.trade_date == subq.c.max_date)
        ).all()
        code_change_map = {r.code: round(float(r.pct_chg or 0), 2) for r in rows}

    return {
        "items": [
            {
                "id": n.id,
                "title": n.title,
                "summary": n.summary,
                "source": n.source,
                "url": n.url,
                "publish_time": (n.publish_time or n.created_at).isoformat() if (n.publish_time or n.created_at) else None,
                "market_type": n.market_type,
                "related_codes": _safe_loads_codes(n.related_codes),
                "sentiment_score": n.sentiment_score,
                "sentiment_label": n.sentiment_label,
                "event_type": n.event_type,
                "nlp_reason": _clean_reason(n.nlp_reason),
            }
            for n in items
        ],
        "total": total,
        "code_name_map": code_name_map,
        "code_change_map": code_change_map,
    }


class RefreshRequest(BaseModel):
    codes: List[str] = Field(default=[], description="股票代码列表（来自自选池）")


@router.post("/refresh")
def refresh_news(req: RefreshRequest):
    """手动触发新闻抓取 — 同步返回 Tushare 结果，AkShare 后台运行"""
    from core.database import db_session
    from models.quant_data import StockBasicInfo

    if req.codes:
        codes = req.codes
        with db_session() as db:
            from utils.name_resolver import resolve_names
            stock_names = resolve_names(codes)
    else:
        with db_session() as db:
            rows = db.query(StockBasicInfo.code, StockBasicInfo.name).limit(30).all()
            codes = [r.code for r in rows]
            stock_names = {r.code: r.name for r in rows if r.name}

    if not codes:
        return {"status": "ok", "count": 0, "message": "无股票可抓取"}

    # 同步执行 Tushare（~2s），直接返回结果
    tushare_count = _pipeline.run_interactive(codes, stock_names)

    # AkShare 在后台线程 fire-and-forget（~30s），完成后 WS 通知
    threading.Thread(
        target=_pipeline.run_batch, args=(codes, stock_names),
        daemon=True,
    ).start()

    return {
        "status": "ok",
        "count": tushare_count,
        "llm_enabled": bool(_load_providers()),
        "message": f"新增 {tushare_count} 条宏观新闻",
    }

_backfill_lock = threading.Lock()

@router.post("/nlp-backfill")
def nlp_backfill(
    limit: int = Query(50, ge=1, le=200, description="本次处理条数"),
):
    """对历史存量新闻补跑 LLM 评分（event_type 为空的记录）"""
    from core.database import db_session
    from services.news.pipeline import enrich_news_llm

    if not _backfill_lock.acquire(blocking=False):
        return {"status": "busy", "message": "上一轮补跑尚未完成，请稍后重试"}

    try:
        with db_session() as db:
            rows = (
                db.query(StockNews)
                .filter(StockNews.event_type.is_(None))
                .order_by(StockNews.id.desc())
                .limit(limit)
                .all()
            )
            if not rows:
                _backfill_lock.release()
                return {"status": "ok", "updated": 0, "remaining": 0, "message": "无需补跑"}

            remaining = db.query(func.count(StockNews.id)).filter(
                StockNews.event_type.is_(None)
            ).scalar() - len(rows)

            llm_items = []
            for row in rows:
                codes = _safe_loads_codes(row.related_codes)
                if not codes:
                    continue
                llm_items.append({"id": row.id, "title": row.title, "codes": codes})

        if not llm_items:
            _backfill_lock.release()
            return {
                "status": "ok", "processing": 0,
                "remaining": max(0, remaining),
                "message": f"剩余 {max(0, remaining)} 条均无关联股票，无需评分",
            }

        def _run_and_release():
            try:
                enrich_news_llm(llm_items)
            finally:
                _backfill_lock.release()

        threading.Thread(target=_run_and_release, daemon=True).start()

        return {
            "status": "ok",
            "processing": len(llm_items),
            "remaining": max(0, remaining),
            "message": f"正在后台补跑 {len(llm_items)} 条，剩余约 {max(0, remaining)} 条",
        }
    except Exception:
        _backfill_lock.release()
        raise

class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=100, description="搜索关键词")


@router.post("/search")
def search_news(req: SearchRequest):
    """用搜索引擎搜索全网新闻并入库"""
    keyword = req.keyword.strip()
    try:
        inserted, items = _pipeline.search(keyword)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "count": len(items),
        "inserted": inserted,
        "llm_enabled": bool(_load_providers()),
        "items": [
            {
                "title": n["title"],
                "summary": n["summary"],
                "url": n.get("url", ""),
                "related_codes": _safe_loads_codes(n.get("related_codes", "[]")),
                "sentiment_score": n.get("sentiment_score"),
                "sentiment_label": n.get("sentiment_label"),
            }
            for n in items
        ],
    }





@router.post("/sentiment/batch")
async def batch_sentiment(
    payload: dict,
    db: Session = Depends(get_db),
):
    """批量查询多只股票的近期新闻情绪（给 ResultTable 舆情列用）"""
    codes = payload.get("codes", [])[:50]
    days = payload.get("days", 7)
    if not codes:
        return {}

    since = datetime.now() - timedelta(days=days)
    effective_time = func.coalesce(StockNews.publish_time, StockNews.created_at)
    # SQL 层按 codes 过滤，避免加载全部新闻到内存
    from sqlalchemy import or_
    bare_codes = [c.split(".")[0] if "." in c else c for c in codes]
    code_filters = [StockNews.related_codes.contains(bc) for bc in bare_codes]
    items = (
        db.query(StockNews)
        .filter(effective_time >= since)
        .filter(or_(*code_filters))
        .filter(or_(StockNews.nlp_reason.is_(None), ~StockNews.nlp_reason.like("[规则]%")))
        .order_by(effective_time.desc())
        .all()
    )

    result = {}
    for code in codes:
        # related_codes 是 JSON 字符串如 '["600519.SH"]'，用 contains 模糊匹配
        bare = code.split(".")[0] if "." in code else code
        matched = [n for n in items if bare in (n.related_codes or "")]
        if not matched:
            continue
        scores = [n.sentiment_score for n in matched if n.sentiment_score is not None]
        avg = round(sum(scores) / len(scores), 2) if scores else 0
        # 取最近一条有 event_type 的强事件
        event = None
        for n in matched:
            if n.event_type and n.event_type not in ("其他", ""):
                event = n.event_type
                break
        result[code] = {
            "count": len(matched),
            "avg": avg,
            "label": "利好" if avg > STRONG_THRESHOLD else "利空" if avg < -STRONG_THRESHOLD else "中性",
            "event": event,
        }
    return result

@router.get("/auto-config")
async def get_auto_config():
    """获取新闻自动抓取配置（含倒计时 + 管道统计）"""
    import main as _m

    # 管道统计（轻量查询）
    pipeline_stats = {}
    try:
        from core.database import db_session
        from sqlalchemy import text as _text
        from services.news.sentiment_llm import _daily
        with db_session() as db:
            row = db.execute(_text(
                "SELECT "
                "  COUNT(*) AS total, "
                "  SUM(CASE WHEN related_codes IS NOT NULL AND related_codes != '[]' THEN 1 ELSE 0 END) AS has_codes, "
                "  SUM(CASE WHEN event_type IS NOT NULL AND event_type != '' "
                "    AND related_codes IS NOT NULL AND related_codes != '[]' "
                "    AND (nlp_reason IS NULL OR nlp_reason NOT LIKE '[规则]%') THEN 1 ELSE 0 END) AS enriched, "
                "  SUM(CASE WHEN event_type IS NOT NULL AND event_type != '' THEN 1 ELSE 0 END) AS events "
                "FROM stock_news"
            )).fetchone()
            stats = _daily.stats
            pipeline_stats = {
                "news_total": row[0] or 0,
                "llm_target": row[1] or 0,      # 有关联股票（可进LLM）
                "llm_enriched": row[2] or 0,     # LLM已标注
                "event_total": row[3] or 0,      # 事件总数
                "llm_calls_today": stats.get("calls", 0),
                "llm_cost_today": stats.get("cost_today", 0),
            }
    except Exception as e:
        import structlog; structlog.get_logger("news_router").debug("pipeline_stats_query_failed", error=str(e))

    return {
        "enabled": _m._news_auto_enabled,
        "interval_hours": _m._news_auto_fetch_hours,
        "next_fetch_time": _m._next_fetch_time.isoformat() if _m._next_fetch_time else None,
        "last_fetch_time": _m._last_fetch_time.isoformat() if _m._last_fetch_time else None,
        "pipeline_stats": pipeline_stats,
    }


class AutoConfigRequest(BaseModel):
    enabled: bool = Field(True, description="是否启用自动抓取")
    interval_hours: int = Field(None, ge=1, le=24, description="间隔小时数(1-24)")


@router.post("/auto-config")
async def set_auto_config(req: AutoConfigRequest):
    """动态调整新闻自动抓取配置（开启时立即执行一次）"""
    import main as _m
    was_enabled = _m._news_auto_enabled
    _m._news_auto_enabled = req.enabled
    if req.interval_hours is not None:
        _m._news_auto_fetch_hours = req.interval_hours

    if req.enabled:
        # 开启：同步赋值 _next_fetch_time，确保响应包含有效倒计时
        _m._next_fetch_time = datetime.now() + timedelta(hours=_m._news_auto_fetch_hours)
        if not was_enabled:
            _m._fetch_now_flag = True
    else:
        # 关闭：同步清除，前端立即停止倒计时
        _m._next_fetch_time = None

    _m.save_news_config(_m._news_auto_enabled, _m._news_auto_fetch_hours)
    return {
        "enabled": _m._news_auto_enabled,
        "interval_hours": _m._news_auto_fetch_hours,
        "next_fetch_time": _m._next_fetch_time.isoformat() if _m._next_fetch_time else None,
    }


@router.post("/send-summary")
async def send_summary():
    """手动触发每日摘要推送"""
    from jobs.daily_summary import send_daily_summary
    ok = send_daily_summary()
    return {"success": ok}





@router.post("/notify-test")
async def test_notify(channel: str = ""):
    """逐渠道测试并返回详细结果（支持指定单渠道: ?channel=pushplus）"""
    from services.notifier import load_config, _CHANNEL_SENDERS, CHANNEL_LABELS

    cfg = load_config()
    results = []
    any_ok = False

    channels = [channel] if channel else list(_CHANNEL_SENDERS.keys())

    for ch in channels:
        sender = _CHANNEL_SENDERS.get(ch)
        if not sender:
            continue
        if not cfg.get(ch, {}).get("enabled"):
            continue
        label = CHANNEL_LABELS.get(ch, ch)
        try:
            ok = sender(f"🔔 测试推送 — {label} 配置成功！", cfg)
            results.append(f"{label}: {'✅ 成功' if ok else '❌ 失败'}")
            any_ok = any_ok or ok
        except Exception as e:
            results.append(f"{label}: ❌ 异常（{e}）")

    if not results:
        return {"success": False, "detail": "未启用任何推送渠道"}

    return {"success": any_ok, "detail": "；".join(results)}


# ── 事件回测统计 ──

@router.get("/event-stats")
def event_stats(
    event_type: str = Query(None, description="筛选事件类型（None=全部）"),
    min_score: float = Query(0.3, description="最低 |sentiment_score| 阈值"),
):
    """按 event_type 统计事件发生后 T+N 天的收益表现"""
    from services.news.event_backtest import analyze_events
    return analyze_events(event_type=event_type, min_score=min_score)

