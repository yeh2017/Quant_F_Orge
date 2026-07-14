/**
 * 因子评分排行表
 * 从 FactorPanel 提取，展示因子计算结果的排行表格
 */
import { makePoolItem } from '../../utils/poolActions';
const FactorScoreTable = ({
    factorScores,
    factors,
    selectedFactors,
    customStocks,
    setCustomStocks,
    onViewKline,
    showAllResults,
    setShowAllResults,
}) => {
    const displayCount = showAllResults ? factorScores.length : 10;
    // 按分数高低着色（A 股约定：红=强势，绿=弱势，与选股器一致）
    // 兼容快速路径(0~1)和慢路径(0~100)两种量纲
    const scoreColor = (val) => {
        if (val == null) return 'text-slate-500';
        const normalized = val <= 1 ? val * 100 : val;
        if (normalized >= 70) return 'text-red-400';
        if (normalized <= 30) return 'text-emerald-400';
        return 'text-slate-300';
    };

    if (factorScores.length === 0) return null;

    return (
        <div className="xl:col-span-2 bg-slate-800/40 backdrop-blur-sm border border-slate-700/50 p-6 rounded-2xl overflow-hidden shadow-lg flex flex-col">
            <h3 className="text-white font-bold flex items-center gap-2 text-lg mb-5">
                <div className="w-2 h-2 rounded-full bg-purple-400 shadow-[0_0_8px_rgba(192,132,252,0.8)]"></div>
                因子综合得分排行
                <span className="text-xs text-slate-500 font-normal ml-2">共 {factorScores.length} 只</span>
            </h3>
            <div className="overflow-x-auto flex-1">
                <table className="w-full text-sm text-left">
                    <thead>
                        <tr className="text-slate-400 border-b border-slate-700/50">
                            <th className="pb-3 pl-2 font-medium w-12">排名</th>
                            <th className="pb-3 font-medium">代码</th>
                            <th className="pb-3 font-medium">名称</th>
                            {factors.filter(f => selectedFactors[f.key]).map(f => (
                                <th key={f.key} className="pb-3 text-right font-medium cursor-help"
                                    title={`${f.desc || f.name}（权重 ${Math.round((f.weight || 0) * 100)}%）\n子指标: ${(f.items || []).join('、')}`}>
                                    {f.name.replace('因子', '')}
                                </th>
                            ))}
                            <th className="pb-3 text-right pr-2 font-medium cursor-help"
                                title="各因子截面百分位排名的加权平均，权重可在因子卡片中调整">综合评分</th>
                            <th className="pb-3 text-center font-medium">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {factorScores.slice(0, displayCount).map((s, idx) => {
                            const inPool = customStocks.some(cs => cs.code === s.code);
                            return (
                                <tr key={idx} className="border-b border-slate-700/30 hover:bg-slate-700/30 transition-colors group">
                                    <td className="py-3 pl-2">
                                        <span className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${idx === 0 ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 shadow-[0_0_10px_rgba(234,179,8,0.2)]' : idx < 3 ? 'bg-slate-300/20 text-slate-300 border border-slate-400/30 shadow-[0_0_10px_rgba(203,213,225,0.1)]' : 'text-slate-500'}`}>
                                            {idx + 1}
                                        </span>
                                    </td>
                                    <td className="py-3">
                                        <span className="font-mono text-slate-300 text-xs tracking-wider">{s.code}</span>
                                    </td>
                                    <td className="py-3">
                                        <span className="text-white font-medium group-hover:text-indigo-300 transition-colors">{s.name}</span>
                                    </td>
                                    {factors.filter(f => selectedFactors[f.key]).map(f => (
                                        <td key={f.key} className={`py-3 text-right font-mono tracking-tighter ${scoreColor(s[f.key])}`}>
                                            {s[f.key] != null ? s[f.key].toFixed(2) : '-'}
                                        </td>
                                    ))}
                                    <td className="py-3 text-right pr-2">
                                        <span className="bg-gradient-to-r from-purple-600 to-indigo-600 px-2.5 py-1.5 rounded-lg text-white font-bold shadow-sm inline-block min-w-[3.5rem] text-center tracking-tight border border-indigo-400/20">
                                            {(s.composite || 0).toFixed(2)}
                                        </span>
                                    </td>
                                    <td className="py-3 text-center">
                                        <div className="flex items-center justify-center gap-1">
                                            {onViewKline && (
                                                <button
                                                    onClick={() => onViewKline(s.code)}
                                                    className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all"
                                                    title={`查看 ${s.name} K线图`}>
                                                    📈
                                                </button>
                                            )}
                                            {setCustomStocks && (
                                                <button
                                                    onClick={() => inPool
                                                        ? setCustomStocks(prev => prev.filter(cs => cs.code !== s.code))
                                                        : setCustomStocks(prev => [...prev, makePoolItem(s.code, s.name, { industry: s.industry || '' })])}
                                                    className={`text-[10px] px-1.5 py-1 rounded border transition-all ${inPool ? 'bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30' : 'bg-emerald-600/30 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/50'}`}
                                                    title={inPool ? '点击移出自选池' : '加入自选池'}>
                                                    {inPool ? '✓' : '➕'}
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
            {factorScores.length > 10 && (
                <button onClick={() => setShowAllResults(!showAllResults)}
                    className="mt-4 w-full py-2 text-sm text-slate-400 hover:text-indigo-300 border border-slate-700/50 rounded-lg hover:border-indigo-500/30 transition-all flex items-center justify-center gap-1.5">
                    {showAllResults ? <>收起仅显示 Top 10</> : <>展开全部 {factorScores.length} 只</>}
                </button>
            )}
        </div>
    );
};

export default FactorScoreTable;
