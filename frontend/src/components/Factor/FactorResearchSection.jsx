/**
 * 因子研究区域 — 嵌入 FactorPanel 的子组件
 * 
 * 功能: 预设因子选择 + 参数调整 + 分层回测 + 结果图表
 */
import { useState, useEffect } from 'react';
import { FlaskConical, ChevronUp, ChevronDown, Play, AlertCircle, BarChart3, TrendingUp } from 'lucide-react';
import { researchApi } from '../../services/api';

const GROUP_COLORS = ['#10b981', '#6366f1', '#f59e0b', '#ef4444', '#94a3b8'];

const FactorResearchSection = () => {
    // 预设因子
    const [presets, setPresets] = useState([]);
    const [selectedPreset, setSelectedPreset] = useState('');
    const [params, setParams] = useState({});
    const [customExpr, setCustomExpr] = useState('');
    const [useCustom, setUseCustom] = useState(false);

    // 回测参数
    const [nGroups, setNGroups] = useState(5);

    // 结果
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    // 折叠
    const [expanded, setExpanded] = useState(false);

    // 加载预设列表
    useEffect(() => {
        researchApi.getPresets()
            .then(data => {
                if (data?.presets?.length > 0) {
                    setPresets(data.presets);
                    setSelectedPreset(data.presets[0].name);
                    // 初始化参数
                    const initParams = {};
                    data.presets[0].params.forEach(p => { initParams[p.name] = p.default; });
                    setParams(initParams);
                }
            })
            .catch(() => {});
    }, []);

    // 切换预设时更新参数
    const handlePresetChange = (name) => {
        setSelectedPreset(name);
        const preset = presets.find(p => p.name === name);
        if (preset) {
            const newParams = {};
            preset.params.forEach(p => { newParams[p.name] = p.default; });
            setParams(newParams);
        }
    };

    // 执行分层回测
    const runStratified = async () => {
        setLoading(true);
        setError('');
        try {
            const options = {
                n_groups: nGroups,
            };
            if (useCustom && customExpr) {
                options.expression = customExpr;
            } else {
                options.preset_name = selectedPreset;
                options.params = params;
            }
            const data = await researchApi.stratified(options);
            setResult(data);
        } catch (e) {
            setError(e.message);
            setResult(null);
        }
        setLoading(false);
    };

    // 验证因子表达式
    const [validating, setValidating] = useState(false);
    const [validateResult, setValidateResult] = useState(null);
    const handleValidate = async () => {
        if (!customExpr.trim()) return;
        setValidating(true);
        try {
            const data = await researchApi.validate(customExpr);
            setValidateResult(data);
        } catch (e) {
            setValidateResult({ valid: false, error: e.message });
        }
        setValidating(false);
    };

    const currentPreset = presets.find(p => p.name === selectedPreset);
    const exprPreview = currentPreset
        ? currentPreset.template.replace(/\{(\w+)\}/g, (_, k) => params[k] ?? k)
        : '';

    return (
        <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl shadow-sm">
            {/* 折叠标题 */}
            <button onClick={() => setExpanded(v => !v)}
                className="w-full p-5 flex items-center justify-between text-left">
                <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                    <FlaskConical className="w-4 h-4 text-emerald-400" />
                    因子研究验证
                    <span className="text-xs text-slate-400 font-normal">分层回测 · 验证因子有效性</span>
                </h3>
                {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
            </button>

            {expanded && (
                <div className="px-5 pb-5 space-y-4">
                    {/* 因子选择 */}
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div>
                            <label className="text-xs text-slate-400 mb-1.5 block">选择因子</label>
                            <div className="flex gap-2">
                                <select
                                    value={useCustom ? '__custom__' : selectedPreset}
                                    onChange={e => {
                                        if (e.target.value === '__custom__') {
                                            setUseCustom(true);
                                        } else {
                                            setUseCustom(false);
                                            handlePresetChange(e.target.value);
                                        }
                                    }}
                                    className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none"
                                >
                                    <optgroup label="内置预设">
                                        {presets.map(p => (
                                            <option key={p.name} value={p.name}>{p.name} — {p.desc}</option>
                                        ))}
                                    </optgroup>
                                    <optgroup label="高级">
                                        <option value="__custom__">✏️ 自定义表达式</option>
                                    </optgroup>
                                </select>
                            </div>
                        </div>

                        {/* 参数调整 */}
                        {!useCustom && currentPreset?.params?.length > 0 && (
                            <div>
                                {currentPreset.params.map(p => (
                                    <div key={p.name}>
                                        <label className="text-xs text-slate-400 mb-1.5 block">{p.label}</label>
                                        <div className="flex items-center gap-3">
                                            <input
                                                type="range"
                                                min={p.min} max={p.max} step={1}
                                                value={params[p.name] || p.default}
                                                onChange={e => setParams(prev => ({ ...prev, [p.name]: parseInt(e.target.value) }))}
                                                className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer"
                                                style={{
                                                    background: `linear-gradient(to right, #10b981 ${((params[p.name] || p.default) - p.min) / (p.max - p.min) * 100}%, #334155 ${((params[p.name] || p.default) - p.min) / (p.max - p.min) * 100}%)`,
                                                }}
                                            />
                                            <span className="text-white font-mono text-sm w-10 text-right">{params[p.name] || p.default}</span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* 自定义表达式输入 */}
                        {useCustom && (
                            <div>
                                <label className="text-xs text-slate-400 mb-1.5 block">自定义表达式</label>
                                <div className="flex gap-2">
                                    <input
                                        type="text"
                                        value={customExpr}
                                        onChange={e => { setCustomExpr(e.target.value); setValidateResult(null); }}
                                        placeholder="例如: rank(close / delay(close, 20))"
                                        className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white font-mono focus:border-emerald-500 focus:outline-none"
                                    />
                                    <button onClick={handleValidate} disabled={validating || !customExpr.trim()}
                                        className="px-3 py-2 rounded-lg bg-sky-600/30 text-sky-300 hover:bg-sky-600/50 text-xs font-medium disabled:opacity-50 transition-all whitespace-nowrap">
                                        {validating ? '...' : '验证'}
                                    </button>
                                </div>
                                {validateResult && (
                                    <div className={`text-xs mt-1.5 ${validateResult.valid !== false ? 'text-red-400' : 'text-green-400'}`}>
                                        {validateResult.valid !== false ? '✅ 表达式有效' : `❌ ${validateResult.error || '无效表达式'}`}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>

                    {/* 公式预览 + 分组数 + 执行按钮 */}
                    <div className="flex items-center gap-3">
                        {!useCustom && (
                            <div className="flex-1 bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2">
                                <span className="text-xs text-slate-400">公式: </span>
                                <code className="text-xs text-emerald-300 font-mono">{exprPreview}</code>
                            </div>
                        )}
                        <div className="flex items-center gap-2">
                            <label className="text-xs text-slate-400">分组</label>
                            <select value={nGroups} onChange={e => setNGroups(parseInt(e.target.value))}
                                className="bg-slate-800 border border-slate-600 rounded-lg px-2 py-2 text-sm text-white focus:outline-none w-16">
                                {[3, 5, 10].map(n => <option key={n} value={n}>{n}</option>)}
                            </select>
                        </div>
                        <button onClick={runStratified} disabled={loading}
                            className="px-5 py-2 rounded-lg bg-gradient-to-r from-emerald-600 to-teal-600 text-white font-bold text-sm hover:opacity-90 transition-all disabled:opacity-50 flex items-center gap-1.5 shadow-lg shadow-emerald-900/20">
                            {loading ? (
                                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> 验证中...</>
                            ) : (
                                <><Play className="w-4 h-4" /> 🔬 验证效果</>
                            )}
                        </button>
                    </div>

                    {/* 错误提示 */}
                    {error && (
                        <div className="flex items-center gap-2 text-xs text-rose-400 bg-rose-900/20 border border-rose-500/30 rounded-lg p-3">
                            <AlertCircle className="w-4 h-4 shrink-0" /> {error}
                        </div>
                    )}

                    {/* 结果展示 */}
                    {result && (
                        <div className="space-y-4 mt-2">
                            {/* 一句话总结 */}
                            <div className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4">
                                <div className="text-xs text-slate-400 mb-1">
                                    表达式: <code className="text-emerald-300 font-mono">{result.expression}</code>
                                    <span className="ml-3">样本: {result.stock_count}只 × {result.period_count}期</span>
                                </div>
                                <div className="text-sm text-white font-medium mt-1">{result.summary}</div>
                            </div>

                            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                                {/* 分层收益柱状图 */}
                                <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                    <h4 className="text-xs text-slate-400 mb-3 flex items-center gap-1.5">
                                        <BarChart3 className="w-3.5 h-3.5 text-indigo-400" />
                                        分层年化收益
                                        <span className="text-xs text-slate-400">（G1=因子值最大）</span>
                                    </h4>
                                    <div className="flex items-end gap-2 h-40 px-2">
                                        {result.groups.map((g, idx) => {
                                            const maxAbs = Math.max(...result.groups.map(x => Math.abs(x.annual_return)));
                                            const pct = maxAbs > 0 ? Math.abs(g.annual_return) / maxAbs * 100 : 0;
                                            const isPositive = g.annual_return >= 0;
                                            return (
                                                <div key={g.id} className="flex-1 flex flex-col items-center justify-end h-full">
                                                    <span className={`text-[10px] font-mono font-bold mb-1 ${isPositive ? 'text-red-400' : 'text-green-400'}`}>
                                                        {(g.annual_return * 100).toFixed(1)}%
                                                    </span>
                                                    <div
                                                        className="w-full rounded-t-md transition-all"
                                                        style={{
                                                            height: `${Math.max(pct, 5)}%`,
                                                            backgroundColor: GROUP_COLORS[idx % GROUP_COLORS.length],
                                                            opacity: 0.8,
                                                        }}
                                                    />
                                                    <span className="text-[10px] text-slate-400 mt-1">{g.label}</span>
                                                </div>
                                            );
                                        })}
                                    </div>
                                    <div className="text-center mt-2">
                                        <span className={`text-xs font-medium ${result.monotonicity_score >= 0.8 ? 'text-red-400' : result.monotonicity_score >= 0.6 ? 'text-amber-400' : 'text-green-400'}`}>
                                            单调性: {(result.monotonicity_score * 100).toFixed(0)}%
                                            {result.monotonicity_score >= 0.8 ? ' ✅ 优秀' : result.monotonicity_score >= 0.6 ? ' ➖ 尚可' : ' ❌ 较差'}
                                        </span>
                                    </div>
                                </div>

                                {/* 多空净值曲线 */}
                                <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                    <h4 className="text-xs text-slate-400 mb-3 flex items-center gap-1.5">
                                        <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
                                        多空净值曲线
                                        <span className="text-xs text-slate-400">年化: {(result.long_short.annual_return * 100).toFixed(1)}% | 夏普: {result.long_short.sharpe.toFixed(2)} | 回撤: {(result.long_short.max_drawdown * 100).toFixed(1)}%</span>
                                    </h4>
                                    <LongShortChart cumReturns={result.long_short.cum_returns} dates={result.dates} />
                                </div>
                            </div>

                            {/* IC 序列 */}
                            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
                                <h4 className="text-xs text-slate-400 mb-3 flex items-center gap-1.5">
                                    <BarChart3 className="w-3.5 h-3.5 text-amber-400" />
                                    IC 序列
                                    <span className="text-xs text-slate-400">
                                        IC均值: {result.ic_series.ic_mean.toFixed(4)} | ICIR: {result.ic_series.ic_ir.toFixed(2)}
                                    </span>
                                </h4>
                                <IcBarChart values={result.ic_series.values} />
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

/* ── 多空净值 SVG 曲线 ── */
const LongShortChart = ({ cumReturns, _dates }) => {
    if (!cumReturns || cumReturns.length < 2) return null;
    const W = 500, H = 140, PAD = { l: 45, r: 10, t: 10, b: 25 };
    const vals = cumReturns;
    const minV = Math.min(...vals) * 0.98;
    const maxV = Math.max(...vals) * 1.02;
    const range = maxV - minV || 1;
    const sx = (i) => PAD.l + (i / (vals.length - 1)) * (W - PAD.l - PAD.r);
    const sy = (v) => PAD.t + ((maxV - v) / range) * (H - PAD.t - PAD.b);
    const points = vals.map((v, i) => `${sx(i)},${sy(v)}`).join(' ');

    return (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 140 }}>
            {/* 基准线 y=1 */}
            <line x1={PAD.l} y1={sy(1)} x2={W - PAD.r} y2={sy(1)} stroke="#475569" strokeWidth={0.5} strokeDasharray="4 2" />
            <text x={PAD.l - 4} y={sy(1) + 3} textAnchor="end" fill="#64748b" fontSize={9}>1.00</text>
            {/* Y 轴 */}
            {[0.25, 0.5, 0.75].map(pct => {
                const val = maxV - pct * range;
                return <text key={pct} x={PAD.l - 4} y={sy(val) + 3} textAnchor="end" fill="#475569" fontSize={9}>{val.toFixed(2)}</text>;
            })}
            {/* 曲线 */}
            <polyline fill="none" stroke="#10b981" strokeWidth={1.5} points={points} />
            {/* 区域填充 */}
            <polygon
                fill="url(#lsGrad)" opacity={0.15}
                points={`${sx(0)},${sy(1)} ${points} ${sx(vals.length - 1)},${sy(1)}`}
            />
            <defs>
                <linearGradient id="lsGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#10b981" />
                    <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
            </defs>
        </svg>
    );
};

/* ── IC 柱状图 ── */
const IcBarChart = ({ values }) => {
    if (!values || values.length < 2) return null;
    const W = 500, H = 80, PAD = { l: 5, r: 5, t: 5, b: 5 };
    const maxAbs = Math.max(...values.map(Math.abs), 0.05);
    const barW = Math.max(1, (W - PAD.l - PAD.r) / values.length - 0.5);
    const midY = PAD.t + (H - PAD.t - PAD.b) / 2;

    return (
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 80 }}>
            <line x1={PAD.l} y1={midY} x2={W - PAD.r} y2={midY} stroke="#475569" strokeWidth={0.5} />
            {values.map((v, i) => {
                const x = PAD.l + (i / values.length) * (W - PAD.l - PAD.r);
                const h = Math.abs(v) / maxAbs * ((H - PAD.t - PAD.b) / 2);
                const y = v >= 0 ? midY - h : midY;
                return (
                    <rect key={i} x={x} y={y} width={barW} height={Math.max(h, 0.5)}
                        fill={v >= 0 ? '#10b981' : '#ef4444'} opacity={0.7} rx={0.5} />
                );
            })}
        </svg>
    );
};

export default FactorResearchSection;
