import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
    Zap, Brain, Shield, Activity, Save, Trash2, FolderOpen, Plus, Calendar,
    BarChart3, Play, TrendingUp, AlertTriangle, Clock, RefreshCw, ChevronDown, SlidersHorizontal, Layers
} from 'lucide-react';
import { strategyApi, backtestApi, riskApi } from '../../services/api';
import { classifyAsset } from '../../utils/assetType';
import { fmtNum, fmtPct, pnlColor, makeAlert } from '../../utils/format';
import NetValueChart from '../Charts/NetValueChart';

const BUILTIN_STRATEGIES = [
    { id: 'multifactor', name: '因子选股', icon: Brain, desc: '多因子复合 / 纯低估值', detail: '复合模式: 价值+质量+动量多维打分 | 估值模式: 纯PE/PB最低排名 | 下拉切换', assetType: 'stock' },
    { id: 'timing', name: '均线择时', icon: Activity, desc: 'MA金叉/回踩双模式', detail: '金叉模式: 快线上穿慢线买入 | 回踩模式: 趋势中回踩短均线买入 | 下拉切换' },
    { id: 'macd', name: '动量指标', icon: TrendingUp, desc: 'MACD趋势 / RSI超买超卖', detail: 'MACD模式: DIF上穿DEA做多 | RSI模式: RSI<30买入 RSI>70卖出 | 下拉切换' },
    { id: 'bband', name: '布林带回归', icon: Shield, desc: '超卖买入超买卖出', detail: '周期20 / 标准差2σ | 下轨买入 / 上轨卖出 | 均值回归策略' },
    { id: 'turtle', name: '海龟交易', icon: Shield, desc: '唐奇安通道趋势突破', detail: '入场20日 / 出场10日 | 突破最高价买入 | ATR 2倍动态止损 | 经典趋势跟踪' },
    { id: 'volume_breakout', name: '放量突破', icon: TrendingUp, desc: '价涨量增突破前高', detail: 'N日最高价突破买入 | 成交量>均量M倍 | 跌破N日最低价止损 | 量价共振' },
    { id: 'grid', name: '网格交易', icon: Activity, desc: '震荡区间内分批高抛低吸', detail: '以均线为中轴，按固定间距设置网格 | 每跌一格加仓 | 每涨一格减仓' },
    { id: 'double_low_cb', name: '可转债双低', icon: Save, desc: '双低分月度轮动', detail: '双低分 = 转债价格 + 溢价率 | 月度调仓 | 仅限可转债标的', assetType: 'bond' },
    { id: 'etf_momentum', name: 'ETF动量轮动', icon: TrendingUp, desc: '持有近期最强ETF', detail: '按N日收益率排序 | 持有TopK个ETF | 定期轮换弱势标的 | 动量因子驱动', assetType: 'etf' },
    { id: 'event_driven', name: '事件驱动', icon: Zap, desc: '新闻事件信号择时', detail: '业绩/重组/大宗/解禁/龙虎榜等事件触发买入 | 持仓N天后卖出 | 可配事件类型·方向·持仓周期', assetType: 'stock' },
];

const STRATEGY_MAP = Object.fromEntries(BUILTIN_STRATEGIES.map(s => [s.id, s]));

// ── 路线图（待开发策略） ──
const ROADMAP_STRATEGIES = [
    { id: 'xgboost', name: 'XGBoost选股', icon: Zap, desc: '机器学习非线性合成' },
    { id: 'lstm', name: 'LSTM时序', icon: Activity, desc: '时间序列动量预测' },
    { id: 'k_pattern', name: 'K线形态', icon: Zap, desc: '早晨之星/红三兵识别' },
    { id: 'fractal', name: '缠论分型', icon: Activity, desc: '底分型与顶分型买卖' },
    { id: 'leader_2b', name: '二板定龙头', icon: Zap, desc: '弱转强换手二板上车' },
    { id: 'sentiment_cycle', name: '情绪周期', icon: Activity, desc: '冰点/回暖/主升判定' },

    { id: 'alert_sys', name: '即时预警', icon: Zap, desc: 'WebSocket条件推送' },
];

const StrategyBacktestPanel = ({
    strategyType,
    setStrategyType,
    runBacktest,
    loading,
    customStocks = [],
    backtestResults,
    setBacktestResults,
    onViewKline,
    currentConfig,
    onLoadStrategy,
    setAlerts,
    setRiskAnalysis,
    onGoToRisk,
}) => {
    // 回测日期独立管理（不依赖全局日期）
    const [startDate, setStartDate] = useState(() => {
        const d = new Date(Date.now() - 365 * 86400000);
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    });
    const [endDate, setEndDate] = useState(() => {
        const d = new Date();
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    });
    const [strategies, setStrategies] = useState([]);
    const [newStrategyName, setNewStrategyName] = useState('');
    const [saving, setSaving] = useState(false);
    const [showSaveInput, setShowSaveInput] = useState(false);
    const [showRoadmap, setShowRoadmap] = useState(false);
    const [showMonthly, setShowMonthly] = useState(false);
    const [showNetValue, setShowNetValue] = useState(false);
    const [showHoldings, setShowHoldings] = useState(false);
    const [showStockPool, setShowStockPool] = useState(false);

    // ── 对比模式 ──
    const [compareMode, setCompareMode] = useState(false);
    const [compareSelected, setCompareSelected] = useState(new Set());
    const [compareLoading, setCompareLoading] = useState(false);
    const [compareResults, setCompareResults] = useState(null);

    // ── 参数优化 ──
    const [optimizeLoading, setOptimizeLoading] = useState(false);
    const [optimizeResults, setOptimizeResults] = useState(null);

    // ── 回测历史 ──
    const [historyRecords, setHistoryRecords] = useState([]);
    const resultsRef = useRef(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [deleting, setDeleting] = useState(null);
    const [loadingHistoryId, setLoadingHistoryId] = useState(null);

    // ── 策略参数 ──
    const [strategyParamsSchema, setStrategyParamsSchema] = useState([]);
    const [strategyParamsValues, setStrategyParamsValues] = useState({});
    const [maxSingleWeight, setMaxSingleWeight] = useState(0); // 0=不限

    // ── 标的来源（独立状态，不寄存在策略参数中） ──
    const [universeSource, setUniverseSource] = useState('pool');
    const [filterValues, setFilterValues] = useState({});
    const [maxStocks, setMaxStocks] = useState(200);
    const [truncateBy, setTruncateBy] = useState('total_mv');
    const [universePreview, setUniversePreview] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [activePreset, setActivePreset] = useState(null);

    // 预览标的池数量（防抖 500ms）
    useEffect(() => {
        if (universeSource === 'pool') { setUniversePreview(null); return; }

        let cancelled = false;
        const timer = setTimeout(async () => {
            let universeConfig = null;
            if (universeSource === 'factor_filter') {
                const filters = {};
                Object.entries(filterValues).forEach(([k, v]) => {
                    if (v !== undefined && v !== '') filters[k] = Number(v);
                });
                if (Object.keys(filters).length === 0) { setUniversePreview(null); return; }
                universeConfig = { type: 'factor_filter', filters, max_stocks: Number(maxStocks) || 200 };
            } else {
                universeConfig = { type: 'full_market', max_stocks: Number(maxStocks) || 300 };
            }
            setPreviewLoading(true);
            try {
                const res = await backtestApi.previewUniverse({ universeConfig });
                if (!cancelled) setUniversePreview(res);
            } catch { if (!cancelled) setUniversePreview(null); }
            if (!cancelled) setPreviewLoading(false);
        }, 500);

        return () => { cancelled = true; clearTimeout(timer); };
    }, [universeSource, filterValues, maxStocks]);

    // 加载策略列表
    useEffect(() => { loadStrategies(); }, []);

    // 加载策略参数 Schema
    useEffect(() => {
        if (!strategyType) return;
        strategyApi.getParams(strategyType)
            .then(params => {
                setStrategyParamsSchema(params || []);
                const defaults = {};
                (params || []).forEach(p => { defaults[p.name] = p.default; });
                setStrategyParamsValues(defaults);
            })
            .catch(() => { setStrategyParamsSchema([]); setStrategyParamsValues({}); });
    }, [strategyType]);

    const loadStrategies = async () => {
        try {
            const res = await strategyApi.getAll();
            setStrategies(res || []);
        } catch (e) {
            console.error("Failed to load strategies", e);
        }
    };

    // 加载回测历史
    const loadHistory = useCallback(async () => {
        setHistoryLoading(true);
        try {
            const data = await backtestApi.listHistory(50);
            setHistoryRecords(data || []);
        } catch (e) { console.error('获取回测历史失败:', e); }
        finally { setHistoryLoading(false); }
    }, []);
    useEffect(() => { loadHistory(); }, [loadHistory]);
    // 回测完成后自动刷新历史（延迟确保后端已保存）
    useEffect(() => {
        if (!backtestResults) return;
        const timer = setTimeout(() => loadHistory(), 500);
        return () => clearTimeout(timer);
    }, [backtestResults]);

    // 清空全部回测记录
    const handleClearAllHistory = async () => {
        if (!historyRecords.length) return;
        if (!window.confirm(`确定清空全部 ${historyRecords.length} 条回测记录？此操作不可撤销。`)) return;
        try {
            // 逐条删除，忽略 404（已不存在的记录）
            await Promise.allSettled(historyRecords.map(r => backtestApi.deleteResult(r.id)));
            setHistoryRecords([]);
            setBacktestResults(null);
            setAlerts([makeAlert('success', '已清空全部回测历史')]);
        } catch (e) {
            setAlerts([makeAlert('error', `清空失败: ${e.message}`)]);
        }
    };

    // 从历史记录加载完整回测结果
    const handleLoadHistory = async (record) => {
        setLoadingHistoryId(record.id);
        try {
            const detail = await backtestApi.getDetail(record.id);
            if (detail?.result) {
                setBacktestResults({ ...detail.result, strategy_type: detail.strategy_type });
                if (detail.strategy_type) setStrategyType(detail.strategy_type);

                // 回显标的池配置
                if (detail.universe_config) {
                    const uc = detail.universe_config;
                    if (uc.type === 'factor_filter') {
                        setUniverseSource('factor_filter');
                        const fv = {};
                        const f = uc.filters || {};
                        if (f.pe_ttm_max !== undefined) fv.pe_ttm_max = String(f.pe_ttm_max);
                        if (f.pb_max !== undefined) fv.pb_max = String(f.pb_max);
                        if (f.total_mv_min !== undefined) fv.total_mv_min = String(f.total_mv_min);
                        if (f.total_mv_max !== undefined) fv.total_mv_max = String(f.total_mv_max);
                        if (f.dv_ratio_min !== undefined) fv.dv_ratio_min = String(f.dv_ratio_min);
                        setFilterValues(fv);
                        if (uc.max_stocks) setMaxStocks(uc.max_stocks);
                    } else if (uc.type === 'full_market') {
                        setUniverseSource('full_market');
                        setFilterValues({});
                        if (uc.max_stocks) setMaxStocks(uc.max_stocks);
                    }
                } else {
                    setUniverseSource('pool');
                }

                // 回显策略参数
                const sp = detail.result.strategy_params;
                if (sp && Object.keys(sp).length > 0) {
                    setStrategyParamsValues(prev => ({ ...prev, ...sp }));
                }

                // 加载历史回测后调用后端计算风险指标
                if (setRiskAnalysis && detail.start_date && detail.end_date) {
                    const codes = detail.codes?.length ? detail.codes : customStocks.map(s => s.code);
                    if (codes.length > 0) {
                        try {
                            const riskRes = await riskApi.analyze(codes, detail.start_date, detail.end_date);
                            setRiskAnalysis(riskRes.risk || null);
                        } catch { /* 风险计算失败不阻塞 */ }
                    }
                }

                setAlerts([makeAlert('success', `已加载历史回测 (${STRATEGY_MAP[detail.strategy_type]?.name || detail.strategy_type} · ${detail.start_date}~${detail.end_date})`)]);
                requestAnimationFrame(() => requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })));
            } else {
                setAlerts([makeAlert('warning', '该记录无完整结果数据，可能是旧版本格式')]);
            }
        } catch (e) {
            setAlerts([makeAlert('error', `加载失败: ${e.message}`)]);
        } finally {
            setLoadingHistoryId(null);
        }
    };

    // 保存策略
    const handleSave = async () => {
        if (!newStrategyName.trim()) {
            setAlerts([makeAlert('error', '请输入策略名称')]);
            return;
        }
        setSaving(true);
        try {
            await strategyApi.create({
                name: newStrategyName,
                description: `Created at ${new Date().toLocaleString()}`,
                strategy_type: strategyType,
                parameters: currentConfig,
            });
            setAlerts([makeAlert('success', '策略保存成功')]);
            setNewStrategyName('');
            setShowSaveInput(false);
            loadStrategies();
        } catch (e) {
            setAlerts([makeAlert('error', `保存失败: ${e.message}`)]);
        }
        setSaving(false);
    };

    // 删除策略
    const handleDeleteStrategy = async (e, id) => {
        e.stopPropagation();
        if (!window.confirm('确定要删除这个策略吗？')) return;
        try {
            await strategyApi.delete(id);
            setAlerts([makeAlert('success', '策略已删除')]);
            loadStrategies();
        } catch (e) {
            setAlerts([makeAlert('error', `删除失败: ${e.message}`)]);
        }
    };

    // 删除回测记录
    const handleDeleteHistory = async (id) => {
        if (!window.confirm('确认删除该条回测记录？')) return;
        setDeleting(id);
        try {
            await backtestApi.deleteResult(id);
            setHistoryRecords(prev => prev.filter(r => r.id !== id));
        } catch (e) { setAlerts([makeAlert('error', '删除失败: ' + e.message)]); }
        finally { setDeleting(null); }
    };

    const selectedStrategy = STRATEGY_MAP[strategyType] || BUILTIN_STRATEGIES[0];

    // 资产类型检测：根据代码判断自选池资产类型（股票/ETF/可转债），含分类计数
    const poolAssetCounts = (() => {
        const counts = { stock: 0, bond: 0, etf: 0 };
        customStocks.forEach(s => {
            const t = classifyAsset(s.code);
            if (counts[t] !== undefined) counts[t]++;
        });
        return counts;
    })();
    const poolAssetTypes = new Set(
        Object.entries(poolAssetCounts).filter(([, v]) => v > 0).map(([k]) => k)
    );

    // 策略与自选池资产类型是否匹配
    const ASSET_LABELS = { stock: '股票', etf: 'ETF', bond: '可转债' };
    const assetMismatch = selectedStrategy.assetType && !poolAssetTypes.has(selectedStrategy.assetType);
    // 策略是否仅限非股票资产（用于禁用因子筛选/全市场按钮）
    const strategyNonStock = selectedStrategy.assetType && selectedStrategy.assetType !== 'stock';

    const fmt = (v, suffix = '%') => fmtNum(v, 2, suffix);
    const color = pnlColor;

    // 对比模式切换
    const toggleCompareStrategy = (id) => {
        setCompareSelected(prev => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    };

    const COMPARE_COLORS = ['#10b981', '#6366f1', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6'];

    const runCompare = async () => {
        if (compareSelected.size < 2) {
            setAlerts([makeAlert('warning', '请至少勾选2个策略进行对比')]);
            return;
        }
        if (customStocks.length === 0) {
            setAlerts([makeAlert('warning', '自选池为空，请先加入标的')]);
            return;
        }
        // 校验：检测选中策略是否有标的类型覆盖不足
        const warnings = [];
        for (const sid of compareSelected) {
            const meta = STRATEGY_MAP[sid];
            if (!meta?.assetType || meta.assetType === 'stock') continue;
            const matched = customStocks.filter(s => classifyAsset(s.code) === meta.assetType);
            if (matched.length === 0) {
                const label = ASSET_LABELS[meta.assetType] || meta.assetType;
                warnings.push(`「${meta.name}」需要${label}标的，但自选池中无匹配代码`);
            }
        }
        if (warnings.length > 0) {
            setAlerts([makeAlert('warning', warnings.join('；') + '。这些策略会被跳过或失败。')]);
        }
        setCompareLoading(true);
        setCompareResults(null);
        try {
            const codes = customStocks.map(s => s.code);
            const res = await backtestApi.compare(codes, [...compareSelected], { startDate, endDate });
            setCompareResults(res);
            // 检查是否有策略失败
            const failedStrategies = Object.entries(res.strategies || {})
                .filter(([, v]) => v.error)
                .map(([k, v]) => `${STRATEGY_MAP[k]?.name || k}: ${v.error}`);
            if (failedStrategies.length > 0) {
                setAlerts([makeAlert('warning', `${compareSelected.size - failedStrategies.length}/${compareSelected.size} 个策略成功，${failedStrategies.length} 个失败`)]);
            } else {
                setAlerts([makeAlert('success', `${compareSelected.size}个策略对比完成`)]);
            }
        } catch (e) {
            setAlerts([makeAlert('error', `对比失败: ${e.message}`)]);
        }
        setCompareLoading(false);
    };

    // 参数优化
    const runOptimize = async () => {
        if (customStocks.length === 0) {
            setAlerts([makeAlert('warning', '自选池为空，请先加入标的')]);
            return;
        }
        // 根据当前策略参数 schema 生成网格范围
        const numericParams = strategyParamsSchema.filter(p => p.type === 'int' || p.type === 'float');
        if (numericParams.length === 0) {
            setAlerts([makeAlert('warning', '当前策略无可优化的数值参数')]);
            return;
        }
        const ranges = {};
        numericParams.forEach(p => {
            const min = p.min ?? 1;
            const max = p.max ?? 100;
            const step = (p.step ?? 1) * 3;  // 3倍步长减少组合数
            const vals = [];
            for (let v = min; v <= max; v += step) vals.push(p.type === 'int' ? Math.round(v) : Number(v.toFixed(2)));
            if (!vals.includes(max)) vals.push(p.type === 'int' ? Math.round(max) : Number(max.toFixed(2)));
            ranges[p.name] = vals;
        });
        setOptimizeLoading(true);
        setOptimizeResults(null);
        try {
            const codes = customStocks.map(s => s.code);
            const res = await backtestApi.optimize(codes, strategyType, ranges, { startDate, endDate });
            if (res.error) {
                setAlerts([makeAlert('error', `${res.error}`)]);
            } else {
                setOptimizeResults(res);
                setAlerts([makeAlert('success', `扫描 ${res.total_combos} 个组合，${res.valid_results} 个有效`)]);
            }
        } catch (e) {
            setAlerts([makeAlert('error', `优化失败: ${e.message}`)]);
        }
        setOptimizeLoading(false);
    };

    return (
        <div className="space-y-6">
            <h2 className="text-2xl font-bold text-white mb-4 flex items-center gap-3">
                <div className="p-2.5 bg-indigo-500/20 rounded-xl border border-indigo-500/30">
                    <Zap className="w-6 h-6 text-indigo-400" />
                </div>
                策略回测
                <span className="text-sm font-normal text-slate-500 ml-2">选择策略 → 运行回测 → 查看结果</span>
            </h2>

            <div className="flex gap-6">
                {/* ════════ 左侧：策略列表 ════════ */}
                <div className="w-64 shrink-0 space-y-4">

                    {/* 内置策略 */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                                <Brain className="w-3.5 h-3.5 text-emerald-400" /> {compareMode ? '勾选对比' : '内置策略'}
                            </h3>
                            <button onClick={() => { setCompareMode(v => !v); setCompareResults(null); setCompareSelected(new Set()); }}
                                className={`text-[10px] px-2 py-1 rounded-md border transition-all ${compareMode ? 'bg-amber-600/20 text-amber-400 border-amber-500/30' : 'bg-slate-700/30 text-slate-500 border-slate-600/30 hover:text-slate-400'}`}>
                                {compareMode ? '✗ 退出对比' : '⚔️ 对比模式'}
                            </button>
                        </div>
                        <div className="space-y-1">
                            {BUILTIN_STRATEGIES.map(s => {
                                const isSelected = compareMode ? compareSelected.has(s.id) : strategyType === s.id;
                                return (
                                    <button key={s.id}
                                        onClick={() => {
                                            if (compareMode) { toggleCompareStrategy(s.id); return; }
                                            setStrategyType(s.id);
                                            // 选了非股票策略时，自动切回自选池（因子筛选/全市场不支持 bond/etf）
                                            if (s.assetType && s.assetType !== 'stock' && universeSource !== 'pool') {
                                                setUniverseSource('pool');
                                            }
                                        }}
                                        className={`w-full text-left px-3 py-2.5 rounded-xl transition-all flex items-center gap-2.5 group ${isSelected
                                            ? compareMode
                                                ? 'bg-amber-600/20 border border-amber-500/40 text-white'
                                                : 'bg-indigo-600/30 border border-indigo-500/50 text-white shadow-[0_0_12px_rgba(99,102,241,0.15)]'
                                            : 'bg-slate-800/30 border border-transparent text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
                                            }`}>
                                        {compareMode && (
                                            <div className={`w-4 h-4 rounded border-2 flex items-center justify-center shrink-0 transition-all ${isSelected ? 'bg-amber-500 border-amber-500' : 'border-slate-600'}`}>
                                                {isSelected && <span className="text-[10px] text-white font-bold">✓</span>}
                                            </div>
                                        )}
                                        {!compareMode && <s.icon className={`w-4 h-4 shrink-0 ${isSelected ? 'text-indigo-400' : 'text-slate-500 group-hover:text-slate-400'}`} />}
                                        <div className="min-w-0">
                                            <div className={`text-sm font-medium truncate ${isSelected ? 'text-white' : ''}`}>{s.name}</div>
                                            <div className="text-xs text-slate-400 truncate">{s.desc}</div>
                                        </div>
                                        {isSelected && !compareMode && <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 ml-auto shrink-0" />}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* 我的策略库 */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                                <FolderOpen className="w-3.5 h-3.5 text-indigo-400" /> 我的策略
                            </h3>
                            <button onClick={() => setShowSaveInput(!showSaveInput)}
                                className="text-[10px] px-2 py-1 rounded-md bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 hover:bg-indigo-600/30 transition-all">
                                <Plus className="w-3 h-3 inline -mt-0.5" /> 保存
                            </button>
                        </div>

                        {showSaveInput && (
                            <div className="flex gap-1.5 mb-2">
                                <input type="text" value={newStrategyName}
                                    onChange={e => setNewStrategyName(e.target.value)}
                                    placeholder="策略名称..."
                                    className="flex-1 bg-slate-800/80 border border-slate-600/50 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition-all" />
                                <button onClick={handleSave} disabled={saving}
                                    className="px-2.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs rounded-lg transition-colors">
                                    {saving ? '...' : '✓'}
                                </button>
                            </div>
                        )}

                        <div className="space-y-1 max-h-40 overflow-y-auto">
                            {strategies.length === 0 ? (
                                <div className="text-center py-4 text-slate-600 text-xs">暂无保存的策略</div>
                            ) : strategies.map(s => (
                                <div key={s.id}
                                    onClick={() => onLoadStrategy(s)}
                                    className="flex items-center justify-between px-3 py-2 bg-slate-800/30 border border-slate-700/30 rounded-lg hover:border-indigo-500/40 hover:bg-slate-800/60 cursor-pointer transition-all group">
                                    <div className="min-w-0">
                                        <div className="text-xs font-medium text-slate-300 group-hover:text-indigo-300 truncate">{s.name}</div>
                                        <div className="text-xs text-slate-400">{s.strategy_type?.toUpperCase()}</div>
                                    </div>
                                    <button onClick={e => handleDeleteStrategy(e, s.id)}
                                        className="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-500 hover:text-rose-400 transition-all">
                                        <Trash2 className="w-3 h-3" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* 路线图折叠 */}
                    <div>
                        <button onClick={() => setShowRoadmap(!showRoadmap)}
                            className="w-full flex items-center justify-between py-2 px-3 bg-slate-800/30 border border-slate-700/30 rounded-lg text-xs text-slate-500 hover:text-slate-400 transition-all">
                            <span className="flex items-center gap-1.5">
                                <Activity className="w-3 h-3" /> 开发路线图
                            </span>
                            <ChevronDown className={`w-3 h-3 transition-transform ${showRoadmap ? 'rotate-180' : ''}`} />
                        </button>
                        {showRoadmap && (
                            <div className="mt-1 space-y-1">
                                {ROADMAP_STRATEGIES.map(s => (
                                    <div key={s.id} className="px-3 py-2 bg-slate-800/20 border border-slate-800/50 rounded-lg opacity-50 flex items-center gap-2">
                                        <s.icon className="w-3.5 h-3.5 text-slate-600" />
                                        <div>
                                            <div className="text-xs text-slate-500">{s.name}</div>
                                            <div className="text-xs text-slate-400">{s.desc}</div>
                                        </div>
                                        <span className="ml-auto text-[9px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-500 border border-slate-600/30">待开发</span>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>

                {/* ════════ 右侧：详情 + 回测 + 结果 ════════ */}
                <div className="flex-1 space-y-5">

                    {/* ── 对比模式 ── */}
                    {compareMode && (
                        <>
                            {/* 对比按钮 */}
                            <button onClick={runCompare}
                                disabled={compareSelected.size < 2 || customStocks.length === 0 || compareLoading}
                                className="w-full relative group overflow-hidden bg-gradient-to-r from-amber-600 via-orange-500 to-amber-600 bg-[length:200%_auto] hover:bg-[position:right_center] text-white py-4 rounded-xl font-bold shadow-lg shadow-amber-900/30 transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                                <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                                {compareLoading ? (
                                    <><div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span className="tracking-wide text-lg">正在对比 {compareSelected.size} 个策略...</span></>
                                ) : (
                                    <><span className="text-lg">⚔️</span> <span className="tracking-wider text-lg">启动策略对比（已选 {compareSelected.size} 个）</span></>
                                )}
                            </button>

                            {/* 对比结果 */}
                            {compareResults && compareResults.strategies && (() => {
                                const strats = compareResults.strategies;
                                const keys = Object.keys(strats).filter(k => !strats[k].error);
                                if (keys.length === 0) return <div className="text-slate-500 text-center py-8">所有策略均回测失败</div>;

                                return (
                                    <div className="space-y-5">
                                        {/* 绩效对比表 */}
                                        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 overflow-x-auto">
                                            <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                                                <BarChart3 className="w-4 h-4 text-amber-400" /> 绩效对比
                                            </h3>
                                            <table className="w-full text-xs">
                                                <thead>
                                                    <tr className="text-slate-400 border-b border-slate-700/50">
                                                        <th className="text-left py-2 px-2">策略</th>
                                                        <th className="text-right py-2 px-2">总收益</th>
                                                        <th className="text-right py-2 px-2">年化</th>
                                                        <th className="text-right py-2 px-2">最大回撤</th>
                                                        <th className="text-right py-2 px-2">夏普</th>
                                                        <th className="text-right py-2 px-2">Sortino</th>
                                                        <th className="text-right py-2 px-2">波动率</th>
                                                        <th className="text-right py-2 px-2">超额</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {keys.map((k, i) => {
                                                        const r = strats[k];
                                                        const name = STRATEGY_MAP[k]?.name || k;
                                                        const clr = COMPARE_COLORS[i % COMPARE_COLORS.length];
                                                        return (
                                                            <tr key={k} className="border-b border-slate-800/50 hover:bg-slate-800/40">
                                                                <td className="py-2 px-2 font-bold" style={{ color: clr }}>
                                                                    <span className="inline-block w-2.5 h-2.5 rounded-full mr-1.5" style={{ backgroundColor: clr }} />
                                                                    {name}
                                                                </td>
                                                                <td className={`text-right py-2 px-2 font-mono font-bold ${color(r.total_return)}`}>{fmt(r.total_return)}</td>
                                                                <td className={`text-right py-2 px-2 font-mono ${color(r.annual_return)}`}>{fmt(r.annual_return)}</td>
                                                                <td className="text-right py-2 px-2 font-mono text-rose-400">{fmt(r.max_drawdown)}</td>
                                                                <td className={`text-right py-2 px-2 font-mono ${color(r.sharpe_ratio)}`}>{fmtNum(r.sharpe_ratio, 2)}</td>
                                                                <td className={`text-right py-2 px-2 font-mono ${color(r.sortino_ratio)}`}>{fmtNum(r.sortino_ratio, 2)}</td>
                                                                <td className="text-right py-2 px-2 font-mono text-amber-400">{fmt(r.volatility)}</td>
                                                                <td className={`text-right py-2 px-2 font-mono ${color(r.excess_return)}`}>{fmt(r.excess_return)}</td>
                                                            </tr>
                                                        );
                                                    })}
                                                </tbody>
                                            </table>
                                        </div>

                                        {/* 净值曲线叠加 */}
                                        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                            <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                                                <TrendingUp className="w-4 h-4 text-emerald-400" /> 净值曲线对比
                                            </h3>
                                            {(() => {
                                                // 用 SVG 画多条净值曲线
                                                const W = 800, H = 300, PAD = 40;
                                                const allCurves = keys.map(k => strats[k].cumReturns || []).filter(c => c.length > 0);
                                                if (allCurves.length === 0) return <div className="text-slate-500 text-xs text-center py-4">无净值数据</div>;

                                                const maxLen = Math.max(...allCurves.map(c => c.length));
                                                const allVals = allCurves.flat();
                                                const minV = Math.min(...allVals, 0.8);
                                                const maxV = Math.max(...allVals, 1.2);
                                                const scaleX = (i) => PAD + (i / (maxLen - 1)) * (W - PAD * 2);
                                                const scaleY = (v) => H - PAD - ((v - minV) / (maxV - minV)) * (H - PAD * 2);

                                                // 基准线
                                                const benchData = strats[keys[0]]?.benchmark || [];

                                                return (
                                                    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 300 }}>
                                                        {/* 网格线 */}
                                                        {[0.25, 0.5, 0.75].map(pct => {
                                                            const y = PAD + pct * (H - PAD * 2);
                                                            const val = maxV - pct * (maxV - minV);
                                                            return (
                                                                <g key={pct}>
                                                                    <line x1={PAD} y1={y} x2={W - PAD} y2={y} stroke="#334155" strokeWidth={0.5} />
                                                                    <text x={PAD - 4} y={y + 4} textAnchor="end" fill="#64748b" fontSize={10}>{val.toFixed(2)}</text>
                                                                </g>
                                                            );
                                                        })}
                                                        {/* 基准 */}
                                                        {benchData.length > 0 && (
                                                            <polyline fill="none" stroke="#475569" strokeWidth={1.5} strokeDasharray="4 2"
                                                                points={benchData.map((v, i) => `${scaleX(i)},${scaleY(v)}`).join(' ')} />
                                                        )}
                                                        {/* 策略曲线 */}
                                                        {keys.map((k, idx) => {
                                                            const curve = strats[k].cumReturns || [];
                                                            if (curve.length < 2) return null;
                                                            return (
                                                                <polyline key={k} fill="none" stroke={COMPARE_COLORS[idx % COMPARE_COLORS.length]}
                                                                    strokeWidth={2} opacity={0.85}
                                                                    points={curve.map((v, i) => `${scaleX(i)},${scaleY(v)}`).join(' ')} />
                                                            );
                                                        })}
                                                    </svg>
                                                );
                                            })()}
                                            {/* 图例 */}
                                            <div className="flex flex-wrap gap-3 mt-2">
                                                {keys.map((k, i) => (
                                                    <div key={k} className="flex items-center gap-1.5 text-xs text-slate-300">
                                                        <span className="w-3 h-1 rounded" style={{ backgroundColor: COMPARE_COLORS[i % COMPARE_COLORS.length] }} />
                                                        {STRATEGY_MAP[k]?.name || k}
                                                    </div>
                                                ))}
                                                <div className="flex items-center gap-1.5 text-xs text-slate-500">
                                                    <span className="w-3 h-0.5 rounded border-t border-dashed border-slate-500" /> 基准(沪深300)
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                );
                            })()}
                        </>
                    )}

                    {/* ── 普通模式 ── */}
                    {!compareMode && (<>

                        {/* 策略详情卡 */}
                        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
                            <div className="flex items-center gap-3 mb-3">
                                <div className="p-2 bg-indigo-500/20 rounded-lg border border-indigo-500/30">
                                    <selectedStrategy.icon className="w-5 h-5 text-indigo-400" />
                                </div>
                                <div>
                                    <div className="flex items-center gap-2">
                                        <h3 className="text-lg font-bold text-white">{selectedStrategy.name}</h3>
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded border ${selectedStrategy.assetType === 'bond' ? 'text-orange-400 bg-orange-900/30 border-orange-500/30' :
                                                selectedStrategy.assetType === 'etf' ? 'text-cyan-400 bg-cyan-900/30 border-cyan-500/30' :
                                                    selectedStrategy.assetType === 'stock' ? 'text-emerald-400 bg-emerald-900/30 border-emerald-500/30' :
                                                        'text-slate-400 bg-slate-700/30 border-slate-600/30'
                                            }`}>{selectedStrategy.assetType ? (ASSET_LABELS[selectedStrategy.assetType] || selectedStrategy.assetType) : '通用'}</span>
                                    </div>
                                    <p className="text-xs text-slate-400">{selectedStrategy.desc}</p>
                                </div>
                            </div>
                            <div className="px-4 py-2.5 bg-indigo-900/20 border border-indigo-500/20 rounded-xl text-xs text-indigo-300/90 flex items-center gap-2">
                                <Zap className="w-3.5 h-3.5 text-indigo-400 flex-shrink-0" />
                                <span>{selectedStrategy.detail}</span>
                            </div>
                        </div>

                        {/* 策略参数面板 */}
                        {strategyParamsSchema.length > 0 && (
                            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
                                <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
                                    <SlidersHorizontal className="w-4 h-4 text-indigo-400" />
                                    策略参数
                                </h3>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                    {strategyParamsSchema.map(p => (
                                        <div key={p.name} className="space-y-1.5">
                                            <label className="text-xs text-slate-400 flex items-center justify-between">
                                                <span>{p.label}</span>
                                                <span className="font-mono text-indigo-300">{strategyParamsValues[p.name] ?? p.default}</span>
                                            </label>
                                            {p.type === 'select' ? (
                                                <select
                                                    value={strategyParamsValues[p.name] ?? p.default}
                                                    onChange={e => setStrategyParamsValues(v => ({ ...v, [p.name]: e.target.value }))}
                                                    className="w-full bg-slate-800 border border-slate-600/50 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 transition-all"
                                                >
                                                    {(p.options || []).map(o => (
                                                        <option key={o.value} value={o.value}>{o.label}</option>
                                                    ))}
                                                </select>
                                            ) : (
                                                <input
                                                    type="range"
                                                    min={p.min ?? 1}
                                                    max={p.max ?? 100}
                                                    step={p.step ?? 1}
                                                    value={strategyParamsValues[p.name] ?? p.default}
                                                    onChange={e => {
                                                        const val = p.type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value);
                                                        setStrategyParamsValues(v => ({ ...v, [p.name]: val }));
                                                    }}
                                                    className="w-full accent-indigo-500 h-2 bg-slate-700 rounded-lg cursor-pointer"
                                                />
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* ── 标的来源选择器 ── */}
                        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
                            <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                                <Layers className="w-4 h-4 text-teal-400" />
                                标的来源
                            </h3>
                            <div className="flex gap-3 mb-3">
                                {[
                                    {
                                        value: 'pool', label: '自选池', desc: (() => {
                                            const parts = [];
                                            if (poolAssetCounts.stock > 0) parts.push(`股票${poolAssetCounts.stock}`);
                                            if (poolAssetCounts.bond > 0) parts.push(`可转债${poolAssetCounts.bond}`);
                                            if (poolAssetCounts.etf > 0) parts.push(`ETF${poolAssetCounts.etf}`);
                                            return parts.length > 0 ? parts.join(' | ') : '空';
                                        })()
                                    },
                                    { value: 'factor_filter', label: '因子筛选', desc: strategyNonStock ? `仅支持股票` : '按条件动态选', defaultMax: 200, disabled: strategyNonStock },
                                    { value: 'full_market', label: '全市场', desc: strategyNonStock ? `仅支持股票` : '所有上市股票', defaultMax: 300, disabled: strategyNonStock },
                                ].map(opt => (
                                    <button key={opt.value}
                                        disabled={opt.disabled}
                                        onClick={() => { if (opt.disabled) return; setUniverseSource(opt.value); setUniversePreview(null); if (opt.defaultMax) setMaxStocks(opt.defaultMax); }}
                                        className={`flex-1 text-center px-3 py-2.5 rounded-lg border text-sm transition-all ${opt.disabled
                                                ? 'bg-slate-900/40 border-slate-800/30 text-slate-600 cursor-not-allowed opacity-50'
                                                : universeSource === opt.value
                                                    ? 'bg-teal-600/20 border-teal-500/50 text-teal-300'
                                                    : 'bg-slate-800/30 border-slate-700/30 text-white/80 hover:text-white'
                                            }`}>
                                        <div className="font-medium">{opt.label}</div>
                                        <div className="text-xs text-slate-500 mt-0.5">{opt.desc}</div>
                                    </button>
                                ))}
                            </div>

                            {/* 因子筛选条件面板 */}
                            {universeSource === 'factor_filter' && (<>
                                {/* 预设模板 */}
                                <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-slate-700/30">
                                    <span className="text-xs text-white/60 leading-7 mr-1">快捷:</span>
                                    {[
                                        { label: '大盘价值', max: 100, desc: 'PE≤20, PB≤3, 市值≥100亿, 上限100只', filters: { pe_ttm_max: '20', pb_max: '3', total_mv_min: '1000000', dv_ratio_min: '' } },
                                        { label: '高股息', max: 100, desc: 'PE≤25, 市值≥50亿, 股息率≥3%, 上限100只', filters: { pe_ttm_max: '25', pb_max: '', total_mv_min: '500000', dv_ratio_min: '3' } },
                                        { label: '成长龙头', max: 50, desc: 'PE≤50, 市值≥200亿, 上限50只', filters: { pe_ttm_max: '50', pb_max: '', total_mv_min: '2000000', dv_ratio_min: '' } },
                                        { label: '低估蓝筹', max: 100, desc: 'PE≤15, PB≤1.5, 市值≥50亿, 股息率≥2%, 上限100只', filters: { pe_ttm_max: '15', pb_max: '1.5', total_mv_min: '500000', dv_ratio_min: '2' } },
                                        { label: '小盘成长', max: 200, desc: 'PE≤40, PB≤5, 市值≤100亿, 上限200只', filters: { pe_ttm_max: '40', pb_max: '5', total_mv_min: '', total_mv_max: '1000000', dv_ratio_min: '' } },
                                    ].map(p => (
                                        <button key={p.label}
                                            onClick={() => { setFilterValues(p.filters); setMaxStocks(p.max); setActivePreset(p.label); }}
                                            title={p.desc}
                                            className={`text-xs px-3 py-1.5 rounded-lg border transition-all flex items-center gap-1 ${activePreset === p.label
                                                    ? 'bg-teal-600/30 border-teal-400/50 text-teal-200 ring-1 ring-teal-400/30 shadow-[0_0_6px_rgba(45,212,191,0.3)]'
                                                    : 'bg-slate-800/40 border-slate-600/30 text-white/80 hover:bg-slate-700/40 hover:text-white'
                                                }`}>
                                            {p.label}
                                        </button>
                                    ))}
                                    <button onClick={() => { setFilterValues({}); setActivePreset(null); }}
                                        className="text-xs px-3 py-1.5 rounded-lg bg-slate-800/40 border border-slate-600/30 text-white/60 hover:text-white transition-all">
                                        清空
                                    </button>
                                </div>
                                <div className="grid grid-cols-2 gap-3 mt-3">
                                    {[
                                        { key: 'pe_ttm_max', label: 'PE(TTM) ≤', placeholder: '如 30' },
                                        { key: 'pb_max', label: 'PB ≤', placeholder: '如 5' },
                                        { key: 'total_mv_min', label: '总市值 ≥ (万)', placeholder: '如 500000' },
                                        { key: 'dv_ratio_min', label: '股息率 ≥ (%)', placeholder: '如 2' },
                                    ].map(f => (
                                        <div key={f.key} className="space-y-1">
                                            <label className="text-[10px] text-slate-400">{f.label}</label>
                                            <input
                                                type="number"
                                                placeholder={f.placeholder}
                                                value={filterValues[f.key] || ''}
                                                onChange={e => setFilterValues(v => ({ ...v, [f.key]: e.target.value }))}
                                                className="w-full bg-slate-900/80 border border-slate-600/50 rounded-lg px-2.5 py-1.5 text-xs text-white placeholder-slate-600 focus:outline-none focus:border-teal-500 transition-all"
                                            />
                                        </div>
                                    ))}
                                </div>
                            </>)}

                            {/* 最大标的数（因子筛选和全市场共用） */}
                            {universeSource !== 'pool' && (
                                <div className="flex items-center gap-2 mt-3 pt-3 border-t border-slate-700/30">
                                    <label className="text-xs text-slate-400 whitespace-nowrap">上限</label>
                                    <input
                                        type="number"
                                        value={maxStocks}
                                        onChange={e => setMaxStocks(e.target.value)}
                                        className="w-20 bg-slate-900/80 border border-slate-600/50 rounded-lg px-2.5 py-1.5 text-xs text-white focus:outline-none focus:border-teal-500 transition-all"
                                    />
                                    <span className="text-xs text-slate-500">只</span>
                                    <span className="text-xs text-slate-500 mx-1">·</span>
                                    <label className="text-xs text-slate-400 whitespace-nowrap">截断排序</label>
                                    <select
                                        value={truncateBy}
                                        onChange={e => setTruncateBy(e.target.value)}
                                        className="bg-slate-800 border border-slate-600/50 rounded-lg px-2 py-1.5 text-xs text-white focus:outline-none focus:border-teal-500 transition-all cursor-pointer"
                                        style={{ colorScheme: 'dark' }}>
                                        <option value="total_mv">市值优先</option>
                                        <option value="pe_ttm">低PE优先</option>
                                        <option value="dv_ratio">高股息优先</option>
                                    </select>
                                </div>
                            )}

                            {/* 预览提示条 */}
                            {universeSource !== 'pool' && universePreview && (
                                <div className={`mt-3 px-3 py-2 rounded-lg text-xs flex items-center gap-2 ${universePreview.count > Number(maxStocks)
                                        ? 'bg-amber-900/20 border border-amber-700/40 text-amber-300'
                                        : 'bg-teal-900/20 border border-teal-700/40 text-teal-300'
                                    }`}>
                                    <Activity className="w-3.5 h-3.5 shrink-0" />
                                    <span>
                                        {universePreview.count > Number(maxStocks) ? (<>
                                            匹配 <strong>{universePreview.count}</strong> 只，按{({ total_mv: '市值', pe_ttm: '低PE', dv_ratio: '高股息' })[truncateBy] || '市值'}优先取前 <strong>{maxStocks}</strong> 只
                                        </>) : (<>
                                            预估 <strong>{universePreview.count}</strong> 只标的
                                        </>)}
                                        {universePreview.estimated_seconds > 10 && (
                                            <span className="text-slate-400">，约需 <strong className="text-white">{universePreview.estimated_seconds}s</strong></span>
                                        )}
                                    </span>
                                    {previewLoading && <div className="w-3 h-3 border border-teal-500/50 border-t-teal-400 rounded-full animate-spin" />}
                                </div>
                            )}
                            {universeSource !== 'pool' && previewLoading && !universePreview && (
                                <div className="mt-3 px-3 py-2 rounded-lg text-xs flex items-center gap-2 bg-slate-800/50 text-slate-400">
                                    <div className="w-3 h-3 border border-slate-500/50 border-t-slate-400 rounded-full animate-spin" />
                                    正在预估标的池...
                                </div>
                            )}
                        </div>

                        {customStocks.length === 0 && universeSource === 'pool' && (
                            <div className="flex items-start gap-3 p-4 bg-amber-900/20 border border-amber-700/40 rounded-xl text-amber-300 text-sm">
                                <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" />
                                <span>自选池为空。请先在 <strong>「智能选股」</strong> 筛选标的并加入自选池，或切换到 <strong>「因子筛选」/「全市场」</strong> 模式。</span>
                            </div>
                        )}

                        {/* 策略-资产类型不匹配警告 */}
                        {assetMismatch && customStocks.length > 0 && universeSource === 'pool' && (
                            <div className="flex items-start gap-3 p-4 bg-rose-900/20 border border-rose-700/40 rounded-xl text-rose-300 text-sm">
                                <AlertTriangle className="w-5 h-5 mt-0.5 shrink-0" />
                                <span>
                                    <strong>「{selectedStrategy.name}」</strong> 仅适用于
                                    <strong>{ASSET_LABELS[selectedStrategy.assetType]}</strong>，
                                    但自选池中未包含该类资产。回测结果可能无意义。
                                </span>
                            </div>
                        )}

                        {/* 回测日期区间 */}
                        <div className="flex items-center gap-3 bg-slate-800/40 border border-slate-700/40 rounded-xl px-4 py-3">
                            <Calendar className="w-4 h-4 text-indigo-400 shrink-0" />
                            <span className="text-xs text-slate-400 shrink-0">回测区间</span>
                            <input type="date" value={startDate || ''}
                                onChange={e => setStartDate?.(e.target.value)}
                                style={{ colorScheme: 'dark' }}
                                className="flex-1 bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-1.5 text-sm text-white focus:border-indigo-500 focus:outline-none transition-colors cursor-pointer" />
                            <span className="text-slate-600 text-xs">~</span>
                            <input type="date" value={endDate || ''}
                                onChange={e => setEndDate?.(e.target.value)}
                                style={{ colorScheme: 'dark' }}
                                className="flex-1 bg-slate-800 border border-slate-700/50 rounded-lg px-3 py-1.5 text-sm text-white focus:border-indigo-500 focus:outline-none transition-colors cursor-pointer" />
                        </div>

                        {/* 单只权重上限（仓位管理级通用设置） */}
                        <div className="flex items-center gap-3 bg-slate-800/40 border border-slate-700/40 rounded-xl px-4 py-3">
                            <Shield className="w-4 h-4 text-amber-400 shrink-0" />
                            <span className="text-xs text-slate-400 shrink-0">单只上限</span>
                            <input
                                type="range" min="0" max="50" step="5"
                                value={maxSingleWeight}
                                onChange={e => setMaxSingleWeight(Number(e.target.value))}
                                className="flex-1 accent-amber-500 h-1.5 bg-slate-700 rounded-lg cursor-pointer"
                            />
                            <span className={`text-xs font-mono min-w-[3.5rem] text-right ${maxSingleWeight > 0 ? 'text-amber-300 font-bold' : 'text-slate-500'}`}>
                                {maxSingleWeight > 0 ? `≤${maxSingleWeight}%` : '不限'}
                            </span>
                            {maxSingleWeight > 0 && (
                                <span className="text-xs text-slate-400 shrink-0">需≥{Math.floor(100 / maxSingleWeight) + 1}只</span>
                            )}
                        </div>

                        {/* 运行按钮 */}
                        <button onClick={() => {
                            // 前端预校验：特殊策略标的类型
                            const strategyMeta = STRATEGY_MAP[strategyType];
                            const assetType = strategyMeta?.assetType;
                            if (assetType && assetType !== 'stock') {
                                const assetLabels = { bond: '可转债', etf: 'ETF' };
                                const label = assetLabels[assetType] || assetType;
                                // 因子筛选 / 全市场只返回股票，不含可转债/ETF
                                if (universeSource === 'factor_filter' || universeSource === 'full_market') {
                                    setAlerts([makeAlert('warning', `${strategyMeta.name} 策略仅支持${label}标的，"${universeSource === 'factor_filter' ? '因子筛选' : '全市场'}"模式仅筛选股票。请切换到"自选池"并添加${label}代码。`)]);
                                    return;
                                }
                                // 自选池：检查是否有匹配代码（复用 classifyAsset，避免正则不一致）
                                if (universeSource === 'pool') {
                                    const matched = customStocks.filter(c => classifyAsset(c.code) === assetType);
                                    if (matched.length === 0) {
                                        setAlerts([makeAlert('warning', `${strategyMeta.name} 策略仅支持${label}标的，当前自选池中无匹配代码。请先添加${label}到自选池。`)]);
                                        return;
                                    }
                                }
                            }
                            let universeConfig = null;
                            if (universeSource === 'factor_filter') {
                                const filters = {};
                                Object.entries(filterValues).forEach(([k, v]) => {
                                    if (v !== undefined && v !== '') filters[k] = Number(v);
                                });
                                if (Object.keys(filters).length === 0) {
                                    setAlerts([makeAlert('warning', '请至少填写一个筛选条件')]);
                                    return;
                                }
                                universeConfig = { type: 'factor_filter', filters, max_stocks: Number(maxStocks) || 200, truncate_by: truncateBy };
                            } else if (universeSource === 'full_market') {
                                universeConfig = { type: 'full_market', max_stocks: Number(maxStocks) || 300, truncate_by: truncateBy };
                            }
                            // 耗时较长时二次确认
                            if (universePreview && universePreview.estimated_seconds > 30) {
                                if (!window.confirm(`预计回测 ${universePreview.actual_count || universePreview.count} 只标的，约需 ${universePreview.estimated_seconds} 秒，确认继续？`)) return;
                            }
                            const mergedParams = { ...strategyParamsValues };
                            if (maxSingleWeight > 0) mergedParams.max_single_weight = maxSingleWeight / 100;
                            runBacktest(mergedParams, universeConfig, { startDate, endDate });
                        }}
                            disabled={(universeSource === 'pool' && customStocks.length === 0) || loading}
                            className="w-full relative group overflow-hidden bg-gradient-to-r from-emerald-600 via-teal-500 to-emerald-600 bg-[length:200%_auto] hover:bg-[position:right_center] text-white py-4 rounded-xl font-bold shadow-lg shadow-emerald-900/30 transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                            <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                            {loading ? (
                                <><div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span className="tracking-wide text-lg">正在执行历史回测...</span></>
                            ) : (
                                <><Play className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
                                    <span className="tracking-wider text-lg">
                                        启动量化回测引擎
                                        {universePreview && universeSource !== 'pool' && (
                                            <span className="text-sm font-normal text-emerald-200 ml-2">({universePreview.count} 只)</span>
                                        )}
                                    </span></>
                            )}
                        </button>

                        {/* 参数优化按钮 */}
                        {strategyParamsSchema.some(p => p.type === 'int' || p.type === 'float') && (
                            <button onClick={runOptimize}
                                disabled={customStocks.length === 0 || optimizeLoading}
                                className="w-full relative group overflow-hidden bg-gradient-to-r from-violet-600 via-purple-500 to-violet-600 bg-[length:200%_auto] hover:bg-[position:right_center] text-white py-3 rounded-xl font-bold shadow-lg shadow-violet-900/30 transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                                <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity" />
                                {optimizeLoading ? (
                                    <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span className="tracking-wide">正在网格搜索最优参数...</span></>
                                ) : (
                                    <><SlidersHorizontal className="w-4 h-4" /> <span className="tracking-wider">参数优化（网格搜索）</span></>
                                )}
                            </button>
                        )}

                        {/* 参数优化结果 */}
                        {optimizeResults && optimizeResults.top?.length > 0 && (
                            <div className="bg-slate-800/40 border border-violet-500/30 rounded-xl p-4 overflow-x-auto">
                                <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                                    <SlidersHorizontal className="w-4 h-4 text-violet-400" />
                                    参数优化结果
                                    <span className="text-xs text-slate-500 font-normal">
                                        共{optimizeResults.total_combos}组合 / {optimizeResults.valid_results}有效 / 显Top{optimizeResults.top.length}
                                    </span>
                                </h3>
                                <table className="w-full text-xs">
                                    <thead>
                                        <tr className="text-slate-400 border-b border-slate-700/50">
                                            <th className="text-left py-2 px-2">#</th>
                                            {Object.keys(optimizeResults.top[0]?.params || {}).map(k => {
                                                const schema = strategyParamsSchema.find(p => p.name === k);
                                                return <th key={k} className="text-right py-2 px-2">{schema?.label || k}</th>;
                                            })}
                                            <th className="text-right py-2 px-2">夏普</th>
                                            <th className="text-right py-2 px-2">总收益</th>
                                            <th className="text-right py-2 px-2">年化</th>
                                            <th className="text-right py-2 px-2">回撤</th>
                                            <th className="text-right py-2 px-2">操作</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {optimizeResults.top.map((r, i) => (
                                            <tr key={i} className={`border-b border-slate-800/50 hover:bg-slate-800/40 ${i === 0 ? 'bg-violet-900/20' : ''}`}>
                                                <td className={`py-2 px-2 font-bold ${i === 0 ? 'text-violet-400' : 'text-slate-500'}`}>{i + 1}</td>
                                                {Object.values(r.params).map((v, j) => (
                                                    <td key={j} className="text-right py-2 px-2 font-mono text-white">{v}</td>
                                                ))}
                                                <td className={`text-right py-2 px-2 font-mono font-bold ${color(r.sharpe_ratio)}`}>{r.sharpe_ratio}</td>
                                                <td className={`text-right py-2 px-2 font-mono ${color(r.total_return)}`}>{fmt(r.total_return)}</td>
                                                <td className={`text-right py-2 px-2 font-mono ${color(r.annual_return)}`}>{fmt(r.annual_return)}</td>
                                                <td className="text-right py-2 px-2 font-mono text-rose-400">{fmt(r.max_drawdown)}</td>
                                                <td className="text-right py-2 px-2">
                                                    <button onClick={() => { setStrategyParamsValues(r.params); setOptimizeResults(null); setAlerts([makeAlert('success', `已应用第${i + 1}名参数`)]); }}
                                                        className="text-[10px] px-2 py-0.5 rounded bg-violet-600/30 text-violet-300 border border-violet-500/30 hover:bg-violet-600/50">
                                                        应用
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}

                        {/* 回测结果 */}
                        {backtestResults && (
                            <div ref={resultsRef} className="flex flex-col gap-5">
                                {/* 结果标题栏 */}
                                <div className="flex items-center justify-between bg-gradient-to-r from-indigo-900/30 to-slate-800/30 border border-indigo-500/20 rounded-xl px-4 py-3">
                                    <div className="flex items-center gap-3">
                                        <span className="text-sm font-bold text-indigo-300 bg-indigo-900/40 px-2.5 py-1 rounded">
                                            {STRATEGY_MAP[backtestResults.strategy_type]?.name || backtestResults.strategy_type || strategyType}
                                        </span>
                                        {backtestResults.dates?.length > 0 && (<>
                                            <span className="text-xs text-slate-400">
                                                {backtestResults.actual_start_date || backtestResults.dates[0]} ~ {backtestResults.actual_end_date || backtestResults.dates[backtestResults.dates.length - 1]}
                                            </span>
                                            {backtestResults.actual_end_date && backtestResults.actual_end_date < endDate && (
                                                <span className="text-[10px] text-amber-400 bg-amber-900/30 px-1.5 py-0.5 rounded border border-amber-500/30">
                                                    数据截止 {backtestResults.actual_end_date}
                                                </span>
                                            )}
                                        </>)}
                                    </div>
                                    <div className="flex items-center gap-2 text-xs text-slate-500">
                                        {backtestResults.strategy_params?.rebalance && (
                                            <span className="bg-slate-800/60 px-2 py-0.5 rounded">{{ 'monthly': '月调仓', 'weekly': '周调仓', 'daily': '日调仓' }[backtestResults.strategy_params.rebalance] || backtestResults.strategy_params.rebalance}</span>
                                        )}
                                        {backtestResults.strategy_params?.top_n && (
                                            <span className="bg-slate-800/60 px-2 py-0.5 rounded">Top{backtestResults.strategy_params.top_n}</span>
                                        )}
                                    </div>
                                </div>
                                {/* 核心指标 */}
                                <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                                    {[
                                        { cn: '总收益率', v: fmtPct(backtestResults.total_return), c: pnlColor(backtestResults.total_return), border: 'border-emerald-500/20 hover:border-emerald-500/40', desc: '回测期间的累计总收益' },
                                        { cn: '年化收益', v: fmtPct(backtestResults.annual_return), c: pnlColor(backtestResults.annual_return), border: 'border-teal-500/20 hover:border-teal-500/40', desc: '按复利折算的每年预期收益率' },
                                        { cn: '最大回撤', v: fmtPct(backtestResults.max_drawdown), c: 'text-rose-400', border: 'border-rose-500/20 hover:border-rose-500/40', desc: '从峰值到谷底的最大亏损幅度' },
                                        { cn: '夏普比率', v: fmtNum(backtestResults.sharpe_ratio, 2), c: pnlColor(backtestResults.sharpe_ratio), border: 'border-sky-500/20 hover:border-sky-500/40', desc: '每承担1单位风险获得的超额收益' }
                                    ].map((m, i) => (
                                        <div key={i} className={`bg-slate-800/60 backdrop-blur-sm px-3.5 py-2.5 rounded-xl border ${m.border} transition-all hover:bg-slate-750 group`} title={m.desc}>
                                            <div className="flex justify-between items-center">
                                                <span className="text-slate-100 font-bold text-sm tracking-wide">{m.cn}</span>
                                                <span className={`${m.c} text-xl font-black tracking-tight group-hover:scale-105 origin-right transition-transform`}>{m.v}</span>
                                            </div>
                                            <div className="mt-0.5">
                                                <span className="text-slate-400 font-normal text-xs">{m.desc}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                {/* 辅助指标 — 更紧凑，保持完整 */}
                                <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                                    {[
                                        { cn: 'Sortino比率', v: fmtNum(backtestResults.sortino_ratio, 2), c: pnlColor(backtestResults.sortino_ratio), border: 'border-cyan-500/20 hover:border-cyan-500/40', desc: '仅考虑下跌风险的收益比' },
                                        { cn: '超额收益', v: fmtPct(backtestResults.excess_return), c: pnlColor(backtestResults.excess_return), border: 'border-purple-500/20 hover:border-purple-500/40', desc: '策略收益 − 基准收益' },
                                        { cn: '年化波动率', v: fmtPct(backtestResults.volatility), c: 'text-amber-400', border: 'border-amber-500/20 hover:border-amber-500/40', desc: '收益率波动程度' },
                                        { cn: '基准(沪深300)', v: fmtPct(backtestResults.benchmark_return), c: pnlColor(backtestResults.benchmark_return), border: 'border-blue-500/20 hover:border-blue-500/40', desc: '同期沪深300涨跌幅' }
                                    ].map((m, i) => (
                                        <div key={i} className={`bg-slate-800/60 backdrop-blur-sm px-3 py-2 rounded-xl border ${m.border} transition-all hover:bg-slate-750 group`} title={m.desc}>
                                            <div className="flex justify-between items-center">
                                                <span className="text-slate-100 font-bold text-xs tracking-wide">{m.cn}</span>
                                                <span className={`${m.c} text-base font-black tracking-tight group-hover:scale-105 origin-right transition-transform`}>{m.v}</span>
                                            </div>
                                            <div className="mt-0.5">
                                                <span className="text-slate-400 font-normal text-[11px]">{m.desc}</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>

                                {/* 一键风险分析快捷入口 */}
                                {onGoToRisk && (
                                    <button onClick={onGoToRisk}
                                        className="w-full bg-gradient-to-r from-sky-600/80 to-cyan-600/80 hover:from-sky-500 hover:to-cyan-500 text-white py-3 rounded-xl font-bold shadow-lg transition-all flex items-center justify-center gap-2 group">
                                        <Shield className="w-5 h-5 group-hover:scale-110 transition-transform" />
                                        <span className="tracking-wide">带当前持仓 → 风险分析</span>
                                    </button>
                                )}

                                {/* 月度收益分解（可折叠） */}
                                {backtestResults.monthly_returns?.length > 0 && (
                                    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                        <button onClick={() => setShowMonthly(v => !v)}
                                            className="w-full flex items-center justify-between text-sm font-semibold text-slate-300">
                                            <div className="flex items-center gap-2">
                                                <BarChart3 className="w-4 h-4 text-indigo-400" />
                                                月度收益分解
                                                <span className="text-xs text-slate-500 font-normal">
                                                    {backtestResults.monthly_returns.length} 个月
                                                </span>
                                            </div>
                                            <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showMonthly ? 'rotate-180' : ''}`} />
                                        </button>
                                        {showMonthly && (
                                            <div className="flex items-end gap-1 h-32 mt-4">
                                                {(() => {
                                                    const data = backtestResults.monthly_returns;
                                                    const maxAbs = Math.max(...data.map(d => Math.abs(d.return)), 1);
                                                    return data.map((d, i) => {
                                                        const pct = Math.abs(d.return) / maxAbs;
                                                        const isPos = d.return >= 0;
                                                        return (
                                                            <div key={i} className="flex-1 flex flex-col items-center justify-end h-full group relative">
                                                                <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900 border border-slate-600 rounded-lg px-2 py-1 text-[10px] whitespace-nowrap z-10 pointer-events-none">
                                                                    <span className={pnlColor(d.return)}>
                                                                        {d.return > 0 ? '+' : ''}{d.return}%
                                                                    </span>
                                                                </div>
                                                                <div
                                                                    className={`w-full rounded-t-sm transition-all group-hover:opacity-80 ${isPos
                                                                            ? 'bg-gradient-to-t from-emerald-600 to-emerald-400'
                                                                            : 'bg-gradient-to-b from-rose-600 to-rose-400'
                                                                        }`}
                                                                    style={{ height: `${Math.max(pct * 80, 2)}%` }}
                                                                />
                                                                <div className="text-[9px] text-slate-500 mt-1 rotate-[-45deg] origin-top-left translate-y-3 whitespace-nowrap">
                                                                    {d.month.slice(5)}月
                                                                </div>
                                                            </div>
                                                        );
                                                    });
                                                })()}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* 净值曲线图（可折叠） */}
                        {backtestResults && backtestResults.cumReturns?.length > 0 && (
                            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                <button onClick={() => setShowNetValue(v => !v)}
                                    className="w-full flex items-center justify-between text-sm font-semibold text-slate-300">
                                    <div className="flex items-center gap-2">
                                        <TrendingUp className="w-4 h-4 text-emerald-400" />
                                        策略净值 vs 基准
                                    </div>
                                    <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showNetValue ? 'rotate-180' : ''}`} />
                                </button>
                                {showNetValue && (
                                    <div className="mt-3">
                                        <NetValueChart
                                            data={backtestResults.cumReturns.map((v, i) => ({
                                                date: backtestResults.dates?.[i] || `Day ${i + 1}`,
                                                value: Number(v.toFixed(4)),
                                                benchmark: backtestResults.benchmark?.[i]
                                                    ? Number(backtestResults.benchmark[i].toFixed(4))
                                                    : undefined,
                                            }))}
                                        />
                                    </div>
                                )}
                            </div>
                        )}

                        {/* 回测参数回显 */}
                        {backtestResults?.strategy_params && Object.keys(backtestResults.strategy_params).length > 0 && (
                            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                                    <SlidersHorizontal className="w-4 h-4 text-indigo-400" />
                                    本次回测参数
                                    {backtestResults.strategy_type && (
                                        <span className="text-xs text-indigo-300 bg-indigo-900/30 border border-indigo-700/30 px-2 py-0.5 rounded">
                                            {STRATEGY_MAP[backtestResults.strategy_type]?.name || backtestResults.strategy_type}
                                        </span>
                                    )}
                                </h3>
                                <div className="flex flex-wrap gap-3">
                                    {Object.entries(backtestResults.strategy_params).map(([k, v]) => {
                                        const schema = strategyParamsSchema.find(p => p.name === k);
                                        return (
                                            <div key={k} className="px-3 py-1.5 bg-slate-900/60 border border-slate-700/40 rounded-lg text-xs">
                                                <span className="text-slate-400">{schema?.label || k}: </span>
                                                <span className="text-white font-mono">{String(v)}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            </div>
                        )}

                        {/* 持仓快照（可折叠） */}
                        {backtestResults?.holdings?.length > 0 && (
                            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                <button onClick={() => setShowHoldings(v => !v)}
                                    className="w-full flex items-center justify-between text-sm font-semibold text-slate-300">
                                    <div className="flex items-center gap-2">
                                        <Activity className="w-4 h-4 text-teal-400" />
                                        持仓快照
                                        <span className="text-xs text-slate-500 font-normal">{backtestResults.holdings.length} 期</span>
                                    </div>
                                    <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showHoldings ? 'rotate-180' : ''}`} />
                                </button>
                                {showHoldings && (
                                    <div className="max-h-56 overflow-y-auto space-y-2 mt-3">
                                        {backtestResults.holdings.slice(-10).map((snap, idx) => (
                                            <div key={idx} className="flex items-start gap-3 px-3 py-2 bg-slate-900/40 rounded-lg">
                                                <span className="text-xs text-slate-500 font-mono shrink-0 mt-0.5">{snap.date}</span>
                                                <div className="flex flex-wrap gap-1.5">
                                                    {snap.holdings.map(h => (
                                                        <span key={h.code} className="text-xs px-2 py-0.5 rounded bg-indigo-900/30 border border-indigo-700/20 text-indigo-300">
                                                            {h.name || h.code} <span className="text-slate-400 font-mono">{h.code}</span> <span className="text-slate-400">{h.weight}%</span>
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        )}

                        {/* 回测股票池（可折叠） */}
                        {backtestResults && (() => {
                            // 从持仓快照提取所有参与回测的标的（去重）
                            const poolMap = new Map();
                            (backtestResults.holdings || []).forEach(snap => {
                                (snap.holdings || []).forEach(h => {
                                    if (!poolMap.has(h.code)) poolMap.set(h.code, h.name || h.code);
                                });
                            });
                            // fallback: 如果没有 holdings，用自选池
                            const poolStocks = poolMap.size > 0
                                ? Array.from(poolMap, ([code, name]) => ({ code, name }))
                                : customStocks;
                            if (poolStocks.length === 0 || !onViewKline) return null;
                            return (
                                <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                    <button onClick={() => setShowStockPool(v => !v)}
                                        className="w-full flex items-center justify-between text-sm font-semibold text-slate-300">
                                        <div className="flex items-center gap-2">
                                            <Layers className="w-4 h-4 text-teal-400" />
                                            回测股票池
                                            <span className="text-xs text-slate-500 font-normal">{poolStocks.length} 只</span>
                                        </div>
                                        <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showStockPool ? 'rotate-180' : ''}`} />
                                    </button>
                                    {showStockPool && (
                                        <div className="flex flex-wrap gap-1.5 mt-3">
                                            {poolStocks.map(s => (
                                                <button key={s.code} onClick={() => onViewKline(s.code)}
                                                    className="text-xs px-2 py-0.5 rounded bg-indigo-900/30 border border-indigo-700/20 text-indigo-300 hover:bg-indigo-900/50 hover:border-indigo-500/40 transition-all cursor-pointer"
                                                    title={`查看 ${s.name || s.code} K线`}>
                                                    {s.name || s.code} <span className="text-slate-400 font-mono">{s.code}</span>
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            );
                        })()}

                    </>)}

                    {/* 回测历史 */}
                    <div className="mt-4 pt-4 border-t border-slate-700/40">
                        <div className="flex items-center justify-between mb-3">
                            <h3 className="text-base font-bold text-white flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full bg-indigo-400 shadow-[0_0_8px_rgba(99,102,241,0.8)]" />
                                回测历史
                                <span className="text-xs text-slate-500 font-normal ml-1">最近50条</span>
                            </h3>
                            <div className="flex items-center gap-2">
                                <button onClick={loadHistory} disabled={historyLoading}
                                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-slate-800/60 border border-slate-700/50 text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-all">
                                    <RefreshCw className={`w-3.5 h-3.5 ${historyLoading ? 'animate-spin' : ''}`} /> 刷新
                                </button>
                                {historyRecords.length > 0 && (
                                    <button onClick={handleClearAllHistory}
                                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg bg-red-900/20 border border-red-500/30 text-red-400 hover:bg-red-900/40 hover:text-red-300 transition-all">
                                        <Trash2 className="w-3.5 h-3.5" /> 清空全部
                                    </button>
                                )}
                            </div>
                        </div>
                        {historyRecords.length === 0 ? (
                            <div className="flex flex-col items-center py-8 text-slate-500">
                                <BarChart3 className="w-8 h-8 mb-2 opacity-30" />
                                <p className="text-xs">暂无回测记录</p>
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {historyRecords.map(r => (
                                    <div key={r.id} className="flex items-center gap-4 bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/40 hover:border-slate-600/60 rounded-xl px-4 py-3 transition-all group">
                                        <div className="w-28 shrink-0">
                                            <span className="text-sm font-bold text-indigo-300 bg-indigo-900/30 border border-indigo-700/30 px-2.5 py-1 rounded">
                                                {STRATEGY_MAP[r.strategy_type]?.name || r.strategy_type}
                                            </span>
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            {r.summary && (
                                                <div className="text-[11px] text-teal-400/80 mb-0.5 truncate" title={r.summary}>
                                                    {r.summary}
                                                </div>
                                            )}
                                            <div className="flex items-center gap-2 text-xs text-slate-400">
                                                <Clock className="w-3 h-3" />
                                                <span>{r.created_at?.slice(0, 16) || '--'}</span>
                                                <span className="text-slate-600">|</span>
                                                <span>{r.start_date} ~ {r.end_date}</span>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-5 shrink-0">
                                            {[
                                                { v: fmt(r.total_return), l: '总收益', c: color(r.total_return) },
                                                { v: fmt(r.annual_return), l: '年化', c: color(r.annual_return) },
                                                { v: fmt(r.max_drawdown), l: '回撤', c: 'text-rose-400' },
                                                { v: r.sharpe_ratio !== null ? fmtNum(r.sharpe_ratio, 2) : '--', l: '夏普', c: color(r.sharpe_ratio) },
                                            ].map((m, i) => (
                                                <div key={i} className="text-center">
                                                    <div className={`text-sm font-bold ${m.c}`}>{m.v}</div>
                                                    <div className="text-xs text-slate-400">{m.l}</div>
                                                </div>
                                            ))}
                                        </div>
                                        <button onClick={() => handleLoadHistory(r)} disabled={loadingHistoryId === r.id}
                                            title="加载此次回测结果"
                                            className="opacity-0 group-hover:opacity-100 px-2.5 py-1 rounded-lg text-xs font-medium text-indigo-400 bg-indigo-900/20 border border-indigo-700/30 hover:bg-indigo-900/40 hover:text-indigo-300 transition-all disabled:opacity-50">
                                            {loadingHistoryId === r.id ? '加载中...' : '回放'}
                                        </button>
                                        <button onClick={() => handleDeleteHistory(r.id)} disabled={deleting === r.id}
                                            className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-rose-900/20 transition-all">
                                            <Trash2 className={`w-4 h-4 ${deleting === r.id ? 'animate-spin' : ''}`} />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default StrategyBacktestPanel;
