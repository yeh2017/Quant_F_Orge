"""
资产类型分类 — 唯一来源（Single Source of Truth）
=================================================
所有后端模块只调此处的函数/常量来判断资产类型。
新增资产类型前缀时，只需修改此文件。

⚠️ 前端镜像: frontend/src/utils/assetType.js
   两文件常量必须严格同步，修改一方时务必同步另一方。
"""

import re

# ── A 股代码前缀 ──
STOCK_PREFIXES = ("60", "00", "30", "68")
BOND_PREFIXES = ("10", "11", "12", "13", "40")
ETF_PREFIXES = ("51", "52", "58", "15", "16", "56")

# ── 港股通 / 期货正则 ──
HK_PATTERN = re.compile(r"^\d{5}$")                     # 港股通: 00700
FUTURE_PATTERN = re.compile(r"^[A-Za-z]{1,2}\d{3,4}$")  # 期货: IF2506, rb2510

# ── 期货品种 → 交易所映射 ──
FUTURE_EXCHANGES: dict[str, str] = {
    # 中金所 (CFFEX) — 股指/国债
    "IF": "CFFEX", "IC": "CFFEX", "IM": "CFFEX", "IH": "CFFEX",
    "TS": "CFFEX", "TF": "CFFEX", "T": "CFFEX",
    # 上期所 (SHFE) — 金属/能化
    "rb": "SHFE", "hc": "SHFE", "cu": "SHFE", "al": "SHFE",
    "zn": "SHFE", "pb": "SHFE", "ni": "SHFE", "sn": "SHFE",
    "au": "SHFE", "ag": "SHFE", "bu": "SHFE", "ru": "SHFE",
    "fu": "SHFE", "sp": "SHFE", "ss": "SHFE", "wr": "SHFE",
    # 大商所 (DCE) — 农产品/工业品
    "i": "DCE", "j": "DCE", "jm": "DCE", "m": "DCE",
    "y": "DCE", "p": "DCE", "c": "DCE", "cs": "DCE",
    "a": "DCE", "b": "DCE", "jd": "DCE", "l": "DCE",
    "v": "DCE", "pp": "DCE", "eg": "DCE", "eb": "DCE",
    "pg": "DCE", "lh": "DCE",
    # 郑商所 (CZCE) — 农产品/化工
    "CF": "CZCE", "SR": "CZCE", "TA": "CZCE", "MA": "CZCE",
    "OI": "CZCE", "RM": "CZCE", "FG": "CZCE", "SA": "CZCE",
    "AP": "CZCE", "CJ": "CZCE", "PK": "CZCE", "UR": "CZCE",
    "SF": "CZCE", "SM": "CZCE", "ZC": "CZCE", "PF": "CZCE",
    # 上海国际能源 (INE)
    "sc": "INE", "nr": "INE", "lu": "INE", "bc": "INE",
}

# 中文标签
TYPE_LABELS = {
    "stock": "股票", "bond": "可转债", "etf": "ETF",
    "hk_stock": "港股通", "future": "期货",
}


def classify(code: str) -> str:
    """
    根据代码特征判断资产类型。

    Returns:
        'stock' | 'etf' | 'bond' | 'hk_stock' | 'future'
    """
    raw = code.split(".")[0].strip()
    # 期货: 字母开头（优先判断，避免被后面的长度检查误拦）
    if FUTURE_PATTERN.match(raw):
        return "future"
    # 港股通: 5 位纯数字
    if HK_PATTERN.match(raw):
        return "hk_stock"
    # A 股体系: 6 位纯数字
    if len(raw) == 6:
        prefix = raw[:2]
        if prefix in BOND_PREFIXES:
            return "bond"
        if prefix in ETF_PREFIXES:
            return "etf"
    return "stock"


def is_bond(code: str) -> bool:
    return classify(code) == "bond"


def is_etf_by_prefix(code: str) -> bool:
    """仅按前缀判断 ETF（不查 DB，用于无法访问数据库的场景）"""
    return classify(code) == "etf"


def is_hk(code: str) -> bool:
    return classify(code) == "hk_stock"


def is_future(code: str) -> bool:
    return classify(code) == "future"


# ── 交易所映射（统一入口） ──

SH_PREFIXES = ("6", "51", "52", "58", "10", "11")


def _future_exchange(code: str) -> str:
    """期货品种代码 → 交易所"""
    raw = code.split(".")[0].strip()
    letters = re.match(r"^[A-Za-z]+", raw)
    if not letters:
        return ""
    symbol = letters.group()
    # 先精确匹配（如 'jm'），再单字符匹配（如 'j'）
    return FUTURE_EXCHANGES.get(symbol, FUTURE_EXCHANGES.get(symbol.upper(), ""))


def get_exchange(code: str) -> str:
    """
    根据代码推导交易所。

    Returns:
        'SH' | 'SZ' | 'BJ' | 'HK' | 'CFFEX' | 'SHFE' | 'DCE' | 'CZCE' | 'INE' | ''
    """
    pure = code.split(".")[0].strip()
    if not pure:
        return ""
    # 期货
    if FUTURE_PATTERN.match(pure):
        return _future_exchange(pure)
    # 港股通
    if HK_PATTERN.match(pure):
        return "HK"
    # A 股
    if pure[:2] in ("83", "87", "43"):
        return "BJ"
    for p in SH_PREFIXES:
        if pure.startswith(p):
            return "SH"
    return "SZ"


def to_ts_code(code: str) -> str:
    """
    确保代码带 Tushare 后缀。

    >>> to_ts_code('600519')
    '600519.SH'
    >>> to_ts_code('00700')
    '00700.HK'
    >>> to_ts_code('IF2506')
    'IF2506.CFFEX'
    """
    code = code.strip()
    if "." in code:
        return code
    exchange = get_exchange(code)
    return f"{code}.{exchange}" if exchange else code


def to_bs_code(code: str) -> str:
    """
    转为 BaoStock 格式（仅 A 股适用）。

    >>> to_bs_code('600519')
    'sh.600519'
    """
    pure = code.split(".")[0].strip()
    asset = classify(pure)
    if asset in ("hk_stock", "future"):
        return pure  # BaoStock 不支持港股/期货，原样返回
    exchange = get_exchange(pure).lower()
    return f"{exchange}.{pure}" if exchange else pure

