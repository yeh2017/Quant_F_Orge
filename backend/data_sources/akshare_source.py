"""
AkShare 数据源实现
免费、稳定、无需 Token
"""

import time
import structlog
from typing import Optional, List, Dict, Any
import pandas as pd
from .base import DataSourceBase, StockInfo, BondInfo

log = structlog.get_logger("akshare_source")

# 缓存 TTL（秒）：1天
_CACHE_TTL = 86400


class AkShareSource(DataSourceBase):
    """AkShare 数据源"""

    name = "akshare"
    description = "AkShare - 免费开源金融数据接口"
    requires_token = False

    def __init__(self):
        import akshare as ak
        self.ak = ak
        self._stock_list_cache = None
        self._stock_list_ts = 0.0   # 缓存时间戳
        self._bond_list_cache = None
        self._bond_list_ts = 0.0

    # ---------- 缓存辅助 ----------

    def _stock_cache_valid(self) -> bool:
        return self._stock_list_cache is not None and (time.time() - self._stock_list_ts) < _CACHE_TTL

    def _bond_cache_valid(self) -> bool:
        return self._bond_list_cache is not None and (time.time() - self._bond_list_ts) < _CACHE_TTL

    # ---------- 股票信息 ----------

    def get_stock_info(self, code: str) -> Optional[StockInfo]:
        """获取股票基本信息"""
        try:
            code = code.strip()
            if not self.validate_stock_code(code):
                return None

            if not self._stock_cache_valid():
                self._stock_list_cache = self.ak.stock_zh_a_spot_em()
                self._stock_list_ts = time.time()

            df = self._stock_list_cache
            match = df[df['代码'] == code]
            if match.empty:
                return None

            row = match.iloc[0]

            if code.startswith('6'):
                market = "上交所"
            elif code.startswith('00') or code.startswith('001'):
                market = "深交所主板"
            elif code.startswith('002') or code.startswith('003'):
                market = "深交所中小板"
            elif code.startswith('30'):
                market = "创业板"
            elif code.startswith('68'):
                market = "科创板"
            else:
                market = "未知"

            industry = self._get_stock_industry(code)

            return StockInfo(
                code=code,
                name=str(row['名称']),
                industry=industry,
                market=market
            )
        except Exception as e:
            log.warning("akshare_get_stock_info_failed", code=code, error=str(e))
            return None

    def _get_stock_industry(self, code: str) -> str:
        """获取股票所属行业（轻量级：查个股详情）"""
        try:
            info_df = self.ak.stock_individual_info_em(symbol=code)
            if info_df is not None and not info_df.empty:
                match = info_df[info_df['item'] == '行业']
                if not match.empty:
                    return str(match.iloc[0]['value'])
            return "未知"
        except Exception:
            return "未知"

    # ---------- 历史行情 ----------

    def get_stock_history(
        self,
        code: str,
        start_date: str,
        end_date: str,
        adjust: str = "qfq"
    ) -> Optional[pd.DataFrame]:
        """获取股票历史行情（仅股票，指数请直接调 _get_index_history）"""
        try:
            code = code.strip()

            if not self.validate_stock_code(code):
                return None

            adj_map = {"qfq": "qfq", "hfq": "hfq", "none": ""}
            adj = adj_map.get(adjust, "qfq")

            df = self.ak.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
                adjust=adj
            )

            if df is None or df.empty:
                return None

            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume',
                '成交额': 'amount'
            })

            columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            df = df[[c for c in columns if c in df.columns]]

            return df
        except Exception as e:
            log.warning("akshare_get_stock_history_failed", code=code, error=str(e))
            return None

    def _get_index_history(
        self,
        code: str,
        start_date: str,
        end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取指数历史行情，失败时 fallback 到 index_zh_a_hist_min_em"""
        try:
            df = self.ak.index_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", "")
            )

            if df is None or df.empty:
                raise ValueError("empty result")

            df = df.rename(columns={
                '日期': 'date', '开盘': 'open', '最高': 'high',
                '最低': 'low', '收盘': 'close', '成交量': 'volume', '成交额': 'amount'
            })
            columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']
            return df[[c for c in columns if c in df.columns]]

        except Exception as e:
            log.warning("akshare_index_history_failed", code=code, error=str(e))
            return None

    # ---------- 股票列表 ----------

    def get_stock_list(self) -> List[StockInfo]:
        """获取全部A股列表（带 TTL 缓存）"""
        try:
            if not self._stock_cache_valid():
                self._stock_list_cache = self.ak.stock_zh_a_spot_em()
                self._stock_list_ts = time.time()

            df = self._stock_list_cache
            stocks = []

            for _, row in df.iterrows():
                code = str(row['代码'])
                if code.startswith('6'):
                    market = "上交所"
                elif code.startswith('30'):
                    market = "创业板"
                elif code.startswith('68'):
                    market = "科创板"
                else:
                    market = "深交所"

                stocks.append(StockInfo(
                    code=code,
                    name=str(row['名称']),
                    industry="",
                    market=market
                ))

            return stocks
        except Exception as e:
            log.warning("akshare_get_stock_list_failed", error=str(e))
            return []

    # ---------- 财务数据 ----------

    def get_financial_data(self, code: str) -> Optional[Dict[str, Any]]:
        """获取财务数据"""
        try:
            code = code.strip()
            symbol = self.format_code(code)

            profit_df = self.ak.stock_profit_sheet_by_report_em(symbol=symbol)
            balance_df = self.ak.stock_balance_sheet_by_report_em(symbol=symbol)

            # 按报告期降序取最新一期
            if profit_df is not None and not profit_df.empty:
                profit_df = profit_df.sort_values('报告期', ascending=False) if '报告期' in profit_df.columns else profit_df
                latest_profit = profit_df.iloc[0]
            else:
                latest_profit = {}

            if balance_df is not None and not balance_df.empty:
                balance_df = balance_df.sort_values('报告期', ascending=False) if '报告期' in balance_df.columns else balance_df
                latest_balance = balance_df.iloc[0]
            else:
                latest_balance = {}

            result = {
                "code": code,
                "revenue": float(latest_profit.get('营业收入', 0) or 0),
                "net_profit": float(latest_profit.get('净利润', 0) or 0),
                "total_assets": float(latest_balance.get('资产总计', 0) or 0),
                "total_equity": float(latest_balance.get('所有者权益合计', 0) or 0),
            }

            result["roe"] = result["net_profit"] / result["total_equity"] * 100 if result["total_equity"] > 0 else 0
            result["roa"] = result["net_profit"] / result["total_assets"] * 100 if result["total_assets"] > 0 else 0

            return result
        except Exception as e:
            log.warning("akshare_get_financial_data_failed", code=code, error=str(e))
            return None

    # ---------- 可转债 ----------

    def get_bond_info(self, code: str) -> Optional[BondInfo]:
        """获取可转债信息（兼容新旧版 AkShare 列名）"""
        try:
            code = code.strip()
            if not self.validate_bond_code(code):
                return None

            if not self._bond_cache_valid():
                self._bond_list_cache = self.ak.bond_zh_cov()
                self._bond_list_ts = time.time()

            df = self._bond_list_cache
            code_col = self._detect_col(df, ['债券代码', 'bond_code', 'code', '代码'])
            if not code_col:
                return None

            match = df[df[code_col] == code]
            if match.empty:
                return None

            row = match.iloc[0]
            name_col = self._detect_col(df, ['债券简称', 'bond_name', 'name', '简称'])
            stock_col = self._detect_col(df, ['正股简称', 'stock_name', '正股名称'])
            stock_code_col = self._detect_col(df, ['正股代码', 'stock_code', '正股股票代码'])
            rating_col = self._detect_col(df, ['债券评级', 'rating', 'bond_rating', '评级'])

            return BondInfo(
                code=code,
                name=str(row.get(name_col, '') or '') or f'转债-{code}' if name_col else f'转债-{code}',
                underlying_stock=str(row.get(stock_col, '') or '') or '未知' if stock_col else '未知',
                underlying_code=str(row.get(stock_code_col, '') or '') if stock_code_col else '',
                rating=str(row.get(rating_col, '') or '') or '-' if rating_col else '-'
            )
        except Exception as e:
            log.warning("akshare_get_bond_info_failed", code=code, error=str(e))
            return None

    def get_bond_list(self) -> List[BondInfo]:
        """获取可转债列表（兼容新旧版 AkShare 列名）"""
        try:
            if not self._bond_cache_valid():
                self._bond_list_cache = self.ak.bond_zh_cov()
                self._bond_list_ts = time.time()

            df = self._bond_list_cache
            code_col = self._detect_col(df, ['债券代码', 'bond_code', 'code', '代码'])
            name_col = self._detect_col(df, ['债券简称', 'bond_name', 'name', '简称'])
            stock_col = self._detect_col(df, ['正股简称', 'stock_name', '正股名称'])
            stock_code_col = self._detect_col(df, ['正股代码', 'stock_code', '正股股票代码'])
            rating_col = self._detect_col(df, ['债券评级', 'rating', 'bond_rating', '评级'])

            if not code_col:
                log.warning("akshare_bond_list_no_code_col", columns=list(df.columns))
                return []

            bonds = []
            for _, row in df.iterrows():
                code = str(row[code_col])
                if not code or len(code) < 6:
                    continue
                bonds.append(BondInfo(
                    code=code,
                    name=str(row.get(name_col, '') or '') or f'转债-{code}' if name_col else '',
                    underlying_stock=str(row.get(stock_col, '') or '') or '未知' if stock_col else '',
                    underlying_code=str(row.get(stock_code_col, '') or '') if stock_code_col else '',
                    rating=str(row.get(rating_col, '') or '') or '-' if rating_col else '-'
                ))
            return bonds
        except Exception as e:
            log.warning("akshare_get_bond_list_failed", error=str(e))
            return []

    @staticmethod
    def _detect_col(df, candidates: list) -> Optional[str]:
        """从候选列名中找到 df 中第一个存在的列名（兼容新旧版 AkShare）"""
        for c in candidates:
            if c in df.columns:
                return c
        return None

    # ---------- 连接测试 ----------

    def test_connection(self) -> bool:
        """测试连接是否正常"""
        try:
            df = self.ak.stock_zh_a_hist(
                symbol="600000", period="daily",
                start_date="20240102", end_date="20240102",
                adjust=""
            )
            return df is not None and not df.empty
        except Exception as e:
            log.warning("akshare_test_connection_failed", error=str(e))
            return False
