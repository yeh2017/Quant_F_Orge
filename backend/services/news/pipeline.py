"""
新闻管道调度中心

唯一入口：所有新闻抓取/搜索都经过此 Pipeline。
职责：
1. 实例化 Fetcher → 2. 抓取 → 3. 代码关联 → 4. 情绪评分 → 5. 去重入库 → 6. 广播通知
"""
import json
import random
import threading
import structlog
from typing import List, Dict, Optional

from services.news.code_resolver import CodeResolver
from services.news.sentiment import score_sentiment, score_to_label
from services.news.sentiment_llm import score_batch_llm
from services.news.storage import upsert_batch, cleanup_old_news
from services.news.fetchers.base import BaseFetcher, RawNewsItem

log = structlog.get_logger("news_pipeline")

# 全局并发锁 — 同一时间只能有一个批处理任务
_pipeline_lock = threading.Lock()

# LLM 评分互斥锁 — 防止 run_interactive + run_batch 竞态重复调用
_llm_lock = threading.Lock()

# 单例 — 整个进程复用同一个 Pipeline（共享 Fetcher + CodeResolver 缓存）
_singleton: "NewsPipeline | None" = None


def get_pipeline() -> "NewsPipeline":
    """获取全局唯一的 NewsPipeline 实例"""
    global _singleton
    if _singleton is None:
        _singleton = NewsPipeline()
    return _singleton


class NewsPipeline:
    """新闻抓取管道"""

    def __init__(self):
        self._resolver = CodeResolver()
        self._fetchers = self._init_fetchers()

    def _init_fetchers(self) -> List[BaseFetcher]:
        """根据可用性自动发现 Fetcher"""
        fetchers = []

        from services.news.fetchers.tushare import TushareFetcher
        fetchers.append(TushareFetcher())

        from services.news.fetchers.akshare import AkShareFetcher
        fetchers.append(AkShareFetcher())

        from services.news.fetchers.tavily import TavilyFetcher
        tavily = TavilyFetcher()
        if tavily.available:
            fetchers.append(tavily)

        log.info("pipeline_init", fetchers=[f.source_name for f in fetchers])
        return fetchers

    def run_interactive(self, codes: List[str], stock_names: Optional[Dict[str, str]] = None) -> int:
        """
        交互模式 — 只跑 Tushare（~2s），同步返回。
        给刷新按钮用，不需要锁（Tushare 是无状态 API 调用）。
        """
        names = stock_names or {}
        if len(names) < 100:
            names = self._load_all_names()

        tushare_items = self._fetch_by_source("tushare", codes, names)
        if not tushare_items:
            return 0

        news_dicts = self._process(tushare_items)
        inserted = upsert_batch(news_dicts)
        log.info("interactive_done", source="tushare", total=len(tushare_items), inserted=inserted)
        self._post_ingest(news_dicts, inserted, broadcast=False)
        return inserted

    def run_batch(self, codes: List[str], stock_names: Optional[Dict[str, str]] = None) -> int:
        """
        批处理模式 — 只跑 AkShare（~30s），后台线程运行。
        完成后 WS 广播通知前端。
        """
        if not _pipeline_lock.acquire(blocking=False):
            log.warning("batch_skipped", reason="another batch is running")
            return 0

        try:
            names = stock_names or {}
            if len(names) < 100:
                names = self._load_all_names()

            ak_codes = self._pick_ak_codes(codes, names)
            raw_items = self._fetch_by_source("akshare", ak_codes, names)
            if not raw_items:
                self._broadcast(0)
                return 0

            news_dicts = self._process(raw_items)
            inserted = upsert_batch(news_dicts)
            log.info("batch_done", source="akshare", total=len(raw_items), inserted=inserted)
            self._post_ingest(news_dicts, inserted)
            return inserted
        finally:
            _pipeline_lock.release()

    def run(self, codes: List[str], stock_names: Optional[Dict[str, str]] = None) -> int:
        """
        完整流程 — Tushare + AkShare，给定时任务用。
        """
        if not _pipeline_lock.acquire(blocking=False):
            log.warning("pipeline_skipped", reason="another task is running")
            return 0

        try:
            names = stock_names or {}
            if len(names) < 100:
                names = self._load_all_names()

            raw_items: List[RawNewsItem] = []

            tushare_items = self._fetch_by_source("tushare", codes, names)
            raw_items.extend(tushare_items)

            ak_codes = self._pick_ak_codes(codes, names)
            raw_items.extend(self._fetch_by_source("akshare", ak_codes, names))

            if not tushare_items:
                log.info("tavily_fallback", reason="tushare returned empty")
                raw_items.extend(self._fetch_by_source("tavily", codes, names))

            news_dicts = self._process(raw_items)
            inserted = upsert_batch(news_dicts)
            log.info("pipeline_done", total=len(raw_items), inserted=inserted)
            self._post_ingest(news_dicts, inserted)
            return inserted

        finally:
            _pipeline_lock.release()

    def search(self, keyword: str) -> tuple[int, List[dict]]:
        """
        用户主动搜索 — 只走搜索引擎类 Fetcher（Tavily）。
        不需要 pipeline_lock：和 run() 操作不同数据源，互不干扰。

        Returns:
            (新增条数, 搜索结果列表)
        """
        raw_items: List[RawNewsItem] = []
        for f in self._fetchers:
            results = f.search(keyword)
            if results:
                raw_items.extend(results)

        if not raw_items:
            return 0, []

        news_dicts = self._process(raw_items, force_code=keyword)
        inserted = upsert_batch(news_dicts)
        log.info("search_done", keyword=keyword, total=len(raw_items), inserted=inserted)
        self._post_ingest(news_dicts, inserted, broadcast=False)
        return inserted, news_dicts

    # ── 内部方法 ──

    def _fetch_by_source(self, source: str, codes, names) -> List[RawNewsItem]:
        for f in self._fetchers:
            if f.source_name == source:
                return f.fetch(codes, names)
        return []

    def _process(self, raw_items: List[RawNewsItem], *, force_code: Optional[str] = None) -> List[dict]:
        """统一处理：代码关联 + 情绪评分 + 内存去重 → dict 列表"""
        seen_titles = set()
        results = []

        for item in raw_items:
            if item.title in seen_titles:
                continue
            seen_titles.add(item.title)

            # 统一乱码过滤（覆盖所有来源）
            from services.news.fetchers.base import is_garbled
            if is_garbled(item.title):
                log.debug("garbled_skip", source=item.source, title=item.title[:30])
                continue

            # 统一代码关联
            text_for_resolve = item.title
            fc = force_code or (item.hint_code.split(".")[0] if "." in item.hint_code else item.hint_code) or None
            related = self._resolver.resolve(text_for_resolve, force_code=fc)

            # hint_code 确保在列表中（AkShare 按个股查询）
            if item.hint_code:
                ts = self._resolver.to_ts_code(item.hint_code.split(".")[0] if "." in item.hint_code else item.hint_code)
                if ts and ts not in related:
                    related.append(ts)

            # 统一情绪评分
            score_text = item.raw_text or item.title
            score = score_sentiment(score_text)

            results.append({
                "title": item.title,
                "summary": item.summary,
                "source": item.source,
                "url": item.url,
                "publish_time": item.publish_time,
                "market_type": item.market_type,
                "related_codes": json.dumps(related),
                "sentiment_score": score,
                "sentiment_label": score_to_label(score),
            })

        return results

    def _pick_ak_codes(self, user_codes: List[str], all_names: Dict[str, str]) -> List[str]:
        """AkShare 抓取：自选股优先，剩余名额随机填充（总量 30 只）"""
        priority = [c for c in user_codes if c in all_names][:30]
        remaining = 30 - len(priority)
        if remaining > 0:
            exclude = set(priority)
            pool = [c for c in all_names if c not in exclude]
            priority += random.sample(pool, min(remaining, len(pool)))
        return priority

    def _load_all_names(self) -> Dict[str, str]:
        from core.database import db_session
        from models.quant_data import StockBasicInfo
        with db_session() as db:
            rows = db.query(StockBasicInfo.code, StockBasicInfo.name).filter(
                StockBasicInfo.name.isnot(None)
            ).all()
            return {r.code: r.name for r in rows}

    def _post_ingest(self, news_dicts: List[dict], inserted: int = 0, *, broadcast: bool = True):
        """统一后处理：清理过期 → 广播前端 → 推送（读 DB）→ LLM 异步 enrich"""
        from settings import NEWS_RETAIN_DAYS
        cleanup_old_news(days=NEWS_RETAIN_DAYS)

        if broadcast:
            self._broadcast(inserted)

        # 推送：从 DB 读取（包含历史 LLM 结果），不依赖当前 LLM
        if news_dicts:
            try:
                from core.database import db_session
                from models.quant_data import StockNews
                titles = [d["title"] for d in news_dicts]
                with db_session() as db:
                    rows = db.query(StockNews).filter(StockNews.title.in_(titles)).all()
                    enriched = [{
                        "title": r.title,
                        "url": r.url or "",
                        "sentiment_score": r.sentiment_score or 0,
                        "related_codes": r.related_codes or "[]",
                        "event_type": r.event_type or "",
                        "nlp_reason": r.nlp_reason or "",
                    } for r in rows]
                self._push_top(enriched)
            except Exception as e:
                log.warning("push_from_db_error", error=str(e))

        # LLM：独立后台任务，仅负责 enrich DB（供下次推送和前端展示）
        threading.Thread(
            target=self._enrich_with_llm,
            args=(news_dicts,),
            daemon=True,
        ).start()

    def _broadcast(self, count: int):
        try:
            from routers.ws import manager
            manager.broadcast_threadsafe({
                "type": "news_update",
                "count": count,
            })
        except Exception as e:
            log.debug("broadcast_skipped", error=str(e))

    def _push_top(self, items: List[dict]):
        """推送情绪分最强的 Top N（参数从配置读取）"""
        try:
            from services.notifier import load_config, save_config, send_notification, is_push_cooling
            from datetime import datetime
            cfg = load_config()
            if not cfg.get("auto_push_enabled", False):
                return
            if is_push_cooling(cfg):
                return
            top_n = cfg.get("push_top_n", 5)
            threshold = cfg.get("push_threshold", 0.5)
            scored = [i for i in items if abs(i.get("sentiment_score", 0)) >= threshold]
            scored.sort(key=lambda x: abs(x.get("sentiment_score", 0)), reverse=True)
            top = scored[:top_n]
            now = str(datetime.now().replace(microsecond=0))[:16]
            if not top:
                cfg["last_push"] = {"time": now, "count": 0, "success": True, "source": "news", "msg": "无匹配新闻"}
                save_config(cfg)
                return

            # 准备模板数据
            push_items = []
            for item in top:
                s = item.get("sentiment_score", 0)
                codes = item.get("related_codes") or "[]"
                if isinstance(codes, str):
                    try:
                        codes = json.loads(codes)
                    except Exception:
                        codes = []
                push_items.append({
                    "emoji": "📈" if s > 0 else "📉",
                    "label": "利好" if s > 0 else "利空",
                    "score": f"{s:+.1f}",
                    "title": item["title"][:50],
                    "url": item.get("url", ""),
                    "codes": ", ".join(codes[:3]) if codes else "",
                    "event_type": item.get("event_type", ""),
                    "reason": (item.get("nlp_reason") or "")[:30],
                })

            from utils.template_engine import render
            content = render("push_top.j2", items=push_items, now=now)
            ok = send_notification(content)
            cfg["last_push"] = {"time": now, "count": len(top), "success": ok, "source": "news"}
            save_config(cfg)
        except Exception as e:
            log.warning("push_top_error", error=str(e))

    def _enrich_with_llm(self, news_dicts: List[dict]):
        """异步调 LLM 增强评分，更新 DB 中的 score/label/event_type/nlp_reason"""
        if not news_dicts:
            return
        with _llm_lock:  # blocking — 等前一批完成再处理，不丢弃
            self._enrich_with_llm_locked(news_dicts)

    def _enrich_with_llm_locked(self, news_dicts: List[dict]):
        """实际 LLM 评分逻辑（已持锁）"""
        if not news_dicts:
            return
        try:
            from core.database import db_session
            from models.quant_data import StockNews

            titles = [d["title"] for d in news_dicts]
            with db_session() as db:
                rows = db.query(StockNews).filter(StockNews.title.in_(titles)).all()
                if not rows:
                    return

                llm_items = []
                for row in rows:
                    if row.nlp_reason:
                        continue
                    codes = json.loads(str(row.related_codes or "[]"))
                    if not codes:
                        continue
                    llm_items.append({
                        "id": row.id,
                        "title": row.title,
                        "codes": codes,
                    })

            enrich_news_llm(llm_items)
        except Exception as e:
            log.warning("llm_enrich_failed", error=str(e))


def enrich_news_llm(llm_items: List[dict]) -> int:
    """
    公共 LLM 评分入口：调 score_batch_llm 并写回 DB。

    pipeline._enrich_with_llm() 和 nlp-backfill 共用此函数，
    避免两套代码做同一件事。

    Args:
        llm_items: [{"id": int, "title": str, "codes": list}]
    Returns:
        实际更新的记录数
    """
    if not llm_items:
        return 0
    try:
        from core.database import db_session
        from models.quant_data import StockNews

        results = score_batch_llm(llm_items)
        if not results:
            return 0

        with db_session() as db:
            for news_id, enriched in results.items():
                db.query(StockNews).filter(StockNews.id == news_id).update({
                    "sentiment_score": enriched["score"],
                    "sentiment_label": enriched["label"],
                    "event_type": enriched.get("event_type"),
                    "nlp_reason": enriched.get("nlp_reason"),
                })

        log.info("llm_enrich_done", updated=len(results))
        # 广播最新 LLM 统计给前端
        _broadcast_llm_stats()
        return len(results)
    except Exception as e:
        log.warning("llm_enrich_failed", error=str(e))
        return 0


def _broadcast_llm_stats():
    """LLM 完成后推送最新 pipeline 统计"""
    try:
        from routers.ws import manager
        from services.news.sentiment_llm import _daily
        manager.broadcast_threadsafe({
            "type": "llm_stats_update",
            "stats": _daily.stats,
        })
    except Exception as e:
        log.debug("llm_stats_broadcast_skipped", error=str(e))
