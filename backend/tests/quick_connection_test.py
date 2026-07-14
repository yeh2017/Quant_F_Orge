"""
数据源连接测试工具
===================
功能:
  - 测试 AkShare, Tushare, Baostock, Polygon 连接
  - 查询股票: 显示代码、名称、行业、市场
  - 查询可转债: 显示代码、名称、正股信息

用法:
  python quick_connection_test.py           # 测试连接 + 交互模式
  python quick_connection_test.py -t        # 仅测试连接
  python quick_connection_test.py 000001    # 查询股票
  python quick_connection_test.py 113021    # 查询可转债
  python quick_connection_test.py -i        # 交互模式
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['TQDM_DISABLE'] = '1'

# 自动加载 .env 文件中的环境变量（如 TUSHARE_TOKEN）
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

import io
import contextlib
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

# 配置
TIMEOUT = 15
MAX_RETRIES = 2

@contextlib.contextmanager
def suppress_output():
    """临时抑制stdout/stderr输出"""
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

# ==================== 工具函数 ====================

def is_bond_code(code):
    """判断是否为可转债代码"""
    from utils.asset_type import classify
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return False
    return classify(code) == "bond"

def is_stock_code(code):
    """判断是否为股票代码"""
    from utils.asset_type import classify
    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        return False
    return classify(code) == "stock"

def retry(func, retries=MAX_RETRIES):
    """带重试的函数执行"""
    last_error = None
    for i in range(retries + 1):
        try:
            return func()
        except Exception as e:
            last_error = e
            if i < retries:
                time.sleep(1)
    return False, str(last_error)[:50]

def run_with_timeout(func, timeout=TIMEOUT):
    """带超时的函数执行（抑制库输出防止混乱）"""
    def wrapped():
        with suppress_output():
            return retry(func)
    
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(wrapped)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeoutError:
            return False, f"超时({timeout}s)"
        except Exception as e:
            return False, str(e)[:50]

# ==================== 数据源测试 ====================

def test_akshare():
    """测试 AkShare"""
    from data_sources.akshare_source import AkShareSource
    source = AkShareSource()
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
    df = source.get_stock_history("000001", start_date, end_date)
    if df is not None and not df.empty:
        return True, f"平安银行 {len(df)}条"
    return False, "无数据"

def test_tushare():
    """测试 Tushare"""
    from data_sources.tushare_source import TushareSource
    source = TushareSource()
    if not source._check_token():
        return None, "Token未配置"
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    df = source.get_stock_history("000001", start_date, end_date)
    if df is not None and not df.empty:
        return True, f"{len(df)}条记录"
    return False, "无数据"

def test_baostock():
    """测试 Baostock"""
    from data_sources.baostock_source import BaostockSource
    source = BaostockSource()
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    df = source.get_stock_history("000001", start_date, end_date)
    if df is not None and not df.empty:
        return True, f"{len(df)}条记录"
    return False, "无数据"





def test_all_connections():
    """测试所有数据源连接"""
    print()
    print("=" * 55)
    print("  数据源连接测试")
    print("=" * 55)
    print()
    
    tests = [
        ("AkShare    ", test_akshare),
        ("Tushare    ", test_tushare),
        ("Baostock   ", test_baostock),
    ]
    
    results = []
    for name, func in tests:
        t0 = time.time()
        success, msg = run_with_timeout(func)
        elapsed = time.time() - t0
        
        if success is None:
            status = "--"
        elif success:
            status = "OK"
        else:
            status = "XX"
        
        print(f"  [{status}] {name} {elapsed:.1f}s - {msg}")
        results.append((name.strip(), status, msg, elapsed))
    
    print()
    passed = sum(1 for r in results if r[1] == "OK")
    print(f"  结果: {passed}/{len(results)} 通过")
    print("=" * 55)
    print()
    return results

# ==================== 股票/可转债查询 ====================

def query_stock(code, source=None):
    """查询股票信息"""
    if source is None:
        from data_sources.akshare_source import AkShareSource
        source = AkShareSource()
    
    print(f"\n  查询股票: {code}")
    print("  " + "-" * 40)
    
    try:
        t0 = time.time()
        info = source.get_stock_info(code)
        elapsed = time.time() - t0
        
        if info:
            print(f"  状态: OK ({elapsed:.2f}s)")
            print(f"  代码: {info.code}")
            print(f"  名称: {info.name}")
            print(f"  行业: {info.industry}")
            print(f"  市场: {info.market}")
            return info
        else:
            print(f"  状态: 未找到 ({elapsed:.2f}s)")
            return None
    except Exception as e:
        print(f"  错误: {e}")
        return None

def query_bond(code, source=None):
    """查询可转债信息"""
    if source is None:
        from data_sources.akshare_source import AkShareSource
        source = AkShareSource()
    
    print(f"\n  查询可转债: {code}")
    print("  " + "-" * 40)
    
    try:
        t0 = time.time()
        info = source.get_bond_info(code)
        elapsed = time.time() - t0
        
        if info:
            print(f"  状态: OK ({elapsed:.2f}s)")
            print(f"  代码: {info.code}")
            print(f"  名称: {info.name}")
            print(f"  正股: {info.underlying_stock} ({info.underlying_code})")
            print(f"  评级: {info.rating}")
            
            # 查询正股行业
            if info.underlying_code:
                stock_info = source.get_stock_info(info.underlying_code)
                if stock_info:
                    print(f"  行业: {stock_info.industry}")
            return info
        else:
            print(f"  状态: 未找到 ({elapsed:.2f}s)")
            return None
    except Exception as e:
        print(f"  错误: {e}")
        return None

# ==================== 交互模式 ====================

def interactive_mode():
    """交互模式"""
    print()
    print("=" * 55)
    print("  快速查询模式")
    print("=" * 55)
    print()
    print("  命令: 输入代码查询 | 't'测试连接 | 'q'退出")
    print("  股票: 60/00/30/68 开头 | 可转债: 11/12/13/40 开头")
    print()
    
    from data_sources.akshare_source import AkShareSource
    source = AkShareSource()
    
    while True:
        try:
            code = input("  > ").strip()
            
            if code.lower() == 'q':
                print("  再见!")
                break
            elif code.lower() == 't':
                test_all_connections()
                continue
            elif not code:
                continue
            
            if is_bond_code(code):
                query_bond(code, source)
            elif is_stock_code(code):
                query_stock(code, source)
            else:
                print(f"  无效代码: {code} (股票60/00/30/68 可转债11/12/13/40)")
        except KeyboardInterrupt:
            print("\n  再见!")
            break
        except Exception as e:
            print(f"  错误: {e}")
    print()

# ==================== 主函数 ====================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='数据源连接测试工具')
    parser.add_argument('code', nargs='?', help='股票或可转债代码')
    parser.add_argument('-t', '--test', action='store_true', help='测试所有数据源连接')
    parser.add_argument('-i', '--interactive', action='store_true', help='交互模式')
    
    args = parser.parse_args()
    
    if args.test:
        test_all_connections()
    elif args.interactive:
        interactive_mode()
    elif args.code:
        if is_bond_code(args.code):
            query_bond(args.code)
        elif is_stock_code(args.code):
            query_stock(args.code)
        else:
            print(f"\n  无效代码: {args.code}")
            print("  股票: 60/00/30/68 开头")
            print("  可转债: 11/12/13/40 开头\n")
    else:
        test_all_connections()
        interactive_mode()

if __name__ == "__main__":
    main()
