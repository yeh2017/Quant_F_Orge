"""
统一名称解析工具
================
覆盖股票/ETF/可转债三类资产，从本地 DB 批量查询 code → name 映射。
所有需要 code→name 的模块统一调用此函数，不再各自查表。"""
import structlog
from typing import Dict, List

log = structlog.get_logger("name_resolver")


def resolve_names(codes: List[str]) -> Dict[str, str]:
    """批量查询资产名称映射 {code: name}，覆盖股票/ETF/可转债

    优先级: StockBasicInfo > ConvertibleBondBasic > EtfBasicInfo
    自动建立6位纯数字→名称的冗余映射，适配不同代码格式。
    """
    if not codes:
        return {}

    from core.database import db_session
    from models.quant_data import StockBasicInfo

    name_map: Dict[str, str] = {}

    try:
        with db_session() as db:
            # 同时匹配原始代码和6位代码
            all_codes = list(set(codes + [c.split('.')[0] for c in codes]))

            # 1. 股票
            rows = db.query(StockBasicInfo.code, StockBasicInfo.name).filter(
                StockBasicInfo.code.in_(all_codes)
            ).all()
            for r in rows:
                if r[1]:
                    name_map[r[0]] = r[1]

            # 2. 可转债
            try:
                from models.quant_data import ConvertibleBondBasic
                bond_rows = db.query(ConvertibleBondBasic.code, ConvertibleBondBasic.name).filter(
                    ConvertibleBondBasic.code.in_(all_codes)
                ).all()
                for r in bond_rows:
                    if r[1] and r[0] not in name_map:
                        name_map[r[0]] = r[1]
            except Exception as e:
                log.debug("bond_name_query_skipped", error=str(e))

            # 3. ETF
            try:
                from models.quant_data import EtfBasicInfo
                etf_rows = db.query(EtfBasicInfo.code, EtfBasicInfo.name).filter(
                    EtfBasicInfo.code.in_(all_codes)
                ).all()
                for r in etf_rows:
                    if r[1] and r[0] not in name_map:
                        name_map[r[0]] = r[1]
            except Exception as e:
                log.debug("etf_name_query_skipped", error=str(e))

            # 建立6位→名称映射
            for code, name in list(name_map.items()):
                clean = code.split('.')[0]
                if clean not in name_map:
                    name_map[clean] = name
    except (AttributeError, TypeError):
        raise
    except Exception as e:
        log.debug("resolve_names_failed", error=str(e))

    return name_map


def resolve_name(code: str) -> str:
    """单个代码→名称查询，未找到时返回代码本身"""
    result = resolve_names([code])
    return result.get(code, result.get(code.split('.')[0], code))
