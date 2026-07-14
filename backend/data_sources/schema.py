"""
数据源 Schema 验证
==================
在数据源层统一校验返回数据的字段完整性，
防止 API 变更导致静默返回空壳数据。

用法:
    from data_sources.schema import validate_records, SCHEMA

    results = fetch_something()
    validate_records(results, SCHEMA["cb_basic"], source="Tushare cb_basic")
"""

import structlog

log = structlog.get_logger(__name__)


# ── 各数据方法的必需字段定义 ──
# key = 数据类型标识, value = (必需字段列表, 至少有值比例阈值)
SCHEMA = {
    # Tushare
    "cb_basic": {
        "required": ["code", "name"],
        "important": ["convert_price", "underlying_code"],
        "min_ratio": 0.5,  # important 字段至少 50% 有值才算正常
    },
    "cb_daily": {
        "required": ["code", "close"],
        "important": ["open", "high", "low", "volume"],
        "min_ratio": 0.8,
    },
    "stock_daily": {
        "required": ["code", "trade_date", "close"],
        "important": ["open", "high", "low", "volume"],
        "min_ratio": 0.9,
    },
    "stock_factor": {
        "required": ["code", "trade_date"],
        "important": ["pe_ttm", "pb", "turnover_rate"],
        "min_ratio": 0.3,  # 部分股票天然无 PE（亏损股）
    },
    # AkShare
    "ak_cb_premium": {
        "required": ["code"],
        "important": ["close", "premium_ratio", "rating"],
        "min_ratio": 0.5,
    },
}


# ── 统一列名映射（API 变更时只改这里）──

COLUMN_MAP = {
    # Tushare cb_basic → 内部字段名
    "tushare_cb_basic": {
        "ts_code": "ts_code",
        "bond_short_name": "name",
        "stk_code": "underlying_code",
        "stk_short_name": "underlying_name",
        "rating_ent": "rating",
        "list_date": "issue_date",
        "delist_date": "mature_date",
        "par_value": "face_value",
        "conv_price": "convert_price",
        "first_conv_price": "convert_price_fallback",
        "list_price": "list_price",
    },
    # Tushare cb_daily → 内部字段名
    "tushare_cb_daily": {
        "ts_code": "ts_code",
        "trade_date": "trade_date",
        "close": "close",
        "open": "open",
        "high": "high",
        "low": "low",
        "vol": "volume",
        "amount": "amount",
        "bond_value": "pure_bond_value",
    },
    # AkShare bond_zh_cov → 内部字段名
    "akshare_cb_premium": {
        "债券代码": "code",
        "债券简称": "name",
        "债现价": "close",
        "转股溢价率": "premium_ratio",
        "转股价值": "convert_value",
        "转股价": "convert_price",
        "正股价": "underlying_close",
        "正股代码": "underlying_code",
        "正股简称": "underlying_name",
        "发行规模": "remaining_size",
        "信用评级": "rating",
    },
}


def get_column_map(source: str) -> dict:
    """获取指定数据源的列名映射，API 变更时只需修改 COLUMN_MAP"""
    mapping = COLUMN_MAP.get(source, {})
    if not mapping:
        log.warning("column_map_not_found", source=source)
    return mapping


def validate_records(
    records: list,
    schema: dict,
    source: str = "unknown",
    raise_on_fail: bool = False,
) -> dict:
    """
    校验记录列表的字段完整性。

    Args:
        records: 字典列表
        schema: SCHEMA 中定义的规则
        source: 数据源标识（用于日志）
        raise_on_fail: 是否在必需字段缺失时抛异常

    Returns:
        {"ok": bool, "total": int, "warnings": list[str]}
    """
    if not records:
        return {"ok": True, "total": 0, "warnings": []}

    total = len(records)
    warnings = []
    required = schema.get("required", [])
    important = schema.get("important", [])
    min_ratio = schema.get("min_ratio", 0.5)

    # 1. 检查第一条记录是否包含必需字段
    sample = records[0]
    missing_required = [f for f in required if f not in sample]
    if missing_required:
        msg = f"[{source}] 缺少必需字段: {missing_required}"
        log.error("schema_validation_failed", source=source,
                  missing=missing_required)
        warnings.append(msg)
        if raise_on_fail:
            raise ValueError(msg)
        return {"ok": False, "total": total, "warnings": warnings}

    # 2. 检查 important 字段的非 NULL 比例
    for field in important:
        if field not in sample:
            warnings.append(f"[{source}] 字段 '{field}' 不存在于返回数据中")
            log.warning("schema_field_missing", source=source, field=field)
            continue

        non_null = sum(1 for r in records if r.get(field) is not None)
        ratio = non_null / total
        if ratio < min_ratio:
            msg = f"[{source}] '{field}' 有值率 {ratio:.0%} < 阈值 {min_ratio:.0%}"
            warnings.append(msg)
            log.warning("schema_low_coverage", source=source, field=field,
                        ratio=round(ratio, 3), threshold=min_ratio)

    ok = len(warnings) == 0
    if ok:
        log.info("schema_validation_ok", source=source, total=total)
    return {"ok": ok, "total": total, "warnings": warnings}
