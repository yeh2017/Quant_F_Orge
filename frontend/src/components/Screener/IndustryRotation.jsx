
// ── 行业轮动信号面板 ──
const IndustryRotation = ({ rankings, heat, heat5d, heatDate, onSelectIndustry, onJumpEtf }) => {
    if (!rankings) return null;

    // 从全部行业（heat map）计算，而非仅排行榜
    const allNames = [...new Set([
        ...Object.keys(heat || {}),
        ...Object.keys(heat5d || {}),
    ])].filter(n => {
        const allKeys = [...new Set([...Object.keys(heat || {}), ...Object.keys(heat5d || {})])];
        return !allKeys.some(other =>
            other !== n && other.includes(n) &&
            (heat[other] || 0) === (heat[n] || 0) &&
            (heat5d[other] || 0) === (heat5d[n] || 0)
        );
    });

    // 相对排名法：行业强弱转换
    const sorted5d = [...allNames].sort((a, b) => (heat5d[a] || 0) - (heat5d[b] || 0));
    const sortedToday = [...allNames].sort((a, b) => (heat[b] || 0) - (heat[a] || 0));
    const total = allNames.length;
    const weakThreshold = Math.max(1, Math.floor(total * 0.3));
    const strongThreshold = Math.max(1, Math.floor(total * 0.3));

    const weak5dSet = new Set(sorted5d.slice(0, weakThreshold));
    const strong5dSet = new Set(sorted5d.slice(-strongThreshold));
    const strongTodaySet = new Set(sortedToday.slice(0, strongThreshold));
    const weakTodaySet = new Set(sortedToday.slice(-weakThreshold));

    const weakToStrong = allNames
        .filter(n => weak5dSet.has(n) && strongTodaySet.has(n))
        .map(n => ({ name: n, from5d: heat5d[n] || 0, today: heat[n] || 0 }))
        .sort((a, b) => (b.today - b.from5d) - (a.today - a.from5d))
        .slice(0, 3);
    const strongToWeak = allNames
        .filter(n => strong5dSet.has(n) && weakTodaySet.has(n))
        .map(n => ({ name: n, from5d: heat5d[n] || 0, today: heat[n] || 0 }))
        .sort((a, b) => (a.today - a.from5d) - (b.today - b.from5d))
        .slice(0, 3);

    const handleClick = (name) => onSelectIndustry(name);

    // 渲染通用涨跌列
    const RankCol = ({ title, data }) => (
        <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-xl p-3">
            <div className="text-xs font-semibold text-slate-400 mb-2">{title}</div>
            <div className="space-y-1.5">
                {(data || []).map((item, idx) => (
                    <div key={item.name}
                        className="flex items-center justify-between text-sm cursor-pointer hover:bg-slate-700/30 rounded-lg px-1.5 py-0.5 transition-colors"
                        onClick={() => handleClick(item.name)}
                        title={`点击选中 ${item.name} 相关行业`}>
                        <span className="text-slate-300 truncate flex items-center gap-1">
                            <span className="text-slate-500 mr-1">{idx + 1}.</span>
                            {item.name}
                            {onJumpEtf && (
                                <span className="text-slate-600 hover:text-amber-400 cursor-pointer transition-colors text-xs"
                                    onClick={e => { e.stopPropagation(); onJumpEtf(item.name); }}
                                    title={`查看${item.name}相关 ETF`}>🏦</span>
                            )}
                        </span>
                            <span className={`font-mono font-medium ${item.pct > 0 ? 'text-red-400' : item.pct < 0 ? 'text-green-400' : 'text-slate-500'}`}>
                                {item.pct > 0 ? '+' : ''}{item.pct.toFixed(2)}%
                            </span>
                    </div>
                ))}
            </div>
        </div>
    );

    // 渲染反转信号列
    const ReversalCol = ({ title, data, color }) => (
        data.length > 0 ? (
            <div className={`bg-gradient-to-br ${color === 'red' ? 'from-red-500/5' : 'from-emerald-500/5'} to-slate-900/50 backdrop-blur-md border ${color === 'red' ? 'border-red-500/20' : 'border-emerald-500/20'} rounded-xl p-3`}>
                <div className={`text-xs font-semibold ${color === 'red' ? 'text-red-400' : 'text-emerald-400'} mb-2`}>{title}</div>
                <div className="space-y-1.5">
                    {data.map((s, i) => (
                        <div key={s.name}
                            className={`flex items-center justify-between text-sm cursor-pointer hover:bg-${color === 'red' ? 'red' : 'emerald'}-500/10 rounded-lg px-1.5 py-0.5 transition-colors`}
                            onClick={() => handleClick(s.name)} title={`点击选中 ${s.name}`}>
                            <span className="text-slate-300 flex items-center gap-1">
                                <span className="text-slate-500 mr-1">{i+1}.</span>{s.name}
                                {onJumpEtf && (
                                    <span className="text-slate-600 hover:text-amber-400 cursor-pointer transition-colors text-xs"
                                        onClick={e => { e.stopPropagation(); onJumpEtf(s.name); }}
                                        title={`查看${s.name}相关 ETF`}>🏦</span>
                                )}
                            </span>
                            <span className="font-mono text-xs">
                                <span className="text-emerald-400">{s.from5d.toFixed(1)}%</span>
                                <span className="text-slate-500 mx-1">→</span>
                                <span className="text-red-400">{s.today > 0 ? '+' : ''}{s.today.toFixed(1)}%</span>
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        ) : null
    );

    return (
        <div className="bg-slate-800/30 border border-slate-700/40 rounded-2xl p-4">
            <div className="text-xs font-semibold text-slate-300 mb-3 flex items-center gap-2">
                📊 行业轮动信号
                {heatDate && <span className="text-slate-500 font-normal">· {heatDate}</span>}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
                <RankCol title="📈 今日领涨" data={rankings.top3_today} />
                <RankCol title="📉 今日领跌" data={rankings.bottom3_today} />
                <RankCol title="🔥 5日领涨" data={rankings.top3_5d} />
                <RankCol title="❄️ 5日领跌" data={rankings.bottom3_5d} />
                <ReversalCol title="⚡ 弱转强（5日→今日）" data={weakToStrong} color="red" />
                <ReversalCol title="⚠️ 强转弱（5日→今日）" data={strongToWeak} color="emerald" />
            </div>
        </div>
    );
};

export default IndustryRotation;
