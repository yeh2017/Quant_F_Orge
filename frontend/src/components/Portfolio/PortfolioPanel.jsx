import { useState, useEffect, useRef } from 'react';
import { Target, RefreshCw, Zap, AlertTriangle } from 'lucide-react';
import { portfolioOptApi } from '../../services/api';
import { fmtPct } from '../../utils/format';
import { TRADING_DAY_PRESETS } from '../../utils/dateUtils';
import LookbackSelector from '../shared/LookbackSelector';



const METHODS = [
    { id: 'max_sharpe', name: '最大夏普', desc: '收益/风险比最优' },
    { id: 'risk_parity', name: '风险平价', desc: '各股风险贡献相等' },
    { id: 'min_variance', name: '最小方差', desc: '组合波动最小' },
    { id: 'equal_weight', name: '等权配置', desc: '均匀分配权重' },
];

const PortfolioPanel = ({
    backtestPortfolio,
    customStocks = [],
    onViewKline,
    setAlerts = () => {},
}) => {
    const [allResults, setAllResults] = useState(null);  // { max_sharpe: {...}, risk_parity: {...}, ... }
    const [selectedMethod, setSelectedMethod] = useState('max_sharpe');
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [lookbackDays, setLookbackDays] = useState(252);
    const [dataRangeInfo, setDataRangeInfo] = useState(null);

    // 回测结果注入：backtestPortfolio 已是 {max_sharpe: {...}, ...} 完整 map
    useEffect(() => {
        if (backtestPortfolio) setAllResults(backtestPortfolio);
    }, [backtestPortfolio]);

    const portfolio = allResults?.[selectedMethod] || null;

    const runOptimizeAll = async () => {
        const codes = customStocks.map(s => s.code);
        if (!codes.length) {
            setError('请先在自定义池中添加股票');
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const stockNames = Object.fromEntries(customStocks.map(s => [s.code, s.name || s.code]));
            const res = await portfolioOptApi.optimizeAll(codes, lookbackDays, stockNames);
            if (res?.results) {
                setAllResults(res.results);
                setAlerts([{ type: 'success', msg: '✓ 4 种组合优化方法计算完成' }]);
                // 数据充足性反馈
                const firstResult = Object.values(res.results).find(r => !r.error);
                if (firstResult?.actual_data_points != null) {
                    setDataRangeInfo({
                        actualDays: firstResult.actual_data_points,
                        requestedDays: lookbackDays,
                        sufficient: firstResult.actual_data_points >= lookbackDays * 0.8,
                    });
                }
            }
        } catch (e) {
            setError(e.message || '组合优化失败');
        }
        setLoading(false);
    };

    return (
        <div className="space-y-6">
            <div className="mb-6">
                <div className="flex items-center justify-between">
                    <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                        <div className="p-2.5 bg-indigo-500/20 rounded-xl border border-indigo-500/30">
                            <Target className="w-6 h-6 text-indigo-400" />
                        </div>
                        组合优化
                        <span className="text-sm font-normal text-slate-500 ml-1">一键对比 4 种方法 — 点击行查看持仓</span>
                    </h2>
                    <div className="flex items-center gap-3">
                        <LookbackSelector
                            presets={TRADING_DAY_PRESETS}
                            value={lookbackDays}
                            onChange={d => { setLookbackDays(d); setDataRangeInfo(null); }}
                            activeColor="bg-indigo-600"
                            unit="交易日"
                        />
                        <button onClick={() => runOptimizeAll()} disabled={loading}
                            className="flex items-center gap-2 px-4 py-2 bg-indigo-600/30 hover:bg-indigo-600/50 border border-indigo-500/40 text-indigo-200 rounded-lg text-sm font-medium transition-all disabled:opacity-50">
                            {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                            {loading ? '4种方法计算中…' : '基于自选池优化（4种方法）'}
                        </button>
                    </div>
                </div>
            </div>

            {/* 数据充足性提示 */}
            {dataRangeInfo && (
                <div className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-2 ${
                    dataRangeInfo.sufficient
                        ? 'bg-slate-800/30 border-slate-700/30 text-slate-400'
                        : 'bg-amber-900/20 border-amber-500/30 text-amber-400'
                }`}>
                    <span>实际数据: {dataRangeInfo.actualDays}个交易日</span>
                    <span>(请求 {dataRangeInfo.requestedDays} 个交易日)</span>
                    {!dataRangeInfo.sufficient && (
                        <span className="font-medium">⚠️ 数据不足</span>
                    )}
                </div>
            )}

            {error && (
                <div className="flex items-center gap-2 p-3 bg-red-900/30 border border-red-500/40 rounded-lg text-red-300 text-sm">
                    <AlertTriangle className="w-4 h-4" /> {error}
                </div>
            )}

            {!allResults && !loading && (
                <div className="text-center py-12">
                    <Target className="w-16 h-16 text-indigo-400 mx-auto mb-4 opacity-30" />
                    <p className="text-slate-400 mb-2">尚无组合数据</p>
                    <p className="text-slate-500 text-sm">点击「基于自选池优化」一键计算 4 种方法</p>
                </div>
            )}

            {allResults && (
                <>
                    {/* 4 方法对比表 */}
                    <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 overflow-x-auto">
                        <h3 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
                            <Target className="w-4 h-4 text-indigo-400" /> 4 种方法对比
                        </h3>
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="text-slate-400 border-b border-slate-700/50 text-xs uppercase tracking-wider">
                                    <th className="text-left py-2 px-2">方法</th>
                                    <th className="text-right py-2 px-2">预期年化</th>
                                    <th className="text-right py-2 px-2">年化波动</th>
                                    <th className="text-right py-2 px-2">夏普比率</th>
                                    <th className="text-right py-2 px-2">分散化</th>
                                    <th className="text-right py-2 px-2">持仓数</th>
                                </tr>
                            </thead>
                            <tbody>
                                {METHODS.map(m => {
                                    const r = allResults[m.id];
                                    if (!r || r.error) return (
                                        <tr key={m.id} className="border-b border-slate-800/50 opacity-50">
                                            <td className="py-2 px-2 text-slate-500">{m.name}</td>
                                            <td colSpan={5} className="py-2 px-2 text-center text-rose-400 text-[10px]">{r?.error || '无数据'}</td>
                                        </tr>
                                    );
                                    const isSel = selectedMethod === m.id;
                                    const retColor = (r.expectedReturn || 0) >= 0 ? 'text-red-400' : 'text-green-400';
                                    const sharpeColor = (r.sharpeRatio || 0) >= 1 ? 'text-red-400' : (r.sharpeRatio || 0) >= 0 ? 'text-sky-400' : 'text-green-400';
                                    const validHoldings = (r.holdings || []).filter(h => (h.weight || 0) > 0.005).length;
                                    return (
                                        <tr key={m.id}
                                            onClick={() => setSelectedMethod(m.id)}
                                            className={`border-b border-slate-800/50 cursor-pointer transition-all ${isSel ? 'bg-indigo-900/30' : 'hover:bg-slate-800/40'}`}>
                                            <td className="py-2.5 px-2">
                                                <div className="flex items-center gap-2">
                                                    <div className={`w-2 h-2 rounded-full ${isSel ? 'bg-indigo-400' : 'bg-slate-600'}`} />
                                                    <span className={`font-bold text-sm ${isSel ? 'text-white' : 'text-slate-300'}`}>{m.name}</span>
                                                    <span className="text-xs text-slate-500">{m.desc}</span>
                                                </div>
                                            </td>
                                            <td className={`text-right py-2 px-2 font-mono font-bold ${retColor}`}>
                                                {((r.expectedReturn || 0) * 100).toFixed(2)}%
                                            </td>
                                            <td className="text-right py-2 px-2 font-mono text-amber-400">
                                                {((r.portfolioRisk || 0) * 100).toFixed(2)}%
                                            </td>
                                            <td className={`text-right py-2 px-2 font-mono font-bold ${sharpeColor}`}>
                                                {r.sharpeRatio?.toFixed(2) || '-'}
                                            </td>
                                            <td className="text-right py-2 px-2 font-mono text-fuchsia-400">
                                                {r.diversification?.toFixed(2) || '-'}
                                            </td>
                                            <td className="text-right py-2 px-2 font-mono text-slate-300">
                                                {validHoldings}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>

                    {/* 当前方法的持仓分布 */}
                    {portfolio && portfolio.holdings?.length > 0 && (
                        <div className="bg-slate-800/40 backdrop-blur-sm border border-slate-700/50 p-4 rounded-xl mt-2">
                            <h3 className="text-white font-semibold mb-3 flex items-center gap-2 text-sm">
                                <div className="w-1.5 h-1.5 rounded-full bg-indigo-400"></div>
                                优化后持仓分布
                                <span className="text-xs text-slate-400 ml-2">单只上限 30%</span>
                            </h3>
                            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2.5">
                                {portfolio.holdings.map((h, i) => (
                                    <div key={i} className="bg-slate-800/60 backdrop-blur-sm border border-slate-700/50 p-3 rounded-xl hover:border-indigo-500/40 transition-all duration-300 group overflow-hidden relative flex flex-col justify-between shadow-sm">
                                        <div
                                            className="absolute left-0 bottom-0 top-0 bg-gradient-to-r from-indigo-500/10 to-purple-500/20 z-0 transition-all duration-500 rounded-r-3xl"
                                            style={{ width: `${((h.weight || 0) * 100).toFixed(1)}%` }}
                                        />
                                        <div className="relative z-10 flex items-start justify-between mb-1.5">
                                            <div className="flex flex-col gap-0.5">
                                                <span className="text-slate-100 font-bold text-sm tracking-wide">{h.name || h.code}</span>
                                                <span className="text-slate-400 font-mono text-[10px] tracking-widest bg-slate-900/40 px-1 py-0.5 rounded border border-slate-700/30 w-fit">{h.code}</span>
                                            </div>
                                            <div className="flex items-center gap-1.5">
                                                {onViewKline && (
                                                    <button onClick={() => onViewKline(h.code)}
                                                        className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all z-20"
                                                        title={`查看 ${h.name || h.code} K线`}>
                                                        📈
                                                    </button>
                                                )}
                                                <div className="flex flex-col items-end">
                                                    <span className="text-indigo-300 font-black text-base tracking-tight">{((h.weight || 0) * 100).toFixed(1)}%</span>
                                                    <span className="text-slate-400 text-xs font-medium">配置权重</span>
                                                </div>
                                            </div>
                                        </div>
                                        <div className="relative z-10 flex items-center justify-between gap-2 mt-1 pt-2 border-t border-slate-700/30">
                                            <div className={`flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md bg-slate-900/30 border border-slate-700/30 ${(h.expectedReturn || 0) >= 0 ? 'text-red-400' : 'text-green-400'}`}>
                                                <span className="opacity-60 text-[10px] font-normal">预期收益</span>
                                                {((h.expectedReturn || 0) * 100).toFixed(1)}%
                                            </div>
                                            <div className="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md bg-slate-900/30 border border-slate-700/30 text-amber-400">
                                                <span className="opacity-60 text-[10px] font-normal">波动风险</span>
                                                {((h.risk || 0) * 100).toFixed(1)}%
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}



                    {/* 再平衡模拟 */}
                    <RebalanceSimSection codes={customStocks.map(s => s.code)} method={selectedMethod} setAlerts={setAlerts} />
                </>
            )}
        </div>
    );
};

/* ── 再平衡模拟子组件 ── */
const RebalanceSimSection = ({ codes, method, setAlerts }) => {
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [period, setPeriod] = useState('monthly');
    const [show, setShow] = useState(false);
    const [hoverIdx, setHoverIdx] = useState(null);

    const run = async () => {
        if (!codes?.length || codes.length < 2) {
            setAlerts([{ type: 'warning', msg: '至少需要2只股票' }]);
            return;
        }
        setLoading(true); setResult(null);
        try {
            const res = await portfolioOptApi.rebalanceSim(codes, { method, period });
            if (res.status === 'success') {
                setResult(res);
                setShow(true);
            } else {
                setAlerts([{ type: 'error', msg: res.detail || '模拟失败' }]);
            }
        } catch (e) {
            setAlerts([{ type: 'error', msg: `再平衡模拟失败: ${e.message}` }]);
        }
        setLoading(false);
    };

    const fmt = (v) => fmtPct(v, 2, '--');

    return (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                    <RefreshCw className="w-4 h-4 text-violet-400" />
                    再平衡模拟
                </h3>
                <div className="flex items-center gap-2">
                    <select value={period} onChange={e => setPeriod(e.target.value)}
                        className="bg-slate-800 border border-slate-600/50 rounded-lg px-2 py-1 text-xs text-white">
                        <option value="monthly">月度调仓</option>
                        <option value="quarterly">季度调仓</option>
                    </select>
                    <button onClick={run} disabled={loading}
                        className="px-4 py-1.5 rounded-lg text-xs font-bold bg-gradient-to-r from-violet-600 to-purple-600 text-white hover:opacity-90 disabled:opacity-50 flex items-center gap-1.5">
                        {loading ? <><div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" /> 模拟中...</> : <><Zap className="w-3.5 h-3.5" /> 运行模拟</>}
                    </button>
                </div>
            </div>

            {show && result && (() => {
                const { net_values, benchmark, dates, turnovers, total_cost, rebalance_count } = result;
                if (!net_values?.length) return <div className="text-slate-500 text-xs text-center py-4">无数据</div>;

                const W = 700, H = 250, PAD = 45;
                const allVals = [...net_values, ...benchmark];
                const minV = Math.min(...allVals) * 0.98;
                const maxV = Math.max(...allVals) * 1.02;
                const scaleX = (i) => PAD + (i / (net_values.length - 1)) * (W - PAD * 2);
                const scaleY = (v) => H - PAD - ((v - minV) / (maxV - minV || 1)) * (H - PAD * 2);

                const avgTurnover = turnovers.length > 0 ? (turnovers.reduce((a, b) => a + b, 0) / turnovers.length).toFixed(1) : 0;
                const finalReturn = ((net_values[net_values.length - 1] - 1) * 100).toFixed(2);
                const benchReturn = ((benchmark[benchmark.length - 1] - 1) * 100).toFixed(2);

                return (
                    <div className="space-y-3">
                        {/* 统计卡片 */}
                        <div className="grid grid-cols-4 gap-2">
                            {[
                                { label: '策略收益', value: `${finalReturn}%`, color: Number(finalReturn) >= 0 ? 'text-red-400' : 'text-green-400' },
                                { label: '等权基准', value: `${benchReturn}%`, color: Number(benchReturn) >= 0 ? 'text-red-400' : 'text-green-400' },
                                { label: '累计成本', value: fmt(total_cost), color: 'text-amber-400' },
                                { label: `调仓${rebalance_count}次`, value: `均换${avgTurnover}%`, color: 'text-violet-400' },
                            ].map((c, i) => (
                                <div key={i} className="bg-slate-900/50 rounded-lg px-3 py-2 text-center">
                                    <div className="text-xs text-slate-300 font-medium">{c.label}</div>
                                    <div className={`text-lg font-bold font-mono ${c.color}`}>{c.value}</div>
                                </div>
                            ))}
                        </div>

                        {/* 净值曲线 */}
                        <svg viewBox={`0 0 ${W} ${H + 30}`} className="w-full" style={{ maxHeight: 280 }}
                            onMouseMove={e => {
                                const rect = e.currentTarget.getBoundingClientRect();
                                const px = (e.clientX - rect.left) / rect.width * W;
                                const idx = Math.round((px - PAD) / (W - PAD * 2) * (net_values.length - 1));
                                if (idx >= 0 && idx < net_values.length) setHoverIdx(idx);
                            }}
                            onMouseLeave={() => setHoverIdx(null)}>
                            {/* 1.0 基准线 */}
                            <line x1={PAD} y1={scaleY(1)} x2={W - PAD} y2={scaleY(1)} stroke="#475569" strokeWidth={1} strokeDasharray="6 3" />
                            <text x={PAD - 4} y={scaleY(1) + 4} textAnchor="end" fill="#94a3b8" fontSize={10} fontWeight="bold">1.00</text>

                            {/* Y 轴网格 + 百分比标签 */}
                            {[0.25, 0.5, 0.75].map(pct => {
                                const y = PAD + pct * (H - PAD * 2);
                                const val = maxV - pct * (maxV - minV);
                                const pctLabel = ((val - 1) * 100).toFixed(0);
                                return (
                                    <g key={pct}>
                                        <line x1={PAD} y1={y} x2={W - PAD} y2={y} stroke="#334155" strokeWidth={0.5} />
                                        <text x={PAD - 4} y={y + 4} textAnchor="end" fill="#64748b" fontSize={10}>
                                            {pctLabel >= 0 ? '+' : ''}{pctLabel}%
                                        </text>
                                    </g>
                                );
                            })}

                            {/* X 轴日期标签 */}
                            {dates && [0, 0.25, 0.5, 0.75, 1].map(pct => {
                                const idx = Math.min(Math.round(pct * (dates.length - 1)), dates.length - 1);
                                const x = scaleX(idx);
                                return (
                                    <text key={pct} x={x} y={H - PAD + 16} textAnchor="middle" fill="#64748b" fontSize={10}>
                                        {dates[idx]?.slice(0, 7) || ''}
                                    </text>
                                );
                            })}

                            {/* 等权基准 */}
                            <polyline fill="none" stroke="#475569" strokeWidth={1.5} strokeDasharray="4 2"
                                points={benchmark.map((v, i) => `${scaleX(i)},${scaleY(v)}`).join(' ')} />
                            {/* 策略净值 */}
                            <polyline fill="none" stroke="#8b5cf6" strokeWidth={2.5}
                                points={net_values.map((v, i) => `${scaleX(i)},${scaleY(v)}`).join(' ')} />

                            {/* 悬停交互 */}
                            {hoverIdx !== null && hoverIdx >= 0 && hoverIdx < net_values.length && (
                                <g>
                                    <line x1={scaleX(hoverIdx)} y1={PAD} x2={scaleX(hoverIdx)} y2={H - PAD}
                                        stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 2" />
                                    <circle cx={scaleX(hoverIdx)} cy={scaleY(net_values[hoverIdx])} r={4}
                                        fill="#8b5cf6" stroke="#fff" strokeWidth={1.5} />
                                    <circle cx={scaleX(hoverIdx)} cy={scaleY(benchmark[hoverIdx])} r={3}
                                        fill="#475569" stroke="#fff" strokeWidth={1} />
                                    <rect x={scaleX(hoverIdx) - 70} y={PAD - 8} width={140} height={48}
                                        rx={6} fill="#0f172a" stroke="#334155" strokeWidth={1} opacity={0.95} />
                                    <text x={scaleX(hoverIdx)} y={PAD + 6} textAnchor="middle" fill="#94a3b8" fontSize={10}>
                                        {dates?.[hoverIdx] || `Day ${hoverIdx}`}
                                    </text>
                                    <text x={scaleX(hoverIdx)} y={PAD + 20} textAnchor="middle" fill="#8b5cf6" fontSize={11} fontWeight="bold">
                                        策略 {((net_values[hoverIdx] - 1) * 100).toFixed(2)}%
                                    </text>
                                    <text x={scaleX(hoverIdx)} y={PAD + 34} textAnchor="middle" fill="#64748b" fontSize={10}>
                                        基准 {((benchmark[hoverIdx] - 1) * 100).toFixed(2)}%
                                    </text>
                                </g>
                            )}
                        </svg>
                        <div className="flex gap-6 text-xs mt-1">
                            <div className="flex items-center gap-2 text-violet-400 font-medium"><span className="w-4 h-1 rounded bg-violet-500" />再平衡策略</div>
                            <div className="flex items-center gap-2 text-slate-400"><span className="w-4 h-0.5 rounded border-t-2 border-dashed border-slate-500" />等权基准</div>
                            <div className="flex items-center gap-2 text-slate-500"><span className="w-4 h-0.5 rounded border-t border-dashed border-slate-600" />初始净值 1.0</div>
                        </div>
                    </div>
                );
            })()}
        </div>
    );
};

export default PortfolioPanel;
