import { useMemo } from 'react';

const CATEGORY_LABELS = {
    return: { label: '📈 收益类', color: 'text-emerald-400' },
    fundamental: { label: '📊 基本面类', color: 'text-blue-400' },
    risk: { label: '🛡️ 风险类', color: 'text-amber-400' },
};

/**
 * 因子卡片网格 — 选择因子 + 调权重
 * 从 FactorPanel 提取，负责因子选择与权重编辑的 UI 交互
 */
const FactorCardGrid = ({
    factors,
    selectedFactors,
    setSelectedFactors,
    factorWeights,
    setFactorWeights,
    showWeightPanel,
    setShowWeightPanel,
}) => {
    // 按 category 分组（保持组内权重降序）
    const grouped = useMemo(() => {
        const groups = {};
        for (const f of factors) {
            const cat = f.category || 'other';
            if (!groups[cat]) groups[cat] = [];
            groups[cat].push(f);
        }
        // 固定顺序: return → fundamental → risk → other
        const order = ['return', 'fundamental', 'risk', 'other'];
        return order.filter(k => groups[k]).map(k => ({ key: k, factors: groups[k] }));
    }, [factors]);

    return (
        <>
            <div className="flex items-center justify-end gap-2 mb-4">
                <button onClick={() => setSelectedFactors(Object.fromEntries(factors.map(f => [f.key, true])))}
                    className="text-[11px] px-2.5 py-1 rounded-lg bg-indigo-900/40 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-800/50 transition-all font-medium">
                    全选
                </button>
                <button onClick={() => setSelectedFactors(Object.fromEntries(factors.map(f => [f.key, false])))}
                    className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800/60 text-slate-400 border border-slate-600/50 hover:bg-slate-700/60 transition-all font-medium">
                    全不选
                </button>
                <button onClick={() => setShowWeightPanel(v => !v)}
                    className={`text-[11px] px-2.5 py-1 rounded-lg border transition-all font-medium ${
                        showWeightPanel ? 'bg-amber-900/40 text-amber-300 border-amber-500/30' : 'bg-slate-800/60 text-slate-400 border-slate-600/50 hover:bg-slate-700/60'
                    }`}>
                    ⚖️ 调权重
                </button>
            </div>

            {grouped.map(group => {
                const catInfo = CATEGORY_LABELS[group.key] || { label: '其他', color: 'text-slate-400' };
                return (
                    <div key={group.key} className="mb-5">
                        <h4 className={`text-xs font-semibold mb-3 ${catInfo.color} tracking-wide`}>{catInfo.label}</h4>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-2">
                {group.factors.map((factor, idx) => {
                    const isSelected = selectedFactors[factor.key];
                    return (
                        <div key={idx}
                            onClick={() => setSelectedFactors({ ...selectedFactors, [factor.key]: !isSelected })}
                            className={`group relative p-5 rounded-2xl cursor-pointer border-2 transition-all duration-300 overflow-hidden ${isSelected
                                ? 'bg-indigo-900/40 border-indigo-500 shadow-[0_0_15px_rgba(99,102,241,0.15)] backdrop-blur-sm'
                                : 'bg-slate-800/50 border-slate-700/50 hover:bg-slate-750 hover:border-slate-500/50 backdrop-blur-sm'}`}>

                            {/* 选中态顶部发光条 */}
                            <div className={`absolute top-0 left-0 right-0 h-1 transition-all duration-500 ${isSelected ? 'bg-gradient-to-r from-indigo-400 to-purple-500 opacity-100' : 'opacity-0'}`} />

                            <div className="flex items-center justify-between mb-3 relative z-10">
                                <div className="flex items-center gap-2">
                                    <span className={`font-bold text-lg tracking-wide ${isSelected ? 'text-white' : 'text-slate-200 group-hover:text-indigo-100 transition-colors'}`}>{factor.name}</span>
                                </div>
                                <div className={`w-5 h-5 rounded border flex items-center justify-center transition-all ${isSelected ? 'bg-indigo-500 border-indigo-400 shadow-[0_0_8px_rgba(99,102,241,0.6)]' : 'border-slate-500 group-hover:border-slate-400'}`}>
                                    {isSelected && <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" /></svg>}
                                </div>
                            </div>

                            <div className={`text-sm mb-3 leading-relaxed ${isSelected ? 'text-slate-200' : 'text-slate-400'}`}>{factor.desc}</div>

                            <div className="flex flex-wrap gap-1.5 relative z-10">
                                {factor.items.map((item, i) => (
                                    <span key={i} className={`text-[11px] px-2.5 py-1 rounded-full border ${isSelected ? 'bg-white/10 border-white/20 text-white/90' : 'bg-slate-800/60 border-slate-600/50 text-slate-300 group-hover:text-slate-200 transition-colors'}`}>
                                        {item}
                                    </span>
                                ))}
                            </div>

                            {/* 权重滑块 */}
                            {showWeightPanel && (
                                <div className="mt-3 pt-3 border-t border-slate-700/50 relative z-20" onClick={e => e.stopPropagation()}>
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-[10px] text-slate-400">权重</span>
                                        <span className={`text-xs font-mono font-bold ${isSelected ? 'text-indigo-300' : 'text-slate-500'}`}>
                                            {Math.round((factorWeights[factor.key] || 0) * 100)}%
                                        </span>
                                    </div>
                                    <input
                                        type="range" min="0" max="50" step="1"
                                        value={Math.round((factorWeights[factor.key] || 0) * 100)}
                                        onChange={e => {
                                            const val = parseInt(e.target.value) / 100;
                                            setFactorWeights(prev => ({ ...prev, [factor.key]: val }));
                                        }}
                                        className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                                        style={{
                                            background: `linear-gradient(to right, #6366f1 ${Math.round((factorWeights[factor.key] || 0) * 200)}%, #334155 ${Math.round((factorWeights[factor.key] || 0) * 200)}%)`,
                                        }}
                                    />
                                </div>
                            )}

                            {isSelected && (
                                <div className="absolute -inset-2 bg-indigo-500/5 blur-xl block -z-10 rounded-3xl pointer-events-none"></div>
                            )}
                        </div>
                    );
                })}
                        </div>
                    </div>
                );
            })}
        </>
    );
};

export default FactorCardGrid;
