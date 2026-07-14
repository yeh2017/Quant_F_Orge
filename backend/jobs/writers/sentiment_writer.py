"""
情绪因子写入器
=============
StockMoneyFlow / StockShareholderCount 的批量写入。
"""

import structlog
import pandas as pd
from datetime import date as date_type
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("sentiment_writer")


class SentimentWriter:
    """情绪类因子数据写入"""

    # ================================================================
    #  资金流向 (StockMoneyFlow)
    # ================================================================

    def upsert_moneyflow_batch(self, db: Session, df: pd.DataFrame, trade_date: date_type, target_set: set):
        """
        将 Tushare moneyflow(trade_date=xxx) 全市场 DataFrame 批量写入。
        """
        if df is None or df.empty:
            return

        filtered = df[df["ts_code"].isin(target_set)].copy()
        if filtered.empty:
            return

        # 计算净主力流入 = (大单买入 + 特大单买入) - (大单卖出 + 特大单卖出)
        records = []
        for _, row in filtered.iterrows():
            buy_lg = float(row.get("buy_lg_amount", 0) or 0)
            sell_lg = float(row.get("sell_lg_amount", 0) or 0)
            buy_elg = float(row.get("buy_elg_amount", 0) or 0)
            sell_elg = float(row.get("sell_elg_amount", 0) or 0)
            net_mf = (buy_lg + buy_elg) - (sell_lg + sell_elg)

            records.append({
                "code": row["ts_code"],
                "trade_date": trade_date,
                "buy_lg_amount": buy_lg,
                "sell_lg_amount": sell_lg,
                "buy_elg_amount": buy_elg,
                "sell_elg_amount": sell_elg,
                "net_mf_amount": net_mf,
            })

        if not records:
            return

        cols = list(records[0].keys())
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)
        update_cols = [c for c in cols if c not in ("code", "trade_date")]
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

        sql = text(f"""
            INSERT INTO stock_money_flow ({col_names})
            VALUES ({placeholders})
            ON CONFLICT (code, trade_date) DO UPDATE SET {update_clause}
        """)
        db.execute(sql, records)
        log.info("upsert_moneyflow", trade_date=str(trade_date), count=len(records))


    # ================================================================
    #  股东户数 (StockShareholderCount)
    # ================================================================

    def upsert_shareholder_batch(self, db: Session, records: list):
        """
        批量写入股东户数数据。

        Args:
            records: [{"code": ..., "end_date": ..., "holder_num": ..., "holder_num_change_rate": ...}]
        """
        if not records:
            return

        sql = text("""
            INSERT INTO stock_shareholder_count (code, end_date, holder_num, holder_num_change_rate)
            VALUES (:code, :end_date, :holder_num, :holder_num_change_rate)
            ON CONFLICT (code, end_date) DO UPDATE SET
                holder_num=excluded.holder_num, holder_num_change_rate=excluded.holder_num_change_rate
        """)
        db.execute(sql, records)
        log.info("upsert_shareholder", count=len(records))
