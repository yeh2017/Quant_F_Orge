"""
财务数据写入器
=============
StockFinancial 表的清洗、去重与写入。
"""

import structlog
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

log = structlog.get_logger("financial_writer")


class FinancialWriter:
    """StockFinancial 写入"""

    def upsert(self, db: Session, code: str, df: pd.DataFrame) -> bool:
        """
        将单只股票的财务数据写入 SQLite。

        Args:
            db: 数据库会话
            code: 股票代码
            df: 原始财务 DataFrame（来自 Tushare fina_indicator 或 Baostock）

        Returns:
            是否写入成功
        """
        if df is None or df.empty:
            return False

        if "end_date" in df.columns:
            df = df.drop_duplicates(subset=["end_date"], keep="first")
            df = df.sort_values("end_date", ascending=False).head(4)

        # 直接 upsert，不清空历史——ON CONFLICT DO UPDATE SET 会覆盖已有期数

        written = 0
        for _, row in df.iterrows():
            report_date = self._parse_report_date(row.get("end_date", ""))
            if report_date is None:
                continue

            record = {
                "code": code,
                "report_date": report_date,
                "roe": self._safe_float(row.get("roe")),
                "roa": self._safe_float(row.get("roa")),
                "gross_profit_margin": self._safe_float(
                    row.get("grossprofit_margin") if "grossprofit_margin" in row.index
                    else row.get("gross_profit_margin")
                ),
                "net_profit_margin": self._safe_float(
                    row.get("netprofit_margin") if "netprofit_margin" in row.index
                    else row.get("net_profit_margin")
                ),
                "revenue_yoy": self._safe_float(
                    row.get("or_yoy") if "or_yoy" in row.index
                    else row.get("revenue_yoy")
                ),
                "net_profit_yoy": self._safe_float(
                    row.get("netprofit_yoy") if "netprofit_yoy" in row.index
                    else row.get("net_profit_yoy")
                ),
                "eps": self._safe_float(
                    row.get("eps") if "eps" in row.index
                    else row.get("basic_eps")
                ),
                "cashflow_oper": self._safe_float(row.get("n_cashflow_act")),
                "debt_to_assets": self._safe_float(row.get("debt_to_assets")),
            }

            upsert_sql = text("""
                INSERT INTO stock_financials (
                    code, report_date, roe, roa, gross_profit_margin,
                    net_profit_margin, revenue_yoy, net_profit_yoy, eps,
                    cashflow_oper, debt_to_assets
                )
                VALUES (
                    :code, :report_date, :roe, :roa, :gross_profit_margin,
                    :net_profit_margin, :revenue_yoy, :net_profit_yoy, :eps,
                    :cashflow_oper, :debt_to_assets
                )
                ON CONFLICT(code, report_date) DO UPDATE SET
                    roe=excluded.roe, roa=excluded.roa,
                    gross_profit_margin=excluded.gross_profit_margin,
                    net_profit_margin=excluded.net_profit_margin,
                    revenue_yoy=excluded.revenue_yoy,
                    net_profit_yoy=excluded.net_profit_yoy,
                    eps=excluded.eps,
                    cashflow_oper=COALESCE(excluded.cashflow_oper, stock_financials.cashflow_oper),
                    debt_to_assets=COALESCE(excluded.debt_to_assets, stock_financials.debt_to_assets)
            """)
            db.execute(upsert_sql, record)
            written += 1

        if written > 0:
            log.info("upsert_financial", code=code, rows=written)
        return written > 0

    # ---------- 工具方法 ----------

    @staticmethod
    def _parse_report_date(val) -> str | None:
        """将 end_date 解析为 'YYYY-MM-DD' 字符串"""
        if not val:
            return None
        val_str = str(val)
        try:
            if len(val_str) == 8:
                dt = pd.to_datetime(val_str, format="%Y%m%d", errors="coerce")
            else:
                dt = pd.to_datetime(val_str, errors="coerce")
            if pd.isna(dt):
                return None
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None

    @staticmethod
    def _safe_float(val):
        """安全转换为 float，处理 None/NaN"""
        if val is None:
            return None
        try:
            import numpy as np
            f = float(val)
            return None if (np.isnan(f) or np.isinf(f)) else f
        except (ValueError, TypeError):
            return None
