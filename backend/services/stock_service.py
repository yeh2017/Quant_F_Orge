import structlog
log = structlog.get_logger(__name__)

"""
股票服务层
统一管理多数据源，提供股票信息查询
支持数据验证和数据源容错
"""

from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import pandas as pd
from data_sources import (
    DataSourceBase, AkShareSource, BaostockSource, TushareSource
)
from utils.cache_manager import cache_data
from utils.data_validator import DataValidator



class StockService:
    """股票服务"""
    
    def __init__(self):
        self._sources: Dict[str, DataSourceBase] = {}
        self._current_source: str = "tushare"  # Tushare Pro 作为首选主力数据源

        self._enable_validation: bool = True
        self._initialize_sources()

    
    def _initialize_sources(self):
        """初始化所有数据源（带超时保护，防止 SSL 环境下启动卡死）"""
        source_classes = [
            ("akshare", AkShareSource),
            ("tushare", TushareSource),
            ("baostock", BaostockSource),
        ]
        
        for name, cls in source_classes:
            if cls is None:
                continue
            try:
                # 用线程超时保护，防止构造函数中的网络调用卡死
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(cls)
                    source = future.result(timeout=8)
                    self._sources[name] = source
            except FuturesTimeoutError:
                log.warning("source_init_timeout", source=name, timeout=8)
            except Exception as e:
                log.warning("source_init_failed", source=name, error=str(e))
    
    def get_current_source(self) -> Optional[DataSourceBase]:
        """获取当前数据源"""
        return self._sources.get(self._current_source)

    def validate_stock_code(self, code: str) -> Dict[str, Any]:
        """验证股票代码"""
        source = self.get_current_source()
        if not source:
            return {"valid": False, "error": "数据源未初始化"}
        
        is_valid = source.validate_stock_code(code)
        if not is_valid:
            return {"valid": False, "error": "股票代码格式无效"}
        
        return {"valid": True}
    
    def validate_bond_code(self, code: str) -> Dict[str, Any]:
        """验证可转债代码"""
        source = self.get_current_source()
        if not source:
            return {"valid": False, "error": "数据源未初始化"}
        
        is_valid = source.validate_bond_code(code)
        if not is_valid:
            return {"valid": False, "error": "可转债代码格式无效"}
        
        return {"valid": True}
    
    def _call_with_timeout(self, func, timeout_sec: int = 10):
        """带超时保护的函数调用，防止数据源 SSL 卡死"""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func)
            try:
                return future.result(timeout=timeout_sec)
            except FuturesTimeoutError:
                log.warning("call_with_timeout_expired", timeout=timeout_sec)
                return None
            except (AttributeError, TypeError):
                raise  # 代码 bug，不能静默
            except Exception as e:
                log.warning("call_with_timeout_error", error=str(e))
                return None

    @cache_data(expire_days=7)
    def get_stock_info(self, code: str, fast: bool = False) -> Optional[Dict[str, Any]]:
        """获取股票信息（优先读本地 StockBasicInfo 表，未命中则 fallback API）"""
        from utils.asset_type import to_ts_code
        resolved_code = to_ts_code(code)
        
        # --- 优先读本地 SQLite ---
        try:
            from core.database import db_session
            from models.quant_data import StockBasicInfo
            with db_session() as db:
                row = db.query(StockBasicInfo).filter(StockBasicInfo.code == resolved_code).first()
                if row:
                    return {
                        "code": code,
                        "name": row.name or f"股票-{code}",
                        "industry": row.industry or "",
                        "market": row.market or "",
                    }
        except Exception as e:
            log.warning("stock_info_local_failed", error=str(e))
        
        # --- Fallback: 原始 API 逻辑 ---
        fallback_order = [self._current_source] + [
            s for s in ["tushare", "baostock", "akshare"]
            if s != self._current_source and s in self._sources
        ]
        
        result = None
        max_attempts = 2  # 最多尝试 2 个源，避免卡太久
        attempts = 0
        for source_name in fallback_order:
            if attempts >= max_attempts:
                break
            source = self._sources.get(source_name)
            if not source:
                continue
            attempts += 1
            try:
                info = self._call_with_timeout(lambda s=source: s.get_stock_info(code), timeout_sec=5)
                if info:
                    result = info.model_dump()
                    break
            except (AttributeError, TypeError) as e:
                log.warning("source_fallback_code_error", source=source_name, code=code, error=str(e))
                continue
            except Exception:
                continue
        
        if not result:
            return None
        
        # 行业补全（快速模式跳过，普通模式限 1 个源 + 3s 超时）
        if not fast and result.get("industry") in (None, "", "未知"):
            for name in ["tushare", "baostock"]:
                if name == self._current_source or name not in self._sources:
                    continue
                try:
                    other_info = self._call_with_timeout(
                        lambda s=self._sources[name]: s.get_stock_info(code),
                        timeout_sec=3
                    )
                    if other_info:
                        industry = other_info.model_dump().get("industry", "")
                        if industry and industry != "未知":
                            result["industry"] = industry
                            break
                except (AttributeError, TypeError) as e:
                    log.warning("industry_fallback_code_error", code=code, error=str(e))
                    continue
                except Exception:
                    continue
        
        return result
    
    # @cache_data(expire_days=1) - 由于走本地 SQLite，不再需要基于内存的 @cache_data
    def get_stock_history(
        self, 
        code: str, 
        start_date: str, 
        end_date: str,
        adjust: str = "qfq",
        validate: bool = True,
        use_fallback: bool = True
    ) -> Optional[List[Dict[str, Any]]]:
        """
        获取股票历史行情 (重构为直读本地 SQLite 数据中台)
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            adjust: 复权类型 (本地入库时默认已经是 qfq，如果不是可以自行转换)
            validate: 是否验证数据质量
            use_fallback: 是否启用数据源容错(已弃用，本地强制直读)
        """
        from core.database import db_session
        from utils.bar_query import get_bar_model
        
        log.warning(f"[StockService] {code}: 极速读取本地数仓 ({start_date} -> {end_date})")
        with db_session() as db:
            try:
                # 根据 code 自动选择 StockDailyBar 或 EtfDailyBar
                BarModel = get_bar_model(code)

                # 代码规范化：使用 to_db_code 按资产类型转为 DB 格式
                # 可转债在 DB 中存纯 6 位码，股票/ETF 带后缀
                from utils.bar_query import to_db_code
                resolved_code = to_db_code(code)

                # 极速索引查询
                query = db.query(BarModel).filter(
                    BarModel.code == resolved_code,
                    BarModel.trade_date >= start_date,
                    BarModel.trade_date <= end_date
                ).order_by(BarModel.trade_date)

                # 使用 pandas 一次性转化为 DataFrame，符合下层处理习惯
                statements = query.statement
                df = pd.read_sql(statements, db.bind)

                if df is None or df.empty:
                    log.info("stock_local_empty", code=code)
                    return None
                    
                # 将列名复原回历史兼容的名字
                rename_map = {'trade_date': 'date'}
                # 可转债 ConvertibleBondBar 字段名是 turnover，统一映射为 amount
                if 'turnover' in df.columns and 'amount' not in df.columns:
                    rename_map['turnover'] = 'amount'
                df = df.rename(columns=rename_map)
                df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

                # ---- 复权处理（数据库存的是不复权原价）----
                price_cols = ['open', 'high', 'low', 'close']
                if adjust in ("qfq", "hfq") and len(df) > 1:
                    df = df.sort_values('date').reset_index(drop=True)

                    has_adj = 'adj_factor' in df.columns and df['adj_factor'].notna().sum() > 0
                    if has_adj:
                        adj = df['adj_factor'].ffill().fillna(1.0)
                    elif 'pre_close' in df.columns:
                        # pre_close 路径：拆分/分红日 pre_close < prev_close
                        # 用 prev_close / pre_close 使 adj 递增，与 adj_factor 方向一致
                        adj = pd.Series(1.0, index=df.index)
                        for i in range(1, len(df)):
                            prev_close = float(df.loc[i - 1, 'close'])  # pyrefly: ignore  # Scalar→float, columns are numeric
                            cur_pre = float(df.loc[i, 'pre_close'])  # pyrefly: ignore  # Scalar→float, columns are numeric
                            if prev_close and cur_pre and cur_pre > 0:
                                adj.iloc[i] = adj.iloc[i - 1] * (prev_close / cur_pre)
                            else:
                                adj.iloc[i] = adj.iloc[i - 1]
                    else:
                        adj = None

                    if adj is not None:
                        if adjust == "qfq":
                            factor = adj / adj.iloc[-1]
                        else:
                            factor = adj / adj.iloc[0]
                        for col in price_cols:
                            if col in df.columns:
                                df[col] = (df[col] * factor).round(2)

                # ---- 换手率：仅股票有（LEFT JOIN StockDailyFactor）----
                if BarModel.__tablename__ == 'stock_daily_bars':
                    try:
                        from models.quant_data import StockDailyFactor
                        factor_df = pd.read_sql(
                            db.query(
                                StockDailyFactor.trade_date,
                                StockDailyFactor.turnover_rate,
                            ).filter(
                                StockDailyFactor.code == resolved_code,
                                StockDailyFactor.trade_date >= start_date,
                                StockDailyFactor.trade_date <= end_date,
                            ).statement,
                            db.bind,
                        )
                        if not factor_df.empty:
                            factor_df['date'] = pd.to_datetime(factor_df['trade_date']).dt.strftime('%Y-%m-%d')
                            df = df.merge(factor_df[['date', 'turnover_rate']], on='date', how='left')
                    except Exception as e:
                        log.debug("turnover_join_skip", error=str(e))

                # 验证数据和清洗
                if validate and self._enable_validation:
                    df, warnings = DataValidator.validate_and_clean(df, code)
                    if warnings:
                        log.warning(f"[DataValidator] {code} 数据质量警告: {len(warnings)} 条")
                
                result = df.to_dict('records') if df is not None and not df.empty else None
                if result:
                    log.warning(f"[StockService] {code}: 成功从本地获取 {len(result)} 条数据 (复权={adjust})")
                return result
            except Exception as e:
                log.warning(f"[StockService] {code} 读取本地库出错: {e}")
                return None

    
    @cache_data(expire_days=7)
    def get_stock_list(self) -> List[Dict[str, Any]]:
        """获取股票列表（优先读本地 StockBasicInfo 表）"""
        # --- 优先读本地 ---
        try:
            from core.database import db_session
            from models.quant_data import StockBasicInfo
            with db_session() as db:
                rows = db.query(StockBasicInfo).filter(StockBasicInfo.is_active == True).all()
                if rows and len(rows) > 10:
                    return [{
                        "code": r.code.split('.')[0] if '.' in r.code else r.code,
                        "name": r.name or "",
                        "industry": r.industry or "未知",
                        "market": r.market or "未知",
                    } for r in rows]
        except Exception as e:
            log.warning(f"[StockService] 本地查询 stock_list 失败: {e}")
        
        # --- Fallback ---
        source = self.get_current_source()
        if not source:
            return []
        stocks = source.get_stock_list()
        return [s.model_dump() for s in stocks]
    
    @cache_data(expire_days=15)
    def get_financial_data(self, code: str, fast: bool = False) -> Optional[Dict[str, Any]]:
        """获取财务数据（优先读本地 StockFinancial 表，未命中则 fallback API）"""
        from utils.asset_type import to_ts_code
        resolved_code = to_ts_code(code)
        # --- 优先读本地 SQLite ---
        try:
            from core.database import db_session
            from models.quant_data import StockFinancial
            with db_session() as db:
                query = db.query(StockFinancial).filter(StockFinancial.code == resolved_code)
                row = query.order_by(StockFinancial.report_date.desc()).first()
                if row:
                    result = {
                        "code": code,
                        "roe": row.roe,
                        "roa": row.roa,
                        "gross_profit_margin": row.gross_profit_margin,
                        "net_profit_margin": row.net_profit_margin,
                        "revenue_yoy": row.revenue_yoy,
                        "net_profit_yoy": row.net_profit_yoy,
                        "eps": row.eps,
                    }
                    # 排除全 None 的无效行
                    if any(v is not None for k, v in result.items() if k != "code"):
                        return result
        except Exception as e:
            log.warning(f"[StockService] 本地查询 financial 失败: {e}")
        
        # --- Fallback: 原始 API 逻辑 ---
        source = self.get_current_source()
        result = source.get_financial_data(code) if source else None
        
        key_fields = ["roe", "roa", "gross_profit_margin", "net_profit_margin",
                       "revenue_yoy", "net_profit_yoy", "eps"]
        missing = [f for f in key_fields if not result or not result.get(f)]
        
        if missing and not fast:
            for name in ["baostock"]:  # AkShare 财务数据质量差，已移除
                if name == self._current_source or name not in self._sources:
                    continue
                try:
                    extra = self._sources[name].get_financial_data(code)
                    if extra:
                        if result is None:
                            result = {"code": code}
                        for f in list(missing):
                            val = extra.get(f)
                            if val:
                                result[f] = val
                                missing.remove(f)
                        if not missing:
                            break
                except (AttributeError, TypeError) as e:
                    log.warning("financial_fallback_code_error", code=code, error=str(e))
                    continue
                except Exception:
                    continue
        
        return result
    
    @cache_data(expire_days=1)
    def get_tushare_daily_basic(self, code: str, trade_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取每日核心估值指标（优先读本地 StockDailyFactor 表）"""
        from utils.asset_type import to_ts_code
        resolved_code = to_ts_code(code)
        result = None
        
        # --- 优先读本地 SQLite ---
        try:
            from core.database import db_session
            from models.quant_data import StockDailyFactor
            with db_session() as db:
                query = db.query(StockDailyFactor).filter(StockDailyFactor.code == resolved_code)
                
                if trade_date:
                    query = query.filter(StockDailyFactor.trade_date <= trade_date)
                
                row = query.order_by(StockDailyFactor.trade_date.desc()).first()
                if row:
                    return {
                        "pe_ttm": row.pe_ttm,
                        "pb": row.pb,
                        "pe": row.pe,
                        "ps_ttm": row.ps_ttm,
                        "turnover_rate": row.turnover_rate,
                        "total_mv": row.total_mv,
                        "circ_mv": row.circ_mv,
                        "dv_ratio": row.dv_ratio,
                        "dv_ttm": row.dv_ttm,
                    }
        except Exception as e:
            log.warning("daily_basic_local_failed", error=str(e))
        
        # --- Fallback: Tushare API ---
        try:
            if "tushare" in self._sources:
                ts_source = self._sources["tushare"]
                if ts_source._is_api_available("daily_basic"):
                    ts_code = ts_source._format_ts_code(code)
                    kwargs = {"ts_code": ts_code}
                    if trade_date:
                        kwargs["trade_date"] = trade_date.replace("-", "")
                    df = ts_source.pro.daily_basic(**kwargs)
                    if df is not None and not df.empty:
                        df = df.sort_values("trade_date", ascending=False)
                        result = df.iloc[0].to_dict()
        except Exception as e:
            err_str = str(e)
            if "权限" in err_str or "积分" in err_str:
                self._sources["tushare"]._mark_api_unavailable("daily_basic", err_str)
            log.warning("tushare_daily_basic_api_error", error=str(e))
        
        # 降级：从财务数据中提取 PE/PB
        if result is None:
            try:
                financial = self.get_financial_data(code, fast=True)
                if financial:
                    fallback = {}
                    pe_val = financial.get("pe_ttm") or financial.get("pe")
                    if pe_val:
                        fallback["pe_ttm"] = float(pe_val)
                    pb_val = financial.get("pb")
                    if pb_val:
                        fallback["pb"] = float(pb_val)
                    if fallback:
                        result = fallback
            except (AttributeError, TypeError):
                raise
            except Exception as e:
                log.warning("daily_basic_fallback_failed", error=str(e))
        return result
            


    # ==================== 指数权重 ====================

    # ==================== 情绪因子（委托 SentimentService）====================

    def _get_sentiment_svc(self):
        """惰性初始化情绪因子服务"""
        if not hasattr(self, '_sentiment_svc'):
            from services.sentiment_service import SentimentService
            self._sentiment_svc = SentimentService(self._sources)
        return self._sentiment_svc

    def get_sentiment_factors(self, code: str):
        return self._get_sentiment_svc().get_sentiment_factors(code)

    def get_tushare_forecast(self, code: str):
        return self._get_sentiment_svc().get_tushare_forecast(code)

    def get_tushare_moneyflow(self, code: str, days: int = 3):
        return self._get_sentiment_svc().get_tushare_moneyflow(code, days)

    def get_akshare_market_forecast(self):
        return self._get_sentiment_svc().get_akshare_market_forecast()

    def get_etf_info(self, code: str) -> Optional[Dict[str, Any]]:
        """获取 ETF 信息（从本地 EtfBasicInfo 表查询）"""
        from utils.asset_type import to_ts_code
        resolved_code = to_ts_code(code)
        try:
            from core.database import db_session
            from models.quant_data import EtfBasicInfo
            with db_session() as db:
                row = db.query(EtfBasicInfo).filter(EtfBasicInfo.code == resolved_code).first()
                if row:
                    return {
                        "code": row.code,
                        "name": row.name or f"ETF-{code}",
                        "category": getattr(row, 'category', '') or '',
                        "market": row.code.split('.')[-1] if '.' in row.code else '',
                    }
        except Exception as e:
            log.warning("etf_info_local_failed", error=str(e))
        return None

    def get_bond_info(self, code: str) -> Optional[Dict[str, Any]]:
        """获取可转债信息（当前源不支持时自动 fallback 到 akshare/tushare）"""
        source = self.get_current_source()
        if source:
            info = source.get_bond_info(code)
            if info:
                return info.model_dump()
        
        # 当前源不支持可转债，尝试其他数据源
        bond_sources = ["tushare", "akshare"]
        for name in bond_sources:
            if name == self._current_source or name not in self._sources:
                continue
            try:
                info = self._sources[name].get_bond_info(code)
                if info:
                    log.info("bond_source_fallback_ok", code=code, source=name)
                    return info.model_dump()
            except (AttributeError, TypeError) as e:
                log.warning("bond_info_fallback_code_error", code=code, error=str(e))
                continue
            except Exception:
                continue
        return None
    
    @cache_data(expire_days=7)
    def get_bond_list(self) -> List[Dict[str, Any]]:
        """获取可转债列表（优先读本地 ConvertibleBondBasic 表；未入库则 fallback 实时 API）"""
        try:
            from core.database import db_session
            from models.quant_data import ConvertibleBondBasic
            with db_session() as db:
                rows = db.query(ConvertibleBondBasic).filter(ConvertibleBondBasic.listed == True).all()
                if rows and len(rows) > 10:
                    return [{
                        "code": r.code,
                        "name": r.name or f"可转债-{r.code}",
                        "underlying_code": r.underlying_code or "",
                        "underlying_name": r.underlying_name or "",
                        "rating": r.rating or "",
                    } for r in rows]
        except Exception as e:
            log.warning("bond_list_local_query_failed", error=str(e))

        # fallback: 实时 API
        source = self.get_current_source()
        if source:
            bonds = source.get_bond_list()
            if bonds:
                return [b.model_dump() for b in bonds]

        for name in ["tushare", "akshare"]:
            if name == self._current_source or name not in self._sources:
                continue
            try:
                bonds = self._sources[name].get_bond_list()
                if bonds:
                    return [b.model_dump() for b in bonds]
            except (AttributeError, TypeError) as e:
                log.warning("bond_list_fallback_code_error", error=str(e))
                continue
            except Exception:
                continue
        return []
    
    def search_stocks(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索股票（包含退市股并标注）"""
        try:
            from core.database import db_session
            from models.quant_data import StockBasicInfo
            kw = keyword.lower()
            active_results, inactive_results = [], []
            with db_session() as db:
                for rec in db.query(StockBasicInfo).all():
                    code_short = rec.code.split('.')[0] if '.' in rec.code else rec.code
                    if kw in code_short.lower() or kw in (rec.name or '').lower():
                        item = {
                            "code": code_short,
                            "name": rec.name or "",
                            "industry": rec.industry or "未知",
                            "market": rec.market or "未知",
                            "listed": rec.is_active,
                        }
                        if rec.is_active:
                            active_results.append(item)
                        else:
                            inactive_results.append(item)
                        if len(active_results) + len(inactive_results) >= 20:
                            break
            return active_results + inactive_results
        except Exception as e:
            log.warning("search_stocks_db_failed", error=str(e))
            # 降级到原逻辑（仅在市）
            all_stocks = self.get_stock_list()
            results = []
            keyword = keyword.lower()
            for stock in all_stocks:
                if keyword in stock['code'].lower() or keyword in stock['name'].lower():
                    results.append(stock)
                    if len(results) >= 20:
                        break
            return results
    
    def search_bonds(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索可转债（按代码或名称模糊匹配，包含退市债并标注）"""
        try:
            from core.database import db_session
            from models.quant_data import ConvertibleBondBasic
            kw = keyword.lower()
            listed_results, delisted_results = [], []
            with db_session() as db:
                for rec in db.query(ConvertibleBondBasic).all():
                    if kw in (rec.code or '').lower() or kw in (rec.name or '').lower():
                        item = {
                            "code": rec.code,
                            "name": rec.name or f"可转债-{rec.code}",
                            "underlying_code": rec.underlying_code or "",
                            "underlying_name": rec.underlying_name or "",
                            "rating": rec.rating or "",
                            "listed": rec.listed,
                        }
                        if rec.listed:
                            listed_results.append(item)
                        else:
                            delisted_results.append(item)
                        if len(listed_results) + len(delisted_results) >= 20:
                            break
            # 在市的排前面，退市的排后面
            return listed_results + delisted_results
        except Exception as e:
            log.warning("search_bonds_failed", error=str(e))
            # 降级到原逻辑
            all_bonds = self.get_bond_list()
            results = []
            keyword = keyword.lower()
            for bond in all_bonds:
                if keyword in bond['code'].lower() or keyword in bond['name'].lower():
                    results.append(bond)
                    if len(results) >= 20:
                        break
            return results

    def search_etf(self, keyword: str) -> List[Dict[str, Any]]:
        """搜索 ETF（包含已终止 ETF 并标注）"""
        try:
            from core.database import db_session
            from models.quant_data import EtfBasicInfo
            kw = keyword.lower()
            active_results, inactive_results = [], []
            with db_session() as db:
                for row in db.query(EtfBasicInfo).all():
                    code = row.code or ''
                    name = row.name or ''
                    if kw in code.lower() or kw in name.lower():
                        item = {
                            "code": code, "name": name,
                            "category": row.category or '',
                            "listed": row.is_active,
                        }
                        if row.is_active:
                            active_results.append(item)
                        else:
                            inactive_results.append(item)
                        if len(active_results) + len(inactive_results) >= 20:
                            break
            return active_results + inactive_results
        except Exception as e:
            log.warning("search_etf_failed", error=str(e))
            return []
