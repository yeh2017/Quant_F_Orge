"""
因子数据写入器
=============
批量 Upsert StockDailyFactor。
"""

import structlog
import pandas as pd
from datetime import date as date_type
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("factor_writer")


class FactorWriter:
    """StockDailyFactor 批量写入"""

    # 因子表所有可能的列
    _ALL_FACTOR_COLS = [
        "code", "trade_date", "turnover_rate", "turnover_rate_f",
        "volume_ratio", "pe", "pe_ttm", "pb", "ps", "ps_ttm",
        "dv_ratio", "dv_ttm", "total_mv", "circ_mv",
    ]

    # ---------- 按交易日全市场批量写入 ----------

    def upsert_batch(self, db: Session, df_basic: pd.DataFrame, trade_date: date_type, target_set: set):
        """
        Tushare daily_basic() 返回的全市场因子数据批量写入。
        """
        if df_basic is None or df_basic.empty:
            return

        df = df_basic[df_basic["ts_code"].isin(target_set)].copy()
        if df.empty:
            return

        df = df.rename(columns={"ts_code": "code"})
        df["trade_date"] = trade_date

        keep = [c for c in self._ALL_FACTOR_COLS if c in df.columns]
        df = df[keep]

        self._bulk_upsert(db, df)
        log.info("batch_upsert_factors", trade_date=str(trade_date), count=len(df))

    # ---------- 按股票写入（fallback） ----------

    def upsert_single(self, db: Session, code: str, df_factors: pd.DataFrame,
                      start_date: str, end_date: str):
        """写入单只股票的因子数据"""
        if df_factors is None or df_factors.empty:
            return

        df = df_factors.copy()
        # 确保 trade_date 是 date 对象
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        if "code" not in df.columns:
            df["code"] = code

        keep = [c for c in self._ALL_FACTOR_COLS if c in df.columns]
        if "code" not in keep:
            keep.insert(0, "code")
        if "trade_date" not in keep:
            keep.insert(1, "trade_date")
        df = df[keep]

        # 使用真正的 ON CONFLICT DO UPDATE，保证幂等性（重复同步不报错）
        self._bulk_upsert(db, df)
        log.info("single_upsert_factors", code=code, rows=len(df))

    # ---------- 内部 ----------

    @staticmethod
    def _bulk_upsert(db: Session, df: pd.DataFrame):
        if df.empty:
            return

        cols = list(df.columns)
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)
        update_cols = [c for c in cols if c not in ("code", "trade_date")]
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

        sql = text(f"""
            INSERT INTO stock_daily_factors ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (code, trade_date) DO UPDATE SET {update_clause}
        """)

        records = df.to_dict("records")
        db.execute(sql, records)
