"""
增量检测器
=========
双轨增量检测：分别检测行情表和因子表的最新日期，避免重复拉取。
同时校验数据密度（实际行数 vs 预期交易日数），防止有空洞时被误判为"已完整"。
"""

import structlog
import pandas as pd
from typing import Dict, Tuple, List, Optional
from datetime import timedelta

from core.database import db_session
from sqlalchemy import text

log = structlog.get_logger("incremental")

# 数据完整度阈值：实际行数 >= 预期交易日数 * DENSITY_THRESHOLD 才认为数据充足
_DENSITY_THRESHOLD = 0.90


class IncrementalChecker:
    """增量同步检测"""

    def check(
        self, codes: List[str], start_date: str, end_date: str
    ) -> Tuple[Dict[str, Optional[str]], Dict[str, str]]:
        """
        批量查询每只股票在 DB 中的行情数据状态。

        逻辑：
          1. 查询每只股票的 max_date 和 bar_count。
          2. 若 max_date >= end_date 且 bar_count >= 预期交易日数 * 0.90，认为数据充足 → skip。
          3. 若 max_date 存在但不够新/数据有空洞 → 从 max_date+1 开始增量补。
          4. 若 DB 中完全没有数据 → 从 start_date 开始全量拉取。

        Returns:
            (incremental_starts, max_dates)
            - incremental_starts: {code: effective_start | None(跳过)}
            - max_dates: {code: max_date_in_db}
        """
        try:
            # 期间预期交易日数（粗估：自然日 * 0.69，A股约每年240天）
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            natural_days = (end_dt - start_dt).days
            # natural_days <= 5 时（区间不足一周）密度校验无意义，设为 0 表示跳过该项检查
            expected_bars = max(0, int(natural_days * 0.69)) if natural_days > 5 else 0

            with db_session() as db:
                placeholders = ", ".join(f":c{i}" for i in range(len(codes)))
                params = {f"c{i}": code for i, code in enumerate(codes)}

                # 一次查：max日期 + 行数
                result = db.execute(text(
                    f"SELECT code, MAX(trade_date) as max_date, COUNT(*) as bar_count "
                    f"FROM stock_daily_bars "
                    f"WHERE code IN ({placeholders}) "
                    f"  AND trade_date BETWEEN :s AND :e "
                    f"GROUP BY code"
                ), {**params, "s": start_date, "e": end_date})

                db_stats: Dict[str, dict] = {}
                for row in result:
                    db_stats[row[0]] = {
                        "max_date": str(row[1]),
                        "bar_count": int(row[2]),
                    }

            max_dates = {code: info["max_date"] for code, info in db_stats.items()}

            incremental_starts: Dict[str, Optional[str]] = {}
            for code in codes:
                if code in db_stats:
                    info = db_stats[code]
                    max_date = info["max_date"]
                    bar_count = info["bar_count"]
                    is_date_ok = max_date >= end_date
                    is_density_ok = bar_count >= expected_bars * _DENSITY_THRESHOLD

                    if is_date_ok and is_density_ok:
                        # 数据完整，直接跳过
                        incremental_starts[code] = None
                    elif is_date_ok and not is_density_ok:
                        # 最新日期够，但内部有空洞 → 全段重同步
                        log.warning(
                            "incremental_gap_detected",
                            code=code,
                            bar_count=bar_count,
                            expected=expected_bars,
                        )
                        incremental_starts[code] = start_date
                    else:
                        # 数据不够新 → 从 max_date 次日开始增量补
                        next_day = (
                            pd.to_datetime(max_date) + timedelta(days=1)
                        ).strftime("%Y-%m-%d")
                        incremental_starts[code] = next_day
                else:
                    # DB 中完全没有该股票的数据 → 全量拉取
                    incremental_starts[code] = start_date  # ← 修复：原来错误地赋 None

            truly_skipped = sum(
                1 for c in codes if incremental_starts.get(c) is None
            )
            if truly_skipped:
                log.info("incremental_skip", skipped=truly_skipped)

            need_count = len(codes) - truly_skipped
            if need_count:
                log.info("incremental_need_sync", need=need_count, expected_bars_each=expected_bars)

            return incremental_starts, max_dates

        except Exception as e:
            log.error("incremental_check_failed", error=str(e))
            # 失败时安全降级：全部重同步
            return {code: start_date for code in codes}, {}

    def split(
        self,
        target_codes: List[str],
        incremental_starts: Dict,
        max_dates: Dict,
        start_date: str,
    ) -> Tuple[List[str], List[str], str]:
        """
        根据增量检测结果拆分出 truly_skipped / need_sync / batch_start。

        Returns:
            (truly_skipped, need_sync, batch_start)
        """
        truly_skipped = [
            c for c in target_codes if incremental_starts.get(c) is None
        ]
        need_sync = [c for c in target_codes if c not in truly_skipped]

        batch_start = start_date
        if need_sync:
            starts = [incremental_starts.get(c) or start_date for c in need_sync]
            batch_start = min(starts)

        return truly_skipped, need_sync, batch_start
