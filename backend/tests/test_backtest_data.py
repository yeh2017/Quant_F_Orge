"""
快速测试回测数据获取
"""
import sys
import os
# 添加 backend 目录到 path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from services.stock_service import StockService
from services.backtest_service import BacktestService
from datetime import datetime, timedelta

def test_data_fetch():
    """测试数据获取"""
    print("=" * 50)
    print("回测数据获取测试")
    print("=" * 50)
    
    # 初始化服务
    stock_service = StockService()
    backtest_service = BacktestService(stock_service)
    
    # 测试参数
    codes = ["000001", "600000", "000002"]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    print(f"\n测试股票: {codes}")
    print(f"日期范围: {start_date} ~ {end_date}")
    
    # 1. 测试直接获取
    print("\n--- 直接数据获取测试 ---")
    for code in codes:
        try:
            history = stock_service.get_stock_history(code, start_date, end_date)
            if history:
                print(f"[OK] {code}: {len(history)}条数据")
                if history:
                    print(f"  列名: {list(history[0].keys())}")
            else:
                print(f"[FAIL] {code}: 无数据")
        except Exception as e:
            print(f"[FAIL] {code}: 错误 - {e}")
    
    # 2. 测试并行获取
    print("\n--- 并行获取测试 ---")
    try:
        stock_data = backtest_service._fetch_all_stocks_parallel(codes, start_date, end_date)
        print(f"并行获取结果: {len(stock_data)}只股票")
        for code, data in stock_data.items():
            print(f"  {code}: {len(data) if data else 0}条")
    except Exception as e:
        print(f"并行获取错误: {e}")
    
    # 3. 测试完整回测
    print("\n--- 回测测试 ---")
    try:
        results = backtest_service.run_backtest(
            stock_codes=codes,
            start_date=start_date,
            end_date=end_date
        )
        print(f"总收益: {results.get('total_return', 0)}%")
        print(f"累计收益长度: {len(results.get('cumReturns', []))}")
        if results.get('error'):
            print(f"错误: {results.get('error')}")
    except Exception as e:
        print(f"回测错误: {e}")

if __name__ == "__main__":
    test_data_fetch()
