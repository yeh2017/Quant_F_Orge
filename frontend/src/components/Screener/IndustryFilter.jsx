import { Check, ChevronDown, ChevronRight } from 'lucide-react';
import { useRef, useEffect } from 'react';
import { groupStyles } from './styles';

const IndustryFilter = ({
    industries, selectedIndustries, setSelectedIndustries,
    groupedIndustries, expandedGroups, setExpandedGroups,
    smartCategories, heat, INDUSTRY_GROUPS,
    onSmartSelect, getIndObj, smartMsg,
    activeSmartCat, setActiveSmartCat,
    setSmartMode,
}) => {
    // 内联提示自动滚入视口
    const smartMsgRef = useRef(null);
    useEffect(() => {
        if (smartMsg && smartMsgRef.current) {
            smartMsgRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }, [smartMsg]);

    // 折叠/展开
    const toggleGroup = (groupId) => {
        setExpandedGroups(prev => {
            const next = new Set(prev);
            next.has(groupId) ? next.delete(groupId) : next.add(groupId);
            return next;
        });
    };

    // 整组选中/取消
    const toggleGroupSelect = (members) => {
        const allSelected = members.every(m => selectedIndustries.includes(m));
        if (allSelected) {
            setSelectedIndustries(prev => prev.filter(i => !members.includes(i)));
        } else {
            setSelectedIndustries(prev => [...new Set([...prev, ...members])]);
        }
        setSmartMode?.(false);
        setActiveSmartCat?.(null);
    };

    const toggleIndustry = (indName) => {
        setSelectedIndustries(prev =>
            prev.includes(indName) ? prev.filter(i => i !== indName) : [...prev, indName]
        );
        setSmartMode?.(false);
        setActiveSmartCat?.(null);
    };

    // 组级平均热度
    const groupHeat = (members) => {
        const vals = members.map(m => heat[m]).filter(v => v != null);
        if (vals.length === 0) return null;
        return vals.reduce((a, b) => a + b, 0) / vals.length;
    };

    // 热度色块
    const HeatBadge = ({ name }) => {
        const val = heat[name];
        if (val == null) return null;
        const isUp = val > 0;
        const color = isUp ? 'text-red-400' : val < 0 ? 'text-emerald-400' : 'text-slate-500';
        return (
            <span className={`text-xs font-mono ${color} ml-auto flex-shrink-0`}>
                {isUp ? '+' : ''}{val.toFixed(2)}%
            </span>
        );
    };

    return (
        <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-5 shadow-sm">
            <div className="flex flex-col md:flex-row md:items-center justify-between mb-4 gap-3">
                <h3 className="text-sm font-semibold text-slate-300 whitespace-nowrap flex items-center gap-2">
                    行业筛选
                    {selectedIndustries.length > 0 && (
                        <span className="text-[11px] text-emerald-400/80 font-normal">
                            已选 {selectedIndustries.length} 个
                        </span>
                    )}
                </h3>

                <div className="flex flex-wrap items-center gap-1.5">
                    {smartCategories.map(cat => {
                        const s = groupStyles[cat.color] || groupStyles.slate;
                        return (
                            <button key={cat.id} onClick={() => onSmartSelect(cat)}
                                className={`text-[11px] px-2.5 py-1 rounded-lg border transition-all font-medium ${
                                    activeSmartCat === cat.id
                                        ? `${s.activeBg} ${s.border} ${s.text}`
                                        : 'bg-slate-800 text-slate-300 border-slate-600/50 hover:bg-slate-700'
                                }`}>
                                {cat.label}
                            </button>
                        );
                    })}

                    <div className="w-[1px] h-4 bg-slate-700/50 mx-1 hidden sm:block"></div>

                    <button onClick={() => {
                        const all = industries.map(i => i.name || i);
                        setSelectedIndustries(all);
                        setExpandedGroups(new Set(INDUSTRY_GROUPS.map(g => g.id)));
                        setSmartMode?.(false);
                        setActiveSmartCat?.(null);
                    }}
                        className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800 text-slate-300 border border-slate-600/50 hover:bg-slate-700 transition-all font-medium">
                        全选
                    </button>
                    <button onClick={() => { setSelectedIndustries([]); setSmartMode?.(false); setActiveSmartCat?.(null); }}
                        className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800/60 text-slate-400 border border-slate-600/50 hover:bg-slate-700/60 transition-all font-medium">
                        清空
                    </button>
                </div>
            </div>

            {/* 内联提示：选中行业反馈 */}
            {smartMsg && (
                <div ref={smartMsgRef} className={`mb-3 px-3 py-2 rounded-lg text-sm flex items-center gap-2 ${
                    smartMsg.type === 'success'
                        ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                        : 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                }`}>
                    <span>{smartMsg.type === 'success' ? '✅' : '⚠️'}</span>
                    <span>{smartMsg.text}</span>
                </div>
            )}

            {industries.length === 0 ? (
                <div className="text-slate-500 text-sm py-4 text-center">
                    暂无行业数据，请先在「数据中台」同步股票基本信息
                </div>
            ) : (
                <div className="space-y-1.5">
                    {groupedIndustries.map(group => {
                        const s = groupStyles[group.color] || groupStyles.slate;
                        const expanded = expandedGroups.has(group.id);
                        const selectedCount = group.members.filter(m => selectedIndustries.includes(m)).length;
                        const allSelected = selectedCount === group.members.length;
                        const gHeat = groupHeat(group.members);

                        return (
                            <div key={group.id} className={`rounded-xl border transition-all ${expanded ? s.border : 'border-slate-700/30'}`}>
                                <div
                                    className={`flex items-center gap-2 px-3 py-2 cursor-pointer rounded-xl transition-all ${s.hoverBg} ${expanded ? s.bg : ''}`}
                                    onClick={() => toggleGroup(group.id)}>
                                    {expanded
                                        ? <ChevronDown className={`w-4 h-4 ${s.text} flex-shrink-0`} />
                                        : <ChevronRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
                                    }
                                    <span className="text-sm">{group.icon}</span>
                                    <span className={`text-sm font-semibold ${expanded ? s.text : 'text-slate-300'}`}>
                                        {group.label}
                                    </span>
                                    <span className="text-[11px] text-slate-500">
                                        {group.members.length} 个行业
                                    </span>

                                    {gHeat != null && (
                                        <span className={`text-sm font-mono font-semibold ml-1 ${gHeat > 0 ? 'text-red-400' : gHeat < 0 ? 'text-emerald-400' : 'text-slate-500'}`}>
                                            {gHeat > 0 ? '+' : ''}{gHeat.toFixed(2)}%
                                        </span>
                                    )}

                                    <div className="flex-1" />

                                    {selectedCount > 0 && (
                                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${s.activeBg} ${s.text}`}>
                                            {selectedCount}/{group.members.length}
                                        </span>
                                    )}

                                    <button
                                        onClick={(e) => { e.stopPropagation(); toggleGroupSelect(group.members); }}
                                        className={`text-[10px] px-2 py-0.5 rounded-md border transition-all
                                            ${allSelected
                                                ? `${s.activeBg} ${s.border} ${s.text}`
                                                : 'bg-slate-800/50 border-slate-600/30 text-slate-400 hover:bg-slate-700/50'
                                            }`}>
                                        {allSelected ? '取消' : '全选'}
                                    </button>
                                </div>

                                {expanded && (
                                    <div className="px-3 pb-2.5 pt-1 grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-1.5">
                                        {group.members.map(indName => {
                                            const active = selectedIndustries.includes(indName);
                                            const indObj = getIndObj(indName);
                                            return (
                                                <button key={indName} onClick={() => toggleIndustry(indName)}
                                                    className={`flex items-center gap-1.5 text-sm py-1.5 px-2.5 rounded-lg border transition-all
                                                        ${active
                                                            ? `${s.activeBg} ${s.border} ${s.text} shadow-sm`
                                                            : 'bg-slate-800/30 border-slate-700/40 text-slate-300 hover:bg-slate-700/40 hover:border-slate-600/50'
                                                        }`}>
                                                    {active && <Check className="w-3 h-3 flex-shrink-0" />}
                                                    <span className="truncate">{indName}</span>
                                                    {indObj?.count && (
                                                        <span className="text-[10px] text-slate-500 flex-shrink-0">{indObj.count}</span>
                                                    )}
                                                    <HeatBadge name={indName} />
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default IndustryFilter;
