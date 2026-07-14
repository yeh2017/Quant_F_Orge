"""
Tavily Search 抓取器

唯一一份 Tavily 逻辑，同时支持 fetch（自动降级）和 search（用户搜索）。
"""
import os
import structlog
from datetime import datetime
from typing import List, Dict

from .base import BaseFetcher, RawNewsItem
from .tushare import _parse_time

log = structlog.get_logger("fetcher.tavily")

# 白名单从 settings.py 集中管理
from settings import TAVILY_NEWS_DOMAINS as _NEWS_DOMAINS

# ── 二级防线：漏网之鱼的垃圾过滤 ──
_JUNK_TITLE_KW = [
    "最新价格", "行情走势", "走势图", "实时行情", "个股资讯",
    "公司概括", "Company Profile", "股票消息和頭條",
    "F10", "f10", "动态_", "Technical Analysis",
    "RT Quote", "Detailed Quote", "股息历史",
]

# 最大新闻年龄（天）
_MAX_AGE_DAYS = 7



class TavilyFetcher(BaseFetcher):

    source_name = "tavily"

    def __init__(self):
        self._api_key = os.getenv("TAVILY_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def fetch(self, codes: List[str], names: Dict[str, str]) -> List[RawNewsItem]:
        """自动抓取模式：按股票名称构建搜索词"""
        if not self.available:
            return []

        search_terms = []
        for code in codes[:5]:
            name = names.get(code, "")
            if name:
                search_terms.append((f"{name} 新闻 利好 利空", code))
            else:
                search_terms.append((f"A股 {code.split('.')[0]} 最新新闻", code))
        # 市场级搜索
        search_terms.append(("A股 重大政策 消费 科技 新能源 今日新闻", ""))

        items = []
        for query, src_code in search_terms:
            items.extend(self._do_search(query, hint_code=src_code))

        log.info("tavily_fetched", count=len(items))
        return items

    def search(self, keyword: str) -> List[RawNewsItem]:
        """用户主动搜索模式"""
        if not self.available:
            return []
        query = f"{keyword} 股票 最新消息 新闻"
        items = self._do_search(query, hint_code=keyword, max_results=10)
        log.info("tavily_searched", keyword=keyword, count=len(items))
        return items

    def _do_search(self, query: str, *, hint_code: str = "", max_results: int = 5) -> List[RawNewsItem]:
        """核心搜索逻辑（只写一次）"""
        import requests
        import time

        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": False,
                    "include_domains": _NEWS_DOMAINS,
                },
                timeout=15,
            )
            if resp.status_code != 200:
                # 精确区分错误类型
                if resp.status_code in (401, 403):
                    log.error("tavily_auth_error", hint="API Key 无效或已过期")
                    raise RuntimeError("Tavily API Key 无效或额度已用完")
                if resp.status_code == 429:
                    log.error("tavily_rate_limit", hint="API 调用额度已用完")
                    raise RuntimeError("Tavily API 额度已用完，请稍后再试")
                log.warning("tavily_http_error", status=resp.status_code)
                return []

            items = []
            for r in resp.json().get("results", []):
                title = r.get("title", "").strip()
                url = r.get("url", "")
                if not title:
                    continue
                # 二级防线：标题关键词 + JSON 检测
                if any(kw in title for kw in _JUNK_TITLE_KW):
                    continue
                if '[[' in title or ']]' in title:
                    continue
                # 垃圾标题过滤（乱码检测已统一到 pipeline._process）

                # 提取真实发布时间
                pub_time = (
                    _parse_time(r.get("published_date"))
                    or _parse_time(r.get("publishedDate"))
                )
                # 过滤超龄旧文
                if pub_time and (datetime.now() - pub_time).days > _MAX_AGE_DAYS:
                    continue

                items.append(RawNewsItem(
                    title=title,
                    summary=r.get("content", "")[:200],
                    source=self.source_name,
                    url=url,
                    publish_time=pub_time,
                    market_type="A股" if hint_code else "全球",
                    hint_code=hint_code,
                    raw_text=title + " " + r.get("content", "")[:100],
                ))
            return items
        except RuntimeError:
            raise  # API 错误向上传播，前端能看到
        except Exception as e:
            log.warning("tavily_search_failed", query=query[:50], error=str(e))
            return []
        finally:
            time.sleep(0.5)
