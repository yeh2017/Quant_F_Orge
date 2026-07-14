"""
行业指数同步
============
从 data_sync_service.py 提取。
"""
import structlog
import time
from core.database import db_session
from utils.trade_date import _parse_date

log = structlog.get_logger("sync_industry")


def sync_industry_index(ts_source, start_date: str, end_date: str) -> dict:
    """同步申万行业指数日线到 industry_index_daily 表"""
    from sqlalchemy import text as sa_text
    from jobs.sync_base import write_watermark

    t_start = time.time()

    rows = ts_source.get_industry_index_daily(
        start_date=start_date, end_date=end_date
    )
    if not rows:
        raise RuntimeError("行业指数数据为空，可能 IP 超限或接口不可用")

    # 将 trade_date 统一转为 date 对象（兼容 YYYYMMDD / YYYY-MM-DD）
    for r in rows:
        r["trade_date"] = _parse_date(r["trade_date"])

    # batch upsert（替代逐行 SELECT + UPDATE/INSERT）
    with db_session() as db:
        sql = sa_text("""
            INSERT INTO industry_index_daily (code, name, trade_date, open, high, low, close, pct_chg, vol, amount)
            VALUES (:code, :name, :trade_date, :open, :high, :low, :close, :pct_chg, :vol, :amount)
            ON CONFLICT (code, trade_date) DO UPDATE SET
                name=excluded.name, open=excluded.open, high=excluded.high,
                low=excluded.low, close=excluded.close, pct_chg=excluded.pct_chg,
                vol=excluded.vol, amount=excluded.amount
        """)
        db.execute(sql, rows)

    # 用实际写入数据的最大日期写水位（非请求 end_date），避免数据未就绪时水位虚高
    actual_max = max(r["trade_date"] for r in rows).strftime("%Y%m%d") if rows else end_date
    write_watermark("industry_index", "all", actual_max, t_start, "success")

    log.info("industry_index_synced", count=len(rows))
    return {"rows": len(rows)}
