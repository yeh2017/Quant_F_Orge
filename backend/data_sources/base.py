"""
数据源基类 - 定义统一接口
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
import pandas as pd
from pydantic import BaseModel
from utils.asset_type import STOCK_PREFIXES, BOND_PREFIXES, ETF_PREFIXES, to_ts_code


class StockInfo(BaseModel):
    """股票基本信息"""
    code: str
    name: str
    industry: str = "未知"
    market: str = "未知"
    list_date: Optional[str] = None


class BondInfo(BaseModel):
    """可转债基本信息"""
    code: str
    name: str
    underlying_stock: str = "未知"
    underlying_code: str = ""
    rating: str = "-"
    maturity_date: Optional[str] = None


class DataSourceBase(ABC):
    """数据源基类"""
    
    name: str = "base"
    description: str = "数据源基类"
    requires_token: bool = False
    
    @abstractmethod
    def get_stock_info(self, code: str) -> Optional[StockInfo]:
        """获取股票基本信息"""
    
    @abstractmethod
    def get_stock_history(
        self, 
        code: str, 
        start_date: str, 
        end_date: str,
        adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        """
        获取股票历史行情
        
        Args:
            code: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            adjust: 复权类型 (qfq=前复权, hfq=后复权, None=不复权)
            
        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount
        """
    
    @abstractmethod
    def get_stock_list(self) -> List[StockInfo]:
        """获取全部股票列表"""

    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接是否正常"""
    
    def get_financial_data(self, code: str) -> Optional[Dict[str, Any]]:
        """获取财务数据（可选实现）"""
        return None
    
    def get_bond_info(self, code: str) -> Optional[BondInfo]:
        """获取可转债信息（可选实现）"""
        return None
    
    def get_bond_list(self) -> List[BondInfo]:
        """获取可转债列表（可选实现）"""
        return []
    
    def validate_stock_code(self, code: str) -> bool:
        """验证股票代码格式"""
        code = code.strip()
        if len(code) != 6 or not code.isdigit():
            return False
        
        # A股 + ETF 代码前缀验证（引用统一常量）
        return code[:2] in STOCK_PREFIXES or code[:2] in ETF_PREFIXES
    
    def validate_bond_code(self, code: str) -> bool:
        """验证可转债代码格式"""
        code = code.strip()
        if len(code) != 6 or not code.isdigit():
            return False
        # 10 - 沪市企业可转债, 11 - 沪市可转债, 12 - 深市可转债, 13 - 沪市可交换债
        # 40 - 退市可转债（正股退到三板市场）
        return code[:2] in BOND_PREFIXES
    
    def format_code(self, code: str) -> str:
        """格式化股票代码（添加市场后缀），委托给统一函数"""
        return to_ts_code(code)
