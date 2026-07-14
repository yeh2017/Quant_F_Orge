import { BarChart3, ChevronDown } from 'lucide-react';

/**
 * IC 衰减曲线图
 * 从 FactorPanel 提取，SVG 手绘的多因子 IC 衰减折线图
 */
const IcDecayChart = ({
    icDecayData,
    icDecayLoading,
    showIcDecay,
    onToggle,
}) => {
    return (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
            <button onClick={onToggle}
                className="w-full flex items-center justify-between text-sm font-semibold text-slate-300">
                <div className="flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-violet-400" />
                    IC 衰减曲线
                    <span className="text-xs text-slate-500 font-normal">因子预测力随持有期的变化</span>
                </div>
                {icDecayLoading
                    ? <div className="w-4 h-4 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
                    : <ChevronDown className={`w-4 h-4 text-slate-500 transition-transform ${showIcDecay ? 'rotate-180' : ''}`} />
                }
            </button>
            {showIcDecay && icDecayData && (() => {
                const { horizons, factors } = icDecayData;
                const keys = Object.keys(factors);
                if (keys.length === 0) return <div className="text-slate-500 text-xs text-center py-4 mt-3">无数据</div>;

                const COLORS = ['#10b981', '#6366f1', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6', '#14b8a6', '#f97316', '#84cc16', '#e879f9', '#22d3ee'];
                const W = 600, H = 260, PAD_L = 50, PAD_R = 20, PAD_T = 20, PAD_B = 40;

                const allIcs = keys.flatMap(k => factors[k].ics.filter(v => v !== null));
                const minIC = Math.min(...allIcs, -0.1);
                const maxIC = Math.max(...allIcs, 0.1);
                const range = maxIC - minIC || 0.2;
                const scaleX = (i) => PAD_L + (i / (horizons.length - 1)) * (W - PAD_L - PAD_R);
                const scaleY = (v) => PAD_T + ((maxIC - v) / range) * (H - PAD_T - PAD_B);

                return (
                    <div className="mt-3">
                        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ maxHeight: 260 }}>
                            {/* 零线 */}
                            {minIC < 0 && maxIC > 0 && (
                                <line x1={PAD_L} y1={scaleY(0)} x2={W - PAD_R} y2={scaleY(0)} stroke="#475569" strokeWidth={0.5} strokeDasharray="4 2" />
                            )}
                            {/* X轴标签 */}
                            {horizons.map((h, i) => (
                                <text key={h} x={scaleX(i)} y={H - 10} textAnchor="middle" fill="#94a3b8" fontSize={11}>{h}日</text>
                            ))}
                            {/* Y轴 */}
                            {[0.25, 0.5, 0.75].map(pct => {
                                const val = maxIC - pct * range;
                                const y = PAD_T + pct * (H - PAD_T - PAD_B);
                                return (
                                    <g key={pct}>
                                        <line x1={PAD_L} y1={y} x2={W - PAD_R} y2={y} stroke="#334155" strokeWidth={0.5} />
                                        <text x={PAD_L - 4} y={y + 4} textAnchor="end" fill="#64748b" fontSize={10}>{val.toFixed(2)}</text>
                                    </g>
                                );
                            })}
                            {/* 因子曲线 */}
                            {keys.map((k, idx) => {
                                const ics = factors[k].ics;
                                const points = ics.map((v, i) => v !== null ? `${scaleX(i)},${scaleY(v)}` : null).filter(Boolean);
                                if (points.length < 2) return null;
                                return (
                                    <g key={k}>
                                        <polyline fill="none" stroke={COLORS[idx % COLORS.length]} strokeWidth={2} opacity={0.85} points={points.join(' ')} />
                                        {ics.map((v, i) => v !== null && (
                                            <circle key={i} cx={scaleX(i)} cy={scaleY(v)} r={3} fill={COLORS[idx % COLORS.length]} />
                                        ))}
                                    </g>
                                );
                            })}
                        </svg>
                        {/* 图例 */}
                        <div className="flex flex-wrap gap-3 mt-1">
                            {keys.map((k, i) => (
                                <div key={k} className="flex items-center gap-1.5 text-[11px] text-slate-300">
                                    <span className="w-3 h-1 rounded" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                                    {factors[k].label}
                                </div>
                            ))}
                        </div>
                        <div className="text-[10px] text-white/50 mt-2">
                            截面日: {icDecayData.snapshot_date} · 股票数: {icDecayData.stock_count} · Y轴=Rank IC（正=有效）
                        </div>
                    </div>
                );
            })()}
        </div>
    );
};

export default IcDecayChart;
