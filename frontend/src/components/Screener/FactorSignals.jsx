import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Signal, ChevronDown, ChevronRight, RefreshCw, Settings, Sparkles } from 'lucide-react';
import { dataCenterApi, factorApi, stockApi } from '../../services/api';
import { buildPoolItem } from '../../utils/poolActions';
import { DEFAULT_WEIGHTS } from './presets';
import { showToast } from '../../utils/toast';

// localStorage 持久化 key
const STORAGE_KEY = 'factor_signal_config';

const FACTOR_LABELS = {
    reversal: { label: '反转', desc: '近期跌的更可能反弹（均值回归）' },
    value: { label: '价值', desc: 'PE/PB 越低越有价值' },
    quality: { label: '质量', desc: '盈利质量 + 杠杆风险（ROE/毛利率/现金流/低杠杆）' },
    size: { label: '规模', desc: '小市值股票长期超额收益显著' },
    momentum: { label: '动量', desc: '12-1月中期趋势延续' },
    lowvol: { label: '低波', desc: '低波动股票风险调整收益更优' },
    growth: { label: '成长', desc: '营收 + 利润增速' },
    dividend: { label: '红利', desc: '股息率越高越好' },
    concentration: { label: '筹码集中', desc: '股东户数减少 = 主力吸筹' },
    leverage: { label: '杠杆情绪', desc: '融资余额/流通市值，越高越看多' },
};

const DEFAULT_CONFIG = {
    excludeSt: true,
    minListDays: 60,
    topN: 10,
    weights: { ...DEFAULT_WEIGHTS },
};

const loadConfig = () => {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
            const saved = JSON.parse(raw);
            return { ...DEFAULT_CONFIG, ...saved, weights: { ...DEFAULT_WEIGHTS, ...saved.weights } };
        }
    } catch { /* ignore */ }
    return { ...DEFAULT_CONFIG };
};

const saveConfig = (cfg) => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg)); } catch { /* ignore */ }
};

/**
 * 因子信号区域 — 折叠式 Top N 表格 + 可配置面板
 * 位置：智能选股面板中「行业轮动信号」之后、「行业选择」之前
 */
const FactorSignals = ({ customStocks = [], setCustomStocks, latestTradeDate, onViewKline }) => {
    const [signals, setSignals] = useState({ date: null, signals: [] });
    const [loading, setLoading] = useState(false);
    const [expanded, setExpanded] = useState(false);
    const [showSettings, setShowSettings] = useState(false);
    const [error, setError] = useState(null);
    const [addAllStatus, setAddAllStatus] = useState(null);
    const addAllTimerRef = useRef(null);
    const pollRef = useRef(null);

    // 技术面诊断缓存 { code: { score, label, trend, trend_color } }
    const [techMap, setTechMap] = useState({});

    // 可配置参数（持久化到 localStorage）
    const [config, setConfig] = useState(loadConfig);

    // config 变化时持久化
    useEffect(() => { saveConfig(config); }, [config]);

    const updateConfig = (patch) => setConfig(prev => ({ ...prev, ...patch }));
    const updateWeight = (key, val) => setConfig(prev => ({
        ...prev,
        weights: { ...prev.weights, [key]: val },
    }));

    // 拉取信号（读取 API，传自定义权重实现全市场重排）
    const fetchSignals = React.useCallback(async (weightsOverride) => {
        const w = weightsOverride || config.weights;
        try {
            const data = await dataCenterApi.getDailySignals(null, config.topN, {
                excludeSt: config.excludeSt, weights: w,
            });
            setSignals({ date: data?.date || null, signals: data?.signals || [] });
        } catch { /* 静默 */ }
    }, [config.topN, config.excludeSt, config.weights]);

    // 挂载时 + 配置变化时自动拉取（权重变化 debounce 500ms）
    const debounceRef = useRef(null);
    useEffect(() => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => { fetchSignals(); }, 500);
        return () => { clearTimeout(debounceRef.current); };
    }, [fetchSignals]);

    // 信号更新后批量拉取技术面诊断
    useEffect(() => {
        if (!signals.signals?.length) return;
        const codes = signals.signals.map(s => s.code);
        stockApi.getDiagnosisBatch(codes)
            .then(res => { if (res) setTechMap(res); })
            .catch(() => {});
    }, [signals.signals]);

    // 组件卸载时清理轮询（与 debounce 分离，避免 slider 拖动时中断重算轮询）
    useEffect(() => {
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, []);

    // 重新计算（带投资域过滤参数）
    const handleTrigger = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await dataCenterApi.triggerSignals({
                excludeSt: config.excludeSt,
                minListDays: config.minListDays,
            });

            if (res?.status === 'already_running') {
                setError(res.message || '有其他同步任务正在运行，请稍后再试');
                setLoading(false);
                return;
            }

            const taskId = res?.task_id;
            if (!taskId) {
                setError('未获取到任务 ID，请稍后重试');
                setLoading(false);
                return;
            }

            // 轮询任务状态（最多 120 秒）
            if (pollRef.current) clearInterval(pollRef.current);
            let pollCount = 0;
            pollRef.current = setInterval(async () => {
                if (++pollCount > 60) {
                    clearInterval(pollRef.current);
                    pollRef.current = null;
                    setError('计算超时，请检查后端日志');
                    setLoading(false);
                    return;
                }
                try {
                    const s = await dataCenterApi.getTaskStatus(taskId);
                    if (s.status === 'completed' || s.status === 'failed') {
                        clearInterval(pollRef.current);
                        pollRef.current = null;
                        if (s.status === 'completed') {
                            await fetchSignals();
                            showToast('因子信号计算完成', 'success');
                        } else {
                            setError(s.error || '信号计算失败');
                        }
                        setLoading(false);
                    }
                } catch { /* 网络抖动忽略 */ }
            }, 2000);
        } catch {
            setError('请求失败，请检查网络');
            setLoading(false);
        }
    };

    // IC 推荐权重
    const [icLoading, setIcLoading] = useState(false);
    const handleIcRecommend = async () => {
        setIcLoading(true);
        try {
            // 用当前信号中的股票做 IC 分析
            const codes = signals.signals.map(s => s.code);
            if (codes.length < 5) {
                setError('至少需要 5 只股票才能进行 IC 分析');
                setIcLoading(false);
                return;
            }
            const res = await factorApi.icAnalysis(codes);
            if (res?.suggested_weights) {
                updateConfig({ weights: res.suggested_weights });
            } else if (res?.error) {
                setError(`IC 分析: ${res.error}`);
            }
        } catch (e) {
            setError(`IC 分析失败: ${e.message}`);
        }
        setIcLoading(false);
    };

    // 用自定义权重对信号做本地重排序（权重 slider 立即生效，无需后端重算）
    const rankedSignals = useMemo(() => {
        if (!signals.signals?.length) return [];
        const wKeys = Object.keys(config.weights).filter(k => config.weights[k] > 0);
        const wTotal = wKeys.reduce((acc, k) => acc + config.weights[k], 0);
        if (wTotal === 0) return signals.signals;

        return signals.signals
            .map(s => {
                const factors = s.factors || {};
                let weighted = 0;
                for (const k of wKeys) {
                    weighted += (factors[k] ?? 0) * config.weights[k];
                }
                return { ...s, composite: weighted / wTotal };
            })
            .sort((a, b) => b.composite - a.composite)
            .map((s, i) => ({ ...s, rank: i + 1 }));
    }, [signals.signals, config.weights]);

    const hasSignals = rankedSignals.length > 0;
    const top1 = hasSignals ? rankedSignals[0] : null;

    // 动态取权重最高的 4 个因子用于表格展示
    const topFactors = useMemo(() =>
        Object.entries(config.weights)
            .filter(([, w]) => w > 0)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 4)
            .map(([key]) => ({ key, label: FACTOR_LABELS[key]?.label || key }))
    , [config.weights]);

    // 权重归一化显示
    const totalWeight = Object.values(config.weights).reduce((a, b) => a + b, 0);

    const addToPool = async (code, name) => {
        if (customStocks.some(cs => cs.code === code)) return;
        const { item, assetType } = await buildPoolItem(code, name);
        if (assetType === 'bond') return;
        setCustomStocks(prev => [...prev, item]);
    };

    const addAllToPool = async () => {
        const newStocks = [];
        for (const s of rankedSignals) {
            if (customStocks.some(cs => cs.code === s.code)) continue;
            const { item, assetType } = await buildPoolItem(s.code, s.name);
            if (assetType === 'bond') continue;
            newStocks.push(item);
        }
        clearTimeout(addAllTimerRef.current);
        if (newStocks.length > 0) {
            setCustomStocks(prev => [...prev, ...newStocks]);
            setAddAllStatus(`✓ 已加入 ${newStocks.length} 只`);
        } else {
            setAddAllStatus('全部已在自选池中');
        }
        addAllTimerRef.current = setTimeout(() => setAddAllStatus(null), 2000);
    };

    return (
        <div className="bg-slate-800/50 backdrop-blur-md border border-slate-700/50 rounded-xl overflow-hidden">
            {/* 折叠标题栏 */}
            <button
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-slate-700/30 transition-colors"
            >
                <div className="flex items-center gap-2.5">
                    <Signal className="w-5 h-5 text-amber-400" />
                    <span className="text-sm font-semibold text-white">因子信号</span>
                    {signals.date && (
                        <span className="text-xs text-slate-400 font-normal">{signals.date}</span>
                    )}
                    {signals.date && latestTradeDate && signals.date < latestTradeDate && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/20 font-normal">
                            ⚠️ 滞后于行情({latestTradeDate})
                        </span>
                    )}
                    {top1 && !expanded && (
                        <span className="text-xs text-slate-400 ml-2">
                            Top1: <span className="text-white font-mono">{top1.code}</span>
                            {' '}<span className="text-slate-300">{top1.name}</span>
                            {' '}<span className="text-amber-400 font-semibold">
                                {top1.composite?.toFixed(3)}
                            </span>
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {hasSignals && (
                        <span className="text-[11px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/20">
                            {rankedSignals.length} 只
                        </span>
                    )}
                    {config.excludeSt && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
                            排除ST
                        </span>
                    )}
                    {expanded
                        ? <ChevronDown className="w-4 h-4 text-slate-400" />
                        : <ChevronRight className="w-4 h-4 text-slate-400" />
                    }
                </div>
            </button>

            {/* 展开内容 */}
            {expanded && (
                <div className="px-5 pb-5 border-t border-slate-700/30">
                    {/* 操作栏 */}
                    <div className="flex items-center gap-2 py-3">
                        {setCustomStocks && hasSignals && (
                            <button
                                onClick={addAllToPool}
                                className={`px-3 py-1.5 rounded-lg text-xs transition-all border ${
                                    addAllStatus?.startsWith('✓')
                                        ? 'bg-emerald-500/30 text-emerald-300 border-emerald-500/40'
                                        : addAllStatus
                                            ? 'bg-slate-700/50 text-slate-400 border-slate-600/30'
                                            : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/30'
                                }`}
                            >
                                {addAllStatus || '全部加入自选池'}
                            </button>
                        )}
                        <button
                            onClick={handleTrigger}
                            disabled={loading}
                            className="px-3 py-1.5 rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30 transition-all text-xs flex items-center gap-1.5 disabled:opacity-50"
                        >
                            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
                            {loading ? '计算中...' : '重新计算'}
                        </button>
                        <button
                            onClick={() => setShowSettings(prev => !prev)}
                            className={`px-3 py-1.5 rounded-lg transition-all text-xs flex items-center gap-1.5 border ${showSettings ? 'bg-amber-500/20 text-amber-400 border-amber-500/30' : 'bg-slate-700/40 text-slate-400 border-slate-600/30 hover:bg-slate-700/60'}`}
                        >
                            <Settings className="w-3.5 h-3.5" />
                            设置
                        </button>
                    </div>

                    {/* ━━━ 设置面板 ━━━ */}
                    {showSettings && (
                        <div className="mb-4 p-4 bg-slate-900/60 border border-slate-700/40 rounded-xl space-y-4">

                            {/* 投资域过滤 */}
                            <div>
                                <h4 className="text-xs font-semibold text-slate-300 mb-2">投资域过滤</h4>
                                <div className="flex items-center gap-5 flex-wrap">
                                    <label className="flex items-center gap-2 cursor-pointer select-none">
                                        <input type="checkbox" checked={config.excludeSt}
                                            onChange={e => updateConfig({ excludeSt: e.target.checked })}
                                            className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500/30 cursor-pointer" />
                                        <span className="text-xs text-slate-300">排除 ST / *ST</span>
                                    </label>
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs text-slate-400">最短上市</span>
                                        <select value={config.minListDays} onChange={e => updateConfig({ minListDays: Number(e.target.value) })}
                                            className="bg-slate-800 border border-slate-700/50 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-amber-500/50">
                                            <option value={0}>不限</option>
                                            <option value={30}>30 天</option>
                                            <option value={60}>60 天</option>
                                            <option value={120}>120 天</option>
                                        </select>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs text-slate-400">显示数量</span>
                                        <select value={config.topN} onChange={e => { updateConfig({ topN: Number(e.target.value) }); }}
                                            className="bg-slate-800 border border-slate-700/50 rounded px-2 py-1 text-xs text-white focus:outline-none focus:border-amber-500/50">
                                            <option value={10}>Top 10</option>
                                            <option value={20}>Top 20</option>
                                            <option value={50}>Top 50</option>
                                        </select>
                                    </div>
                                </div>
                            </div>

                            {/* 因子权重 */}
                            <div>
                                <div className="flex items-center justify-between mb-2">
                                    <h4 className="text-xs font-semibold text-slate-300">因子权重</h4>
                                    <div className="flex items-center gap-2">
                                        <button onClick={handleIcRecommend} disabled={icLoading || !hasSignals}
                                            className="text-[10px] px-2 py-1 rounded bg-violet-500/20 text-violet-300 border border-violet-500/30 hover:bg-violet-500/30 transition-all disabled:opacity-40 flex items-center gap-1"
                                            title="根据因子 IC 分析自动推荐最优权重">
                                            <Sparkles className="w-3 h-3" />
                                            {icLoading ? '分析中...' : 'IC 推荐'}
                                        </button>
                                        <button onClick={() => updateConfig({ weights: { ...DEFAULT_WEIGHTS } })}
                                            className="text-[10px] px-2 py-1 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30 hover:bg-slate-700/70 transition-all">
                                            重置默认
                                        </button>
                                    </div>
                                </div>
                                <div className="grid grid-cols-3 gap-x-5 gap-y-2">
                                    {Object.entries(FACTOR_LABELS).map(([key, { label, desc }]) => {
                                        const w = config.weights[key] ?? 0;
                                        const pct = totalWeight > 0 ? Math.round(w / totalWeight * 100) : 0;
                                        return (
                                            <div key={key} className="flex items-center gap-2">
                                                <span className="text-[11px] text-slate-400 w-14 shrink-0 cursor-help" title={desc}>{label}</span>
                                                <input type="range" min={0} max={0.5} step={0.01} value={w}
                                                    onChange={e => updateWeight(key, Number(e.target.value))}
                                                    className="flex-1 h-1 rounded-full appearance-none cursor-pointer accent-amber-500 bg-slate-700" />
                                                <span className="text-[10px] font-mono text-amber-400 w-8 text-right">{pct}%</span>
                                            </div>
                                        );
                                    })}
                                </div>
                                <div className="text-xs text-slate-300 mt-2">
                                    拖动权重自动生效（全市场重排）。IC 推荐基于历史因子收益率相关性分析。
                                </div>
                            </div>
                        </div>
                    )}

                    {error && (
                        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2 mb-2">
                            {error}
                        </div>
                    )}

                    {/* 信号表格 */}
                    {hasSignals ? (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-slate-400 border-b border-slate-700/50">
                                        <th className="text-left py-2 px-2">#</th>
                                        <th className="text-left py-2 px-2">代码</th>
                                        <th className="text-left py-2 px-2">名称</th>
                                        <th className="text-left py-2 px-2">行业</th>
                                        <th className="text-right py-2 px-2 cursor-help" title="多因子加权综合得分，权重可在设置中调整">综合得分</th>
                                        <th className="text-right py-2 px-2">最新价</th>
                                        <th className="text-right py-2 px-2">涨跌%</th>
                                        <th className="text-center py-2 px-2 cursor-help" title="技术诊断引擎7维综合评分">趋势</th>
                                        {topFactors.map(f => (
                                            <th key={f.key} className="text-right py-2 px-2">{f.label}</th>
                                        ))}
                                        {setCustomStocks && <th className="text-center py-2 px-2">操作</th>}
                                    </tr>
                                </thead>
                                <tbody>
                                    {rankedSignals.map((s) => (
                                        <tr key={s.code} className="border-b border-slate-800/50 hover:bg-slate-700/30 transition-colors">
                                            <td className="py-2 px-2 text-slate-500">{s.rank}</td>
                                            <td className="py-2 px-2 text-white font-mono">{s.code}</td>
                                            <td className="py-2 px-2 text-slate-300">{s.name || '-'}</td>
                                            <td className="py-2 px-2 text-slate-400 text-xs">{s.industry || '-'}</td>
                                            <td className="py-2 px-2 text-right">
                                                <span className="font-semibold text-amber-400">
                                                    {s.composite.toFixed(3)}
                                                </span>
                                            </td>
                                            <td className="py-2 px-2 text-right text-white font-mono">{s.close != null ? s.close.toFixed(2) : '-'}</td>
                                            <td className={`py-2 px-2 text-right font-mono ${s.pct_chg > 0 ? 'text-red-400' : s.pct_chg < 0 ? 'text-green-400' : 'text-slate-400'}`}>{s.pct_chg != null ? `${s.pct_chg > 0 ? '+' : ''}${s.pct_chg}%` : '-'}</td>
                                            <td className="py-2 px-2 text-center">
                                                {techMap[s.code] ? (
                                                    <span className="text-xs" title={`技术分 ${techMap[s.code].score}`}>
                                                        <span style={{ color: techMap[s.code].trend_color }}>{techMap[s.code].label}</span>
                                                    </span>
                                                ) : <span className="text-slate-600 text-xs">-</span>}
                                            </td>
                                            {topFactors.map(f => (
                                                <td key={f.key} className="py-2 px-2 text-right text-slate-300">{s.factors?.[f.key]?.toFixed(2) ?? '-'}</td>
                                            ))}
                                            {setCustomStocks && (
                                                <td className="py-2 px-2 text-center">
                                                    <div className="flex items-center justify-center gap-1">
                                                        {onViewKline && (
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); onViewKline(s.code); }}
                                                                className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all"
                                                                title={`查看 ${s.name} K线图`}
                                                            >📈</button>
                                                        )}
                                                        {(() => { const inPool = customStocks.some(cs => cs.code === s.code); return (
                                                            <button
                                                                onClick={() => inPool ? setCustomStocks(prev => prev.filter(cs => cs.code !== s.code)) : addToPool(s.code, s.name)}
                                                                className={`text-[10px] px-1.5 py-1 rounded border transition-all ${inPool ? 'bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30' : 'bg-emerald-600/30 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/50'}`}
                                                                title={inPool ? '点击移出自选池' : '加入自选池'}
                                                            >{inPool ? '✓' : '➕'}</button>
                                                        ); })()}
                                                    </div>
                                                </td>
                                            )}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="text-center text-slate-500 py-8">
                            暂无信号数据，请点击「重新计算」生成
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default FactorSignals;
