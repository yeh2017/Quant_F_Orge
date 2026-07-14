"""
行情数据写入器
=============
批量 Upsert StockDailyBar，替代逐行 ORM 操作。
"""

import structlog
import pandas as pd
from datetime import date as date_type
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("bar_writer")


class BarWriter:
    """StockDailyBar 批量写入"""

    # ---------- 按交易日全市场批量写入（供 BatchFetcher 使用） ----------

    def upsert_batch(self, db: Session, df_daily: pd.DataFrame, trade_date: date_type, target_set: set) -> set:
        """
        将 Tushare daily() 返回的全市场 DataFrame 筛选后批量写入。

        Args:
            db: 数据库会话
            df_daily: Tushare daily(trade_date=xxx) 原始 DataFrame
            trade_date: Python date 对象
            target_set: 目标股票代码集合

        Returns:
            本次写入成功的股票代码集合
        """
        if df_daily is None or df_daily.empty:
            return set()

        df = df_daily[df_daily["ts_code"].isin(target_set)].copy()
        if df.empty:
            return set()

        # 列名映射
        col_map = {
            "ts_code": "code",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "vol": "volume",
            "amount": "amount",
            "pre_close": "pre_close",
            "change": "change",
            "pct_chg": "pct_chg",
        }
        valid_cols = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=valid_cols)
        df["trade_date"] = trade_date

        # 保留实际存在的列
        keep = [c for c in ["code", "trade_date", "open", "high", "low", "close",
                            "volume", "amount", "pre_close", "change", "pct_chg", "adj_factor"] if c in df.columns]
        df = df[keep]

        synced = set(df["code"].unique())
        self._bulk_upsert(db, df)
        log.info("batch_upsert_bars", trade_date=str(trade_date), count=len(df))
        return synced

    # ---------- 按股票写入（供 SingleFetcher / fallback 使用） ----------

    def upsert_single(self, db: Session, code: str, df_bars: pd.DataFrame,
                      start_date: str, end_date: str):
        """
        写入单只股票的行情数据（先 delete range 再 append）。
        """
        if df_bars is None or df_bars.empty:
            return

        df = df_bars.copy()
        # 列名兼容
        if "date" in df.columns and "trade_date" not in df.columns:
            df = df.rename(columns={"date": "trade_date"})
        if "vol" in df.columns and "volume" not in df.columns:
            df = df.rename(columns={"vol": "volume"})
        df["code"] = code

        # 确保 trade_date 是 date 对象
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date

        keep = [c for c in ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "adj_factor"]
                if c in df.columns]
        df = df[keep]

        db.execute(text(
            "DELETE FROM stock_daily_bars WHERE code=:code AND trade_date >= :start AND trade_date <= :end"
        ), {"code": code, "start": start_date, "end": end_date})
        db.flush()

        # 使用同一 db 会话的 _bulk_upsert，保证 DELETE+INSERT 在一个事务内
        self._bulk_upsert(db, df)
        log.info("single_upsert_bars", code=code, rows=len(df))

    # ---------- 内部批量 Upsert ----------

    @staticmethod
    def _bulk_upsert(db: Session, df: pd.DataFrame):
        """使用 SQLite INSERT OR REPLACE 进行批量 upsert"""
        if df.empty:
            return

        cols = list(df.columns)
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)

        # 构建 ON CONFLICT 更新子句（排除主键）
        update_cols = [c for c in cols if c not in ("code", "trade_date")]
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

        sql = text(f"""
            INSERT INTO stock_daily_bars ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (code, trade_date) DO UPDATE SET {update_clause}
        """)

        records = df.to_dict("records")
        db.execute(sql, records)
