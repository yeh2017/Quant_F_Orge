/**
 * API 服务层 - 连接 Python 后端
 */

import { showToast } from '../utils/toast';

const API_BASE = '/api';

// 通用请求方法（含全局错误拦截）
async function request(url, options = {}) {
    let response;
    try {
        response = await fetch(`${API_BASE}${url}`, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            cache: 'no-store',
            ...options,
        });
    } catch (networkError) {
        // 网络不可达（后端没启动、断网等）
        showToast('网络连接失败，请检查后端是否启动', 'error');
        throw networkError;
    }

    if (!response.ok) {
        const error = await response.json().catch(() => ({ detail: '请求失败' }));
        const msg = error.detail || `HTTP ${response.status}`;

        // 全局 toast：5xx 服务端错误 或 非 4xx 的异常
        if (response.status >= 500) {
            showToast(`服务端错误: ${msg}`, 'error');
        } else if (response.status === 404) {
            showToast(`接口不存在: ${url}`, 'warning');
        }
        // 4xx 业务错误不弹 toast，交给组件自行处理

        throw new Error(msg);
    }

    return response.json();
}



// ==================== 数据中台 API ====================
export const dataCenterApi = {
    // 获取中台状态（含各表记录数、最新日期）
    getStatus: () => request('/data_center/status'),

    // 查询同步任务进度
    getTaskStatus: (taskId) => request(`/data_center/task/${taskId}`),



    // 全量同步（支持 scope 控制同步范围）
    syncFull: (options) => request('/data_center/sync_full', {
        method: 'POST',
        body: JSON.stringify({
            start_date: options.start_date,
            end_date: options.end_date,
            mode: options.mode,
            codes: options.codes || null,
            force_refill: options.force_refill || false,
            scope: options.scope || null,
        }),
    }),



    // 获取最新每日信号（Top N 股票因子得分）
    getDailySignals: (date = null, topN = 10, { excludeSt = true, weights = null } = {}) => {
        const params = new URLSearchParams();
        if (date) params.append('date', date);
        params.append('top_n', topN);
        params.append('exclude_st', excludeSt);
        if (weights) params.append('weights', JSON.stringify(weights));
        return request(`/data_center/daily_signals?${params}`);
    },

    // 手动触发每日信号计算
    triggerSignals: ({ date = null, excludeSt = true, minListDays = 60 } = {}) => {
        const params = new URLSearchParams();
        if (date) params.append('date', date);
        params.append('exclude_st', excludeSt);
        params.append('min_list_days', minListDays);
        return request(`/data_center/trigger_signals?${params}`, { method: 'POST' });
    },

};


// ==================== 可转债因子 API ====================
export const bondFactorApi = {
    // 获取最新双低排行（按 double_low_score 升序）
    getSnapshot: (options = {}) => {
        const params = new URLSearchParams();
        if (options.limit) params.append('limit', options.limit);
        if (options.max_premium !== undefined) params.append('max_premium', options.max_premium);
        if (options.max_price !== undefined) params.append('max_price', options.max_price);
        if (options.min_rating) params.append('min_rating', options.min_rating);
        if (options.include_all) params.append('include_all', 'true');
        return request(`/bonds/factor_snapshot?${params.toString()}`);
    },

    // 全市场可转债概览统计（不依赖筛选条件）
    getOverview: () => request('/bonds/overview'),

};

// ==================== 选股器 API ====================
export const screenerApi = {
    // 获取可选行业列表
    getIndustries: () => request('/screener/industries'),

    // 获取行业当日平均涨跌幅
    getIndustryHeat: () => request('/screener/industry-heat'),

    // 大盘市场状态
    getMarketRegime: () => request('/screener/market-regime'),

    // 个股弱转强/强转弱
    getStockReversal: () => request('/screener/stock-reversal'),

    // 按因子阈值筛选股票
    screen: (filters) => request('/screener/', {
        method: 'POST',
        body: JSON.stringify(filters),
    }),

    // ── ETF ──
    getEtfReversal: () => request('/screener/etf-reversal'),
    getEtfSmart: (topN = 20, category = null, subCategory = null) => {
        const params = new URLSearchParams({ top_n: topN });
        if (category) params.append('category', category);
        if (subCategory) params.append('sub_category', subCategory);
        return request(`/screener/etf-smart?${params}`);
    },
    getEtfRanking: (topN = 10) => request(`/screener/etf-ranking?top_n=${topN}`),
    getEtfOverview: () => request('/screener/etf-overview'),
    getEtfStockLink: (volumeRatio = 1.5) => request(`/screener/etf-stock-link?volume_ratio=${volumeRatio}`),
    getStockToEtf: (code) => request(`/screener/stock-to-etf?code=${encodeURIComponent(code)}`),
    getEtfRotation: (days = 30) => request(`/screener/etf-rotation?days=${days}`),

    // 批量事件标签（大宗/解禁/龙虎/融资趋势）
    getEventTags: (codes) => request('/screener/event-tags', {
        method: 'POST',
        body: JSON.stringify({ codes }),
    }),
};

// ==================== 股票 API ====================

export const stockApi = {

    // 获取股票信息
    getInfo: (code) => request(`/stocks/info/${code}`),



    // 获取历史行情
    getHistory: (code, startDate, endDate, adjust = 'qfq') => {
        const params = new URLSearchParams();
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);
        params.append('adjust', adjust);
        return request(`/stocks/history/${code}?${params}`);
    },

    // 获取个股融资余额时序（K线叠加用）
    getMargin: (code, startDate, endDate) => {
        const params = new URLSearchParams();
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);
        return request(`/stocks/margin/${code}?${params}`);
    },



    // 搜索股票
    search: (keyword) => request(`/stocks/search?keyword=${encodeURIComponent(keyword)}`),

    // 技术诊断 — 单只完整
    getDiagnosis: (code, endDate) => {
        const params = new URLSearchParams();
        if (endDate) params.append('end_date', endDate);
        return request(`/stocks/diagnosis/${code}?${params}`);
    },

    // 技术诊断 — 批量精简
    getDiagnosisBatch: (codes) => request('/stocks/diagnosis/batch', {
        method: 'POST',
        body: JSON.stringify({ codes }),
    }),

};

// ==================== 可转债 API ====================

export const bondApi = {


    // 获取可转债信息
    getInfo: (code) => request(`/bonds/info/${code}`),



    // 搜索可转债
    search: (keyword) => request(`/bonds/search?keyword=${encodeURIComponent(keyword)}`),
};

// ==================== 因子计算 API ====================

export const factorApi = {
    // 获取因子元数据（卡片定义 + 权重）
    getMeta: () => request('/factors/meta'),

    // 计算因子得分
    calculate: (codes, options = {}) => request('/factors/calculate', {
        method: 'POST',
        body: JSON.stringify({
            codes,
            start_date: options.startDate,
            end_date: options.endDate,
            selected_factors: options.selectedFactors,
            factor_weights: options.factorWeights,
        }),
    }),
    // 因子 IC 分析（绩效归因 + 推荐权重）
    icAnalysis: (codes, options = {}) => request('/factors/ic_analysis', {
        method: 'POST',
        body: JSON.stringify({
            codes,
            start_date: options.startDate,
            end_date: options.endDate,
        }),
    }),

    // IC 衰减曲线
    getIcDecay: () => request('/factors/ic-decay'),

    // 读取最新因子评分快照（挂载时缓存用）
    getLatestSnapshot: () => request('/factors/snapshot/latest'),
};

// ==================== 回测 API ====================

export const backtestApi = {
    // 同步路由 POST /backtest/run 保留供 curl 调试，前端统一走 runAsync

    // 运行回测 (异步)
    runAsync: (codes, options = {}) => request('/backtest/run_async', {
        method: 'POST',
        body: JSON.stringify({
            codes,
            strategy_type: options.strategyType || 'multifactor',
            start_date: options.startDate,
            end_date: options.endDate,
            initial_cash: options.initialCash || 1000000,
            commission: options.commission || 0.0003,
            selected_factors: options.selectedFactors,
            rebalance_period: options.rebalancePeriod || 'monthly',
            strategy_params: options.strategyParams || null,
            universe_config: options.universeConfig || null,
        }),
    }),

    // 获取任务状态
    getStatus: (taskId) => request(`/backtest/status/${taskId}`),

    // 获取历史回测记录列表
    listHistory: (limit = 50) => request(`/backtest/list?limit=${limit}`),

    // 删除回测记录
    deleteResult: (id) => request(`/backtest/${id}`, { method: 'DELETE' }),

    // 回测详情
    getDetail: (id) => request(`/backtest/${id}/detail`),

    // 全市场标的池预览
    previewUniverse: ({ universeConfig }) => request('/backtest/preview_universe', {
        method: 'POST',
        body: JSON.stringify({ universe_config: universeConfig }),
    }),

    // 多策略对比
    compare: (codes, strategies, options = {}) => request('/backtest/compare', {
        method: 'POST',
        body: JSON.stringify({
            codes,
            strategies,
            start_date: options.startDate,
            end_date: options.endDate,
            initial_cash: options.initialCash || 1000000,
            commission: options.commission || 0.0003,
            rebalance_period: options.rebalancePeriod || 'monthly',
        }),
    }),

    // 参数优化（网格搜索）
    optimize: (codes, strategyType, paramRanges, options = {}) => request('/backtest/optimize', {
        method: 'POST',
        body: JSON.stringify({
            codes,
            strategy_type: strategyType,
            param_ranges: paramRanges,
            start_date: options.startDate,
            end_date: options.endDate,
            initial_cash: options.initialCash || 1000000,
            commission: options.commission || 0.0003,
            rebalance_period: options.rebalancePeriod || 'monthly',
            top_n: options.topN || 10,
        }),
    }),
};


// ==================== 策略管理 API ====================

export const strategyApi = {
    // 获取用户保存的策略（main.py CRUD）
    getAll: () => request('/strategies'),

    // 获取策略参数 Schema（供前端动态渲染）
    getParams: (strategyId) => request(`/strategies/params/${strategyId}`),



    // 保存策略
    create: (strategy) => request('/strategies', {
        method: 'POST',
        body: JSON.stringify(strategy),
    }),

    // 删除策略
    delete: (id) => request(`/strategies/${id}`, {
        method: 'DELETE',
    }),
};

// ==================== 风险分析 API ====================
export const riskApi = {
    // 基于持仓代码+时间范围计算风险指标
    analyze: (codes, startDate, endDate, weights = null, includeBenchmark = true) =>
        request('/risk/analyze', {
            method: 'POST',
            body: JSON.stringify({
                codes,
                start_date: startDate,
                end_date: endDate,
                weights,
                include_benchmark: includeBenchmark,
            }),
        }),


};

// ==================== 组合优化 API ====================
export const portfolioOptApi = {
    // 计算最优权重（单种方法）
    optimize: (codes, method = 'max_sharpe', lookbackDays = 252, stockNames = null, expectedReturns = null) =>
        request('/portfolio/optimize', {
            method: 'POST',
            body: JSON.stringify({
                codes,
                method,
                lookback_days: lookbackDays,
                stock_names: stockNames,
                expected_returns: expectedReturns,
            }),
        }),

    // 一次计算全部 4 种优化方法
    optimizeAll: (codes, lookbackDays = 252, stockNames = null, expectedReturns = null) =>
        request('/portfolio/optimize-all', {
            method: 'POST',
            body: JSON.stringify({
                codes,
                lookback_days: lookbackDays,
                stock_names: stockNames,
                expected_returns: expectedReturns,
            }),
        }),

    // 再平衡模拟
    rebalanceSim: (codes, options = {}) => request('/portfolio/rebalance-sim', {
        method: 'POST',
        body: JSON.stringify({
            codes,
            method: options.method || 'max_sharpe',
            period: options.period || 'monthly',
            lookback_days: options.lookbackDays || 252,
            commission_rate: options.commissionRate || 0.001,
            start_date: options.startDate,
            end_date: options.endDate,
        }),
    }),
};

// ==================== 新闻资讯 API ====================
export const newsApi = {
    getList: (params = {}) => {
        const qs = new URLSearchParams();
        for (const [k, v] of Object.entries(params)) {
            if (v !== undefined && v !== null && v !== '') qs.append(k, v);
        }
        return request(`/news?${qs}`);
    },

    // 刷新新闻（手动拉取）
    refresh: (codes = []) => request('/news/refresh', {
        method: 'POST',
        body: JSON.stringify({ codes }),
    }),

    // 搜索新闻
    search: (keyword) => request('/news/search', {
        method: 'POST',
        body: JSON.stringify({ keyword }),
    }),

    // 获取自动拉取配置
    getAutoConfig: () => request('/news/auto-config'),

    // 设置自动拉取配置
    setAutoConfig: (config) => request('/news/auto-config', {
        method: 'POST',
        body: JSON.stringify(config),
    }),

    // 推送摘要
    sendSummary: () => request('/news/send-summary', { method: 'POST' }),

    // 推送测试（SettingsModal 调用，可指定渠道）
    testNotify: (channel = '') => request(`/news/notify-test${channel ? `?channel=${channel}` : ''}`, { method: 'POST' }),

    // 批量情绪查询（给 ResultTable 舆情列用）
    getSentimentBatch: (codes, days = 7) => request('/news/sentiment/batch', {
        method: 'POST',
        body: JSON.stringify({ codes, days }),
    }),

    // 事件回测统计
    getEventStats: (eventType = null, minScore = 0.3) => {
        const qs = new URLSearchParams();
        if (eventType) qs.append('event_type', eventType);
        qs.append('min_score', minScore);
        return request(`/news/event-stats?${qs}`);
    },
};

// ==================== 因子研究 API ====================
export const researchApi = {
    // 获取预设因子列表
    getPresets: () => request('/research/presets'),

    // 验证因子表达式
    validate: (expression) => request('/research/validate', {
        method: 'POST',
        body: JSON.stringify({ expression }),
    }),

    // 分层回测
    stratified: (options) => request('/research/stratified', {
        method: 'POST',
        body: JSON.stringify(options),
    }),
};

// ==================== 系统配置 API ====================
export const systemApi = {
    getConfig: () => request('/system/config'),
    updateConfig: (data) => request('/system/config', {
        method: 'PUT',
        body: JSON.stringify(data),
    }),
    getStatus: () => request('/system/status'),
    testLlm: () => request('/system/test-llm', { method: 'POST' }),
};

// 导出所有 API
export default {
    stock: stockApi,
    bond: bondApi,
    factor: factorApi,
    backtest: backtestApi,
    portfolio: portfolioOptApi,
    strategy: strategyApi,
    dataCenter: dataCenterApi,
    screener: screenerApi,
    risk: riskApi,
    news: newsApi,
    research: researchApi,
    system: systemApi,
};
