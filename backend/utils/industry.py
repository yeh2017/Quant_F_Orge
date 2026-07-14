"""
行业分类桥接工具
================
系统存在两套行业分类体系：
  - Tushare sub-industry（110 个，如 "房产服务"）→ StockBasicInfo.industry
  - 申万 L1（31 个，如 "房地产"）→ SwIndustry.sw_l1_name

本模块提供统一查询接口，任何需要按行业过滤股票的地方都应使用此模块，
而不是直接写 StockBasicInfo.industry == xxx。
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models.quant_data import StockBasicInfo, SwIndustry


def industry_filter(db: Session, industries: list[str]):
    """
    构建行业过滤 SQLAlchemy 条件，自动兼容 Tushare sub 和申万 L1。

    Args:
        db: SQLAlchemy Session
        industries: 行业名称列表（可混传两套体系）

    Returns:
        SQLAlchemy BooleanClauseList，可直接传给 query.filter()

    Usage:
        query = query.filter(industry_filter(db, ["房地产", "煤炭开采"]))
    """
    ts_sub_set = set(
        r[0] for r in db.query(StockBasicInfo.industry).distinct().all() if r[0]
    )
    conditions = []
    direct = [i for i in industries if i in ts_sub_set]
    if direct:
        conditions.append(StockBasicInfo.industry.in_(direct))
    # 所有名称都尝试申万匹配（覆盖重叠名称如"家用电器"）
    sw_codes_q = db.query(SwIndustry.code).filter(
        SwIndustry.sw_l1_name.in_(industries), SwIndustry.out_date.is_(None)
    )
    conditions.append(StockBasicInfo.code.in_(sw_codes_q))
    return or_(*conditions)


def get_industry_codes(db: Session, industry: str) -> set[str]:
    """
    获取某个行业下的所有股票代码集合，自动兼容两套体系。

    Args:
        db: SQLAlchemy Session
        industry: 单个行业名称

    Returns:
        股票代码 set
    """
    codes = set()
    # Tushare sub-industry
    ts_codes = {
        r[0] for r in
        db.query(StockBasicInfo.code).filter(StockBasicInfo.industry == industry).all()
    }
    codes.update(ts_codes)
    # 申万 L1
    sw_codes = {
        r[0] for r in
        db.query(SwIndustry.code).filter(
            SwIndustry.sw_l1_name == industry, SwIndustry.out_date.is_(None)
        ).all()
    }
    codes.update(sw_codes)
    return codes
