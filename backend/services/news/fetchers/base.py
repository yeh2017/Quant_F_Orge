"""
数据源抽象基类

所有新闻数据源（Tushare/AkShare/Tavily）实现此接口。
新增数据源只需继承 BaseFetcher 并实现 fetch()。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional


@dataclass
class RawNewsItem:
    """抓取阶段的新闻条目（未经评分、未经代码解析）"""
    title: str
    summary: str = ""
    source: str = ""           # tushare / akshare / tavily
    url: str = ""
    publish_time: Optional[datetime] = None
    market_type: str = "A股"
    hint_code: str = ""        # 抓取时已知的关联代码（如 AkShare 按个股查询）
    raw_text: str = ""         # 用于情绪评分的原始文本


class BaseFetcher(ABC):
    """新闻数据源统一接口"""

    source_name: str  # 子类通过类变量赋值覆盖

    @abstractmethod
    def fetch(self, codes: List[str], names: Dict[str, str]) -> List[RawNewsItem]:
        """
        抓取新闻。

        Args:
            codes: 股票代码列表，如 ["600519.SH"]
            names: {code: name} 映射
        Returns:
            原始新闻列表（不含情绪分和关联代码解析）
        """
        ...

    def search(self, keyword: str) -> List[RawNewsItem]:
        """
        搜索模式（仅搜索引擎类 Fetcher 需要实现）。
        默认不支持。
        """
        return []


def is_garbled(text: str) -> bool:
    """检测文本是否为乱码。

    中文新闻标题应包含汉字/中文标点。若文本含非 ASCII 字符但
    中文字符占比极低，说明是编码损坏（如 GBK 被当作 Latin-1 解码）。
    """
    if not text or len(text) < 5:
        return False
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if non_ascii == 0:
        return False  # 纯 ASCII（英文标题），放行
    # CJK 统一汉字 + 中文标点 + 全角字符 都算"正常中文"
    def _is_cjk_or_punct(c):
        cp = ord(c)
        return ('\u4e00' <= c <= '\u9fff'       # CJK 统一汉字
                or '\u3000' <= c <= '\u303f'     # CJK 标点（、。〈〉）
                or '\uff00' <= c <= '\uffef'     # 全角字符（！？）
                or '\u2018' <= c <= '\u201f')    # 引号（""''）
    cjk = sum(1 for c in text if _is_cjk_or_punct(c))
    # 非 ASCII 字符中，中文字符不到一半 → 大概率是乱码
    return cjk < non_ascii * 0.5
