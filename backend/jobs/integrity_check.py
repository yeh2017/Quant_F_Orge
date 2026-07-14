"""
数据完整性校验
==============
从 data_sync_service.py 提取的 full_sync 后校验逻辑。
"""
import structlog
from core.database import db_session

log = structlog.get_logger("integrity_check")


def run_integrity_check(step_reports: list):
    """
    full_sync 完成后的数据完整性校验（<1 秒）。
    将校验结果追加到 step_reports 列表。
    """
    from sqlalchemy import text as _vtext

    checks = [
        ("stock_basic_info",    "is_active = 1", "活跃股票", None),
        ("stock_daily_bars",    "1=1", "行情日线",   "trade_date"),
        ("stock_daily_factors", "1=1", "日线因子",   "trade_date"),
        ("stock_financials",    "1=1", "财务报表",   "report_date"),
        ("stock_money_flow",    "1=1", "资金流向",   "trade_date"),
        # ETF / 转债 / 行业（v2 审计补充）
        ("etf_basic_info",            "is_active = 1", "活跃ETF",  None),
        ("etf_daily_bars",            "1=1", "ETF日线",  "trade_date"),
        ("convertible_bond_basic",    "listed = 1",  "在市转债", None),
        ("convertible_bond_factor",   "1=1", "转债因子", "trade_date"),
        ("industry_index_daily",      "1=1", "行业指数", "trade_date"),
    ]
    verify_parts = []

    try:
        with db_session() as db:
            for table, where, label, date_col in checks:
                try:
                    cnt = db.execute(_vtext(f"SELECT COUNT(*) FROM {table} WHERE {where}")).scalar() or 0
                    if date_col:
                        mx = db.execute(_vtext(f"SELECT MAX({date_col}) FROM {table}")).scalar()
                        mx_str = str(mx) if mx else "无"
                        verify_parts.append(f"{label}: {cnt:,}条 (最新{mx_str})")
                    else:
                        verify_parts.append(f"{label}: {cnt:,}")
                except Exception as e:
                    verify_parts.append(f"{label}: 查询失败")
                    log.warning("integrity_check_item_failed", table=table, error=str(e))

            # 覆盖率
            bar_cnt = db.execute(_vtext(
                "SELECT COUNT(DISTINCT code) FROM stock_daily_bars "
                "WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_bars)"
            )).scalar() or 0
            basic_cnt = db.execute(_vtext(
                "SELECT COUNT(*) FROM stock_basic_info WHERE is_active = 1"
            )).scalar() or 0

        coverage = round(bar_cnt / basic_cnt * 100) if basic_cnt > 0 else 0
        if coverage >= 80:
            step_reports.append(f"🔍 校验通过: 覆盖率{coverage}% ({bar_cnt}/{basic_cnt})")
        elif coverage >= 50:
            step_reports.append(f"⚠️ 校验警告: 覆盖率{coverage}% ({bar_cnt}/{basic_cnt})")
        else:
            step_reports.append(f"🔴 校验异常: 覆盖率仅{coverage}% ({bar_cnt}/{basic_cnt})")
        log.info("integrity_check", coverage_pct=coverage, detail=verify_parts)

    except Exception as vc_err:
        log.warning("integrity_check_failed", error=str(vc_err))


def run_quality_check(step_reports: list):
    """关键字段 NULL 比例检查，追加到 step_reports。"""
    from sqlalchemy import text as _vtext

    quality_warnings = []

    try:
        with db_session() as db:
            # 股票因子质量
            factor_total = db.execute(_vtext(
                "SELECT COUNT(*) FROM stock_daily_factors "
                "WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_factors)"
            )).scalar() or 0
            if factor_total > 0:
                for col, label in [("pe_ttm", "PE_TTM"), ("pb", "PB"), ("turnover_rate", "换手率")]:
                    null_cnt = db.execute(_vtext(
                        f"SELECT COUNT(*) FROM stock_daily_factors "
                        f"WHERE trade_date = (SELECT MAX(trade_date) FROM stock_daily_factors) "
                        f"AND {col} IS NULL"
                    )).scalar() or 0
                    pct = round(null_cnt / factor_total * 100, 1)
                    if pct > 50:
                        quality_warnings.append(f"股票 {label} NULL {pct}%")

            # 可转债因子质量
            bond_total = db.execute(_vtext(
                "SELECT COUNT(*) FROM convertible_bond_factor "
                "WHERE trade_date = (SELECT MAX(trade_date) FROM convertible_bond_factor)"
            )).scalar() or 0
            if bond_total > 0:
                for col, label in [("premium_ratio", "溢价率"), ("double_low_score", "双低分"), ("rating", "评级")]:
                    null_cnt = db.execute(_vtext(
                        f"SELECT COUNT(*) FROM convertible_bond_factor "
                        f"WHERE trade_date = (SELECT MAX(trade_date) FROM convertible_bond_factor) "
                        f"AND {col} IS NULL"
                    )).scalar() or 0
                    pct = round(null_cnt / bond_total * 100, 1)
                    if pct > 30:
                        quality_warnings.append(f"转债因子 {label} NULL {pct}%")

            # 可转债基本信息质量（数据源回补盲区检测）
            bond_basic_total = db.execute(_vtext(
                "SELECT COUNT(*) FROM convertible_bond_basic WHERE listed = 1"
            )).scalar() or 0
            if bond_basic_total > 0:
                for col, label in [("rating", "评级"), ("issue_date", "发行日期"), ("underlying_code", "正股代码")]:
                    null_cnt = db.execute(_vtext(
                        f"SELECT COUNT(*) FROM convertible_bond_basic "
                        f"WHERE listed = 1 AND {col} IS NULL"
                    )).scalar() or 0
                    pct = round(null_cnt / bond_basic_total * 100, 1)
                    if pct > 5:
                        quality_warnings.append(f"转债基础 {label} NULL {pct}%")

        if quality_warnings:
            warn_msg = "⚠️ 数据质量: " + ", ".join(quality_warnings)
            step_reports.append(warn_msg)
            log.warning("data_quality_warning", issues=quality_warnings)
        else:
            step_reports.append("🔍 数据质量正常")

    except Exception as e:
        log.warning("quality_check_failed", error=str(e))
