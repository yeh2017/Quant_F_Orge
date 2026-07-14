import React, { useState, useEffect, useRef, useCallback } from 'react';
import { TrendingUp, Database, Brain, Target, Play, BarChart3, Settings, Activity, AlertCircle, Download, Zap, Shield, LineChart, Filter, RefreshCw, Layers, Search, Newspaper } from 'lucide-react';
import { stockApi, bondApi, factorApi, backtestApi, portfolioOptApi, screenerApi, dataCenterApi, riskApi } from './services/api';
import { makeAlert } from './utils/format';
import DataCenterPanel from './components/DataSource/DataCenterPanel';

import StockPoolPanel from './components/StockPool/StockPoolPanel';
import FactorPanel from './components/Factor/FactorPanel';
import StrategyBacktestPanel from './components/StrategyBacktest/StrategyBacktestPanel';
import PortfolioPanel from './components/Portfolio/PortfolioPanel';
import RiskPanel from './components/Risk/RiskPanel';
import VisualPanel from './components/Visual/VisualPanel';
import ScreenerPanel from './components/Screener/ScreenerPanel';
import NewsPanel from './components/News/NewsPanel';
import SettingsModal from './components/Settings/SettingsModal';
import GlobalLoading from './components/common/GlobalLoading';
import ErrorBoundary from './components/common/ErrorBoundary';
import useWebSocket from './hooks/useWebSocket';

// ── localStorage 持久化工具 ──
const STORAGE_KEYS = {
    stocks: 'qp_customStocks',
    bonds: 'qp_customBonds',
};
const loadJSON = (key, fallback) => { try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; } catch { return fallback; } };

const QuantPlatform = () => {
    // activeTab 固定默认"数据中台"，不从 localStorage 恢复，避免每次打开随机跳页
    const [activeTab, setActiveTab] = useState('data');
    
    const [customStocks, setCustomStocks] = useState(() => loadJSON(STORAGE_KEYS.stocks, []));
    const [customBonds, setCustomBonds] = useState(() => loadJSON(STORAGE_KEYS.bonds, []));
    const [loading, setLoading] = useState(false);
    const [alerts, setAlerts] = useState([]);
    const [pendingStock, setPendingStock] = useState(null);

    // ── 回测链路状态（回测→风险→组合，三面板共享）──
    const [strategyType, setStrategyType] = useState('multifactor');
    const [selectedFactors, setSelectedFactors] = useState({
        reversal: true, value: true, quality: true, size: true,
        momentum: true, lowvol: true, growth: true,
        dividend: true, concentration: true, leverage: true,
    });
    const [backtestResults, setBacktestResults] = useState(null);
    const [riskAnalysis, setRiskAnalysis] = useState(null);
    const [portfolio, setPortfolio] = useState(null);

    // ── 同步状态 ──
    const [syncing, setSyncing] = useState(false);
    const [syncProgress, setSyncProgress] = useState({ status: 'ready', message: '', percent: 0 });
    const [showSettings, setShowSettings] = useState(false);
    const [settingsVersion, setSettingsVersion] = useState(0);  // 设置弹窗关闭时递增，通知子组件刷新
    const [refreshTrigger, setRefreshTrigger] = useState(0);  // 同步完成后递增，触发子组件重新拉取
    // 拉取日期范围（由 DataCenterPanel 控制）
    const today = new Date().toISOString().slice(0, 10);
    const [startDate, setStartDate] = useState('2024-01-01');
    const [endDate, setEndDate] = useState(today);
    const pollRef = useRef(null);
    const syncTaskIdRef = useRef(null);  // 当前同步任务 ID
    const backtestTaskIdRef = useRef(null);  // 当前回测任务 ID
    const backtestPollRef = useRef(null);    // 回测轮询 fallback

    // 清理轮询定时器
    useEffect(() => {
        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
            if (backtestPollRef.current) clearInterval(backtestPollRef.current);
        };
    }, []);


    // ── 状态变化 → 写入 localStorage（仅持久化自选池，日期不持久化）──
    useEffect(() => { localStorage.setItem(STORAGE_KEYS.stocks, JSON.stringify(customStocks)); }, [customStocks]);
    useEffect(() => { localStorage.setItem(STORAGE_KEYS.bonds, JSON.stringify(customBonds)); }, [customBonds]);

    // ── WebSocket 推送（任务进度 + 新闻更新）──
    // ── 回测完成后的结果处理（WS 和轮询共用） ──
    const handleBacktestResult = useCallback(async (results, taskCtx) => {
        setBacktestResults({ ...results, strategy_type: taskCtx.strategyType });
        // 用后端 /risk/analyze 计算完整风险指标
        try {
            const codes = taskCtx.targetCodes || [...customStocks, ...customBonds].map(s => s.code);
            const dates = results.dates || [];
            if (codes.length > 0 && dates.length >= 2) {
                const res = await riskApi.analyze(codes, dates[0], dates[dates.length - 1]);
                setRiskAnalysis(res.risk || null);
            }
        } catch { /* risk 失败不阻塞 */ }
        // 固定池才做组合优化
        if (taskCtx.targetCodes && taskCtx.targetCodes.length > 0) {
            try {
                const allStocks = [...customStocks, ...customBonds];
                const stockNames = Object.fromEntries(allStocks.map(s => [s.code, s.name || s.code]));
                const res = await portfolioOptApi.optimizeAll(taskCtx.targetCodes, 252, stockNames);
                setPortfolio(res?.results || null);
            } catch { setPortfolio(null); }
        } else {
            setPortfolio(null);
        }
        setAlerts([makeAlert('success', '回测完成')]);
        setLoading(false);
    }, [customStocks, customBonds]);

    const handleWsMessage = useCallback((msg) => {

        if (msg.type !== 'task_update') return;
        const { task_id, task_type, status, result, error } = msg.payload;

        // ── 回测任务 WS 推送 ──
        if (task_type === 'backtest' && backtestTaskIdRef.current?.taskId === task_id) {
            if (status === 'completed' && result) {
                if (backtestPollRef.current) { clearInterval(backtestPollRef.current); backtestPollRef.current = null; }
                const ctx = backtestTaskIdRef.current;
                backtestTaskIdRef.current = null;
                handleBacktestResult(result, ctx);
            } else if (status === 'failed') {
                if (backtestPollRef.current) { clearInterval(backtestPollRef.current); backtestPollRef.current = null; }
                backtestTaskIdRef.current = null;
                setAlerts([makeAlert('error', `回测失败: ${error}`)]);
                setLoading(false);
            }
            return;
        }

        // ── 同步任务 ──
        if (!syncTaskIdRef.current || task_id !== syncTaskIdRef.current) return;

        if (status === 'completed') {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setSyncProgress({ status: 'completed', message: result?.message || '同步完成！', percent: 100 });
            setSyncing(false);
            syncTaskIdRef.current = null;
            setRefreshTrigger(prev => prev + 1);
        } else if (status === 'failed') {
            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
            setSyncProgress({ status: 'error', message: `同步失败: ${error || '未知错误'}`, percent: 0 });
            setSyncing(false);
            syncTaskIdRef.current = null;
        } else {
            const progress = result?.progress || 0;
            const steps = result?.steps || [];
            setSyncProgress({
                status: 'syncing',
                message: result?.message || '同步中...',
                percent: Math.max(10, Math.min(95, progress)),
                steps,
            });
        }
    }, [handleBacktestResult]);

    useWebSocket(handleWsMessage);

    const handleDataSync = useCallback(async (targetMode, forceRefill = false, scope = null) => {
        setSyncing(true);
        setSyncProgress({ status: 'starting', message: '正在初始化同步任务...', percent: 5 });

        try {
            const syncPayload = {
                start_date: startDate,
                end_date: endDate,
                mode: targetMode,
                force_refill: forceRefill,
                scope,
            };
            if (targetMode === 'pool' && (customStocks.length > 0 || customBonds.length > 0)) {
                syncPayload.codes = [...customStocks, ...customBonds].map(s => s.code);
            }
            const res = await dataCenterApi.syncFull(syncPayload);
            const taskId = res.task_id;
            syncTaskIdRef.current = taskId;  // WS 推送用

            setSyncProgress({ status: 'syncing', message: '后台全量同步中（股票列表→行情→因子→财务）...', percent: 10 });

            if (pollRef.current) clearInterval(pollRef.current);

            pollRef.current = setInterval(async () => {
                // 如果 WS 已处理了终态，跳过轮询
                if (!syncTaskIdRef.current) {
                    clearInterval(pollRef.current);
                    pollRef.current = null;
                    return;
                }
                try {
                    const taskStatus = await dataCenterApi.getTaskStatus(taskId);

                    if (taskStatus.status === 'completed') {
                        clearInterval(pollRef.current);
                        pollRef.current = null;
                        const doneMsg = taskStatus.result?.message || '全量同步完成！';
                        setSyncProgress({ status: 'completed', message: doneMsg, percent: 100 });
                        setSyncing(false);
                        syncTaskIdRef.current = null;
                        setRefreshTrigger(prev => prev + 1);
                    } else if (taskStatus.status === 'failed') {
                        clearInterval(pollRef.current);
                        pollRef.current = null;
                        setSyncProgress({ status: 'error', message: `同步失败: ${taskStatus.error || '未知错误'}`, percent: 0 });
                        setSyncing(false);
                        syncTaskIdRef.current = null;
                    } else {
                        const progress = taskStatus.result?.progress || 0;
                        const msg = taskStatus.result?.message || '后台同步中...';
                        const steps = taskStatus.result?.steps || [];
                        setSyncProgress({
                            status: 'syncing',
                            message: msg,
                            percent: Math.max(10, Math.min(95, progress)),
                            steps,
                        });
                    }
                } catch (pollErr) {
                    console.warn('Task poll error:', pollErr);
                }
            }, 2000);

        } catch (error) {
            console.error('Sync failed', error);
            setSyncProgress({ status: 'error', message: `同步失败: ${error.message}`, percent: 0 });
            setSyncing(false);
        }
    }, [customStocks, customBonds, startDate, endDate]);


    // 运行回测 (异步 + 轮询)
    const runBacktest = async (strategyParams = null, universeConfig = null, backtestDates = null) => {
        const allStocks = [...customStocks, ...customBonds];
        if (!universeConfig && allStocks.length === 0) {
            setAlerts([makeAlert('error', '请先在自选池中添加标的，或选择动态标的池')]);
            return;
        }
        setLoading(true);
        setBacktestResults(null);
        setRiskAnalysis(null);
        try {
            const targetCodes = universeConfig ? null : allStocks.map(s => s.code);

            const { task_id } = await backtestApi.runAsync(targetCodes, {
                strategyType, selectedFactors, rebalancePeriod: 'monthly',
                startDate: backtestDates?.startDate,
                endDate: backtestDates?.endDate,
                strategyParams,
                universeConfig,
            });

            // 存入 ref 供 WS 回调使用（快照提交时的上下文）
            backtestTaskIdRef.current = { taskId: task_id, targetCodes, strategyType };
            setAlerts([makeAlert('info', `回测任务已提交 (ID: ${task_id.slice(0, 8)}...)，等待结果...`)]);

            // 轮询 fallback（3 秒一次，WS 正常时不会用到）
            const taskCtx = backtestTaskIdRef.current;  // 快照
            backtestPollRef.current = setInterval(async () => {
                if (!backtestTaskIdRef.current) return;  // WS 已处理，跳过
                try {
                    const statusRes = await backtestApi.getStatus(task_id);
                    if (!backtestTaskIdRef.current) return;  // 请求期间 WS 已处理
                    if (statusRes.status === 'completed') {
                        clearInterval(backtestPollRef.current); backtestPollRef.current = null;
                        backtestTaskIdRef.current = null;
                        handleBacktestResult(statusRes.result, taskCtx);
                    } else if (statusRes.status === 'failed') {
                        clearInterval(backtestPollRef.current); backtestPollRef.current = null;
                        backtestTaskIdRef.current = null;
                        setAlerts([makeAlert('error', `回测失败: ${statusRes.error}`)]);
                        setLoading(false);
                    }
                } catch (e) {
                    clearInterval(backtestPollRef.current); backtestPollRef.current = null;
                    backtestTaskIdRef.current = null;
                    setAlerts([makeAlert('error', `轮询出错: ${e.message}`)]);
                    setLoading(false);
                }
            }, 3000);

        } catch (e) {
            setLoading(false);
            setAlerts([makeAlert('error', `任务提交失败: ${e.message}`)]);
        }
    };

    // 加载策略
    const handleLoadStrategy = (strategy) => {
        const params = strategy.parameters;
        if (!params) return;
        if (params.customStocks) setCustomStocks(params.customStocks);
        if (params.selectedFactors) setSelectedFactors(params.selectedFactors);
        if (params.strategyType) setStrategyType(params.strategyType);
        setAlerts([makeAlert('success', `已加载策略: ${strategy.name}`)]);
    };

    const tabs = [
        { id: 'data', label: '数据中台', icon: Database },
        { id: 'screener', label: '智能选股', icon: Search },
        { id: 'factor', label: '因子模块', icon: Brain },
        { id: 'strategy-backtest', label: '策略回测', icon: Zap },
        { id: 'portfolio', label: '组合优化', icon: Target },
        { id: 'risk', label: '风险管理', icon: Shield },
        { id: 'visual', label: '可视化', icon: LineChart },
        { id: 'news', label: '新闻中心', icon: Newspaper }
    ];

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-950 p-4">
            <div className="max-w-7xl mx-auto">
                {/* Header */}
                <div className="bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 rounded-xl p-6 mb-6 shadow-2xl">
                    <div className="flex items-center justify-between">
                        <div>
                            <h1 className="text-3xl font-bold text-white mb-2">
                                QFO量化回测平台
                            </h1>
                            <p className="text-purple-100">多数据源集成 | 因子模块 | 策略回测 | 组合优化</p>
                        </div>
                        <div className="flex items-center gap-4">
                            <div className="text-right">
                                <div className="text-purple-100 text-sm mb-1">数据中台</div>
                                <div className="flex items-center gap-2">
                                    <div className="w-3 h-3 rounded-full bg-green-400 animate-pulse" />
                                    <span className="text-white font-bold">Tushare Pro</span>
                                </div>
                            </div>
                            <button onClick={() => setShowSettings(true)}
                                className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-white/90 hover:bg-white text-slate-800 transition-all shadow-sm"
                                title="系统设置">
                                <Settings className="w-5 h-5" />
                                <span className="text-sm font-medium">管理</span>
                            </button>
                        </div>
                    </div>
                </div>

                {/* Alerts */}
                {alerts.length > 0 && (
                    <div className="mb-4 space-y-2">
                        {alerts.map((alert, idx) => (
                            <div key={idx} className={`p-3 rounded-lg flex items-center gap-2 border ${alert.type === 'success' ? 'bg-green-900/30 border-green-500/50 text-green-200' :
                                alert.type === 'error' ? 'bg-red-900/30 border-red-500/50 text-red-200' :
                                    'bg-blue-900/30 border-blue-500/50 text-blue-200'
                                }`}>
                                <AlertCircle className="w-4 h-4" />
                                {alert.msg}
                            </div>
                        ))}
                    </div>
                )}

                {/* Navigation */}
                <div className="grid grid-cols-8 gap-2 mb-6">
                    {tabs.map(tab => (
                        <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                            className={`py-3 px-3 rounded-lg font-medium transition-all flex flex-col items-center gap-1 ${activeTab === tab.id
                                ? 'bg-gradient-to-r from-indigo-600 to-purple-600 text-white shadow-lg scale-105'
                                : 'bg-slate-800/50 text-purple-200 hover:bg-slate-700/50'
                                }`}>
                            <tab.icon className="w-5 h-5" />
                            <span className="text-xs">{tab.label}</span>
                        </button>
                    ))}
                </div>

                {/* Main Content */}
                <div className="bg-slate-800/50 rounded-xl p-6 shadow-2xl border border-slate-700/50">

                    <div style={{ display: activeTab === 'data' ? 'block' : 'none' }}>
                        <ErrorBoundary name="数据中台">
                            <div className="flex flex-col gap-6">
                                <DataCenterPanel
                                    startDate={startDate}
                                    endDate={endDate}
                                    setStartDate={setStartDate}
                                    setEndDate={setEndDate}
                                    syncing={syncing}
                                    syncProgress={syncProgress}
                                    onSync={handleDataSync}
                                    isActive={activeTab === 'data'}
                                    settingsVersion={settingsVersion}
                                />

                                <StockPoolPanel
                                    customStocks={customStocks}
                                    setCustomStocks={setCustomStocks}
                                    customBonds={customBonds}
                                    setCustomBonds={setCustomBonds}
                                    setAlerts={setAlerts}
                                    setLoading={setLoading}
                                    loading={loading}
                                />
                            </div>
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'screener' ? 'block' : 'none' }}>
                        <ErrorBoundary name="智能选股">
                            <ScreenerPanel
                                isActive={activeTab === 'screener'}
                                customStocks={customStocks}
                                setCustomStocks={setCustomStocks}
                                customBonds={customBonds}
                                setCustomBonds={setCustomBonds}
                                setAlerts={setAlerts}
                                refreshTrigger={refreshTrigger}
                                onViewKline={(code) => {
                                    setPendingStock(code);
                                    setActiveTab('visual');
                                }}
                            />
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'factor' ? 'block' : 'none' }}>
                        <ErrorBoundary name="因子模块">
                            <FactorPanel
                                selectedFactors={selectedFactors}
                                setSelectedFactors={setSelectedFactors}
                                customStocks={customStocks}
                                setCustomStocks={setCustomStocks}
                                loading={loading}
                                setLoading={setLoading}
                                setAlerts={setAlerts}
                                onViewKline={(code) => { setPendingStock(code); setActiveTab('visual'); }}
                                onGoToBacktest={() => setActiveTab('strategy-backtest')}
                            />
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'strategy-backtest' ? 'block' : 'none' }}>
                        <ErrorBoundary name="策略回测">
                            <StrategyBacktestPanel
                                strategyType={strategyType}
                                setStrategyType={setStrategyType}
                                runBacktest={runBacktest}
                                loading={loading}
                                customStocks={[...customStocks, ...customBonds]}
                                backtestResults={backtestResults}
                                setBacktestResults={setBacktestResults}
                                onViewKline={(code) => { setPendingStock(code); setActiveTab('visual'); }}
                                currentConfig={{
                                    customStocks,
                                    selectedFactors,
                                    strategyType,
                                }}
                                onLoadStrategy={handleLoadStrategy}
                                setAlerts={setAlerts}
                                setRiskAnalysis={setRiskAnalysis}
                                onGoToRisk={() => setActiveTab('risk')}
                            />
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'portfolio' ? 'block' : 'none' }}>
                        <ErrorBoundary name="组合优化">
                            <PortfolioPanel
                                backtestPortfolio={portfolio}
                                customStocks={[...customStocks, ...customBonds]}
                                onViewKline={(code) => { setPendingStock(code); setActiveTab('visual'); }}
                                setAlerts={setAlerts}
                            />
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'risk' ? 'block' : 'none' }}>
                        <ErrorBoundary name="风险管理">
                            <RiskPanel
                                riskAnalysis={riskAnalysis}
                                customStocks={[...customStocks, ...customBonds]}
                                onResult={(r) => setRiskAnalysis(r)}
                                cumReturns={backtestResults?.cumReturns}
                                dates={backtestResults?.dates}
                            />
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'visual' ? 'block' : 'none' }}>
                        <ErrorBoundary name="可视化">
                            <VisualPanel backtestResults={backtestResults} customStocks={[...customStocks, ...customBonds]}
                                setCustomStocks={setCustomStocks} setCustomBonds={setCustomBonds}
                                initialStock={pendingStock} onInitialStockConsumed={() => setPendingStock(null)} />
                        </ErrorBoundary>
                    </div>

                    <div style={{ display: activeTab === 'news' ? 'block' : 'none' }}>
                        <ErrorBoundary name="新闻中心">
                            <NewsPanel
                                isActive={activeTab === 'news'}
                                customStocks={customStocks}
                                onViewKline={(code) => { setPendingStock(code); setActiveTab('visual'); }}
                            />
                        </ErrorBoundary>
                    </div>
                </div>

                {/* Footer */}
                <div className="mt-6 bg-slate-800/50 rounded-lg px-4 py-3 text-purple-200 text-sm">
                    自选池: <span className="text-white font-bold">{customStocks.length + customBonds.length}</span> 只
                </div>
            </div>
            <GlobalLoading loading={loading} text="处理中..." onCancel={() => setLoading(false)} />
            {showSettings && <SettingsModal onClose={() => { setShowSettings(false); setSettingsVersion(v => v + 1); }} />}
        </div>
    );
};

export default QuantPlatform;
