
import { makePoolItem } from '../../utils/poolActions';

// ── 大盘市场状态条 ──
const MarketRegimeBar = ({ regime }) => {
    if (!regime || regime.regime === '未知') return null;

    const colorMap = {
        green: { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', bar: 'bg-green-500' },
        emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', bar: 'bg-emerald-500' },
        amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', bar: 'bg-amber-500' },
        orange: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', bar: 'bg-orange-500' },
        red: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', bar: 'bg-red-500' },
        slate: { bg: 'bg-slate-500/10', border: 'border-slate-500/30', text: 'text-slate-400', bar: 'bg-slate-500' },
    };
    const c = colorMap[regime.regime_color] || colorMap.slate;
    const dims = regime.dimensions || {};

    return (
        <div className={`${c.bg} ${c.border} border rounded-xl p-4 flex items-center gap-6`}>
            <div className="flex items-center gap-2 shrink-0">
                <span className="text-lg">{regime.regime_icon}</span>
                <div>
                    <div className={`text-lg font-bold ${c.text}`}>{regime.regime}</div>
                    <div className="text-xs text-white/80">{regime.trade_date}</div>
                </div>
            </div>
            <div className="shrink-0 text-center">
                <div className={`text-2xl font-black font-mono ${c.text}`}>{regime.composite_score}</div>
                <div className="text-xs text-white/80">综合分</div>
            </div>
            <div className="w-px h-10 bg-slate-700/50 shrink-0" />
            <div className="flex-1 grid grid-cols-3 gap-4">
                {Object.entries(dims).map(([key, dim]) => (
                    <div key={key}>
                        <div className="flex items-center justify-between mb-1">
                            <span className="text-sm text-white/90">{dim.label}</span>
                            <span className={`text-xs font-mono font-bold ${dim.score >= 55 ? 'text-green-400' : dim.score >= 45 ? 'text-amber-400' : 'text-red-400'}`}>
                                {dim.score}
                            </span>
                        </div>
                        <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                            <div
                                className={`h-full rounded-full transition-all duration-500 ${dim.score >= 55 ? 'bg-green-500' : dim.score >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                                style={{ width: `${Math.min(100, Math.max(0, dim.score))}%` }}
                            />
                        </div>
                        <div className="text-xs text-white/80 mt-0.5">{dim.detail}</div>
                    </div>
                ))}
            </div>
        </div>
    );
};

// ── 个股弱转强/强转弱反转信号 ──
const StockReversalCards = ({ stockReversal, customStocks, setCustomStocks, onViewKline }) => {
    if (!stockReversal) return null;
    if (!stockReversal.weak_to_strong?.length && !stockReversal.strong_to_weak?.length) return null;

    const ReversalHalf = ({ title, items, titleColor, bgClass, borderClass }) => (
        <div className={`${bgClass} ${borderClass} border rounded-xl p-3`}>
            <h3 className={`text-sm font-bold ${titleColor} mb-2 flex items-center gap-1.5`}>
                {title}
            </h3>
            <div className="space-y-0.5">
                {(items || []).map(s => {
                    const inPool = customStocks.some(cs => cs.code === s.code);
                    return (
                        <div key={s.code} className="flex items-center justify-between bg-slate-800/40 rounded-lg px-3 py-1 hover:bg-slate-700/40 transition-colors">
                            <div className="flex items-center gap-2 min-w-0">
                                <div className="truncate">
                                    <span className="text-white font-medium text-sm">{s.name}</span>
                                    <span className="text-xs text-white/80 ml-1.5 font-mono">{s.code}</span>
                                </div>
                                {s.industry && <span className="text-[11px] px-1.5 py-0.5 rounded bg-slate-700/60 text-white/80 shrink-0">{s.industry}</span>}
                            </div>
                            <div className="flex items-center gap-3 shrink-0">
                                <div className="text-right">
                                    <div className="text-[10px] text-slate-500">5日 <span className={`${s.pct_5d > 0 ? 'text-red-400' : s.pct_5d < 0 ? 'text-green-400' : 'text-slate-400'} font-mono`}>{s.pct_5d > 0 ? '+' : ''}{s.pct_5d}%</span></div>
                                    <div className="text-[10px] text-slate-500">今日 <span className={`${s.pct_today > 0 ? 'text-red-400' : s.pct_today < 0 ? 'text-green-400' : 'text-slate-400'} font-mono font-bold`}>{s.pct_today > 0 ? '+' : ''}{s.pct_today}%</span></div>
                                </div>
                                {onViewKline && <button onClick={() => onViewKline(s.code)} className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all" title={`查看 ${s.name} K线图`}>📈</button>}
                                <button onClick={() => inPool ? setCustomStocks(prev => prev.filter(cs => cs.code !== s.code)) : setCustomStocks(prev => [...prev, makePoolItem(s.code, s.name, { industry: s.industry || '' })])}
                                    className={`text-[10px] px-1.5 py-1 rounded border transition-all ${inPool ? 'bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30' : 'bg-emerald-600/30 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/50'}`}
                                    title={inPool ? '点击移出自选池' : '加入自选池'}>{inPool ? '✓' : '➕'}</button>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );

    return (
        <div className="grid grid-cols-2 gap-4">
            <ReversalHalf
                title={`⚡ 个股弱转强 Top${stockReversal.weak_to_strong?.length || 0}`}
                items={stockReversal.weak_to_strong}
                titleColor="text-red-400"
                bgClass="bg-red-500/5" borderClass="border-red-500/20" />
            <ReversalHalf
                title={`⚠️ 个股强转弱 Top${stockReversal.strong_to_weak?.length || 0}`}
                items={stockReversal.strong_to_weak}
                titleColor="text-green-400"
                bgClass="bg-green-500/5" borderClass="border-green-500/20" />
        </div>
    );
};

const MarketOverview = ({ regime, stockReversal, customStocks, setCustomStocks, onViewKline }) => (
    <>
        <MarketRegimeBar regime={regime} />
        <StockReversalCards stockReversal={stockReversal} customStocks={customStocks} setCustomStocks={setCustomStocks} onViewKline={onViewKline} />
    </>
);

export default MarketOverview;
