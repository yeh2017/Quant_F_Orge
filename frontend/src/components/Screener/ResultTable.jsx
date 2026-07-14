import { useState, useEffect, useRef } from 'react';
import { Check, Plus } from 'lucide-react';
import { screenerApi, stockApi, newsApi } from '../../services/api';
import { makePoolItem } from '../../utils/poolActions';

import { fmtNum } from '../../utils/format';

const fmt = (v, suffix = '') => fmtNum(v, 2, suffix, '-');
const getColorClass = (val, defaultClass) => {
    if (val == null) return defaultClass;
    const num = Number(val);
    if (num > 0) return 'text-red-400 font-medium';
    if (num < 0) return 'text-green-400 font-medium';
    return defaultClass;
};

const PAGE_SIZE = 50;

// 可切换列定义（固定列 checkbox/代码/名称/操作 不在此列表中）
const COLUMN_DEFS = [
    { key: 'industry',       label: '行业',         group: '基本' },
    { key: 'score',          label: '评分',         group: '基本' },
    { key: 'close',          label: '最新价',       group: '行情' },
    { key: 'pct_chg',        label: '涨跌%',        group: '行情' },
    { key: 'amount',         label: '成交额(万)',    group: '行情' },
    { key: 'volume',         label: '成交量(手)',    group: '行情' },
    { key: 'pe_ttm',         label: 'PE(TTM)',      group: '估值' },
    { key: 'pb',             label: 'PB',           group: '估值' },
    { key: 'roe',            label: 'ROE(%)',        group: '盈利' },
    { key: 'eps',            label: 'EPS',          group: '盈利' },
    { key: 'revenue_yoy',    label: '营收同比(%)',   group: '成长' },
    { key: 'net_profit_yoy', label: '净利润同比(%)', group: '成长' },
    { key: 'turnover_rate',  label: '换手率(%)',     group: '行情' },
    { key: 'net_mf_amount',  label: '主力净流入(万)', group: '资金' },
    { key: 'total_mv',       label: '总市值(亿)',    group: '基本' },
    { key: 'holder_chg',     label: '股东变化(%)',   group: '结构' },
    { key: 'trend',          label: '趋势',         group: '技术' },
    { key: 'sentiment',      label: '舆情',         group: '情绪' },
    { key: 'event_tags',     label: '事件标签',     group: '事件' },
];

const DEFAULT_VISIBLE = new Set([
    'industry', 'score', 'close', 'pct_chg', 'amount', 'pe_ttm', 'roe',
    'net_profit_yoy', 'turnover_rate', 'net_mf_amount', 'total_mv',
    'trend', 'sentiment', 'event_tags',
]);

const STORAGE_KEY = 'screener_visible_cols';

const VALID_KEYS = new Set(COLUMN_DEFS.map(c => c.key));

const loadVisibleCols = () => {
    const SCHEMA_VERSION = 2; // v2=新增 event_tags 默认可见
    try {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved) {
            // 过滤掉已删除/重命名的旧 key
            const parsed = JSON.parse(saved).filter(k => VALID_KEYS.has(k));
            if (parsed.length > 0) {
                const result = new Set(parsed);
                const savedVer = parseInt(localStorage.getItem(STORAGE_KEY + '_ver') || '0');
                if (savedVer < SCHEMA_VERSION) {
                    // 一次性合并：把新增的默认可见列补入
                    for (const k of DEFAULT_VISIBLE) {
                        if (!result.has(k)) result.add(k);
                    }
                    localStorage.setItem(STORAGE_KEY, JSON.stringify([...result]));
                    localStorage.setItem(STORAGE_KEY + '_ver', String(SCHEMA_VERSION));
                }
                return result;
            }
        }
    } catch { /* ignore */ }
    localStorage.setItem(STORAGE_KEY + '_ver', String(SCHEMA_VERSION));
    return new Set(DEFAULT_VISIBLE);
};

const ResultTable = ({
    results, setResults,
    selectedCodes, setSelectedCodes,
    customStocks, setCustomStocks,
    sortBy, setSortBy, sortOrder, setSortOrder,
    currentPage, setCurrentPage, totalPages, setTotalPages,
    totalMatched, setTotalMatched,
    selectedIndustries, filters, indexFilter, loading, setLoading,
    setAlerts, onViewKline,
}) => {
    // 个股→ETF反查（Hook 必须在条件返回前）
    const [etfLookup, setEtfLookup] = useState({});
    // 批量技术诊断
    const [diagMap, setDiagMap] = useState({});
    // 批量舆情
    const [sentimentMap, setSentimentMap] = useState({});
    // 批量事件标签
    const [eventMap, setEventMap] = useState({});
    // 列可见性
    const [visibleCols, setVisibleCols] = useState(loadVisibleCols);
    const [showColPicker, setShowColPicker] = useState(false);
    const colPickerRef = useRef(null);

    const toggleCol = (key) => {
        setVisibleCols(prev => {
            const next = new Set(prev);
            next.has(key) ? next.delete(key) : next.add(key);
            localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]));
            return next;
        });
    };

    const isVisible = (key) => visibleCols.has(key);

    // 点击外部关闭列选择器
    useEffect(() => {
        if (!showColPicker) return;
        const handler = (e) => { if (colPickerRef.current && !colPickerRef.current.contains(e.target)) setShowColPicker(false); };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [showColPicker]);

    // 筛选结果变化时自动加载批量诊断 + 舆情 + 事件标签
    useEffect(() => {
        if (results.length === 0) return;
        // 立即清空旧数据，避免跨页残留
        setDiagMap({});
        setSentimentMap({});
        setEventMap({});
        const codes = results.map(s => s.code);
        // 事件标签和舆情是轻量查询，优先响应；诊断较慢，独立不阻塞
        screenerApi.getEventTags(codes)
            .then(data => setEventMap(data || {}))
            .catch(() => setEventMap({}));
        newsApi.getSentimentBatch(codes)
            .then(data => setSentimentMap(data || {}))
            .catch(() => setSentimentMap({}));
        stockApi.getDiagnosisBatch(codes)
            .then(data => setDiagMap(data || {}))
            .catch(() => setDiagMap({}));
    }, [results]);

    if (results.length === 0) return null;

    const handleStockToEtf = async (e, code) => {
        e.stopPropagation();
        if (etfLookup[code]) { setEtfLookup(prev => { const n = { ...prev }; delete n[code]; return n; }); return; }
        try {
            const res = await screenerApi.getStockToEtf(code);
            setEtfLookup(prev => ({ ...prev, [code]: res.etfs || res || [] }));
        } catch { setEtfLookup(prev => ({ ...prev, [code]: [] })); }
    };

    const toggleSelectAll = () => {
        if (selectedCodes.size === results.length) {
            setSelectedCodes(new Set());
        } else {
            setSelectedCodes(new Set(results.map(s => s.code)));
        }
    };

    const toggleSelectCode = (code) => {
        setSelectedCodes(prev => {
            const next = new Set(prev);
            next.has(code) ? next.delete(code) : next.add(code);
            return next;
        });
    };

    const addToPool = () => {
        const existingCodes = new Set(customStocks.map(s => s.code));
        const newStocks = results
            .filter(s => selectedCodes.has(s.code) && !existingCodes.has(s.code))
            .map(s => makePoolItem(s.code, s.name, {
                industry: s.industry || '',
            }));

        if (newStocks.length === 0) {
            setAlerts([{ type: 'warning', msg: '所选股票已全部在自选池中' }]);
            return;
        }
        setCustomStocks(prev => [...prev, ...newStocks]);
        setAlerts([{ type: 'success', msg: `✓ 已将 ${newStocks.length} 只股票加入自选池` }]);
        setSelectedCodes(new Set());
    };

    // 统一翻页逻辑
    const goToPage = async (page) => {
        if (page === currentPage || page < 1 || page > totalPages) return;
        setLoading(true);
        try {
            const payload = { page_size: PAGE_SIZE, page };
            if (selectedIndustries.length > 0) payload.industries = selectedIndustries;
            if (filters.pe_max !== '') payload.pe_max = parseFloat(filters.pe_max);
            if (filters.pb_max !== '') payload.pb_max = parseFloat(filters.pb_max);
            if (filters.roe_min !== '') payload.roe_min = parseFloat(filters.roe_min);
            if (filters.revenue_yoy_min !== '') payload.revenue_yoy_min = parseFloat(filters.revenue_yoy_min);
            if (filters.net_profit_yoy_min !== '') payload.net_profit_yoy_min = parseFloat(filters.net_profit_yoy_min);
            if (filters.turnover_rate_min !== '') payload.turnover_rate_min = parseFloat(filters.turnover_rate_min);
            if (filters.net_inflow_min !== '') payload.net_inflow_min = parseFloat(filters.net_inflow_min);
            if (filters.pct_chg_min !== '') payload.pct_chg_min = parseFloat(filters.pct_chg_min);
            if (filters.pct_chg_max !== '') payload.pct_chg_max = parseFloat(filters.pct_chg_max);
            if (filters.gap_up) payload.gap_up = true;
            if (filters.holder_chg_max !== '') payload.holder_chg_max = parseFloat(filters.holder_chg_max);
            if (filters.max_list_days !== '' && filters.max_list_days != null) payload.max_list_days = parseInt(filters.max_list_days);
            if (filters.volume_ratio_min !== '' && filters.volume_ratio_min != null) payload.volume_ratio_min = parseFloat(filters.volume_ratio_min);
            if (filters.has_block_trade) payload.has_block_trade = true;
            if (filters.has_unlock) payload.has_unlock = true;
            if (filters.has_top_list) payload.has_top_list = true;
            if (filters.margin_chg_min !== '' && filters.margin_chg_min != null) payload.margin_chg_min = parseFloat(filters.margin_chg_min);
            if (indexFilter) payload.index_filter = indexFilter;
            if (sortBy !== 'sentiment') {
                payload.sort_by = sortBy;
                payload.sort_order = sortOrder;
            }
            const res = await screenerApi.screen(payload);
            setResults(res.stocks || []);
            setCurrentPage(res.page || page);
            setTotalPages(res.total_pages || 1);
            setSelectedCodes(new Set());
        } catch (e) {
            setAlerts([{ type: 'error', msg: `✗ 翻页失败: ${e.message}` }]);
        }
        setLoading(false);
    };

    // 页码序列
    const pageNumbers = (() => {
        const pages = [];
        let start = Math.max(1, currentPage - 2);
        let end = Math.min(totalPages, start + 4);
        start = Math.max(1, end - 4);
        for (let i = start; i <= end; i++) pages.push(i);
        return pages;
    })();

    return (
        <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-5 shadow-sm">
            <div className="flex items-center justify-between mb-4">
                <h4 className="text-sm font-semibold text-teal-400 flex items-center gap-2">
                    <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"></div>
                    筛选结果 · 共 {totalMatched || results.length} 只
                    <span className="text-slate-500 font-normal" title="筛选范围排除 B 股(9xx)、三板(4xx)、北交所(8xx)，与数据中台「股票数」统计口径不同">（已排除B股/三板/北交所）</span>
                </h4>
                <div className="flex items-center gap-3">
                    <select value={sortBy}
                        onChange={e => { setSortBy(e.target.value); }}
                        className="text-[11px] px-2 py-1.5 rounded-lg bg-slate-800 border border-slate-600/50 text-slate-300 focus:outline-none focus:border-emerald-500/50">
                        <option value="score">综合分</option>
                        <option value="pct_chg">涨跌幅</option>
                        <option value="amount">成交额</option>
                        <option value="pe">PE</option>
                        <option value="pb">PB</option>
                        <option value="roe">ROE</option>
                        <option value="revenue_yoy">营收同比</option>
                        <option value="net_profit_yoy">净利润同比</option>
                        <option value="turnover">换手率</option>
                        <option value="net_mf_amount">主力净流入</option>
                        <option value="total_mv">总市值</option>
                        <option value="holder_chg">股东变化</option>
                        <option value="margin_chg">融资变化</option>
                        <option value="sentiment">舆情</option>
                    </select>
                    <button onClick={() => setSortOrder(prev => prev === 'desc' ? 'asc' : 'desc')}
                        className="text-[11px] px-2 py-1.5 rounded-lg bg-slate-800/70 border border-slate-600/50 text-slate-300 hover:bg-slate-700/50 transition-all"
                        title={sortOrder === 'desc' ? '降序' : '升序'}>
                        {sortOrder === 'desc' ? '↓ 降序' : '↑ 升序'}
                    </button>
                    <button onClick={toggleSelectAll}
                        className="text-[11px] px-3 py-1.5 rounded-lg bg-slate-700/50 text-slate-300 border border-slate-600/50 hover:bg-slate-600/50 transition-all font-medium">
                        {selectedCodes.size === results.length ? '取消全选' : '全选'}
                    </button>
                    <button onClick={addToPool} disabled={selectedCodes.size === 0}
                        className="text-xs px-4 py-1.5 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/30 font-medium transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5">
                        <Plus className="w-3.5 h-3.5" />
                        加入自选池 ({selectedCodes.size})
                    </button>
                    <button onClick={() => { setResults([]); setSelectedCodes(new Set()); setTotalMatched(0); setCurrentPage(1); }}
                        className="text-[11px] px-3 py-1.5 rounded-lg bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-all">
                        清空结果
                    </button>
                    {/* 列可见性选择器 */}
                    <div className="relative" ref={colPickerRef}>
                        <button onClick={() => setShowColPicker(p => !p)}
                            className={`text-[11px] px-2 py-1.5 rounded-lg border transition-all ${showColPicker ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' : 'bg-slate-800/70 border-slate-600/50 text-slate-300 hover:bg-slate-700/50'}`}
                            title="自定义显示列">
                            ☰ 列 ({visibleCols.size}/{COLUMN_DEFS.length})
                        </button>
                        {showColPicker && (
                            <div className="absolute right-0 top-9 z-50 w-56 bg-slate-800 border border-slate-600/50 rounded-xl shadow-2xl p-3 animate-in fade-in slide-in-from-top-1">
                                <div className="flex items-center justify-between mb-2 pb-2 border-b border-slate-700/50">
                                    <span className="text-xs text-slate-400 font-medium">显示列</span>
                                    <div className="flex gap-1.5">
                                        <button onClick={() => { const all = new Set(COLUMN_DEFS.map(c => c.key)); setVisibleCols(all); localStorage.setItem(STORAGE_KEY, JSON.stringify([...all])); }}
                                            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors">全选</button>
                                        <button onClick={() => { setVisibleCols(new Set(DEFAULT_VISIBLE)); localStorage.removeItem(STORAGE_KEY); }}
                                            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600 transition-colors">默认</button>
                                    </div>
                                </div>
                                <div className="max-h-64 overflow-y-auto space-y-0.5">
                                    {[...new Set(COLUMN_DEFS.map(c => c.group))].map(group => (
                                        <div key={group}>
                                            <div className="text-[10px] text-slate-500 font-medium mt-1.5 mb-0.5">{group}</div>
                                            {COLUMN_DEFS.filter(c => c.group === group).map(col => (
                                                <div key={col.key} onClick={() => toggleCol(col.key)}
                                                    className="flex items-center gap-2 py-1 px-1 rounded hover:bg-slate-700/50 cursor-pointer transition-colors">
                                                    <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center transition-all ${isVisible(col.key) ? 'bg-indigo-500 border-indigo-400' : 'border-slate-500 bg-slate-700'}`}>
                                                        {isVisible(col.key) && <Check className="w-2.5 h-2.5 text-white" />}
                                                    </div>
                                                    <span className="text-xs text-slate-300">{col.label}</span>
                                                </div>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>

            <div className="overflow-x-auto max-h-[500px] border border-slate-700/40 rounded-xl rounded-t-none">
                <table className="w-full text-sm text-left relative">
                    <thead className="sticky top-0 z-10 bg-slate-800/90 backdrop-blur-sm shadow-sm">
                        <tr className="text-slate-400 border-b border-slate-700/50">
                            <th className="py-3 pl-3 w-10"></th>
                            <th className="py-3 font-medium">代码</th>
                            <th className="py-3 font-medium">名称</th>
                            {isVisible('industry') && <th className="py-3 font-medium">行业</th>}
                            {isVisible('score') && <th className="py-3 text-right font-medium cursor-help" title="综合评分 = 因子模型评分（优先）或基础评分 ROE(40%)+低PE(30%)+成长(30%)">评分</th>}
                            {isVisible('close') && <th className="py-3 text-right font-medium">最新价</th>}
                            {isVisible('pct_chg') && <th className="py-3 text-right font-medium">涨跌%</th>}
                            {isVisible('amount') && <th className="py-3 text-right font-medium">成交额(万)</th>}
                            {isVisible('volume') && <th className="py-3 text-right font-medium">成交量(手)</th>}
                            {isVisible('pe_ttm') && <th className="py-3 text-right font-medium cursor-help" title="市盈率(TTM) = 股价/近四季度每股收益，越低越便宜，负值表示亏损">PE(TTM)</th>}
                            {isVisible('pb') && <th className="py-3 text-right font-medium cursor-help" title="市净率 = 股价/每股净资产，<1表示破净，越低安全边际越高">PB</th>}
                            {isVisible('roe') && <th className="py-3 text-right font-medium cursor-help" title="净资产收益率 = 净利润/净资产，衡量盈利能力，>15%一般认为优秀">ROE(%)</th>}
                            {isVisible('eps') && <th className="py-3 text-right font-medium cursor-help" title="每股收益 = 净利润/总股本，反映每股创造的利润，越高越好">EPS</th>}
                            {isVisible('revenue_yoy') && <th className="py-3 text-right font-medium cursor-help" title="营业收入较去年同期增长比率，来自最新季报">营收同比(%)</th>}
                            {isVisible('net_profit_yoy') && <th className="py-3 text-right font-medium cursor-help" title="净利润较去年同期增长比率，来自最新季报">净利润同比(%)</th>}
                            {isVisible('turnover_rate') && <th className="py-3 text-right font-medium cursor-help" title="当日成交量/流通股本×100%，衡量交易活跃度">换手率(%)</th>}
                            {isVisible('net_mf_amount') && <th className="py-3 text-right font-medium cursor-help" title="大单+特大单资金净流入额，正值=主力买入，负值=主力卖出">主力净流入(万)</th>}
                            {isVisible('total_mv') && <th className="py-3 text-right font-medium">总市值(亿)</th>}
                            {isVisible('holder_chg') && <th className="py-3 text-right font-medium cursor-help" title="股东户数季度环比变化率，负值=筹码集中">股东变化(%)</th>}
                            {isVisible('trend') && <th className="py-3 text-center font-medium cursor-help" title="技术面趋势判定，点击查看K线">趋势</th>}
                            {isVisible('sentiment') && <th className="py-3 text-center font-medium cursor-help" title="近7天新闻情绪汇总">舆情</th>}
                            <th className="py-3 text-center font-medium pr-3">操作</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/30">
                        {(sortBy === 'sentiment'
                            ? [...results].sort((a, b) => {
                                const sa = sentimentMap[a.code]?.avg ?? 0;
                                const sb = sentimentMap[b.code]?.avg ?? 0;
                                return sortOrder === 'desc' ? sb - sa : sa - sb;
                            })
                            : results
                        ).map((s) => {
                            const checked = selectedCodes.has(s.code);
                            const inPool = customStocks.some(cs => cs.code === s.code);
                            return (
                                <tr key={s.code}
                                    onClick={() => toggleSelectCode(s.code)}
                                    className={`relative group cursor-pointer transition-colors
                                        ${checked ? 'bg-emerald-900/20' : 'hover:bg-slate-700/40'}`}
                                    style={{ borderLeft: '2px solid transparent' }}
                                    onMouseEnter={e => e.currentTarget.style.borderLeft = '2px solid #34d399'}
                                    onMouseLeave={e => e.currentTarget.style.borderLeft = '2px solid transparent'}>
                                    <td className="py-3 pl-3">
                                        <div className={`w-4 h-4 rounded border flex items-center justify-center transition-all
                                            ${checked ? 'bg-emerald-500 border-emerald-400' : 'border-slate-500 bg-slate-800/50 group-hover:border-emerald-500/50'}`}>
                                            {checked && <Check className="w-3 h-3 text-white" />}
                                        </div>
                                    </td>
                                    <td className="py-3">
                                        <span className="font-mono text-slate-300 text-xs tracking-wider">{s.code}</span>
                                    </td>
                                    <td className="py-3 text-white font-medium whitespace-nowrap">
                                        {s.name}
                                        {s.list_date && ((Date.now() - new Date(s.list_date)) / 86400000) < 365 && (
                                            <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-rose-900/40 text-rose-400 border border-rose-500/30"
                                                title={`上市日期 ${s.list_date}`}>新</span>
                                        )}
                                        {s.has_cb && (
                                            <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-orange-900/40 text-orange-400 border border-orange-500/30 cursor-pointer hover:bg-orange-500/20 transition-colors"
                                                title={`正股有可转债 ${s.cb_code}，点击查看K线`}
                                                onClick={(e) => { e.stopPropagation(); onViewKline && onViewKline(s.cb_code); }}>债</span>
                                        )}
                                        {etfLookup[s.code]?.length > 0 && (
                                            <div className="flex flex-wrap gap-1 mt-0.5">
                                                {etfLookup[s.code].map((etf, ei) => (
                                                    <span key={ei}
                                                        className="text-xs px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-300 border border-amber-500/20 cursor-pointer hover:bg-amber-500/20 transition-colors"
                                                        title={`点击查看 ${etf.name} K线 · ${etf.code}${etf.close ? ` ¥${etf.close}` : ''}`}
                                                        onClick={(e) => { e.stopPropagation(); onViewKline && onViewKline(etf.code); }}>
                                                        {etf.name || etf.code}
                                                        {etf.pct_chg != null && (
                                                            <span className={`ml-1 font-mono ${etf.pct_chg > 0 ? 'text-red-400' : etf.pct_chg < 0 ? 'text-green-400' : 'text-slate-400'}`}>
                                                                {etf.pct_chg > 0 ? '+' : ''}{etf.pct_chg}%
                                                            </span>
                                                        )}
                                                    </span>
                                                ))}
                                            </div>
                                        )}
                                        {isVisible('event_tags') && eventMap[s.code] && (
                                            <div className="flex flex-wrap gap-1 mt-0.5">
                                                {eventMap[s.code].block && (
                                                    <span className="text-[9px] px-1 py-0.5 rounded bg-indigo-900/40 text-indigo-400 border border-indigo-500/30" title="近5日有大宗交易">宗</span>
                                                )}
                                                {eventMap[s.code].unlock && (
                                                    <span className="text-[9px] px-1 py-0.5 rounded bg-purple-900/40 text-purple-400 border border-purple-500/30" title="近5日有解禁">禁</span>
                                                )}
                                                {eventMap[s.code].top && (
                                                    <span className="text-[9px] px-1 py-0.5 rounded bg-cyan-900/40 text-cyan-400 border border-cyan-500/30" title="近5日上龙虎榜">龙</span>
                                                )}
                                                {eventMap[s.code].margin_up != null && (
                                                    <span className={`text-[9px] px-1 py-0.5 rounded border ${eventMap[s.code].margin_up ? 'bg-blue-900/40 text-blue-400 border-blue-500/30' : 'bg-green-900/40 text-green-400 border-green-500/30'}`}
                                                        title={`融资余额${eventMap[s.code].margin_up ? '增加' : '减少'}`}>融{eventMap[s.code].margin_up ? '↑' : '↓'}</span>
                                                )}
                                            </div>
                                        )}
                                    </td>
                                    {isVisible('industry') && <td className="py-3 text-slate-400 text-xs whitespace-nowrap">{s.industry || '-'}</td>}
                                    {isVisible('score') && <td className="py-3 text-right">
                                        <span className="font-mono text-xs font-semibold text-amber-400">{(s.score || 0).toFixed(0)}</span>
                                    </td>}
                                    {isVisible('close') && <td className="py-3 text-right font-mono text-white">{s.close != null ? Number(s.close).toFixed(2) : '-'}</td>}
                                    {isVisible('pct_chg') && <td className={`py-3 text-right font-mono ${getColorClass(s.pct_chg, 'text-slate-400')}`}>{fmt(s.pct_chg, '%')}</td>}
                                    {isVisible('amount') && <td className="py-3 text-right font-mono text-slate-300">{s.amount != null ? Number(s.amount).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '-'}</td>}
                                    {isVisible('volume') && <td className="py-3 text-right font-mono text-slate-300">{s.volume != null ? Number(s.volume).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '-'}</td>}
                                    {isVisible('pe_ttm') && <td className="py-3 text-right font-mono text-slate-300">{fmt(s.pe_ttm)}</td>}
                                    {isVisible('pb') && <td className="py-3 text-right font-mono text-slate-300">{fmt(s.pb)}</td>}
                                    {isVisible('roe') && <td className="py-3 text-right font-mono text-slate-300">{fmt(s.roe)}</td>}
                                    {isVisible('eps') && <td className="py-3 text-right font-mono text-slate-300">{s.eps != null ? Number(s.eps).toFixed(2) : '-'}</td>}
                                    {isVisible('revenue_yoy') && <td className={`py-3 text-right font-mono ${getColorClass(s.revenue_yoy, 'text-slate-400')}`}>{fmt(s.revenue_yoy)}</td>}
                                    {isVisible('net_profit_yoy') && <td className={`py-3 text-right font-mono ${getColorClass(s.net_profit_yoy, 'text-slate-400')}`}>{fmt(s.net_profit_yoy)}</td>}
                                    {isVisible('turnover_rate') && <td className="py-3 text-right font-mono text-slate-300">{fmt(s.turnover_rate)}</td>}
                                    {isVisible('net_mf_amount') && <td className={`py-3 text-right font-mono ${getColorClass(s.net_mf_amount, 'text-slate-400')}`}>
                                        {s.net_mf_amount != null ? Number(s.net_mf_amount).toFixed(0) : '-'}
                                    </td>}
                                    {isVisible('total_mv') && <td className="py-3 text-right text-slate-300 font-mono">
                                        {s.total_mv != null ? (s.total_mv / 10000).toFixed(1) : '-'}
                                    </td>}
                                    {isVisible('holder_chg') && <td className={`py-3 text-right font-mono ${s.holder_chg != null && s.holder_chg < 0 ? 'text-red-400 font-medium' : s.holder_chg != null && s.holder_chg > 0 ? 'text-green-400' : 'text-slate-400'}`} title={s.holder_chg != null ? `股东户数变化${s.holder_chg > 0 ? '+' : ''}${Number(s.holder_chg).toFixed(1)}%` : ''}>{s.holder_chg != null ? `${Number(s.holder_chg).toFixed(1)}` : '-'}</td>}
                                    {isVisible('trend') && <td className="py-3 text-center">
                                        {diagMap[s.code] ? (
                                            <span className="text-xs" title={`技术分 ${diagMap[s.code].score} · ${diagMap[s.code].trend}`}>
                                                <span style={{ color: diagMap[s.code].trend_color }}>{diagMap[s.code].label}</span>
                                            </span>
                                        ) : <span className="text-slate-600 text-xs">···</span>}
                                    </td>}
                                    {isVisible('sentiment') && <td className="py-3 text-center">
                                        {sentimentMap[s.code] ? (
                                            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${sentimentMap[s.code].label === '利好' ? 'text-red-400 border-red-500/40 bg-red-500/15' :
                                                sentimentMap[s.code].label === '利空' ? 'text-green-400 border-green-500/40 bg-green-500/15' :
                                                    'text-slate-400 border-slate-500/40 bg-slate-500/10'
                                                }`} title={`${sentimentMap[s.code].count}条新闻 · 均分${sentimentMap[s.code].avg}`}>
                                                {sentimentMap[s.code].label}{sentimentMap[s.code].event ? `·${sentimentMap[s.code].event}` : ''} {sentimentMap[s.code].count}
                                            </span>
                                        ) : <span className="text-slate-600 text-[10px]">-</span>}
                                    </td>}
                                    <td className="py-3 text-center pr-3">
                                        <div className="flex items-center justify-center gap-1">
                                            {onViewKline && (
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); onViewKline(s.code); }}
                                                    className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all"
                                                    title={`查看 ${s.name} K线图`}>
                                                    📈
                                                </button>
                                            )}
                                            <button
                                                onClick={(e) => handleStockToEtf(e, s.code)}
                                                className={`text-[10px] px-1.5 py-1 rounded border transition-all ${etfLookup[s.code] ? 'bg-amber-600/30 text-amber-300 border-amber-500/30' : 'bg-slate-600/30 text-slate-400 border-slate-500/30 hover:bg-amber-600/20'}`}
                                                title="查找关联ETF">
                                                🏷
                                            </button>
                                            <button
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    if (inPool) {
                                                        setCustomStocks(prev => prev.filter(cs => cs.code !== s.code));
                                                    } else {
                                                        setCustomStocks(prev => [...prev, makePoolItem(s.code, s.name, {
                                                            industry: s.industry || '',
                                                        })]);
                                                    }
                                                }}
                                                className={`text-[10px] px-1.5 py-1 rounded border transition-all ${inPool
                                                    ? 'bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30'
                                                    : 'bg-emerald-600/30 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/50'}`}
                                                title={inPool ? '点击移出自选池' : '加入自选池'}>
                                                {inPool ? '✓' : '➕'}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {/* 分页控件 */}
            {totalPages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-700/30">
                    <span className="text-xs text-slate-500">
                        共 {totalMatched} 只 | 第 {currentPage}/{totalPages} 页
                    </span>
                    <div className="flex items-center gap-1.5">
                        <button disabled={currentPage <= 1 || loading}
                            onClick={() => goToPage(currentPage - 1)}
                            className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 border border-slate-600/50 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                            ← 上一页
                        </button>
                        {pageNumbers.map(p => (
                            <button key={p} disabled={loading}
                                onClick={() => goToPage(p)}
                                className={`w-8 h-8 text-xs rounded-lg border transition-all ${p === currentPage
                                    ? 'bg-emerald-500/20 border-emerald-500/50 text-emerald-400 font-bold'
                                    : 'bg-slate-800 border-slate-600/50 text-slate-300 hover:bg-slate-700'
                                    }`}>
                                {p}
                            </button>
                        ))}
                        <button disabled={currentPage >= totalPages || loading}
                            onClick={() => goToPage(currentPage + 1)}
                            className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 border border-slate-600/50 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                            下一页 →
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

export default ResultTable;
