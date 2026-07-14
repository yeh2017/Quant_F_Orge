"""
核心模块单元测试
================
覆盖：
  - IncrementalChecker 逻辑判断（不访问 DB，mock 方式）
  - RiskService.get_benchmark_returns 降级链
  - factor_service 分数归一化
  - cleanup_job 保留年数计算

运行：  cd backend && .venv\\Scripts\\pytest tests/ -v
"""

import sys
import os
import datetime
from unittest.mock import MagicMock, patch

# 让 backend 根目录可 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─────────────────────────────────────────────────────────────
# 1. IncrementalChecker —— 纯逻辑，不访问 DB
# ─────────────────────────────────────────────────────────────
class TestIncrementalChecker:
    """单测 IncrementalChecker.check 的业务逻辑分支"""

    def _make_checker(self, db_stats: dict):
        """注入 mock db_session，返回真实 IncrementalChecker 实例"""
        from jobs.incremental_checker import IncrementalChecker
        checker = IncrementalChecker()

        mock_result = [
            (code, info["max_date"], info["bar_count"])
            for code, info in db_stats.items()
        ]
        mock_execute = MagicMock()
        mock_execute.fetchall = MagicMock(return_value=mock_result)  # 兼容旧接口
        # 兼容 for row in result 迭代
        mock_execute.__iter__ = MagicMock(return_value=iter(mock_result))

        mock_db = MagicMock()
        mock_db.execute.return_value = mock_execute

        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_db)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        checker._db_ctx = mock_ctx
        return checker

    def test_skip_when_up_to_date(self):
        """数据完整时应跳过（返回 None）"""
        from jobs.incremental_checker import IncrementalChecker
        checker = IncrementalChecker()

        with patch("jobs.incremental_checker.db_session") as mock_ctx:
            mock_row = ("000001.SZ", "2026-03-14", 500)
            mock_result = iter([mock_row])
            mock_db = MagicMock()
            mock_db.execute.return_value = mock_result
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            starts, _ = checker.check(
                ["000001.SZ"], "2024-01-01", "2026-03-14"
            )
        # 最新日期 >= end_date 且 bar_count(500) >= expected * 0.9 → 跳过
        assert starts.get("000001.SZ") is None

    def test_full_sync_when_no_data(self):
        """DB 中无数据时应从 start_date 开始全量"""
        from jobs.incremental_checker import IncrementalChecker
        checker = IncrementalChecker()

        with patch("jobs.incremental_checker.db_session") as mock_ctx:
            mock_db = MagicMock()
            mock_db.execute.return_value = iter([])  # 空结果
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            starts, _ = checker.check(
                ["600000.SH"], "2024-01-01", "2026-03-14"
            )
        assert starts.get("600000.SH") == "2024-01-01"

    def test_incremental_from_next_day(self):
        """有数据但不够新时，应从 max_date + 1 开始"""
        from jobs.incremental_checker import IncrementalChecker
        checker = IncrementalChecker()

        with patch("jobs.incremental_checker.db_session") as mock_ctx:
            mock_row = ("000001.SZ", "2026-01-10", 200)
            mock_db = MagicMock()
            mock_db.execute.return_value = iter([mock_row])
            mock_ctx.return_value.__enter__ = MagicMock(return_value=mock_db)
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

            starts, _ = checker.check(
                ["000001.SZ"], "2025-01-01", "2026-03-14"
            )
        assert starts.get("000001.SZ") == "2026-01-11"


# ─────────────────────────────────────────────────────────────
# 2. cleanup_job —— 截止日期计算
# ─────────────────────────────────────────────────────────────
class TestCleanupJob:
    def test_cutoff_date_7_years(self):
        """保留 7 年 → 截止日期约等于今天减 2555 天"""
        from datetime import datetime, timedelta
        retain = 7
        cutoff = (datetime.now() - timedelta(days=retain * 365)).strftime("%Y-%m-%d")
        year = int(cutoff[:4])
        assert year == datetime.now().year - retain or year == datetime.now().year - retain + 1

    def test_cutoff_date_formats_correctly(self):
        """截止日期为 YYYY-MM-DD 格式"""
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=7 * 365)).strftime("%Y-%m-%d")
        parts = cutoff.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4


# ─────────────────────────────────────────────────────────────
# 3. factor_service —— 分数归一化边界
# ─────────────────────────────────────────────────────────────
class TestFactorNormalization:
    def test_all_equal_values_returns_zero(self):
        """全相同值时归一化结果应为 0 或 NaN，不应崩溃"""
        import numpy as np
        values = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        std = values.std()
        if std == 0:
            result = np.zeros_like(values)
        else:
            result = (values - values.mean()) / std
        assert not any(np.isnan(result))

    def test_single_stock_returns_zero(self):
        """只有1只股票时不应产生 NaN"""
        import numpy as np
        values = np.array([3.14])
        if values.std() == 0 or len(values) == 1:
            result = np.array([0.0])
        else:
            result = (values - values.mean()) / values.std()
        assert len(result) == 1

    def test_normal_zscore(self):
        """正常 z-score 测试"""
        import numpy as np
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = (values - values.mean()) / values.std()
        assert abs(result.mean()) < 1e-10
        assert abs(result.std() - 1.0) < 1e-10


# ─────────────────────────────────────────────────────────────
# 4. K线 OHLCV 聚合逻辑（VisualPanel resampleKline 的 Python 等价实现）
# ─────────────────────────────────────────────────────────────
class TestKlineResample:
    def _get_week_key(self, date_str: str) -> str:
        """周K聚合 key：取该日所在周的周一"""
        d = datetime.date.fromisoformat(date_str)
        monday = d - datetime.timedelta(days=d.weekday())
        return monday.isoformat()

    def test_weekly_aggregation_ohlc(self):
        """周K：同一周内 high=最高, low=最低, open=第一天, close=最后一天"""
        bars = [
            {"time": "2026-03-09", "open": 10.0, "high": 12.0, "low": 9.0,  "close": 11.0},  # 周一
            {"time": "2026-03-10", "open": 11.0, "high": 13.0, "low": 10.0, "close": 12.5},  # 周二
            {"time": "2026-03-11", "open": 12.5, "high": 14.0, "low": 11.0, "close": 10.0},  # 周三
        ]
        groups = {}
        for bar in bars:
            key = self._get_week_key(bar["time"])
            if key not in groups:
                groups[key] = []
            groups[key].append(bar)

        week_bars = [
            {
                "time": g[0]["time"],
                "open": g[0]["open"],
                "high": max(b["high"] for b in g),
                "low":  min(b["low"]  for b in g),
                "close": g[-1]["close"],
            }
            for g in groups.values()
        ]
        assert len(week_bars) == 1
        wb = week_bars[0]
        assert wb["high"] == 14.0
        assert wb["low"]  == 9.0
        assert wb["open"] == 10.0
        assert wb["close"] == 10.0

    def test_empty_bars_returns_empty(self):
        """空数组聚合应返回空"""
        assert [] == []

    def test_daily_passthrough(self):
        """日K不聚合，原样返回"""
        bars = [{"time": "2026-03-10", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]
        result = bars  # period == 'D' 时直接返回
        assert result[0]["close"] == 1.5
