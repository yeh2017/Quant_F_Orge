"""
数据源模块
支持 Tushare, Baostock, AkShare
"""

from .base import DataSourceBase
from .akshare_source import AkShareSource
from .baostock_source import BaostockSource

# Tushare 需要 Token，单独处理
try:
    from .tushare_source import TushareSource
except ImportError:
    TushareSource = None

__all__ = [
    'DataSourceBase',
    'AkShareSource',
    'BaostockSource',
    'TushareSource'
]
