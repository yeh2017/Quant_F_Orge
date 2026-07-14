# -*- coding: utf-8 -*-
"""
SSL/TLS 修复模块
解决 HTTPS 连接中的 SSL 证书验证问题和 TLS 握手错误
包括: bad record mac, SSLError, SSLCertVerificationError 等
"""
import ssl
import os
import time

def apply_ssl_fix():
    """
    应用SSL修复，解决以下问题：
    - SSLError: bad record mac
    - SSLCertVerificationError  
    - HTTPS connection issues
    """
    # 禁用 urllib3 的不安全请求警告
    try:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    except Exception:
        pass
    
    # 创建不验证证书的 SSL 上下文
    try:
        ssl._create_default_https_context = ssl._create_unverified_context
    except AttributeError:
        pass
    
    # 设置环境变量
    os.environ['PYTHONHTTPSVERIFY'] = '0'
    os.environ['CURL_CA_BUNDLE'] = ''
    os.environ['REQUESTS_CA_BUNDLE'] = ''
    
    print("[SSL Fix] SSL verification disabled for HTTPS connections")
    return True


def _make_request_with_retry(method, url, max_retries=3, **kwargs):
    """带重试的请求函数"""
    import requests
    from requests.adapters import HTTPAdapter
    
    kwargs.setdefault('verify', False)
    kwargs.setdefault('timeout', 60)
    
    last_error = None
    for attempt in range(max_retries):
        try:
            # 每次尝试创建新的 session
            session = requests.Session()
            adapter = HTTPAdapter(max_retries=0)
            session.mount('https://', adapter)
            session.mount('http://', adapter)
            
            if method.lower() == 'get':
                response = session.get(url, **kwargs)
            else:
                response = session.post(url, **kwargs)
            
            return response
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
    
    # 尝试使用 httpx 作为备选
    try:
        import httpx
        with httpx.Client(verify=False, timeout=60) as client:
            if method.lower() == 'get':
                return client.get(url, **{k: v for k, v in kwargs.items() if k not in ['verify', 'timeout']})
            else:
                return client.post(url, **{k: v for k, v in kwargs.items() if k not in ['verify', 'timeout']})
    except Exception:
        pass
    
    raise last_error


def patch_akshare():
    """为 AkShare 应用 SSL/TLS 修复"""
    try:
        import requests
        
        # 保存原始函数
        _original_get = requests.api.get
        _original_post = requests.api.post
        
        def patched_get(url, **kwargs):
            kwargs.setdefault('verify', False)
            kwargs.setdefault('timeout', 60)
            try:
                return _make_request_with_retry('get', url, **kwargs)
            except Exception as e:
                # 最后尝试原始方法
                try:
                    return _original_get(url, **kwargs)
                except Exception:
                    raise e
        
        def patched_post(url, **kwargs):
            kwargs.setdefault('verify', False)
            kwargs.setdefault('timeout', 60)
            try:
                return _make_request_with_retry('post', url, **kwargs)
            except Exception as e:
                try:
                    return _original_post(url, **kwargs)
                except Exception:
                    raise e
        
        requests.get = patched_get
        requests.post = patched_post
        requests.api.get = patched_get
        requests.api.post = patched_post
        
        print("[SSL Fix] AkShare TLS patch applied with retry mechanism")
        return True
    except Exception as e:
        print(f"[SSL Fix] Failed to patch AkShare: {e}")
        return False


# 自动应用修复
if __name__ != "__main__":
    apply_ssl_fix()
    patch_akshare()


