import structlog
log = structlog.get_logger(__name__)


def validate_tushare_fields(df, expected_fields, api_name="unknown"):
    """检查 Tushare 返回的 DataFrame 是否包含所有请求的字段。
    
    防止字段名拼写错误导致数据静默丢失（Tushare 不报错，只是不返回该列）。
    """
    if df is None or df.empty:
        return df
    actual = set(df.columns)
    missing = set(expected_fields) - actual
    if missing:
        log.error("tushare_fields_missing",
                  api=api_name,
                  missing=sorted(missing),
                  hint="字段名可能拼写错误，Tushare 不报错但不返回该列，导致数据静默丢失")
    return df

"""
Tushare 数据源实现
专业、准确、需要 Token
"""

import os
import time
import threading
import functools
from typing import Optional, List, Dict, Any
import pandas as pd
from .base import DataSourceBase, StockInfo, BondInfo
from utils.asset_type import to_ts_code, get_exchange


class _TushareRateLimiter:
    """全局令牌桶限流器 + 熔断保护

    参数集中管理于 settings.py，支持 .env 覆盖：
    - TUSHARE_RATE_LIMIT_PER_MIN: 令牌桶上限
    - TUSHARE_BREAKER_FAIL_THRESHOLD: 熔断触发阈值
    - TUSHARE_BREAKER_COOLDOWN: 熔断冷却秒数
    """
    from settings import (TUSHARE_RATE_LIMIT_PER_MIN,
                          TUSHARE_BREAKER_FAIL_THRESHOLD,
                          TUSHARE_BREAKER_COOLDOWN)

    _lock = threading.Lock()
    _call_times: list = []
    _max_calls_per_min = TUSHARE_RATE_LIMIT_PER_MIN

    # 熔断状态
    _consecutive_failures = 0
    _circuit_open_until = 0.0   # 熔断恢复时间戳
    _FAILURE_THRESHOLD = TUSHARE_BREAKER_FAIL_THRESHOLD
    _CIRCUIT_COOLDOWN = TUSHARE_BREAKER_COOLDOWN

    @classmethod
    def acquire(cls):
        """获取调用许可：超频阻塞 + 熔断检查"""
        with cls._lock:
            now = time.time()

            # 熔断状态检查
            if now < cls._circuit_open_until:
                wait = cls._circuit_open_until - now
                log.info("tushare_circuit_open", wait_secs=round(wait, 1))
                time.sleep(wait)

            # 令牌桶
            cls._call_times = [t for t in cls._call_times if now - t < 60]

            if len(cls._call_times) >= cls._max_calls_per_min:
                sleep_time = 60 - (now - cls._call_times[0]) + 0.1
                if sleep_time > 0:
                    log.warning(f"[Tushare RateLimiter] 达到频率上限 ({cls._max_calls_per_min}/min)，等待 {sleep_time:.1f}s")
                    time.sleep(max(sleep_time, 0.5))

            cls._call_times.append(time.time())

    @classmethod
    def report_success(cls):
        """报告成功调用，重置失败计数"""
        with cls._lock:
            cls._consecutive_failures = 0

    @classmethod
    def report_failure(cls):
        """报告失败调用，触发熔断检查"""
        with cls._lock:
            cls._consecutive_failures += 1
            if cls._consecutive_failures >= cls._FAILURE_THRESHOLD:
                cls._circuit_open_until = time.time() + cls._CIRCUIT_COOLDOWN
                cls._consecutive_failures = 0
                log.warning(f"[Tushare] 连续失败 {cls._FAILURE_THRESHOLD} 次，触发熔断 {cls._CIRCUIT_COOLDOWN}s")


def with_tushare_retry(max_retries=3, delay=1.2):
    """
    Tushare 接口调用重试装饰器。

    - 全局令牌桶限流
    - 指数退避: delay × 2^attempt
    - 熔断联动: 失败/成功自动汇报
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    _TushareRateLimiter.acquire()
                    result = func(*args, **kwargs)
                    _TushareRateLimiter.report_success()
                    # 统一消毒：pandas float 列中 NaN 是 truthy（bool(NaN)==True），
                    # 导致下游 `x or default` 失效。必须先 astype(object) 再 where，
                    # 否则 pandas 会把 None 自动转回 NaN（float 列不能存 None）。
                    if hasattr(result, 'where'):  # DataFrame / Series
                        result = result.astype(object).where(pd.notna(result), None)
                    return result
                except Exception as e:
                    err_str = str(e)

                    # IP 白名单超限：换 VPN 导致绑定 IP 超过上限，重试无用
                    is_ip_limit = any(kw in err_str for kw in ("IP", "ip", "白名单", "绑定"))
                    if is_ip_limit:
                        log.error("tushare_ip_whitelist_exceeded",
                                  error=err_str,
                                  hint="Tushare IP 白名单超限，请登录 tushare.pro → 个人中心 → 清空已绑定 IP")
                        _TushareRateLimiter.report_failure()
                        raise  # IP 限制重试无意义，直接抛出

                    is_rate_limit = any(kw in err_str for kw in ("最多访问", "每分钟", "频次"))

                    if is_rate_limit and attempt < max_retries - 1:
                        sleep_time = delay * (2 ** attempt)  # 指数退避
                        log.warning(f"[Tushare Retry] 触发频控，等待 {sleep_time:.1f}s 后第 {attempt+2} 次重试...")
                        _TushareRateLimiter.report_failure()
                        time.sleep(sleep_time)
                        continue

                    _TushareRateLimiter.report_failure()
                    raise
            return None
        return wrapper
    return decorator



class TushareSource(DataSourceBase):
    """Tushare 数据源"""
    
    name = "tushare"
    description = "Tushare - 专业金融数据接口（需Token）"
    requires_token = True
    
    # Tushare Pro 各接口积分需求（来源: https://tushare.pro/weborder/#/user/privilege）
    _API_POINTS = {
        # 120 积分（免费）
        "daily": 120, "adj_factor": 120, "stock_basic": 120,
        "trade_cal": 120, "fina_indicator": 120, "index_daily": 120,
        "forecast": 120, "express": 120, "limit_list": 120, "concept": 120,
        "fund_basic": 120, "fund_daily": 120, "fund_nav": 120, "fund_share": 120,
        "index_classify": 120, "index_member_all": 120,
        # 600 积分
        "stk_holdernumber": 600,
        # 2000 积分
        "daily_basic": 2000, "income": 2000, "balancesheet": 2000,
        "cashflow": 2000, "index_weight": 2000,
        # 5000 积分
        "cb_basic": 5000, "cb_daily": 5000,
        "moneyflow": 5000, "margin_detail": 5000,
        "block_trade": 5000, "share_float": 5000, "top_list": 5000,
    }
    _unavailable_apis: set = set()  # 缓存已确认不可用的接口，避免反复尝试
    
    def __init__(self, token: str = None):
        import tushare as ts
        self.ts = ts
        
        # 从参数或环境变量获取 Token
        self.token = token or os.getenv('TUSHARE_TOKEN', '')
        if self.token:
            ts.set_token(self.token)
            self.pro = ts.pro_api()
        else:
            self.pro = None
        
        self._stock_list_cache = None
    
    def _check_token(self) -> bool:
        """检查 Token 是否有效"""
        return self.pro is not None and bool(self.token)
    
    def _is_api_available(self, api_name: str) -> bool:
        """检查接口是否可用（基于缓存的不可用记录）"""
        return api_name not in self._unavailable_apis
    
    def _mark_api_unavailable(self, api_name: str, error: str):
        """标记接口为不可用（积分不足或权限不够），后续调用直接跳过"""
        self._unavailable_apis.add(api_name)
        pts = self._API_POINTS.get(api_name, "?")
        log.warning("tushare_api_unavailable", api=api_name, required_pts=pts, error=str(error)[:60])
    
    def _format_ts_code(self, code: str) -> str:
        """格式化为 Tushare 代码格式 (600519.SH)

        已带后缀 → 直接返回；纯 6 位码 → 由 to_ts_code() 按前缀规则补后缀。
        不再硬编码指数列表，避免 000001 被错误格式化为 .SH（应为 .SZ 平安银行）。
        """
        code = code.strip()
        if '.' in code:
            return code.upper()
        return to_ts_code(code)
    
    def get_stock_info(self, code: str) -> Optional[StockInfo]:
        """获取股票基本信息"""
        try:
            if not self._check_token():
                log.info("Tushare: Token not configured")
                return None
            
            code = code.strip()
            if not self.validate_stock_code(code):
                return None
            
            ts_code = self._format_ts_code(code)
            
            # 使用包装了重试逻辑的局部函数
            @with_tushare_retry()
            def _fetch():
                return self.pro.stock_basic(
                    ts_code=ts_code,
                    fields='ts_code,symbol,name,area,industry,market,list_date'
                )
            
            df = _fetch()
            
            if df is None or df.empty:
                return None
            
            row = df.iloc[0]
            
            # 确定市场
            market_map = {
                '主板': '主板',
                '中小板': '中小板', 
                '创业板': '创业板',
                '科创板': '科创板'
            }
            market = market_map.get(str(row.get('market', '')), '主板')
            exchange_label = '上交所' if get_exchange(code) == 'SH' else '深交所'
            market = f"{exchange_label}{market}"
            
            return StockInfo(
                code=code,
                name=str(row['name']),
                industry=str(row.get('industry', '') or '') or '未知',
                market=market,
                list_date=str(row.get('list_date', ''))
            )
        except Exception as e:
            log.warning("tushare_get_stock_info_error", error=str(e))
            return None
    
    def get_stock_history(
        self, 
        code: str, 
        start_date: str, 
        end_date: str,
        adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        """获取股票历史行情（仅股票，指数请用 get_industry_index_daily 或直接调 pro.index_daily）"""
        try:
            if not self._check_token():
                return None
            
            code = code.strip()
            if not self.validate_stock_code(code):
                return None
            
            ts_code = self._format_ts_code(code)
            
            @with_tushare_retry()
            def _fetch_history():
                return self.pro.daily(
                    ts_code=ts_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", "")
                )
                    
            df = _fetch_history()
            
            if df is None or df.empty:
                return None
            
            # 复权处理
            if adjust in ["qfq", "hfq"]:
                try:
                    @with_tushare_retry()
                    def _fetch_adj():
                        return self.pro.adj_factor(
                            ts_code=ts_code,
                            start_date=start_date.replace("-", ""),
                            end_date=end_date.replace("-", "")
                        )
                    adj_df = _fetch_adj()
                    if adj_df is not None and not adj_df.empty:
                        df = df.merge(adj_df[['trade_date', 'adj_factor']], on='trade_date', how='left')
                        # 注意：df 此时还未 sort_values，Tushare 返回倒序（最新在前）
                        # 前复权：以最新日因子为基准，iloc[0] = 最新日
                        if adjust == "qfq":
                            latest_factor = df['adj_factor'].dropna().iloc[0] if not df['adj_factor'].dropna().empty else 1.0
                            for col in ['open', 'high', 'low', 'close']:
                                df[col] = df[col] * df['adj_factor'] / latest_factor
                        elif adjust == "hfq":
                            # 后复权：直接乘以复权因子
                            for col in ['open', 'high', 'low', 'close']:
                                df[col] = df[col] * df['adj_factor']
                except Exception:
                    pass  # 复权失败则使用不复权数据
            
            # 统一列名
            df = df.rename(columns={
                'trade_date': 'date',
                'vol': 'volume'
            })
            
            # 日期格式转换
            df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
            
            # 按日期升序排列
            df = df.sort_values('date').reset_index(drop=True)
            
            columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            df = df[[c for c in columns if c in df.columns]]
            
            return df
        except Exception as e:
            log.warning("tushare_get_stock_history_error", error=str(e))
            return None
    
    def get_stock_list(self) -> List[StockInfo]:
        """获取全部股票列表"""
        try:
            if not self._check_token():
                return []
            
            if self._stock_list_cache is not None:
                return self._stock_list_cache
            
            @with_tushare_retry()
            def _fetch_stock_list():
                return self.pro.stock_basic(
                    exchange='',
                    list_status='L',
                    fields='ts_code,symbol,name,area,industry,market,list_date'
                )
                
            df = _fetch_stock_list()
            
            if df is None or df.empty:
                return []
            
            stocks = []
            for _, row in df.iterrows():
                code = str(row['symbol'])
                
                exchange = get_exchange(code)
                if exchange == 'SH':
                    market = "上交所"
                elif code.startswith('30'):
                    market = "创业板"
                elif code.startswith('68'):
                    market = "科创板"
                else:
                    market = "深交所"
                
                stocks.append(StockInfo(
                    code=code,
                    name=str(row['name']),
                    industry=str(row.get('industry', '') or '') or '未知',
                    market=market,
                    list_date=str(row.get('list_date', ''))
                ))
            
            self._stock_list_cache = stocks
            return stocks
        except Exception as e:
            log.warning("tushare_get_stock_list_error", error=str(e))
            return []
    
    def get_financial_data(self, code: str) -> Optional[Dict[str, Any]]:
        """获取财务数据"""
        try:
            if not self._check_token():
                return None
            
            ts_code = self._format_ts_code(code)
            
            @with_tushare_retry()
            def _fetch_fina():
                return self.pro.fina_indicator(
                    ts_code=ts_code,
                    fields='ts_code,end_date,roe,roa,grossprofit_margin,netprofit_margin,or_yoy,netprofit_yoy,eps'
                )
                
            # 获取财务指标
            df = _fetch_fina()
            
            if df is None or df.empty:
                return None
            
            latest = df.iloc[0]
            
            return {
                "code": code,
                "roe": float(latest.get('roe', 0) or 0),
                "roa": float(latest.get('roa', 0) or 0),
                "gross_profit_margin": float(latest.get('grossprofit_margin', 0) or 0),
                "net_profit_margin": float(latest.get('netprofit_margin', 0) or 0),
                "revenue_yoy": float(latest.get('or_yoy', 0) or 0),
                "net_profit_yoy": float(latest.get('netprofit_yoy', 0) or 0),
                "eps": float(latest.get('eps', 0) or 0),
            }
        except Exception as e:
            log.warning(f"Tushare get_financial_data error: {e}")
            return None
    
    def get_bond_info(self, code: str) -> Optional[BondInfo]:
        """获取可转债信息"""
        try:
            if not self._check_token():
                return None
            
            code = code.strip()
            if not self.validate_bond_code(code):
                return None
            
            # Tushare 可转债代码格式
            ts_code = to_ts_code(code)
            
            @with_tushare_retry()
            def _fetch_cb_basic():
                return self.pro.cb_basic(ts_code=ts_code)
                
            df = _fetch_cb_basic()
            
            if df is None or df.empty:
                return None
            
            row = df.iloc[0]
            # rating 优先用 Tushare 的 rating 字段（信用评级），fallback 到本地 DB
            credit_rating = row.get('rating') or None
            if not credit_rating or str(credit_rating) in ('nan', 'None', ''):
                try:
                    from core.database import db_session
                    from models.quant_data import ConvertibleBondBasic
                    with db_session() as _db:
                        local = _db.query(ConvertibleBondBasic.rating).filter(
                            ConvertibleBondBasic.code == code).scalar()
                        if local:
                            credit_rating = local
                except Exception:
                    pass

            # 正股名称补全：stk_short_name 缺失时从 StockBasicInfo 反查
            stk_name = row.get('stk_short_name')
            stk_code_raw = str(row.get('stk_code', '') or '').split('.')[0]
            if not stk_name or str(stk_name) in ('nan', 'None', ''):
                try:
                    from core.database import db_session
                    from models.quant_data import StockBasicInfo
                    with db_session() as _db:
                        stock_row = _db.query(StockBasicInfo.name).filter(
                            StockBasicInfo.code.like(f"{stk_code_raw}%")).first()
                        if stock_row and stock_row.name:
                            stk_name = stock_row.name
                except Exception:
                    pass
            if not stk_name or str(stk_name) in ('nan', 'None', ''):
                stk_name = stk_code_raw or '未知'

            return BondInfo(
                code=code,
                name=str(row.get('bond_short_name', '') or '') or f'转债-{code}',
                underlying_stock=str(stk_name),
                underlying_code=stk_code_raw,
                rating=str(credit_rating) if credit_rating else '-',
                maturity_date=str(row.get('maturity_date', ''))
            )
        except Exception as e:
            log.warning(f"Tushare get_bond_info error: {e}")
            return None
    
    def get_bond_list(self) -> List[BondInfo]:
        """获取可转债列表（委托 get_cb_basic，避免重复调用 pro.cb_basic）"""
        try:
            cb_list = self.get_cb_basic()
            if not cb_list:
                return []

            bonds = []
            for item in cb_list:
                bonds.append(BondInfo(
                    code=item.get("code", ""),
                    name=item.get("name") or f'转债-{item.get("code", "")}',
                    underlying_stock=item.get("underlying_name") or "未知",
                    underlying_code=item.get("underlying_code", "").split('.')[0],
                    rating=item.get("rating") or "-",
                ))

            return bonds
        except Exception as e:
            log.warning(f"Tushare get_bond_list error: {e}")
            return []

    def test_connection(self) -> bool:
        """测试连接是否正常"""
        try:
            if not self._check_token():
                return False
            
            @with_tushare_retry()
            def _test_cal():
                return self.pro.trade_cal(exchange='', start_date='20240101', end_date='20240105')
                
            # 尝试获取交易日历（轻量级接口）
            df = _test_cal()
            return df is not None and not df.empty
        except Exception as e:
            log.warning("tushare_test_connection_error", error=str(e))
            return False

    def get_cb_basic(self) -> List[Dict]:
        """
        获取全市场在市可转债基本信息。
        接口: pro.cb_basic()，需要 ≥2000 积分
        返回字段: code, name, underlying_code, underlying_name, rating,
                  issue_date, mature_date, face_value, convert_price, listed
        """
        if not self._check_token():
            return []
        try:
            @with_tushare_retry()
            def _call():
                return self.pro.cb_basic(
                    fields=[
                        "ts_code", "bond_short_name", "stk_code", "stk_short_name",
                        "rating_ent", "issue_date", "list_date", "delist_date", "maturity_date",
                        "par_value", "conv_price", "first_conv_price", "list_price",
                    ],
                )
            df = _call()
            if df is None or df.empty:
                log.info("[TushareSource] cb_basic 返回空，降级到 AkShare")
                return []


            # 字段完整性校验
            validate_tushare_fields(df,
                ["stk_code", "stk_short_name", "list_date", "maturity_date"],
                api_name="cb_basic")

            results = []
            for _, row in df.iterrows():
                results.append({
                    "code": str(row.get("ts_code", "")).replace(".SH", "").replace(".SZ", "").strip(),
                    "ts_code": str(row.get("ts_code", "")),
                    "name": row.get("bond_short_name"),
                    "underlying_code": str(row.get("stk_code", "") or "").strip(),
                    "underlying_name": row.get("stk_short_name"),
                    # 评级清洗：Tushare 偶尔附加 'sti' 后缀（如 'AA+sti' → 'AA+'）
                    "rating": (lambda v: str(v).replace("sti", "").strip() or None if v else None)(row.get("rating_ent")),
                    "issue_date": str(row.get("issue_date") or row.get("list_date") or ""),
                    "mature_date": str(row.get("maturity_date") or ""),
                    "face_value": float(row.get("par_value") or 100),
                    "convert_price": float(row.get("conv_price") or row.get("first_conv_price") or 0) or None,
                    "delist_date": str(row.get("delist_date") or ""),
                    "list_price": float(row.get("list_price") or 100),
                })
            log.info("cb_basic_ok", count=len(results))

            from data_sources.schema import validate_records, SCHEMA
            validate_records(results, SCHEMA["cb_basic"], source="Tushare cb_basic")
            return results

        except Exception as e:
            log.warning("cb_basic_error", error=str(e))
            return []

    def get_cb_daily(self, trade_date: str = None) -> List[Dict]:
        """
        获取指定交易日的可转债行情（收盘价/成交量/剩余规模等）。
        接口: pro.cb_daily()，需要 ≥2000 积分
        Args:
            trade_date: 格式 YYYYMMDD，默认取最近一个交易日
        返回字段: code, close, vol, amount, remaining_size
        """
        if not self._check_token():
            return []
        try:
            if not trade_date:
                from utils.trade_date import resolve_end_date
                trade_date = resolve_end_date(fmt="%Y%m%d")

            @with_tushare_retry()
            def _call():
                return self.pro.cb_daily(
                    trade_date=trade_date,
                    fields=["ts_code", "trade_date", "pre_close", "open",
                            "high", "low", "close", "vol", "amount", "bond_value"],
                )
            df = _call()
            if df is None or df.empty:
                log.info("cb_daily_empty", trade_date=trade_date)
                return []


            def _f(v):
                """安全转 float：None/NaN → None，0 → 0.0（保留零值）"""
                if v is None:
                    return None
                try:
                    import math
                    fv = float(v)
                    return None if math.isnan(fv) else fv
                except (ValueError, TypeError):
                    return None

            results = []
            for _, row in df.iterrows():
                ts_code = str(row.get("ts_code", ""))
                code = ts_code.replace(".SH", "").replace(".SZ", "").strip()
                close_val = _f(row.get("close"))
                open_val = _f(row.get("open"))
                high_val = _f(row.get("high"))
                low_val = _f(row.get("low"))
                vol_val = _f(row.get("vol"))

                # 停牌日修正：API 返回 open/high/low=0 但 close>0，用 close 填充
                # 避免 K 线图和技术指标被 0 值拉坏
                if close_val and close_val > 0 and vol_val == 0:
                    if not open_val:
                        open_val = close_val
                    if not high_val:
                        high_val = close_val
                    if not low_val:
                        low_val = close_val

                results.append({
                    "code": code,
                    "ts_code": ts_code,
                    "trade_date": str(row.get("trade_date", "")),
                    "close": close_val,
                    "open": open_val,
                    "high": high_val,
                    "low": low_val,
                    "volume": vol_val,
                    "amount": _f(row.get("amount")),
                    # bond_value ≈ 剩余规模（亿元），Tushare 有时以"纯债价值"名称返回
                    "pure_bond_value": _f(row.get("bond_value")),
                })
            log.info("cb_daily_ok", trade_date=trade_date, count=len(results))

            from data_sources.schema import validate_records, SCHEMA
            validate_records(results, SCHEMA["cb_daily"], source="Tushare cb_daily")
            return results

        except Exception as e:
            log.warning("cb_daily_error", error=str(e))
            return []

    # 申万一级行业指数代码（31 个）
    SW_INDUSTRY_CODES = {
        "801010.SI": "农林牧渔", "801020.SI": "采掘", "801030.SI": "基础化工",
        "801040.SI": "钢铁", "801050.SI": "有色金属", "801080.SI": "电子",
        "801110.SI": "家用电器", "801120.SI": "食品饮料", "801130.SI": "纺织服饰",
        "801140.SI": "轻工制造", "801150.SI": "医药生物", "801160.SI": "公用事业",
        "801170.SI": "交通运输", "801180.SI": "房地产", "801200.SI": "商贸零售",
        "801210.SI": "社会服务", "801230.SI": "综合", "801710.SI": "建筑材料",
        "801720.SI": "建筑装饰", "801730.SI": "电力设备", "801740.SI": "国防军工",
        "801750.SI": "计算机", "801760.SI": "传媒", "801770.SI": "通信",
        "801780.SI": "银行", "801790.SI": "非银金融", "801880.SI": "汽车",
        "801890.SI": "机械设备", "801950.SI": "煤炭", "801960.SI": "石油石化",
        "801970.SI": "环保", "801980.SI": "美容护理",
    }

    @with_tushare_retry(max_retries=2)
    def get_industry_index_daily(self, trade_date: str = None,
                                  start_date: str = None, end_date: str = None) -> list:
        """
        拉取申万一级行业指数日线数据。
        trade_date: 单日  start_date/end_date: 日期范围
        返回: [{ code, name, trade_date, open, high, low, close, pct_chg, vol, amount }, ...]
        """
        results = []

        # 申万行业指数必须用 sw_daily，index_daily 不支持 .SI 代码
        for ts_code, ind_name in self.SW_INDUSTRY_CODES.items():
            try:
                params = {"ts_code": ts_code}
                if trade_date:
                    params["trade_date"] = trade_date.replace("-", "")
                if start_date:
                    params["start_date"] = start_date.replace("-", "")
                if end_date:
                    params["end_date"] = end_date.replace("-", "")

                df = self.pro.sw_daily(**params)
                if df is None or df.empty:
                    continue

                for _, row in df.iterrows():
                    # sw_daily 返回 pct_change（不是 pct_chg）
                    pct = row.get("pct_change") if pd.notna(row.get("pct_change")) else row.get("pct_chg")
                    # trade_date: Tushare 返回 YYYYMMDD，转为 YYYY-MM-DD 与其他表一致
                    raw_td = str(row.get("trade_date", ""))
                    td = f"{raw_td[:4]}-{raw_td[4:6]}-{raw_td[6:8]}" if len(raw_td) == 8 else raw_td
                    results.append({
                        "code": ts_code,
                        "name": ind_name,
                        "trade_date": td,
                        "open": float(row["open"]) if pd.notna(row.get("open")) else None,
                        "high": float(row["high"]) if pd.notna(row.get("high")) else None,
                        "low": float(row["low"]) if pd.notna(row.get("low")) else None,
                        "close": float(row["close"]) if pd.notna(row.get("close")) else None,
                        "pct_chg": float(pct) if pd.notna(pct) else None,
                        "vol": float(row["vol"]) if pd.notna(row.get("vol")) else None,
                        "amount": float(row["amount"]) if pd.notna(row.get("amount")) else None,
                    })

                # 控制频率
                from settings import TUSHARE_FETCH_SLEEP
                import time as _time
                _time.sleep(TUSHARE_FETCH_SLEEP)

            except Exception as e:
                err_str = str(e)
                # IP 超限/权限不足 = 致命错误，不再静默跳过
                if any(kw in err_str for kw in ("IP", "ip", "超限", "白名单", "权限", "积分")):
                    log.error("industry_index_fatal", code=ts_code, error=err_str)
                    raise  # 向上抛出，让同步框架标记失败
                log.warning("industry_index_fetch_error", code=ts_code, error=err_str)
                continue

        log.info("industry_index_daily_ok", count=len(results))
        return results
