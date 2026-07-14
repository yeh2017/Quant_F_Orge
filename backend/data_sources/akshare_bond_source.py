"""
AkShare 可转债专用数据模块
============================
作为可转债溢价率/纯债价值数据的降级兜底来源。
Tushare Pro 为主力，若 Tushare 接口返回空或异常，自动触发此模块。

主要接口:
  get_cb_premium_list()  → 全市场溢价率快照（bond_zh_convertible_premium）
  get_cb_comparison(code) → 正股联动数据（bond_cov_comparison, 仅部分债可用）
"""

import structlog
from typing import Optional, List, Dict

log = structlog.get_logger(__name__)


def get_cb_premium_list() -> List[Dict]:
    """
    获取全市场可转债溢价率快照（当日最新数据）。
    返回字段: code, name, close, premium_ratio, pure_bond_value,
              pure_bond_premium, convert_value, remaining_size,
              convert_price, rating
    数据源: AkShare bond_zh_cov()（全市场可转债概览，含转股溢价率/评级）
    """
    try:
        import akshare as ak
        df = ak.bond_zh_cov()
        if df is None or df.empty:
            log.warning("akshare_cb_premium_empty")
            return []

        # 列名映射（集中管理在 schema.py）
        from data_sources.schema import get_column_map
        col_map = get_column_map("akshare_cb_premium")
        rename = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=rename)

        results = []
        numeric_cols = {"close", "premium_ratio", "convert_value",
                        "convert_price", "underlying_close", "remaining_size"}
        for _, row in df.iterrows():
            record = {}
            for col in ["code", "name", "close", "premium_ratio",
                         "convert_value", "convert_price",
                         "remaining_size", "rating",
                         "underlying_code", "underlying_name", "underlying_close"]:
                val = row.get(col)
                try:
                    record[col] = float(val) if col in numeric_cols and val is not None else val
                except (ValueError, TypeError):
                    record[col] = None
            code = str(record.get("code") or "").strip()
            code = code.replace(".SH", "").replace(".SZ", "").strip()
            if code:
                record["code"] = code
                results.append(record)

        log.info("akshare_cb_premium_fetched", count=len(results))

        from data_sources.schema import validate_records, SCHEMA
        validate_records(results, SCHEMA["ak_cb_premium"], source="AkShare bond_zh_cov")
        return results

    except Exception as e:
        log.warning("akshare_cb_premium_failed", error=str(e))
        return []


def get_cb_comparison(bond_code: str) -> Optional[Dict]:
    """
    获取单只可转债与正股的价格联动数据。
    返回: {"underlying_close": float, "premium_ratio": float, ...}
    数据源: AkShare bond_cov_comparison()（并非所有债都有，失败返回 None）
    """
    try:
        import akshare as ak
        df = ak.bond_cov_comparison(bond=bond_code)
        if df is None or df.empty:
            return None
        row = df.iloc[-1]
        return {
            "underlying_close": float(row.get("正股价格", 0) or 0) or None,
            "premium_ratio": float(row.get("转股溢价率", 0) or 0) or None,
            "convert_value": float(row.get("转股价值", 0) or 0) or None,
        }
    except Exception as e:
        log.debug("akshare_cb_comparison_failed", code=bond_code, error=str(e))
        return None
