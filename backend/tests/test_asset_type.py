"""asset_type 单元测试 — 守护全系统的分类逻辑"""
import pytest
from utils.asset_type import classify, is_bond, is_etf_by_prefix
from utils.asset_type import STOCK_PREFIXES, BOND_PREFIXES, ETF_PREFIXES


class TestClassify:
    """分类函数正确性"""

    @pytest.mark.parametrize("code,expected", [
        ("600519", "stock"),    # 沪主板
        ("000001", "stock"),    # 深主板
        ("300750", "stock"),    # 创业板
        ("688981", "stock"),    # 科创板
        ("510300", "etf"),      # 沪 ETF
        ("159915", "etf"),      # 深 ETF
        ("588000", "etf"),      # 科创板 ETF
        ("113050", "bond"),     # 沪可转债
        ("128136", "bond"),     # 深可转债
        ("127063", "bond"),     # 深可交换债
        ("400041", "bond"),     # 退市可转债
    ])
    def test_basic(self, code, expected):
        assert classify(code) == expected

    @pytest.mark.parametrize("code", [
        "600519.SH", "510300.SH", "113050.SH",  # 带后缀
    ])
    def test_with_suffix(self, code):
        """带交易所后缀也能正确分类"""
        assert classify(code) in ("stock", "etf", "bond")

    @pytest.mark.parametrize("code", [
        "", "11", "1234", "99", "ABCDEF",  # 非法输入
    ])
    def test_invalid_returns_stock(self, code):
        """非法输入默认返回 stock（安全降级）"""
        assert classify(code) == "stock"


class TestPrefixConsistency:
    """前缀常量完整性"""

    def test_no_overlap(self):
        """三组前缀不能有重叠"""
        all_prefixes = set(STOCK_PREFIXES) | set(BOND_PREFIXES) | set(ETF_PREFIXES)
        assert len(all_prefixes) == len(STOCK_PREFIXES) + len(BOND_PREFIXES) + len(ETF_PREFIXES)

    def test_helpers_consistent(self):
        """is_bond / is_etf_by_prefix 与 classify 一致"""
        cases = ["600519", "113050", "510300", "128136", "159915"]
        for code in cases:
            assert is_bond(code) == (classify(code) == "bond")
            assert is_etf_by_prefix(code) == (classify(code) == "etf")
