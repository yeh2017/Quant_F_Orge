"""
Baostock 数据源实现
免费、历史数据全、开源
"""

import atexit
import threading
import structlog
from typing import Optional, List, Dict, Any
import pandas as pd
from .base import DataSourceBase, StockInfo
from utils.asset_type import to_bs_code, get_exchange

log = structlog.get_logger("baostock_source")


class BaostockSource(DataSourceBase):
    """Baostock 数据源"""

    name = "baostock"
    description = "Baostock - 免费开源证券数据"
    requires_token = False

    # 类变量单例状态：保证同进程内只登录一次
    _bs_module = None
    _logged_in = False
    _class_lock = threading.Lock()

    def __init__(self):
        import baostock as bs
        BaostockSource._bs_module = bs
        self._stock_list_cache = None
        self._lock = threading.Lock()  # Baostock 全局会话不支持并行

    @classmethod
    def _login(cls):
        """(类方法) 登录 Baostock，已登录则直接返回"""
        with cls._class_lock:
            if not cls._logged_in and cls._bs_module is not None:
                lg = cls._bs_module.login()
                if lg.error_code == '0':
                    cls._logged_in = True
                    atexit.register(BaostockSource._logout)  # 进程退出时自动登出
                    log.info("baostock_login_ok")
                else:
                    raise Exception(f"Baostock login failed: {lg.error_msg}")

    @classmethod
    def _logout(cls):
        """(类方法) 登出 Baostock"""
        with cls._class_lock:
            if cls._logged_in and cls._bs_module is not None:
                cls._bs_module.logout()
                cls._logged_in = False
                log.info("baostock_logout_ok")

    def _format_bs_code(self, code: str) -> str:
        """格式化为 Baostock 代码格式 (sh.600519)

        不再硬编码指数列表，纯 6 位码统一走 to_bs_code() 按前缀规则补交易所。
        """
        code = code.strip()
        # 已带后缀的，先剥离转换
        if '.' in code:
            parts = code.split('.')
            suffix = parts[-1].upper()
            pure = parts[0]
            if suffix in ('SH', 'SS'):
                return f"sh.{pure}"
            elif suffix == 'SZ':
                return f"sz.{pure}"
            code = pure
        return to_bs_code(code)
    
    def get_stock_info(self, code: str) -> Optional[StockInfo]:
        """获取股票基本信息"""
        try:
            code = code.strip()
            if not self.validate_stock_code(code):
                return None
            
            with self._lock:
                self._login()
                bs_code = self._format_bs_code(code)
                
                # 查询股票基本信息
                rs = BaostockSource._bs_module.query_stock_basic(code=bs_code)
                if rs.error_code != '0':
                    return None
                
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
                
                if not data:
                    return None
                
                row = data[0]
                
                # 确定市场
                exchange = get_exchange(code)
                if exchange == 'SH':
                    market = "上交所"
                elif code.startswith('30'):
                    market = "创业板"
                elif code.startswith('68'):
                    market = "科创板"
                else:
                    market = "深交所"
                
                # 获取行业（已在锁内，安全调用）
                industry = self._get_stock_industry(code)
            
            return StockInfo(
                code=code,
                name=row[1] if len(row) > 1 else f"股票-{code}",
                industry=industry,
                market=market,
                list_date=row[2] if len(row) > 2 else None
            )
        except Exception as e:
            log.warning("baostock_get_stock_info_failed", error=str(e))
            return None
    
    def _get_stock_industry(self, code: str) -> str:
        """获取股票行业分类"""
        try:
            self._login()
            bs_code = self._format_bs_code(code)
            rs = BaostockSource._bs_module.query_stock_industry(code=bs_code)
            
            if rs.error_code != '0':
                return "未知"
            
            data = []
            while rs.next():
                data.append(rs.get_row_data())
            
            if data:
                # columns: updateDate, code, code_name, industry, industryClassification
                return data[0][3] if len(data[0]) > 3 else "未知"
            return "未知"
        except Exception:
            return "未知"
    
    def get_stock_history(
        self, 
        code: str, 
        start_date: str, 
        end_date: str,
        adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        """获取股票历史行情（仅股票，不处理指数）"""
        try:
            code = code.strip()
            if not self.validate_stock_code(code):
                return None
            
            with self._lock:
                self._login()
                bs_code = self._format_bs_code(code)
                
                adj_map = {"qfq": "2", "hfq": "1", "none": "3"}
                adjustflag = adj_map.get(adjust, "2")
                
                rs = BaostockSource._bs_module.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,volume,amount",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag=adjustflag
                )
                
                if rs.error_code != '0':
                    log.warning("baostock_query_error", code=bs_code, error=rs.error_msg)
                    return None
                
                data = []
                while rs.next():
                    data.append(rs.get_row_data())
            
            if not data:
                return None
            
            df = pd.DataFrame(data, columns=rs.fields)
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
        except Exception as e:
            log.warning("baostock_get_stock_history_failed", error=str(e))
            return None
    
    def get_stock_list(self) -> List[StockInfo]:
        """获取全部股票列表"""
        try:
            if self._stock_list_cache is not None:
                return self._stock_list_cache
            
            self._login()
            
            # 获取沪深A股列表
            rs = BaostockSource._bs_module.query_stock_basic()
            if rs.error_code != '0':
                return []
            
            data = []
            while rs.next():
                data.append(rs.get_row_data())
            
            stocks = []
            for row in data:
                # columns: code, code_name, ipoDate, outDate, type, status
                if len(row) < 2:
                    continue
                
                full_code = row[0]  # sh.600519
                code = full_code.split('.')[-1] if '.' in full_code else full_code
                
                if not self.validate_stock_code(code):
                    continue
                
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
                    name=row[1],
                    industry="",
                    market=market,
                    list_date=row[2] if len(row) > 2 else None
                ))
            
            self._stock_list_cache = stocks
            return stocks
        except Exception as e:
            print(f"Baostock get_stock_list error: {e}")
            return []
    
    def get_financial_data(self, code: str) -> Optional[Dict[str, Any]]:
        """获取财务数据"""
        try:
            with self._lock:
                self._login()
                bs_code = self._format_bs_code(code)
                
                # 动态计算最新可用报告期
                # 年报通常在 4 月底前披露，所以 4 月之前查上一年 Q4
                from datetime import datetime
                now = datetime.now()
                if now.month <= 4:
                    year, quarter = now.year - 1, 4
                else:
                    # Q1报告5月前出 → month<=7时取Q1，以此类推
                    quarter = max(1, (now.month - 1) // 3)
                    year = now.year
                
                rs_profit = BaostockSource._bs_module.query_profit_data(code=bs_code, year=year, quarter=quarter)
                
                profit_data = []
                while rs_profit.next():
                    profit_data.append(rs_profit.get_row_data())
            
            if not profit_data:
                return None
            
            latest = profit_data[0]
            return {
                "code": code,
                "roe": float(latest[3]) if len(latest) > 3 and latest[3] else 0,
                "net_profit_margin": float(latest[4]) if len(latest) > 4 and latest[4] else 0,
                "gross_profit_margin": float(latest[5]) if len(latest) > 5 and latest[5] else 0,
                "net_profit": float(latest[6]) if len(latest) > 6 and latest[6] else 0,
                "eps": float(latest[7]) if len(latest) > 7 and latest[7] else 0,
            }
        except Exception as e:
            log.warning("baostock_get_financial_data_failed", error=str(e))
            return None

    def test_connection(self) -> bool:
        """测试连接是否正常"""
        try:
            BaostockSource._login()
            bs = BaostockSource._bs_module
            rs = bs.query_stock_basic(code="sh.600000")
            return rs.error_code == '0'
        except Exception as e:
            log.warning("baostock_test_connection_failed", error=str(e))
            return False
