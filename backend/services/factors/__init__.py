"""
因子模块
========
将 factor_service.py 的内部逻辑按职责拆分：
- calculator.py   : 单只股票的因子计算函数
- loader.py       : 批量 SQL 截面数据加载（打分系统用）
- panel_loader.py  : 面板数据加载（研究平台用，date × code 结构）
- scoring.py      : 截面标准化 + 综合评分 + 向量化打分 + IC 分析
- expression.py   : 因子表达式 DSL 引擎（AST 解析 + 安全执行）
- stratified.py   : 分层回测（因子有效性验证）
- utils.py        : 工具函数

FactorService 仍作为唯一公开入口，保持向后兼容。
"""
