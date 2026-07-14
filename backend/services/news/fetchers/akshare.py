"""
AkShare stock_news_em 抓取器

按个股查询，天然有 code 关联。
"""
import time
import structlog
from typing import List, Dict

from .base import BaseFetcher, RawNewsItem
from .tushare import _parse_time
from services.news.sentiment import strip_html
from settings import AKSHARE_NEWS_SLEEP

log = structlog.get_logger("fetcher.akshare")


class AkShareFetcher(BaseFetcher):

    source_name = "akshare"

    def fetch(self, codes: List[str], names: Dict[str, str]) -> List[RawNewsItem]:
        items = []
        try:
            import akshare as ak
        except ImportError:
            log.warning("akshare_not_installed")
            return items

        for code in codes:
            symbol = code.split(".")[0] if "." in code else code
            try:
                df = ak.stock_news_em(symbol=symbol)
                if df is None or df.empty:
                    continue
                for _, row in df.head(20).iterrows():
                    title = str(row.get("新闻标题", "") or "").strip()
                    if not title:
                        continue
                    items.append(RawNewsItem(
                        title=title,
                        summary=strip_html(str(row.get("新闻内容", "") or ""))[:200],
                        source=self.source_name,
                        url=str(row.get("新闻链接", "") or ""),
                        publish_time=_parse_time(row.get("发布时间")),
                        hint_code=code,          # AkShare 按个股查询，天然关联
                        raw_text=title,
                    ))
            except Exception as e:
                log.warning("akshare_fetch_failed", code=code, error=str(e))
            time.sleep(AKSHARE_NEWS_SLEEP)

        log.info("akshare_fetched", count=len(items))
        return items
