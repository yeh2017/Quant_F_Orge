"""
新闻抓取入口（编排层）

保持 jobs/ 目录模式统一：main.py 调度器只和 jobs/ 层交互。
实际逻辑在 services/news/pipeline.py。
"""
from services.news.pipeline import get_pipeline
from typing import List, Dict, Optional


def sync_stock_news(codes: List[str], stock_names: Optional[Dict[str, str]] = None) -> int:
    """
    抓取新闻并写入数据库（三源合并 + 去重）

    Args:
        codes: 股票代码列表，如 ["600519.SH", "000858.SZ"]
        stock_names: 可选，{code: name} 映射
    Returns:
        新增新闻条数
    """
    return get_pipeline().run(codes, stock_names=stock_names)
