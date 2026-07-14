import { BarChart3, ChevronDown, ChevronUp } from 'lucide-react';

/**
 * 因子 IC 归因分析面板
 * 从 FactorPanel 提取，展示 Rank IC 分析结果和推荐权重
 */
const IcAnalysisPanel = ({
    icData,
    icLoading,
    showIcSection,
    setShowIcSection,
    onRunAnalysis,
    setSelectedFactors,
    setFactorWeights,
    setShowWeightPanel,
}) => {
    return (
        <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl shadow-sm">
            <button onClick={() => setShowIcSection(!showIcSection)}
                className="w-full p-5 flex items-center justify-between text-left">
                <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-amber-400" />
                    因子绩效归因
                    <span className="text-xs text-slate-400 font-normal">Rank IC 分析 · 科学调权</span>
                </h3>
                <div className="flex items-center gap-2">
                    {showIcSection ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
                </div>
            </button>

            {showIcSection && (
                <div className="px-5 pb-5">
                    <button onClick={onRunAnalysis} disabled={icLoading}
                        className="text-xs px-4 py-1.5 rounded-lg bg-amber-900/30 text-amber-300 border border-amber-500/30 hover:bg-amber-800/40 transition-all font-medium disabled:opacity-50 flex items-center gap-1.5 mb-4">
                        {icLoading ? (
                            <><div className="w-3 h-3 border-2 border-amber-300/30 border-t-amber-300 rounded-full animate-spin" /> 分析中...</>
                        ) : (
                            <><BarChart3 className="w-3.5 h-3.5" /> 运行归因分析</>
                        )}
                    </button>

                    {icData?.error && (
                        <div className="text-xs text-rose-400 bg-rose-900/20 border border-rose-500/30 rounded-lg p-3">
                            {icData.error}
                        </div>
                    )}

                    {icData?.factors && (
                        <>
                            <div className="text-xs text-slate-400 mb-3 flex items-center gap-3">
                                <span>样本: {icData.stock_count} 只 · 区间: {icData.date_range}</span>
                                {icData.method === 'rolling_forward_ic' && (
                                    <span className="px-1.5 py-0.5 rounded bg-emerald-900/40 text-emerald-300 border border-emerald-600/30">
                                        滚动Forward IC · {icData.periods}期
                                    </span>
                                )}
                                {icData.method === 'single_snapshot_ic' && (
                                    <span className="px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-300 border border-amber-600/30">
                                        单截面同期IC（降级）
                                    </span>
                                )}
                            </div>
                            <div className="overflow-x-auto border border-slate-700/40 rounded-xl">
                                <table className="w-full text-sm text-left">
                                    <thead className="bg-slate-800/90">
                                        <tr className="text-slate-400 border-b border-slate-700/50">
                                            <th className="py-2.5 pl-3 font-medium">因子</th>
                                            <th className="py-2.5 text-right font-medium">IC均值</th>
                                            <th className="py-2.5 text-right font-medium">ICIR</th>
                                            <th className="py-2.5 text-right font-medium">当前权重</th>
                                            <th className="py-2.5 text-right font-medium">推荐权重</th>
                                            <th className="py-2.5 text-center font-medium">差异</th>
                                            <th className="py-2.5 text-center font-medium pr-3">判定</th>
                                        </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-700/30">
                                        {icData.factors.map(f => {
                                            const diff = ((f.suggested_weight - f.current_weight) * 100).toFixed(1);
                                            const diffColor = diff > 0 ? 'text-red-400' : diff < 0 ? 'text-green-400' : 'text-slate-500';
                                            const icColor = f.ic_mean == null ? 'text-slate-500'
                                                : Math.abs(f.ic_mean) >= 0.05 ? 'text-red-400 font-bold'
                                                : Math.abs(f.ic_mean) >= 0.02 ? 'text-amber-400'
                                                : 'text-slate-500';
                                            return (
                                                <tr key={f.name} className="hover:bg-slate-700/30 transition-colors">
                                                    <td className="py-2.5 pl-3 text-white font-medium">{f.label}</td>
                                                    <td className={`py-2.5 text-right font-mono ${icColor}`}>
                                                        {f.ic_mean != null ? f.ic_mean.toFixed(4) : '-'}
                                                    </td>
                                                    <td className={`py-2.5 text-right font-mono ${f.ic_ir != null && Math.abs(f.ic_ir) >= 0.5 ? 'text-red-400 font-bold' : f.ic_ir != null && Math.abs(f.ic_ir) >= 0.3 ? 'text-amber-400' : 'text-slate-500'}`}>
                                                        {f.ic_ir != null ? f.ic_ir.toFixed(3) : '-'}
                                                    </td>
                                                    <td className="py-2.5 text-right font-mono text-slate-400">
                                                        {(f.current_weight * 100).toFixed(0)}%
                                                    </td>
                                                    <td className="py-2.5 text-right font-mono text-indigo-300 font-bold">
                                                        {(f.suggested_weight * 100).toFixed(0)}%
                                                    </td>
                                                    <td className={`py-2.5 text-center font-mono text-xs ${diffColor}`}>
                                                        {diff > 0 ? `+${diff}` : diff}%
                                                    </td>
                                                    <td className={`py-2.5 text-center pr-3 text-xs font-medium ${
                                                        f.verdict?.startsWith('✅') ? 'text-emerald-400' :
                                                        f.verdict?.startsWith('⚠') ? 'text-amber-400' :
                                                        f.verdict?.startsWith('❌') ? 'text-red-400' :
                                                        'text-slate-400'
                                                    }`}>{f.verdict}</td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>

                            {icData.suggested_weights && (
                                <button
                                    onClick={() => {
                                        const newFactors = {};
                                        const newWeights = {};
                                        for (const [key, weight] of Object.entries(icData.suggested_weights)) {
                                            newFactors[key] = weight > 0.01;
                                            newWeights[key] = weight;
                                        }
                                        setSelectedFactors(prev => ({ ...prev, ...newFactors }));
                                        setFactorWeights(prev => ({ ...prev, ...newWeights }));
                                        setShowWeightPanel(true);
                                    }}
                                    className="mt-4 w-full py-3 rounded-xl bg-gradient-to-r from-amber-600 to-orange-600 text-white font-bold text-sm hover:opacity-90 transition-all flex items-center justify-center gap-2 shadow-lg shadow-amber-900/20">
                                    <BarChart3 className="w-4 h-4" />
                                    一键应用推荐权重
                                </button>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
};

export default IcAnalysisPanel;
