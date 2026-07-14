import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Search, Check, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import { screenerApi } from '../../services/api';
import MarketOverview from './MarketOverview';
import IndustryRotation from './IndustryRotation';
import IndustryFilter from './IndustryFilter';
import ResultTable from './ResultTable';
import FactorSignals from './FactorSignals';
import { groupStyles, INDUSTRY_GROUPS } from './styles';
import { EMPTY_FILTERS, STRATEGY_TEMPLATES as STRATEGY_PRESETS } from './presets';


const filterFields = [
    { key: 'pe_max', label: 'PE 上限', placeholder: '推荐 ≤30', desc: '市盈率，越低理论回本越快', hints: [15, 25, 40] },
    { key: 'pb_max', label: 'PB 上限', placeholder: '推荐 ≤5', desc: '市净率，防范高溢价泡沫', hints: [1.5, 3, 5] },
    { key: 'roe_min', label: 'ROE 下限(%)', placeholder: '推荐 ≥8', desc: '净资产收益率，衡量盈利能力', hints: [8, 12, 20] },
    { key: 'revenue_yoy_min', label: '营收同比 下限(%)', placeholder: '推荐 ≥10', desc: '营收较去年同期增长比率', hints: [10, 20, 50] },
    { key: 'net_profit_yoy_min', label: '净利润同比 下限(%)', placeholder: '推荐 ≥10', desc: '净利润增速，成长性核心指标', hints: [10, 20, 50] },
    { key: 'turnover_rate_min', label: '换手率 下限(%)', placeholder: '推荐 ≥1', desc: '每日股票流通易手活跃度', hints: [1, 3, 5] },
    { key: 'volume_ratio_min', label: '量比 下限', placeholder: '如 1.5', desc: '当日成交量/5日均量，>1放量，>2显著放量', hints: [1, 1.5, 2] },
    { key: 'net_inflow_min', label: '主力净流入 下限(万)', placeholder: '如 500', desc: '大单+特大单资金净流入额', hints: [200, 500, 1000] },
    { key: 'pct_chg_min', label: '涨幅 下限(%)', placeholder: '如 3', desc: '当日涨跌幅下限，筛选强势股', hints: [-3, 0, 3] },
    { key: 'pct_chg_max', label: '涨幅 上限(%)', placeholder: '如 -3', desc: '当日涨跌幅上限，筛选超跌股', hints: [-3, 5, 10] },
    { key: 'holder_chg_max', label: '股东变化率上限(%)', placeholder: '如 -10', desc: '负值=筹码集中（股东减少），如-10表示户数减10%以上', hints: [-5, -10, -20] },
    { key: 'max_list_days', label: '上市天数上限', placeholder: '如 365', desc: '筛选次新股，如365=上市不超过1年', hints: [180, 365, 730] },
];



// ── 股票筛选 Tab 主组件 ──
const StockTab = ({
    industries, heat, heat5d, rankings, l1ToSubs, regime, stockReversal, heatDate,
    customStocks, setCustomStocks, setAlerts, onViewKline, onJumpEtf,
}) => {
    // ── 自管状态 ──
    const [selectedIndustries, setSelectedIndustries] = useState([]);
    const [expandedGroups, setExpandedGroups] = useState(new Set(['tech']));
    const [filters, setFilters] = useState(EMPTY_FILTERS);
    const [sortBy, setSortBy] = useState('score');
    const [sortOrder, setSortOrder] = useState('desc');
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [selectedCodes, setSelectedCodes] = useState(new Set());
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [smartMode, setSmartMode] = useState(true);
    const [btnStatus, setBtnStatus] = useState('idle');
    const btnTimerRef = useRef(null);
    const mountedRef = useRef(true);
    useEffect(() => () => { mountedRef.current = false; }, []);
    const [currentPage, setCurrentPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [totalMatched, setTotalMatched] = useState(0);
    const PAGE_SIZE = 50;
    const [activePreset, setActivePreset] = useState(null);
    const [smartMsg, setSmartMsg] = useState(null);
    const [activeSmartCat, setActiveSmartCat] = useState(null);
    const [factorDate, setFactorDate] = useState(null);
    const [indexFilter, setIndexFilter] = useState('');

    // 将行业按 INDUSTRY_GROUPS 归组
    const groupedIndustries = useMemo(() => {
        const allNames = industries.map(i => i.name || i);
        const assigned = new Set();
        const result = INDUSTRY_GROUPS.map(group => {
            let members;
            if (group.keywords.length === 0) {
                members = allNames.filter(n => !assigned.has(n));
            } else {
                members = allNames.filter(n => !assigned.has(n) && group.keywords.some(kw => n.includes(kw)));
                members.forEach(m => assigned.add(m));
            }
            return { ...group, members };
        });
        return result.filter(g => g.members.length > 0);
    }, [industries]);

    // 点击行业轮动信号 → 兼容 SW L1 名和 Tushare 子行业名
    const selectL1Industry = (name) => {
        const subs = l1ToSubs?.[name];
        // SW L1 名 → 展开为对应子行业；Tushare 子行业名 → 直接选中
        const toSelect = subs?.length > 0 ? subs : [name];
        setSelectedIndustries(toSelect);
        setSmartMode(false);
        // 展开包含选中子行业的分组
        const groupIds = new Set();
        toSelect.forEach(n => {
            const g = groupedIndustries.find(gr => gr.members.includes(n));
            if (g) groupIds.add(g.id);
        });
        if (groupIds.size > 0) setExpandedGroups(prev => new Set([...prev, ...groupIds]));
        // 提示信息
        const detail = subs?.length > 0 ? `${name}：${toSelect.join('、')}` : name;
        setSmartMsg({ type: 'success', text: detail });
        setTimeout(() => setSmartMsg(null), 5000);
        handleScreen(filters, `行业：${name}`, toSelect);
    };

    // 快捷标签
    const SMART_CATEGORIES = useMemo(() => [
        { id: 'top5', label: '🔥 5日强势Top5', color: 'orange',
          getIndustries: () => (rankings?.top5_5d_sub || []).map(item => item.name) },
    ], [rankings]);

    const handleSmartSelect = (category) => {
        const targets = category.getIndustries();
        if (targets.length === 0) {
            setSmartMsg({ type: 'warning', text: `未找到符合【${category.label}】的行业数据` });
            setTimeout(() => setSmartMsg(null), 3000);
            return;
        }
        setSelectedIndustries(targets);
        setSmartMode(false);
        setActiveSmartCat(category.id);
        // 展开包含选中子行业的分组（仅对 Tushare 子行业名有效）
        const groupIds = new Set();
        targets.forEach(name => {
            const g = groupedIndustries.find(gr => gr.members.includes(name));
            if (g) groupIds.add(g.id);
        });
        if (groupIds.size > 0) setExpandedGroups(prev => new Set([...prev, ...groupIds]));
        const msg = `${category.label}：${targets.join('、')}`;
        setSmartMsg({ type: 'success', text: msg });
        if (mountedRef.current) setAlerts([{ type: 'success', msg }]);
        setTimeout(() => setSmartMsg(null), 5000);
    };

    const handleFilterChange = (key, value) => {
        setFilters(prev => ({ ...prev, [key]: value }));
    };

    // 排序切换时自动重新筛选
    const sortTriggerRef = React.useRef(false);
    useEffect(() => {
        if (sortTriggerRef.current && results.length > 0) handleScreen();
        sortTriggerRef.current = true;
    }, [sortBy, sortOrder]);

    // 执行筛选
    const handleScreen = async (overrideFilters, overrideLabel, overrideIndustries) => {
        const f = overrideFilters || filters;
        const ind = overrideIndustries || selectedIndustries;
        setLoading(true);
        setBtnStatus('loading');
        clearTimeout(btnTimerRef.current);
        try {
            const payload = { page_size: PAGE_SIZE, page: 1 };
            if (ind.length > 0) payload.industries = ind;
            if (f.pe_max !== '') payload.pe_max = parseFloat(f.pe_max);
            if (f.pb_max !== '') payload.pb_max = parseFloat(f.pb_max);
            if (f.roe_min !== '') payload.roe_min = parseFloat(f.roe_min);
            if (f.revenue_yoy_min !== '') payload.revenue_yoy_min = parseFloat(f.revenue_yoy_min);
            if (f.net_profit_yoy_min !== '') payload.net_profit_yoy_min = parseFloat(f.net_profit_yoy_min);
            if (f.turnover_rate_min !== '') payload.turnover_rate_min = parseFloat(f.turnover_rate_min);
            if (f.net_inflow_min !== '') payload.net_inflow_min = parseFloat(f.net_inflow_min);
            if (f.pct_chg_min !== '') payload.pct_chg_min = parseFloat(f.pct_chg_min);
            if (f.pct_chg_max !== '') payload.pct_chg_max = parseFloat(f.pct_chg_max);
            if (f.gap_up) payload.gap_up = true;
            if (f.holder_chg_max !== '') payload.holder_chg_max = parseFloat(f.holder_chg_max);
            if (f.max_list_days !== '' && f.max_list_days != null) payload.max_list_days = parseInt(f.max_list_days);
            if (f.volume_ratio_min !== '' && f.volume_ratio_min != null) payload.volume_ratio_min = parseFloat(f.volume_ratio_min);
            if (f.has_block_trade) payload.has_block_trade = true;
            if (f.has_unlock) payload.has_unlock = true;
            if (f.has_top_list) payload.has_top_list = true;
            if (f.margin_chg_min !== '' && f.margin_chg_min != null) payload.margin_chg_min = parseFloat(f.margin_chg_min);
            if (indexFilter) payload.index_filter = indexFilter;
            payload.sort_by = sortBy;
            payload.sort_order = sortOrder;
            const res = await screenerApi.screen(payload);
            setResults(res.stocks || []);
            setSelectedCodes(new Set());
            setCurrentPage(res.page || 1);
            setTotalPages(res.total_pages || 1);
            setTotalMatched(res.total_matched || res.total || 0);
            if (res.factor_date) setFactorDate(res.factor_date);
            if (res.error) {
                setBtnStatus('error');
                if (mountedRef.current) setAlerts([{ type: 'error', msg: `✗ 筛选出错: ${res.error}` }]);
            } else if (res.stocks?.length === 0) {
                setBtnStatus('warning');
                // 根据筛选条件给出具体原因
                const reasons = [];
                const ef = overrideFilters || filters;
                if (ef.pct_chg_min && parseFloat(ef.pct_chg_min) > 0) reasons.push(`当日涨幅≥${ef.pct_chg_min}%（今日可能无强势股）`);
                if (ef.pct_chg_max && parseFloat(ef.pct_chg_max) < 0) reasons.push(`当日跌幅≤${ef.pct_chg_max}%（今日可能无超跌股）`);
                if (ef.gap_up) reasons.push('要求跳空高开（当日可能无跳空）');
                if (ef.net_inflow_min && parseFloat(ef.net_inflow_min) > 0) reasons.push(`主力净流入≥${ef.net_inflow_min}万（当日资金可能偏弱）`);
                if (ef.holder_chg_max && parseFloat(ef.holder_chg_max) < 0) reasons.push(`股东变化率≤${ef.holder_chg_max}%（需等季报更新）`);
                if (ef.max_list_days) reasons.push(`上市天数≤${ef.max_list_days}天（次新股数量有限，可放宽天数）`);
                const reasonText = reasons.length > 0
                    ? `\n可能原因：${reasons.join('；')}` : '\n建议：放宽条件或减少筛选维度';
                if (mountedRef.current) setAlerts([{ type: 'warning', msg: `${overrideLabel ? overrideLabel + '：' : ''}未找到符合条件的股票${reasonText}` }]);
            } else {
                setBtnStatus('success');
                const matched = res.total_matched || res.total;
                const shown = res.stocks.length;
                const truncated = matched > shown ? `（共匹配 ${matched} 只，显示前 ${shown} 只）` : '';
                if (mountedRef.current) setAlerts([{ type: 'success', msg: `✓ ${overrideLabel ? overrideLabel + '策略' : '筛选完成'}，找到 ${matched} 只股票${truncated}` }]);
            }
        } catch (e) {
            setBtnStatus('error');
            if (mountedRef.current) setAlerts([{ type: 'error', msg: `✗ 筛选请求失败: ${e.message}` }]);
        }
        setLoading(false);
        btnTimerRef.current = setTimeout(() => setBtnStatus('idle'), 2000);
    };

    const getIndObj = (name) => industries.find(i => (i.name || i) === name);

    return (<>
        {/* ── 大盘状态 + 个股反转 ── */}
        <MarketOverview regime={regime} stockReversal={stockReversal}
            customStocks={customStocks} setCustomStocks={setCustomStocks} onViewKline={onViewKline} />

        {/* ── 因子信号（宏观→个股→行业→筛选） ── */}
        <FactorSignals customStocks={customStocks} setCustomStocks={setCustomStocks} latestTradeDate={heatDate} onViewKline={onViewKline} />

        {/* ── 行业轮动信号 ── */}
        <IndustryRotation rankings={rankings} heat={heat} heat5d={heat5d}
            heatDate={heatDate} onSelectIndustry={selectL1Industry} onJumpEtf={onJumpEtf} />

        {/* ── 行业选择 ── */}
        <IndustryFilter
            industries={industries} selectedIndustries={selectedIndustries} setSelectedIndustries={setSelectedIndustries}
            groupedIndustries={groupedIndustries} expandedGroups={expandedGroups} setExpandedGroups={setExpandedGroups}
            smartCategories={SMART_CATEGORIES} heat={heat} INDUSTRY_GROUPS={INDUSTRY_GROUPS}
            onSmartSelect={handleSmartSelect} getIndObj={getIndObj} smartMsg={smartMsg}
            activeSmartCat={activeSmartCat} setActiveSmartCat={setActiveSmartCat}
            setSmartMode={setSmartMode} />

        {/* 因子条件区 */}
        <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-5 shadow-sm">
            {/* 指数成分筛选 */}
            <div className="flex items-center gap-3 mb-4">
                <span className="text-sm font-semibold text-slate-300">指数成分</span>
                {['', 'hs300', 'csi500', 'csi1000'].map(v => {
                    const labels = { '': '全市场', hs300: '沪深300', csi500: '中证500', csi1000: '中证1000' };
                    const isActive = indexFilter === v;
                    return (
                        <button key={v} onClick={() => setIndexFilter(v)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all border ${
                                isActive
                                    ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400'
                                    : 'bg-slate-800/40 border-slate-700/40 text-slate-400 hover:border-slate-600/50 hover:text-slate-300'
                            }`}>
                            {labels[v]}
                        </button>
                    );
                })}
            </div>
            <h3 className="text-sm font-semibold text-slate-300 mb-4">策略模板</h3>
            <div className="grid grid-cols-5 gap-3 mb-4">
                {STRATEGY_PRESETS.map(preset => {
                    const s = groupStyles[preset.color] || groupStyles.slate;
                    const isActive = activePreset === preset.key;
                    const SHORT = { pe_max:'PE', pb_max:'PB', roe_min:'ROE', revenue_yoy_min:'营收',
                        net_profit_yoy_min:'净利', turnover_rate_min:'换手', net_inflow_min:'主力',
                        pct_chg_min:'涨幅', pct_chg_max:'涨幅', holder_chg_max:'股东', max_list_days:'上市天数',
                        volume_ratio_min:'量比',
                        has_block_trade:'大宗', has_unlock:'解禁', has_top_list:'龙虎',
                        margin_chg_min:'融资' };
                    const paramText = Object.entries(preset.filters)
                        .filter(([, v]) => v !== '' && v !== false)
                        .map(([k, v]) => {
                            if (k === 'gap_up') return '跳空';
                            if (typeof v === 'boolean') return `☑${SHORT[k] || k}`;
                            return `${SHORT[k] || k}${k.includes('max') ? '≤' : '≥'}${v}`;
                        }).join(' · ');
                    return (
                        <button key={preset.key}
                            onClick={() => {
                                setFilters(preset.filters);
                                setActivePreset(preset.key);
                                setShowAdvanced(false);
                                setSmartMode(false);
                                handleScreen(preset.filters, preset.name);
                            }}
                            className={`p-3 rounded-xl border transition-all text-left disabled:opacity-60
                                ${isActive
                                    ? `${s.activeBg} ${s.border} ring-1 ring-${preset.color}-500/30`
                                    : `bg-slate-800/40 border-slate-700/40 hover:border-slate-600/50 ${s.hoverBg}`
                                }`}>
                            <div className="flex items-center gap-2">
                                <span className={`text-sm font-bold ${isActive ? s.text : 'text-slate-200'}`}>{preset.icon} {preset.name}</span>
                                {isActive && <Check className={`w-3.5 h-3.5 ${s.text} ml-auto`} />}
                            </div>
                            <div className="text-xs text-slate-400 mt-0.5">
                                {preset.desc}
                                <span className={`ml-1.5 px-1 py-px rounded text-xs ${preset.freq === '当日' ? 'bg-blue-500/20 text-blue-300' : 'bg-slate-600/40 text-slate-400'}`}>{preset.freq}</span>
                            </div>
                            <div className="text-xs mt-1 text-slate-200 font-mono truncate" title={paramText}>{paramText}</div>
                        </button>
                    );
                })}
            </div>

            {/* 自定义/清空 按钮行 */}
            <div className="flex items-center gap-2 mb-3">
                <button onClick={() => setShowAdvanced(prev => !prev)}
                    className="text-xs px-3 py-1.5 rounded-lg bg-slate-800/60 border border-slate-600/40 text-slate-300 hover:bg-slate-700/60 transition-all flex items-center gap-1.5">
                    {showAdvanced ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                    ⚙️ 自定义条件
                </button>
                <button onClick={() => { setFilters(EMPTY_FILTERS); setActivePreset(null); setSmartMode(false); setIndexFilter(''); }}
                    className="text-xs px-3 py-1.5 rounded-lg bg-slate-800/40 border border-slate-600/30 text-slate-400 hover:bg-slate-700/40 transition-all">
                    清空条件
                </button>
                {Object.values(filters).some(v => v !== '' && v !== false) && (
                    <span className="text-[11px] text-slate-500 ml-2">
                        已设 {Object.values(filters).filter(v => v !== '' && v !== false).length} 个条件
                    </span>
                )}
            </div>

            {/* 手动输入框 + 快捷标签（可折叠） */}
            {showAdvanced && (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 pt-3 border-t border-slate-700/30">
                    {filterFields.map(f => (
                        <div key={f.key} className="flex flex-col">
                            <div className="mb-1.5 flex flex-col gap-0.5">
                                <label className="block text-xs text-slate-400 font-medium">{f.label}</label>
                                <span className="text-[10px] text-white opacity-90 leading-tight">{f.desc}</span>
                            </div>
                            <input type="number" step="any" value={filters[f.key]}
                                onChange={e => { handleFilterChange(f.key, e.target.value); setActivePreset(null); setSmartMode(false); }}
                                placeholder={f.placeholder}
                                className="w-full bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 focus:ring-2 focus:ring-emerald-500/30 transition-all shadow-inner" />
                            {f.hints && (
                                <div className="mt-1.5 text-xs text-white/70">
                                    <span className="text-slate-400 mr-1">常用</span>
                                    {f.hints.map((v, i) => (
                                        <span key={v}>
                                            <span onClick={() => { handleFilterChange(f.key, String(v)); setActivePreset(null); setSmartMode(false); }}
                                                className={`cursor-pointer transition-colors ${String(filters[f.key]) === String(v) ? 'text-emerald-400 font-semibold' : 'hover:text-emerald-300'}`}>{v}</span>
                                            {i < f.hints.length - 1 && <span className="mx-1 text-slate-500">·</span>}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>

        {/* ── 事件 · 杠杆筛选区（始终可见） ── */}
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 mb-3 px-1">
            <span className="text-xs text-slate-400 mr-1">事件</span>
            {[{key: 'has_block_trade', label: '大宗交易'}, {key: 'has_unlock', label: '解禁'}, {key: 'has_top_list', label: '龙虎榜'}].map(ev => (
                <label key={ev.key} className="flex items-center gap-1.5 cursor-pointer">
                    <input type="checkbox" checked={!!filters[ev.key]}
                        onChange={e => { handleFilterChange(ev.key, e.target.checked); setActivePreset(null); setSmartMode(false); }}
                        className="w-3.5 h-3.5 rounded border-slate-600 bg-slate-700 text-indigo-500 focus:ring-indigo-500/30 cursor-pointer" />
                    <span className="text-xs text-slate-300">近5日{ev.label}</span>
                </label>
            ))}
            <span className="text-slate-600">|</span>
            <div className="flex items-center gap-2">
                <label className="text-xs text-slate-400 font-medium shrink-0 cursor-help" title="近5个交易日融资余额变化百分比，正值=融资净买入增加">融资变化率 ≥(%)</label>
                <input type="number" step="any" value={filters.margin_chg_min}
                    onChange={e => { handleFilterChange('margin_chg_min', e.target.value); setActivePreset(null); setSmartMode(false); }}
                    placeholder="如5"
                    className="w-20 bg-slate-800/60 border border-slate-700/50 rounded-lg px-2 py-1.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-indigo-500/50" />
                <span className="text-xs text-white/60">
                    <span className="text-slate-400 mr-1">常用</span>
                    {[3, 5, 10].map((v, i) => (
                        <span key={v}>
                            <span onClick={() => { handleFilterChange('margin_chg_min', String(v)); setActivePreset(null); setSmartMode(false); }}
                                className={`cursor-pointer transition-colors ${String(filters.margin_chg_min) === String(v) ? 'text-indigo-400 font-semibold' : 'hover:text-indigo-300'}`}>{v}</span>
                            {i < 2 && <span className="mx-1 text-slate-500">·</span>}
                        </span>
                    ))}
                </span>
            </div>
        </div>

        {/* 筛选按钮 */}
        <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer select-none shrink-0" title="自动选取5日最强行业，结合上方策略条件一键筛选">
                <input type="checkbox" checked={smartMode} onChange={e => { setSmartMode(e.target.checked); if (e.target.checked) setActivePreset(null); }}
                    className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500/30 cursor-pointer" />
                <span className={`text-sm font-medium ${smartMode ? 'text-amber-400' : 'text-slate-400'}`}>🧠 智能行业</span>
            </label>
            <button onClick={async () => {
                if (smartMode) {
                    const top5 = (rankings?.top5_5d_sub || []).map(item => item.name);
                    if (top5.length === 0) {
                        setAlerts([{ type: 'warning', msg: '⚠ 行业热度数据尚未加载，请稍后再试或关闭智能行业手动筛选' }]);
                        return;
                    }
                    setSelectedIndustries(top5);
                    await handleScreen(filters, `🧠 智能行业（${top5.join('、')}）`, top5);
                } else {
                    handleScreen();
                }
            }} disabled={loading}
                className={`flex-1 px-5 py-2.5 rounded-xl font-semibold text-sm shadow-lg transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 ${
                    btnStatus === 'success' ? 'bg-gradient-to-r from-emerald-500 to-green-500 text-white'
                    : btnStatus === 'warning' ? 'bg-gradient-to-r from-amber-500 to-yellow-500 text-white'
                    : btnStatus === 'error' ? 'bg-gradient-to-r from-red-500 to-rose-500 text-white'
                    : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white hover:shadow-emerald-500/25'
                }`}>
                {loading ? (
                    <><RefreshCw className="w-4 h-4 animate-spin" /><span>筛选中...</span></>
                ) : btnStatus === 'success' ? (
                    <><Check className="w-4 h-4" /><span>筛选完成 · {totalMatched} 只</span></>
                ) : btnStatus === 'warning' ? (
                    <><Search className="w-4 h-4" /><span>未找到结果</span></>
                ) : btnStatus === 'error' ? (
                    <><span>✗ 筛选失败</span></>
                ) : (
                    <><Search className="w-4 h-4" /> <span>开始筛选</span></>
                )}
            </button>
        </div>
        <div className="text-xs text-slate-400 mt-3">
            {smartMode
                ? '🧠 智能行业：自动选取5日强势行业 + 上方已选策略条件'
                : '🔍 手动模式：使用上方手动设置的行业与参数筛选'
            }
        </div>

        {/* 条件摘要标签 */}
        {results.length > 0 && (
            <div className="flex items-center gap-2 flex-wrap text-xs my-3">
                <span className="text-slate-500">当前条件：</span>
                <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">
                    {smartMode ? '🧠 智能行业' : activePreset
                        ? `📋 ${STRATEGY_PRESETS.find(p => p.key === activePreset)?.name || ''}`
                        : '🔍 手动筛选'}
                </span>
                {selectedIndustries.length > 0 && (
                    <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
                        行业: {selectedIndustries.length}个
                    </span>
                )}
                {indexFilter && (
                    <span className="px-2 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/20">
                        🎯 {{ '': '', hs300: '沪深300', csi500: '中证500', csi1000: '中证1000' }[indexFilter]}
                    </span>
                )}
                {Object.entries(filters).filter(([, v]) => v !== '' && v !== false).length > 0 && (
                    <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
                        条件: {Object.entries(filters).filter(([, v]) => v !== '' && v !== false).length}项
                    </span>
                )}
                <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
                    共 {totalMatched} 只
                </span>
                {heatDate && (
                    <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">
                        数据: {heatDate}
                    </span>
                )}
                {factorDate && factorDate !== heatDate && (
                    <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                        ⚠ 因子: {factorDate}
                    </span>
                )}
            </div>
        )}
        <ResultTable
            results={results} setResults={setResults}
            selectedCodes={selectedCodes} setSelectedCodes={setSelectedCodes}
            customStocks={customStocks} setCustomStocks={setCustomStocks}
            sortBy={sortBy} setSortBy={setSortBy} sortOrder={sortOrder} setSortOrder={setSortOrder}
            currentPage={currentPage} setCurrentPage={setCurrentPage}
            totalPages={totalPages} setTotalPages={setTotalPages}
            totalMatched={totalMatched} setTotalMatched={setTotalMatched}
            selectedIndustries={selectedIndustries} filters={filters}
            indexFilter={indexFilter}
            loading={loading} setLoading={setLoading}
            setAlerts={setAlerts} onViewKline={onViewKline} />
    </>);
};

export default StockTab;
