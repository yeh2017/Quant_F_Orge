"""
统一的新闻 → 股票代码关联解析器

所有数据源（Tushare/AkShare/Tavily）共用此模块匹配关联代码，
消除各源各自实现导致的规则不一致。
"""
import re
import structlog
from typing import List, Optional

log = structlog.get_logger("code_resolver")


class CodeResolver:
    """从文本中提取关联的 A 股代码"""

    def __init__(self):
        self._name_map: dict[str, str] = {}       # "招商银行" → "600036.SH"
        self._prefix_map: dict[str, str] = {}     # "600036" → "600036.SH"
        self._loaded = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        from core.database import db_session
        from models.quant_data import StockBasicInfo
        with db_session() as db:
            rows = db.query(StockBasicInfo.code, StockBasicInfo.name).all()
            for r in rows:
                # 代码前缀映射（全量，不受名称限制）
                prefix = r.code.split(".")[0] if "." in r.code else r.code
                if len(prefix) == 6:
                    self._prefix_map[prefix] = r.code
                # 名称映射（≥2 字即可，靠标题精确匹配避免误命中）
                if r.name and len(r.name) >= 2:
                    self._name_map[r.name] = r.code
        self._loaded = True
        log.info("code_resolver_loaded", names=len(self._name_map), prefixes=len(self._prefix_map))

    def resolve(self, text: str, *, force_code: Optional[str] = None, max_codes: int = 5) -> List[str]:
        """
        从文本中提取关联股票代码。

        Args:
            text: 标题或标题+摘要的短文本
            force_code: 强制关联的代码前缀（如用户搜索 "600001"）
            max_codes: 超过此数量视为宏观新闻，清空关联
        Returns:
            代码列表，如 ["600036.SH", "000858.SZ"]
        """
        self._ensure_loaded()
        matched = set()

        # 1. 名称匹配
        for name, code in self._name_map.items():
            if name in text:
                matched.add(code)

        # 2. 6 位数字代码匹配（不限开头，覆盖 ETF/可转债）
        for d in re.findall(r'(?<!\d)\d{6}(?!\d)', text):
            if d in self._prefix_map:
                matched.add(self._prefix_map[d])

        # 3. 强制关联（搜索词对应的代码）
        if force_code:
            ts = self.to_ts_code(force_code)
            if ts:
                matched.add(ts)

        # 超过 max_codes 说明是宏观新闻，清空
        if len(matched) > max_codes:
            return []
        return list(matched)

    def to_ts_code(self, prefix: str) -> Optional[str]:
        """
        将 6 位纯数字代码转为 ts_code。
        优先查数据库映射，查不到则按交易所规则猜测。
        """
        self._ensure_loaded()
        if not (len(prefix) == 6 and prefix.isdigit()):
            # 可能是股票名称
            return self._name_map.get(prefix)
        if prefix in self._prefix_map:
            return self._prefix_map[prefix]
        # 兜底：按交易所前缀规则（5/6/7/9 开头 → 上交所 .SH）
        return f"{prefix}.SH" if prefix[0] in "5679" else f"{prefix}.SZ"

    def search_codes(self, keyword: str, max_results: int = 10) -> List[str]:
        """
        模糊搜索：将关键词解析为可能关联的股票代码列表。
        支持: 精确名称、部分名称、代码前缀。
        如 "茅台" → ["600519.SH"]，"银行" → ["600036.SH", "601398.SH", ...]
        """
        self._ensure_loaded()
        keyword = keyword.strip()
        if not keyword:
            return []

        # 1. 精确匹配（最快路径）
        exact = self.to_ts_code(keyword)
        if exact:
            return [exact]

        # 2. 部分名称匹配
        matched = []
        for name, code in self._name_map.items():
            if keyword in name:
                matched.append(code)
                if len(matched) >= max_results:
                    break
        return matched
