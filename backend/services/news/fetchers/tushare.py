"""
Tushare major_news 抓取器

市场级新闻，标题匹配关联股票由 Pipeline 统一处理。
"""
import os
import structlog
from datetime import datetime, timedelta
from typing import List, Dict

from .base import BaseFetcher, RawNewsItem
from services.news.sentiment import strip_html

log = structlog.get_logger("fetcher.tushare")


class TushareFetcher(BaseFetcher):

    source_name = "tushare"

    def fetch(self, codes: List[str], names: Dict[str, str]) -> List[RawNewsItem]:
        items = []
        try:
            import tushare as ts
            token = os.getenv("TUSHARE_TOKEN")
            if not token:
                return items
            pro = ts.pro_api(token)

            end_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_dt = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

            try:
                df = pro.major_news(
                    start_date=start_dt,
                    end_date=end_dt,
                    fields="title,content,src,pub_time",
                )
            except Exception as e:
                log.warning("tushare_major_news_failed", error=str(e))
                return items

            if df is None or df.empty:
                return items

            for _, row in df.iterrows():
                title = str(row.get("title", "") or "").strip()
                if not title:
                    continue

                raw_content = str(row.get("content", "") or "")
                clean_content = strip_html(raw_content)

                items.append(RawNewsItem(
                    title=title,
                    summary=clean_content[:200],
                    source=self.source_name,
                    publish_time=_parse_time(row.get("pub_time")),
                    raw_text=title + " " + clean_content[:200],
                ))

            log.info("tushare_fetched", count=len(items))
        except ImportError:
            log.warning("tushare_not_installed")
        except Exception as e:
            log.warning("tushare_error", error=str(e))

        return items


def _parse_time(val) -> datetime | None:
    """解析时间字符串"""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None
