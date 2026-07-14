# -*- coding: utf-8 -*-
"""
数据验证器
异常值检测、停牌处理、非交易日识别
"""

from typing import Tuple, List, Dict, Any
import pandas as pd


class DataValidator:
    """数据质量验证器"""

    # A股涨跌停限制
    NORMAL_LIMIT = 0.10  # 普通股票10%
    ST_LIMIT = 0.05      # ST股票5%
    KC_LIMIT = 0.20      # 科创板/创业板20%

    # ── 交易日历：委托给 trade_date 模块（唯一权威来源）──

    @classmethod
    def _get_trade_dates(cls) -> set:
        """获取交易日集合（委托给 trade_date 模块）"""
        from utils.trade_date import _load_trade_dates
        return _load_trade_dates()

    @classmethod
    def _is_non_trade_date(cls, date_str: str) -> bool:
        """判断日期是否为非交易日（委托给 trade_date 模块）"""
        from utils.trade_date import is_non_trade_date
        return is_non_trade_date(date_str)

    @classmethod
    def detect_price_jump(
        cls,
        df: pd.DataFrame,
        code: str = "",
        threshold: float = None
    ) -> List[Dict[str, Any]]:
        """
        检测行情跳变（涨跌幅超过阈值）

        Args:
            df: 行情数据，需包含 close 列
            code: 股票代码（用于确定涨跌幅限制）
            threshold: 自定义阈值，None则根据股票类型自动确定

        Returns:
            异常记录列表
        """
        if df is None or df.empty or 'close' not in df.columns:
            return []

        if threshold is None:
            if code.startswith('30') or code.startswith('68'):
                threshold = cls.KC_LIMIT
            elif 'ST' in code.upper():
                threshold = cls.ST_LIMIT
            else:
                threshold = cls.NORMAL_LIMIT

        warnings = []
        df = df.copy()
        df['pct_change'] = df['close'].pct_change()

        # 超过涨跌停 50% 视为异常
        anomaly_threshold = threshold * 1.5
        anomalies = df[abs(df['pct_change']) > anomaly_threshold]

        for idx, row in anomalies.iterrows():
            date_str = row.get('date', str(idx))
            pct = row['pct_change'] * 100
            warnings.append({
                'type': 'price_jump',
                'date': date_str,
                'value': f'{pct:.2f}%',
                'message': f'异常涨跌幅 {pct:.2f}%（超过{anomaly_threshold*100:.0f}%阈值）'
            })

        return warnings

    @classmethod
    def detect_suspension(cls, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测停牌（成交量为0）"""
        if df is None or df.empty or 'volume' not in df.columns:
            return []

        suspensions = df[(df['volume'] == 0) | (df['volume'].isna())]
        return [
            {
                'type': 'suspension',
                'date': row.get('date', str(idx)),
                'value': '0',
                'message': f'{row.get("date", str(idx))} 疑似停牌（成交量为0）'
            }
            for idx, row in suspensions.iterrows()
        ]

    @classmethod
    def detect_invalid_dates(cls, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        检测非交易日的错误填充。
        优先使用 Tushare trade_cal 交易日历（最权威），降级到静态节假日+周末。
        """
        if df is None or df.empty or 'date' not in df.columns:
            return []

        warnings = []

        # 向量化解析日期
        dates = pd.to_datetime(df['date'], errors='coerce')
        valid_mask = dates.notna()
        date_strs = dates.dt.strftime('%Y-%m-%d')

        # 预热缓存（首次会触发 Tushare 请求）
        trade_dates = cls._get_trade_dates()

        import utils.trade_date as _td
        if _td._cache_source == 'tushare' and trade_dates:
            # 权威模式：直接用交易日历判断（一次性覆盖周末+节假日+补班日）
            non_trade_mask = valid_mask & ~date_strs.isin(trade_dates)
            for idx in df.index[non_trade_mask]:
                d = dates[idx]
                # 区分类型用于统计
                if d.weekday() >= 5:
                    wtype, val = 'weekend', d.strftime('%A')
                    msg = f'{df.loc[idx, "date"]} 为周末（{val}），不应有数据'
                else:
                    wtype, val = 'holiday', 'holiday'
                    msg = f'{df.loc[idx, "date"]} 为非交易日（节假日），不应有数据'
                warnings.append({'type': wtype, 'date': str(df.loc[idx, 'date']), 'value': val, 'message': msg})
        else:
            # 降级模式：周末 + 静态节假日表
            weekend_mask = valid_mask & (dates.dt.weekday >= 5)
            for idx in df.index[weekend_mask]:
                d = dates[idx]
                warnings.append({
                    'type': 'weekend', 'date': str(df.loc[idx, 'date']),
                    'value': d.strftime('%A'),
                    'message': f'{df.loc[idx, "date"]} 为周末（{d.strftime("%A")}），不应有数据'
                })
            holiday_mask = valid_mask & date_strs.isin(_td.CN_HOLIDAYS)
            for idx in df.index[holiday_mask]:
                warnings.append({
                    'type': 'holiday', 'date': str(df.loc[idx, 'date']),
                    'value': 'holiday',
                    'message': f'{df.loc[idx, "date"]} 为法定节假日，不应有数据'
                })

        # 无法解析的日期
        for idx in df.index[~valid_mask]:
            warnings.append({
                'type': 'invalid_date_format', 'date': str(df.loc[idx, 'date']),
                'value': 'parse_error', 'message': f'日期格式无效: {df.loc[idx, "date"]}'
            })

        return warnings

    @classmethod
    def detect_data_gaps(cls, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """检测数据缺口（连续交易日之间缺少数据）"""
        if df is None or df.empty or 'date' not in df.columns:
            return []

        warnings = []
        df = df.copy()

        df['_date'] = pd.to_datetime(df['date'])
        df = df.sort_values('_date')

        df['_gap'] = df['_date'].diff().dt.days

        # 超过5天的缺口可能是缺数据（考虑周末+节假日）
        gaps = df[df['_gap'] > 5]

        for idx, row in gaps.iterrows():
            prev_idx = df.index[df.index.get_loc(idx) - 1]
            prev_date = df.loc[prev_idx, '_date']
            curr_date = row['_date']
            gap_days = int(row['_gap'])

            warnings.append({
                'type': 'data_gap',
                'date': str(curr_date.date()),
                'value': f'{gap_days} days',
                'message': f'{prev_date.date()} 到 {curr_date.date()} 之间缺少 {gap_days-1} 天数据'
            })

        return warnings

    @classmethod
    def validate_and_clean(
        cls,
        df: pd.DataFrame,
        code: str = "",
        remove_suspensions: bool = True,
        remove_invalid_dates: bool = True
    ) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
        """综合验证并清洗数据"""
        if df is None or df.empty:
            return df, []

        all_warnings = []
        df_clean = df.copy()

        # 1. 检测行情跳变
        jump_warnings = cls.detect_price_jump(df_clean, code)
        all_warnings.extend(jump_warnings)

        # 2. 检测并处理停牌
        suspension_warnings = cls.detect_suspension(df_clean)
        all_warnings.extend(suspension_warnings)

        if remove_suspensions and 'volume' in df_clean.columns:
            df_clean = df_clean[(df_clean['volume'] > 0) & (df_clean['volume'].notna())]

        # 3. 检测无效日期（向量化，高性能）
        invalid_date_warnings = cls.detect_invalid_dates(df_clean)
        all_warnings.extend(invalid_date_warnings)

        if remove_invalid_dates and 'date' in df_clean.columns:
            # 用交易日历缓存移除非交易日数据
            dates = pd.to_datetime(df_clean['date'], errors='coerce')
            valid = dates.notna()
            trade_dates = cls._get_trade_dates()
            import utils.trade_date as _td
            if _td._cache_source == 'tushare' and trade_dates:
                is_trade = dates.dt.strftime('%Y-%m-%d').isin(trade_dates)
                df_clean = df_clean[valid & is_trade]
            else:
                not_weekend = dates.dt.weekday < 5
                not_holiday = ~dates.dt.strftime('%Y-%m-%d').isin(_td.CN_HOLIDAYS)
                df_clean = df_clean[valid & not_weekend & not_holiday]

        # 4. 检测数据缺口
        gap_warnings = cls.detect_data_gaps(df_clean)
        all_warnings.extend(gap_warnings)

        return df_clean, all_warnings

    @classmethod
    def get_validation_summary(cls, warnings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成验证摘要"""
        return {
            'total_warnings': len(warnings),
            'price_jumps': len([w for w in warnings if w['type'] == 'price_jump']),
            'suspensions': len([w for w in warnings if w['type'] == 'suspension']),
            'invalid_dates': len([w for w in warnings if w['type'] in ['weekend', 'holiday']]),
            'data_gaps': len([w for w in warnings if w['type'] == 'data_gap']),
        }
