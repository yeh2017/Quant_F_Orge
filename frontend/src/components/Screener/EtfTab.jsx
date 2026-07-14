import React, { useState, useEffect, useRef } from 'react';
import { Search as SearchIcon } from 'lucide-react';
import { RefreshCw, Search, Check } from 'lucide-react';
import { makePoolItem } from '../../utils/poolActions';
import { screenerApi } from '../../services/api';

// ETF→个股联动卡片（双栏布局，对齐弱转强面板样式）
const EtfStockLinkCard = ({ screenerApi, onViewKline }) => {
    const [linkData, setLinkData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [show, setShow] = useState(false);

    const fetchLink = async () => {
        setLoading(true);
        try {
            const res = await screenerApi.getEtfStockLink(1.5);
            setLinkData(res);
        } catch { /* 忽略加载失败 */ } finally { setLoading(false); }
    };

    // 将 links 按行业展平为个股列表
    const flattenLinks = (links) => {
        if (!links?.length) return [];
        const stocks = [];
        for (const link of links) {
            for (const s of (link.stocks || [])) {
                stocks.push({
                    ...s,
                    industry: link.industry,
                    etfCode: link.etf?.code,
                    etfName: link.etf?.name,
                    etfChg: link.etf?.pct_chg,
                    volumeRatio: link.etf?.volume_ratio,
                });
            }
        }
        return stocks;
    };

    // 4栏数据：今日上涨、今日下跌、5日上涨、5日下跌
    const todayBull = flattenLinks(linkData?.today_links).slice(0, 6);
    const todayBear = flattenLinks(linkData?.today_warnings).slice(0, 6);
    const weekBull = flattenLinks(linkData?.week_links).slice(0, 6);
    const weekBear = flattenLinks(linkData?.week_warnings).slice(0, 6);

    const hasData = todayBull.length > 0 || todayBear.length > 0 || weekBull.length > 0 || weekBear.length > 0;

    const LinkCol = ({ title, items, titleColor, bgClass, borderClass, chgColor }) => (
        <div className={`${bgClass} ${borderClass} border rounded-xl p-2.5`}>
            <h3 className={`text-sm font-bold ${titleColor} mb-2`}>{title}</h3>
            {items.length > 0 ? (
                <div className="space-y-0.5">
                    {items.map((s, i) => (
                        <div key={`${s.code}-${i}`} className="flex items-center justify-between bg-slate-800/40 rounded px-2 py-1.5 hover:bg-slate-700/40 transition-colors">
                            <div className="min-w-0 flex-1">
                                <div className="truncate text-sm font-medium">
                                    {onViewKline ? (
                                        <span className="text-white hover:text-indigo-400 cursor-pointer transition-colors"
                                            onClick={() => onViewKline(s.code)}
                                            title={`查看 ${s.name} K线图`}>{s.name}</span>
                                    ) : (
                                        <span className="text-white">{s.name}</span>
                                    )}
                                    {s.is_leader && <span className="text-[10px] ml-1" title="成交额龙头">🏆</span>}
                                </div>
                                <span className="text-xs text-white/80 font-mono">{s.code}</span>
                            </div>
                            <div className="text-right shrink-0 ml-2">
                                {s.etfCode && onViewKline ? (
                                    <span className="text-xs text-white hover:text-indigo-400 cursor-pointer transition-colors"
                                        onClick={() => onViewKline(s.etfCode)}
                                        title={`查看 ${s.etfName} K线图`}>{s.etfName}</span>
                                ) : (
                                    <div className="text-xs text-white">{s.etfName}</div>
                                )}
                                <div className={`text-sm font-mono font-bold ${chgColor}`}>
                                    {s.pct_chg > 0 ? '+' : ''}{s.pct_chg}%
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <div className="text-[10px] text-slate-500 text-center py-3">暂无</div>
            )}
        </div>
    );

    return (
        <div className="bg-slate-800/40 rounded-xl border border-slate-700/30 p-4">
            <button onClick={() => { setShow(v => !v); if (!linkData && !loading) fetchLink(); }}
                className="w-full flex items-center justify-between text-sm font-bold text-white/80">
                <span>⚡ ETF→个股联动 <span className="text-xs text-slate-500 font-normal">放量ETF推荐同行业个股</span></span>
                <span className="text-xs text-slate-400">{show ? '▲ 收起' : '▼ 展开'}</span>
            </button>
            {show && (
                <div className="mt-3">
                    {loading ? (
                        <div className="text-center text-slate-400 py-6"><RefreshCw className="w-4 h-4 animate-spin inline mr-2" />加载中...</div>
                    ) : hasData ? (
                        <>
                            <div className="grid grid-cols-4 gap-3">
                                <LinkCol title="📈 当日涨幅 Top" items={todayBull}
                                    titleColor="text-red-400" chgColor="text-red-400"
                                    bgClass="bg-red-500/5" borderClass="border-red-500/20" />
                                <LinkCol title="📉 当日跌幅 Top" items={todayBear}
                                    titleColor="text-green-400" chgColor="text-green-400"
                                    bgClass="bg-green-500/5" borderClass="border-green-500/20" />
                                <LinkCol title="🔥 5日涨幅 Top" items={weekBull}
                                    titleColor="text-red-400" chgColor="text-red-400"
                                    bgClass="bg-red-500/5" borderClass="border-red-500/20" />
                                <LinkCol title="❄️ 5日跌幅 Top" items={weekBear}
                                    titleColor="text-green-400" chgColor="text-green-400"
                                    bgClass="bg-green-500/5" borderClass="border-green-500/20" />
                            </div>
                        </>
                    ) : (
                        <div className="text-center text-slate-500 py-4 text-sm">暂无联动数据</div>
                    )}
                </div>
            )}
        </div>
    );
};

// ── 市场总览状态条 ──
const EtfOverviewBar = ({ etfOverview }) => {
    if (!etfOverview?.overview) return null;
    const ov = etfOverview.overview;
    if (!ov.total) return null;

    const colorMap = {
        green: { bg: 'bg-green-500/10', border: 'border-green-500/30', text: 'text-green-400', bar: 'bg-green-500' },
        emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', bar: 'bg-emerald-500' },
        amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', bar: 'bg-amber-500' },
        orange: { bg: 'bg-orange-500/10', border: 'border-orange-500/30', text: 'text-orange-400', bar: 'bg-orange-500' },
        red: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', bar: 'bg-red-500' },
        slate: { bg: 'bg-slate-500/10', border: 'border-slate-500/30', text: 'text-slate-400', bar: 'bg-slate-500' },
    };
    const c = colorMap[ov.regime_color] || colorMap.slate;
    const upRatio = Math.round(ov.up / Math.max(ov.total, 1) * 100);

    return (
        <div className={`${c.bg} ${c.border} border rounded-xl p-4 flex items-center gap-6`}>
            <div className="flex items-center gap-2 shrink-0">
                <span className="text-lg">{ov.regime_icon}</span>
                <div>
                    <div className={`text-lg font-bold ${c.text}`}>{ov.regime}</div>
                    <div className="text-xs text-white/80">{ov.trade_date}</div>
                </div>
            </div>
            <div className="shrink-0 text-center">
                <div className={`text-2xl font-black font-mono ${c.text}`}>{ov.score}</div>
                <div className="text-xs text-white/80">综合分</div>
            </div>
            <div className="w-px h-10 bg-slate-700/50 shrink-0" />
            <div className="flex-1 grid grid-cols-3 gap-4">
                {/* 市场广度 */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-white/90">市场广度</span>
                        <span className={`text-xs font-mono font-bold ${upRatio >= 55 ? 'text-green-400' : upRatio >= 45 ? 'text-amber-400' : 'text-red-400'}`}>
                            {upRatio}
                        </span>
                    </div>
                    <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all duration-500 ${upRatio >= 55 ? 'bg-green-500' : upRatio >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                            style={{ width: `${upRatio}%` }} />
                    </div>
                    <div className="text-xs text-white/80 mt-0.5">涨{ov.up} / 跌{ov.down} / 平{ov.flat}</div>
                </div>
                {/* 平均涨跌 */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-white/90">平均涨跌</span>
                        <span className={`text-xs font-mono font-bold ${ov.avg_pct > 0 ? 'text-red-400' : ov.avg_pct < 0 ? 'text-green-400' : 'text-slate-400'}`}>
                            {ov.avg_pct > 0 ? '+' : ''}{ov.avg_pct}%
                        </span>
                    </div>
                    <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                        <div className={`h-full rounded-full transition-all duration-500 ${ov.avg_pct > 0 ? 'bg-red-500' : 'bg-green-500'}`}
                            style={{ width: `${Math.min(100, Math.abs(ov.avg_pct) * 20 + 50)}%` }} />
                    </div>
                    <div className="text-xs text-white/80 mt-0.5">全市场 ETF 均值</div>
                </div>
                {/* 成交额 */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-white/90">成交额</span>
                        <span className="text-xs font-mono font-bold text-cyan-400">
                            {(ov.total_amount / 1e5).toFixed(1)}亿
                        </span>
                    </div>
                    <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                        <div className="h-full rounded-full bg-cyan-500 transition-all duration-500" style={{ width: '60%' }} />
                    </div>
                    <div className="text-[11px] text-white/60 mt-0.5">共 {ov.total} 只 ETF</div>
                </div>
            </div>
        </div>
    );
};

// ── 分类涨跌热力图 ──
const CategoryHeatMap = ({ categoryHeat }) => {
    if (!categoryHeat?.length) return null;
    return (
        <div className="bg-slate-800/40 rounded-xl border border-slate-700/30 p-4">
            <h3 className="text-sm font-bold text-white/80 mb-3">🗺️ 分类涨跌热力图</h3>
            <div className="flex gap-3">
                {categoryHeat.map(cat => {
                    const pct = cat.avg_pct;
                    const bgColor = pct > 1 ? 'bg-red-500/30 border-red-500/40'
                        : pct > 0.3 ? 'bg-red-500/15 border-red-500/25'
                            : pct > -0.3 ? 'bg-slate-700/40 border-slate-600/40'
                                : pct > -1 ? 'bg-green-500/15 border-green-500/25'
                                    : 'bg-green-500/30 border-green-500/40';
                    return (
                        <div key={cat.category} className={`${bgColor} border rounded-xl p-3 text-center transition-all hover:scale-[1.02] flex-1 min-w-0`}>
                            <div className="flex items-center justify-center gap-2">
                                <span className="text-base font-bold text-white">{cat.category}</span>
                                <span className={`text-base font-black font-mono ${pct > 0 ? 'text-red-400' : pct < 0 ? 'text-green-400' : 'text-slate-400'}`}>
                                    {pct > 0 ? '+' : ''}{pct}%
                                </span>
                            </div>
                            <div className="text-sm text-white/70 mt-1.5 truncate" title={`涨${cat.up} 跌${cat.down} · 共${cat.total}只`}>
                                <span className="text-red-400">涨{cat.up}</span>/<span className="text-green-400">跌{cat.down}</span> · {cat.total}只
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// ── 通用 ETF 排行卡片 ──
const RankCard = ({ title, subtitle, items, valueKey, bgClass, borderClass, textClass, emptyMsg, customStocks, setCustomStocks, stockW2sIndustries, onViewKline }) => (
    <div className={`${bgClass} ${borderClass} border rounded-xl p-3`}>
        <h3 className={`text-sm font-bold ${textClass} mb-2 flex items-center gap-1.5`}>
            {title}
            {subtitle && <span className="text-[11px] text-white/60 font-normal">{subtitle}</span>}
        </h3>
        <div className="space-y-0.5">
            {(items || []).length > 0 ? items.map(s => {
                const inPool = customStocks.some(cs => cs.code === s.code);
                const val = s[valueKey];
                const matchedInd = s.industry || null;
                const hasCross = matchedInd && stockW2sIndustries.has(matchedInd);
                return (
                    <div key={s.code} className="flex items-center justify-between bg-slate-800/40 rounded-lg px-3 py-1 hover:bg-slate-700/40 transition-colors">
                        <div className="min-w-0 flex-1">
                            <div className="truncate text-sm text-white font-medium" title={`${s.name} ${s.code}`}>{s.name}</div>
                            <div className="flex items-center gap-1.5 mt-0.5">
                                <span className="text-xs text-white/80 font-mono">{s.code}</span>
                                {s.category && <span className="text-[11px] px-1.5 py-0.5 rounded bg-slate-700/60 text-white/80">{s.category}</span>}
                                {hasCross && <span className="text-[11px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 animate-pulse">🔥 双重确认</span>}
                            </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                            <span className={`font-mono font-bold text-sm ${val > 0 ? 'text-red-400' : val < 0 ? 'text-green-400' : 'text-slate-400'}`}>
                                {val > 0 ? '+' : ''}{val}%
                            </span>
                            {onViewKline && <button onClick={() => onViewKline(s.code)}
                                className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all"
                                title={`查看 ${s.name} K线图`}>📈</button>}
                            <button onClick={() => inPool ? setCustomStocks(prev => prev.filter(cs => cs.code !== s.code)) : setCustomStocks(prev => [...prev, makePoolItem(s.code, s.name)])}
                                className={`text-[10px] px-1.5 py-1 rounded border transition-all ${inPool ? 'bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30' : 'bg-emerald-600/30 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/50'}`}
                                title={inPool ? '点击移出自选池' : '加入自选池'}>{inPool ? '✓' : '➕'}</button>
                        </div>
                    </div>
                );
            }) : <div className="text-slate-500 text-xs text-center py-3">{emptyMsg || '暂无数据'}</div>}
        </div>
    </div>
);

// ── 智能筛选结果表 ──
// ETF 可切换列定义（固定列：代码/名称/操作 不在此列表中）
const ETF_COLUMN_DEFS = [
    { key: 'category',      label: '分类',      group: '基本' },
    { key: 'score',          label: '综合分',    group: '评分' },
    { key: 'close',          label: '最新价',    group: '行情' },
    { key: 'pct_chg',        label: '涨跌%',     group: '行情' },
    { key: 'avg_amount_20d', label: '成交额(万)', group: '行情' },
    { key: 'premium',        label: '溢价率%',   group: '净值' },
    { key: 'unit_nav',       label: '净值',      group: '净值' },
    { key: 'nav_date',       label: '净值日期',  group: '净值' },
    { key: 'total_share',    label: '份额(万份)',   group: '规模' },
    { key: 'size_chg',       label: '规模变化(亿元)', group: '规模' },
    { key: 'total_size',     label: '规模(亿元)',   group: '规模' },
    { key: 'pct_chg_20d',    label: '近1月',     group: '涨幅' },
    { key: 'pct_chg_1y',     label: '近1年',     group: '涨幅' },
    { key: 'benchmark',      label: '跟踪指数',  group: '基本' },
    { key: 'reversal',       label: '信号',      group: '评分' },
];

// 默认显示：溢价率+规模 可见，净值/净值日期/份额/规模变化 隐藏
const _DEFAULT_HIDDEN = new Set(['unit_nav', 'nav_date', 'total_share', 'size_chg']);
const DEFAULT_ETF_VISIBLE = new Set(ETF_COLUMN_DEFS.filter(c => !_DEFAULT_HIDDEN.has(c.key)).map(c => c.key));
const ETF_COL_STORAGE_KEY = 'etf_screener_visible_cols';
const ETF_VALID_KEYS = new Set(ETF_COLUMN_DEFS.map(c => c.key));

const loadEtfVisibleCols = () => {
    const SCHEMA_VERSION = 2; // 每次新增列时 +1（v1=原始列, v2=新增6列净值/份额/规模）
    try {
        const saved = localStorage.getItem(ETF_COL_STORAGE_KEY);
        if (saved) {
            const parsed = JSON.parse(saved).filter(k => ETF_VALID_KEYS.has(k));
            if (parsed.length > 0) {
                const s = new Set(parsed);
                const savedVer = parseInt(localStorage.getItem(ETF_COL_STORAGE_KEY + '_ver') || '0');
                if (savedVer < SCHEMA_VERSION) {
                    // 一次性合并：把新增的默认可见列补入
                    for (const k of DEFAULT_ETF_VISIBLE) {
                        if (!s.has(k)) s.add(k);
                    }
                    localStorage.setItem(ETF_COL_STORAGE_KEY, JSON.stringify([...s]));
                    localStorage.setItem(ETF_COL_STORAGE_KEY + '_ver', String(SCHEMA_VERSION));
                }
                return s;
            }
        }
    } catch { /* ignore */ }
    localStorage.setItem(ETF_COL_STORAGE_KEY + '_ver', String(SCHEMA_VERSION));
    return new Set(DEFAULT_ETF_VISIBLE);
};

const EtfSmartTable = ({ etfSmart, etfSortKey, etfSortDir, setEtfSortKey, setEtfSortDir, customStocks, setCustomStocks, etfCategory, etfSearch, onViewKline }) => {
    // ── Hooks 必须在所有条件返回之前 ──
    const [addAllStatus, setAddAllStatus] = React.useState(null);
    const addAllTimerRef = React.useRef(null);
    const [visibleCols, setVisibleCols] = React.useState(loadEtfVisibleCols);
    const [showColPicker, setShowColPicker] = React.useState(false);
    const colPickerRef = React.useRef(null);
    const [currentPage, setCurrentPage] = React.useState(1);

    const toggleCol = (key) => {
        setVisibleCols(prev => {
            const next = new Set(prev);
            next.has(key) ? next.delete(key) : next.add(key);
            localStorage.setItem(ETF_COL_STORAGE_KEY, JSON.stringify([...next]));
            return next;
        });
    };
    const isV = (key) => visibleCols.has(key);

    React.useEffect(() => {
        if (!showColPicker) return;
        const h = (e) => { if (colPickerRef.current && !colPickerRef.current.contains(e.target)) setShowColPicker(false); };
        document.addEventListener('mousedown', h);
        return () => document.removeEventListener('mousedown', h);
    }, [showColPicker]);

    React.useEffect(() => { setCurrentPage(1); }, [etfSortKey, etfSortDir, etfCategory, etfSmart?.etfs?.length, etfSearch]);

    // ── 条件返回（hooks 之后）──
    if (!etfSmart?.etfs?.length) return null;

    // 按分类 + 搜索关键词过滤
    let filtered = etfCategory
        ? etfSmart.etfs.filter(e => e.category === etfCategory)
        : etfSmart.etfs;
    if (etfSearch) {
        const kw = etfSearch.toLowerCase();
        filtered = filtered.filter(e => (e.name || '').toLowerCase().includes(kw) || (e.code || '').includes(kw));
    }
    if (!filtered.length) return (
        <div className="bg-slate-800/60 rounded-xl border border-teal-500/20 p-8 text-center text-slate-500">
            {etfSearch
                ? `未找到「${etfSearch}」相关 ETF${etfCategory ? `（分类: ${etfCategory}）` : ''}，请尝试其他关键词`
                : `当前分类「${etfCategory}」下无匹配结果，请尝试其他分类或点击「🧠 一键智能」查看全市场`}
        </div>
    );

    const toggleSort = (key) => {
        if (etfSortKey === key) {
            setEtfSortDir(d => d === 'desc' ? 'asc' : 'desc');
        } else {
            setEtfSortKey(key);
            setEtfSortDir('desc');
        }
    };
    const arrow = (key) => etfSortKey === key ? (etfSortDir === 'desc' ? ' ▼' : ' ▲') : '';
    const sorted = [...filtered].sort((a, b) => {
        const va = a[etfSortKey] ?? 0, vb = b[etfSortKey] ?? 0;
        return etfSortDir === 'desc' ? vb - va : va - vb;
    });

    const SortTh = ({ k, label, align = 'right', title }) => (
        <th onClick={() => toggleSort(k)} title={title}
            className={`text-${align} py-2 px-2 cursor-pointer select-none hover:text-white transition-colors ${etfSortKey === k ? 'text-teal-400' : ''}`}>
            {label}{arrow(k)}
        </th>
    );

    const PAGE_SIZE = 50;
    const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
    const paged = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);



    const pageNumbers = (() => {
        const pages = [];
        let start = Math.max(1, currentPage - 2);
        let end = Math.min(totalPages, start + 4);
        start = Math.max(1, end - 4);
        for (let i = start; i <= end; i++) pages.push(i);
        return pages;
    })();

    return (
        <div className="bg-slate-800/60 rounded-xl border border-teal-500/20 p-4">
            <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-semibold text-teal-400" title="已排除近20日交易不足5天或日均成交额＜100万的低流动性品种">✨ 智能筛选 · 共 {sorted.length} 只{etfSmart?.filtered_out > 0 && <span className="text-slate-500 font-normal">（{etfSmart.filtered_out} 只因成交额不足未展示）</span>}{etfCategory ? ` · ${etfCategory}` : ''}</h4>
                <div className="flex items-center gap-3">
                    <button onClick={() => {
                        const existCodes = new Set(customStocks.map(s => s.code));
                        const newItems = sorted.filter(e => !existCodes.has(e.code)).map(e => makePoolItem(e.code, e.name));
                        clearTimeout(addAllTimerRef.current);
                        if (newItems.length > 0) {
                            setCustomStocks(prev => [...prev, ...newItems]);
                            setAddAllStatus(`✓ 已加入 ${newItems.length} 只`);
                        } else {
                            setAddAllStatus('全部已在自选池中');
                        }
                        addAllTimerRef.current = setTimeout(() => setAddAllStatus(null), 2000);
                    }}
                        className={`text-xs px-3 py-1.5 rounded-lg transition-all shrink-0 border ${addAllStatus?.startsWith('✓')
                                ? 'bg-emerald-500/30 text-emerald-300 border-emerald-500/40'
                                : addAllStatus
                                    ? 'bg-slate-700/50 text-slate-400 border-slate-600/30'
                                    : 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30 hover:bg-emerald-500/30'
                            }`}>
                        {addAllStatus || '全部加入自选池'}
                    </button>
                    {/* 列显隐选择器 */}
                    <div className="relative" ref={colPickerRef}>
                        <button onClick={() => setShowColPicker(p => !p)}
                            className={`text-[11px] px-2 py-1.5 rounded-lg border transition-all ${showColPicker ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-300' : 'bg-slate-800/70 border-slate-600/50 text-slate-300 hover:bg-slate-700/50'}`}
                            title="自定义显示列">☰ 列 ({visibleCols.size}/{ETF_COLUMN_DEFS.length})</button>
                        {showColPicker && (
                            <div className="absolute right-0 top-9 z-50 w-52 bg-slate-800 border border-slate-600/50 rounded-xl shadow-2xl p-3">
                                <div className="flex items-center justify-between mb-2 pb-2 border-b border-slate-700/50">
                                    <span className="text-xs text-slate-400 font-medium">显示列</span>
                                    <div className="flex gap-1.5">
                                        <button onClick={() => { const all = new Set(ETF_COLUMN_DEFS.map(c => c.key)); setVisibleCols(all); localStorage.setItem(ETF_COL_STORAGE_KEY, JSON.stringify([...all])); }}
                                            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600">全选</button>
                                        <button onClick={() => { setVisibleCols(new Set(DEFAULT_ETF_VISIBLE)); localStorage.removeItem(ETF_COL_STORAGE_KEY); }}
                                            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600">默认</button>
                                    </div>
                                </div>
                                <div className="max-h-64 overflow-y-auto space-y-0.5">
                                    {[...new Set(ETF_COLUMN_DEFS.map(c => c.group))].map(group => (
                                        <div key={group}>
                                            <div className="text-[10px] text-slate-500 font-medium mt-1.5 mb-0.5">{group}</div>
                                            {ETF_COLUMN_DEFS.filter(c => c.group === group).map(col => (
                                                <div key={col.key} onClick={() => toggleCol(col.key)}
                                                    className="flex items-center gap-2 py-1 px-1 rounded hover:bg-slate-700/50 cursor-pointer transition-colors">
                                                    <div className={`w-3.5 h-3.5 rounded border flex items-center justify-center transition-all ${isV(col.key) ? 'bg-indigo-500 border-indigo-400' : 'border-slate-500 bg-slate-700'}`}>
                                                        {isV(col.key) && <Check className="w-2.5 h-2.5 text-white" />}
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
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead>
                        <tr className="text-slate-400 border-b border-slate-700/50">
                            <th className="text-left py-2 px-2">代码</th>
                            <th className="text-left py-2 px-2">名称</th>
                            {isV('category') && <th className="text-center py-2 px-2">分类</th>}
                            {isV('score') && <SortTh k="score" label="综合分" title="趋势(70%) + 活跃度(20%) + 今日动量(10%)，经回测验证" />}
                            {isV('close') && <SortTh k="close" label="最新价" />}
                            {isV('pct_chg') && <SortTh k="pct_chg" label="涨跌%" />}
                            {isV('avg_amount_20d') && <SortTh k="avg_amount_20d" label="成交额(万)" title="近20个交易日日均成交额" />}
                            {isV('premium') && <SortTh k="premium" label="溢价率%" title="收盘价/单位净值-1，正值=溢价，负值=折价" />}
                            {isV('unit_nav') && <SortTh k="unit_nav" label="净值" />}
                            {isV('nav_date') && <th className="text-center py-2 px-2">净值日期</th>}
                            {isV('total_share') && <SortTh k="total_share" label="份额(万份)" />}
                            {isV('size_chg') && <SortTh k="size_chg" label="规模变化(亿元)" title="对比约20个交易日前的规模变化，含份额申赎+净值涨跌双重影响" />}
                            {isV('total_size') && <SortTh k="total_size" label="规模(亿元)" />}
                            {isV('pct_chg_20d') && <SortTh k="pct_chg_20d" label="近1月" />}
                            {isV('pct_chg_1y') && <SortTh k="pct_chg_1y" label="近1年" />}
                            {isV('benchmark') && <th className="text-left py-2 px-2">跟踪指数</th>}
                            {isV('reversal') && <th className="text-center py-2 px-2" title="弱转强：近5日弱势今日反弹；强转弱：近5日强势今日回调">信号</th>}
                            <th className="text-center py-2 px-2">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {paged.map(e => (
                            <tr key={e.code} className="border-b border-slate-800/50 hover:bg-slate-700/30 transition-colors">
                                <td className="py-2 px-2 text-white font-mono text-xs">{e.code}</td>
                                <td className="py-2 px-2 text-slate-300 whitespace-nowrap">
                                    {e.name}
                                    {e.list_date && ((Date.now() - new Date(e.list_date)) / 86400000) < 365 && (
                                        <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-rose-900/40 text-rose-400 border border-rose-500/30"
                                            title={`上市日期 ${e.list_date}`}>新</span>
                                    )}
                                    {['跨境', '商品'].includes(e.category) && (
                                        <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-cyan-500/20 text-cyan-400 border border-cyan-500/30" title="支持 T+0 日内交易">T+0</span>
                                    )}
                                </td>
                                {isV('category') && <td className="py-2 px-2 text-center"><span className="text-xs px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-400">{e.category}</span></td>}
                                {isV('score') && <td className="py-2 px-2 text-right text-amber-400 font-semibold">{e.score}</td>}
                                {isV('close') && <td className="py-2 px-2 text-right text-white">{e.close}</td>}
                                {isV('pct_chg') && <td className={`py-2 px-2 text-right ${e.pct_chg > 0 ? 'text-red-400' : e.pct_chg < 0 ? 'text-green-400' : 'text-slate-400'}`}>{e.pct_chg > 0 ? '+' : ''}{e.pct_chg}%</td>}
                                {isV('avg_amount_20d') && <td className="py-2 px-2 text-right text-slate-400 font-mono">{e.avg_amount_20d != null ? (e.avg_amount_20d / 10).toLocaleString(undefined, { maximumFractionDigits: 0 }) : '-'}</td>}
                                {isV('premium') && <td className={`py-2 px-2 text-right ${e.premium != null ? (e.premium > 0 ? 'text-red-400' : e.premium < 0 ? 'text-green-400' : 'text-slate-400') : 'text-slate-400'}`}>{e.premium != null ? `${e.premium > 0 ? '+' : ''}${e.premium}%` : (e.unit_nav == null && (e.category === '跨境' || e.category === 'REITs') ? <span title={e.category === 'REITs' ? 'REITs 净值按季/月公布' : 'QDII 净值滞后 T+2'}>⏳</span> : '-')}</td>}
                                {isV('unit_nav') && <td className="py-2 px-2 text-right text-white">{e.unit_nav != null ? e.unit_nav.toFixed(4) : ((e.category === '跨境' || e.category === 'REITs') ? <span title={e.category === 'REITs' ? 'REITs 净值按季/月公布' : 'QDII 净值滞后 T+2'}>⏳</span> : '-')}</td>}
                                {isV('nav_date') && <td className="py-2 px-2 text-center text-slate-400 text-xs">{e.nav_date ? e.nav_date.slice(5) : '-'}</td>}
                                {isV('total_share') && <td className="py-2 px-2 text-right text-slate-400 font-mono">{e.total_share != null ? e.total_share.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '-'}</td>}
                                {isV('size_chg') && <td className={`py-2 px-2 text-right ${e.size_chg != null ? (e.size_chg > 0 ? 'text-red-400' : e.size_chg < 0 ? 'text-green-400' : 'text-slate-400') : 'text-slate-400'}`}>{e.size_chg != null ? `${e.size_chg > 0 ? '+' : ''}${e.size_chg}` : (e.unit_nav == null && (e.category === '跨境' || e.category === 'REITs') ? <span title={e.category === 'REITs' ? 'REITs 净值按季/月公布' : 'QDII 净值滞后 T+2'}>⏳</span> : '-')}</td>}
                                {isV('total_size') && <td className="py-2 px-2 text-right text-slate-400 font-mono">{e.total_size != null ? e.total_size.toLocaleString(undefined, { maximumFractionDigits: 2 }) : (e.unit_nav == null && (e.category === '跨境' || e.category === 'REITs') ? <span title={e.category === 'REITs' ? 'REITs 净值按季/月公布' : 'QDII 净值滞后 T+2'}>⏳</span> : '-')}</td>}
                                {isV('pct_chg_20d') && <td className={`py-2 px-2 text-right ${(e.pct_chg_20d || 0) > 0 ? 'text-red-400' : 'text-green-400'}`}>{(e.pct_chg_20d || 0) > 0 ? '+' : ''}{e.pct_chg_20d || 0}%</td>}
                                {isV('pct_chg_1y') && <td className={`py-2 px-2 text-right ${(e.pct_chg_1y || 0) > 0 ? 'text-red-400' : 'text-green-400'}`}>{(e.pct_chg_1y || 0) > 0 ? '+' : ''}{e.pct_chg_1y || 0}%</td>}
                                {isV('benchmark') && <td className="py-2 px-2 text-slate-400 text-xs whitespace-nowrap" title={e.benchmark || ''}>{e.benchmark || '-'}</td>}
                                {isV('reversal') && <td className="py-2 px-2 text-center">{e.reversal && <span className={`text-xs px-1.5 py-0.5 rounded ${e.reversal === '弱转强' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>{e.reversal}</span>}</td>}
                                <td className="py-2 px-2 text-center">
                                    <div className="flex items-center justify-center gap-1">
                                        {onViewKline && <button onClick={() => onViewKline(e.code)}
                                            className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all"
                                            title={`查看 ${e.name} K线图`}>📈</button>}
                                        {(() => { const inPool = customStocks.some(cs => cs.code === e.code); return (
                                            <button onClick={() => inPool ? setCustomStocks(prev => prev.filter(cs => cs.code !== e.code)) : setCustomStocks(prev => [...prev, makePoolItem(e.code, e.name)])}
                                                className={`text-[10px] px-1.5 py-1 rounded border transition-all ${inPool ? 'bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30' : 'bg-emerald-600/30 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/50'}`}
                                                title={inPool ? '点击移出自选池' : '加入自选池'}>{inPool ? '✓' : '➕'}</button>
                                        ); })()}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            {totalPages > 1 && (
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-slate-700/30">
                    <span className="text-xs text-slate-500">
                        共 {sorted.length} 只 | 第 {currentPage}/{totalPages} 页
                    </span>
                    <div className="flex items-center gap-1.5">
                        <button disabled={currentPage <= 1}
                            onClick={() => setCurrentPage(p => p - 1)}
                            className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 border border-slate-600/50 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                            ← 上一页
                        </button>
                        {pageNumbers.map(p => (
                            <button key={p}
                                onClick={() => setCurrentPage(p)}
                                className={`w-8 h-8 text-xs rounded-lg border transition-all ${p === currentPage
                                        ? 'bg-teal-500/20 border-teal-500/50 text-teal-400 font-bold'
                                        : 'bg-slate-800 border-slate-600/50 text-slate-300 hover:bg-slate-700'
                                    }`}>
                                {p}
                            </button>
                        ))}
                        <button disabled={currentPage >= totalPages}
                            onClick={() => setCurrentPage(p => p + 1)}
                            className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 border border-slate-600/50 text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed transition-all">
                            下一页 →
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
};

// ── 板块轮动热力矩阵 ──
const RotationHeatmap = ({ screenerApi, onJumpSubCategory }) => {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [show, setShow] = useState(false);
    const [expandedRotCat, setExpandedRotCat] = useState(null);

    const fetchRotation = async () => {
        setLoading(true);
        try {
            const res = await screenerApi.getEtfRotation(30);
            setData(res);
        } catch { /* 忽略加载失败 */ } finally { setLoading(false); }
    };

    const pctColor = (v) => {
        if (v > 1.5) return 'bg-red-500/60';
        if (v > 0.5) return 'bg-red-500/30';
        if (v > 0.1) return 'bg-red-500/15';
        if (v > -0.1) return 'bg-slate-700/40';
        if (v > -0.5) return 'bg-green-500/15';
        if (v > -1.5) return 'bg-green-500/30';
        return 'bg-green-500/60';
    };

    return (
        <div className="bg-slate-800/40 rounded-xl border border-slate-700/30 p-4">
            <button onClick={() => { setShow(v => !v); if (!data && !loading) fetchRotation(); }}
                className="w-full flex items-center justify-between text-sm font-bold text-white/80">
                <span>🔄 板块轮动热力图 <span className="text-xs text-slate-500 font-normal">近30个交易日各分类ETF日均涨跌</span></span>
                <span className="text-xs text-slate-400">{show ? '▲ 收起' : '▼ 展开'}</span>
            </button>
            {show && (
                <div className="mt-3">
                    {loading ? (
                        <div className="text-center text-slate-400 py-6"><RefreshCw className="w-4 h-4 animate-spin inline mr-2" />加载中...</div>
                    ) : data?.categories?.length > 0 ? (
                        <>
                            {data.cat_totals?.length > 0 && (() => {
                                const up = data.cat_totals.filter(c => c.total_pct > 0).length;
                                const down = data.cat_totals.filter(c => c.total_pct < 0).length;
                                const best = data.cat_totals[0];
                                const worst = data.cat_totals[data.cat_totals.length - 1];
                                // 取一级分类内涨幅最大的二级分类
                                const topSub = (cat) => {
                                    const t = data.sub_rotation?.[cat]?.totals?.[0];
                                    return t ? t : null;
                                };
                                const topSub5d = (cat) => {
                                    const totals = data.sub_rotation?.[cat]?.totals;
                                    if (!totals?.length) return null;
                                    return [...totals].sort((a, b) => b.pct_5d - a.pct_5d)[0];
                                };
                                const SubTag = ({ s, field, cat }) => s ? (
                                    <span className="text-[11px] text-indigo-300/70 ml-1 cursor-pointer hover:text-indigo-200 transition-colors"
                                        onClick={(e) => { e.stopPropagation(); setExpandedRotCat(cat); if (onJumpSubCategory) onJumpSubCategory(cat, s.sub); else setTimeout(() => document.getElementById(`rot-rank-${cat}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 50); }}
                                        title={`点击筛选 ${cat} → ${s.sub}`}
                                    >(<span className="text-indigo-300/70">{s.sub}</span> <span className={s[field] > 0 ? 'text-red-400/80' : s[field] < 0 ? 'text-green-400/80' : 'text-slate-400'}>{s[field] > 0 ? '+' : ''}{s[field]}%</span>)</span>
                                ) : null;
                                return (
                                    <div className="flex flex-wrap items-center gap-2.5 mb-3 text-sm">
                                        <span className="text-slate-500">近{data.total_days}日</span>
                                        <span className="text-red-400">▲ {up}</span>
                                        <span className="text-green-400">▼ {down}</span>
                                        <span className="text-slate-600">|</span>
                                        <span className="text-slate-400">
                                            最强 <span className={`font-medium ${best.total_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>{best.category}</span>
                                            <span className={`font-mono ml-1 ${best.total_pct >= 0 ? 'text-red-400/70' : 'text-green-400/70'}`}>{best.total_pct > 0 ? '+' : ''}{best.total_pct}%</span>
                                            <SubTag s={topSub(best.category)} field="total_pct" cat={best.category} />
                                        </span>
                                        <span className="text-slate-400">
                                            最弱 <span className={`font-medium ${worst.total_pct >= 0 ? 'text-red-400' : 'text-green-400'}`}>{worst.category}</span>
                                            <span className={`font-mono ml-1 ${worst.total_pct >= 0 ? 'text-red-400/70' : 'text-green-400/70'}`}>{worst.total_pct > 0 ? '+' : ''}{worst.total_pct}%</span>
                                            <SubTag s={topSub(worst.category)} field="total_pct" cat={worst.category} />
                                        </span>
                                        {(() => {
                                            const sorted5d = [...data.cat_totals].sort((a, b) => b.pct_5d - a.pct_5d);
                                            const best5 = sorted5d[0];
                                            const worst5 = sorted5d[sorted5d.length - 1];
                                            return (<>
                                                <span className="text-slate-600">|</span>
                                                <span className="text-slate-500 text-xs">近5日</span>
                                                <span className="text-slate-400 text-xs">
                                                    最强 <span className={`font-medium ${best5.pct_5d >= 0 ? 'text-red-400' : 'text-green-400'}`}>{best5.category}</span>
                                                    <span className={`font-mono ml-1 ${best5.pct_5d >= 0 ? 'text-red-400/70' : 'text-green-400/70'}`}>{best5.pct_5d > 0 ? '+' : ''}{best5.pct_5d}%</span>
                                                    <SubTag s={topSub5d(best5.category)} field="pct_5d" cat={best5.category} />
                                                </span>
                                                <span className="text-slate-400 text-xs">
                                                    最弱 <span className={`font-medium ${worst5.pct_5d >= 0 ? 'text-red-400' : 'text-green-400'}`}>{worst5.category}</span>
                                                    <span className={`font-mono ml-1 ${worst5.pct_5d >= 0 ? 'text-red-400/70' : 'text-green-400/70'}`}>{worst5.pct_5d > 0 ? '+' : ''}{worst5.pct_5d}%</span>
                                                    <SubTag s={topSub5d(worst5.category)} field="pct_5d" cat={worst5.category} />
                                                </span>
                                            </>);
                                        })()}
                                    </div>
                                );
                            })()}
                            {/* 热力矩阵 */}
                            <div className="overflow-x-auto">
                                <div className="inline-block min-w-full">
                                    {/* 日期头 */}
                                    <div className="flex">
                                        <div className="w-16 flex-shrink-0" />
                                        {data.dates.map((d, i) => (
                                            <div key={i} className="flex-1 min-w-[28px] text-center text-[9px] text-slate-500 -rotate-45 origin-center h-8 flex items-end justify-center pb-0.5">
                                                {d.slice(5)}
                                            </div>
                                        ))}
                                    </div>
                                    {/* 行 */}
                                    {data.categories.map((cat, ci) => {
                                        const subData = data.sub_rotation?.[cat];
                                        return (<React.Fragment key={cat}>
                                            <div className="flex items-center">
                                                <div className={`w-16 flex-shrink-0 text-xs text-slate-300 truncate pr-1 text-right ${subData ? 'cursor-pointer hover:text-white' : ''}`}
                                                    onClick={() => subData && setExpandedRotCat(prev => prev === cat ? null : cat)}
                                                    title={subData ? '点击展开二级分类' : ''}>
                                                    {subData ? <span className="text-slate-500 mr-0.5">{expandedRotCat === cat ? '▾' : '▸'}</span> : null}{cat}
                                                </div>
                                                {data.matrix[ci].map((v, di) => (
                                                    <div key={di} className={`flex-1 min-w-[28px] h-6 ${pctColor(v)} border border-slate-800/30 flex items-center justify-center`}
                                                        title={`${cat} ${data.dates[di]}: ${v > 0 ? '+' : ''}${v}%`}>
                                                        <span className={`text-[9px] font-mono ${v > 0 ? 'text-red-300' : v < 0 ? 'text-green-300' : 'text-slate-500'}`}>
                                                            {Math.abs(v) >= 0.1 ? (v > 0 ? '+' : '') + v : ''}
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>
                                            {expandedRotCat === cat && subData && subData.subs.slice(0, 3).map((sub, si) => (
                                                <div key={sub} className="flex items-center bg-slate-900/30 border-l-2 border-indigo-500/40">
                                                    <div className="w-16 flex-shrink-0 text-[10px] text-indigo-300/60 truncate pr-1 text-right pl-2 cursor-pointer hover:text-indigo-200 transition-colors"
                                                        onClick={() => onJumpSubCategory && onJumpSubCategory(cat, sub)}
                                                        title={`点击筛选 ${cat} → ${sub}`}>{sub}</div>
                                                    {subData.matrix[si].map((v, di) => (
                                                        <div key={di} className={`flex-1 min-w-[28px] h-5 ${pctColor(v)} border border-slate-900/20 flex items-center justify-center opacity-80`}
                                                            title={`${cat}/${sub} ${data.dates[di]}: ${v > 0 ? '+' : ''}${v}%`}>
                                                            <span className={`text-[8px] font-mono ${v > 0 ? 'text-red-300' : v < 0 ? 'text-green-300' : 'text-slate-600'}`}>
                                                                {Math.abs(v) >= 0.2 ? (v > 0 ? '+' : '') + v : ''}
                                                            </span>
                                                        </div>
                                                    ))}
                                                </div>
                                            ))}
                                        </React.Fragment>);
                                    })}
                                </div>
                            </div>
                            {/* 累计涨跌排名 */}
                            {data.cat_totals?.length > 0 && (() => {
                                const maxAbs = Math.max(...data.cat_totals.map(c => Math.abs(c.total_pct)), 0.1);
                                return (
                                    <div className="mt-4 pt-3 border-t border-slate-700/30">
                                        <div className="flex items-center gap-2 mb-2">
                                            <span className="w-14 shrink-0" />
                                            <span className="flex-1 text-xs text-slate-400 font-medium">📊 累计涨跌排名</span>
                                            <span className="w-12 text-[10px] text-slate-500 text-right shrink-0">{data.total_days}日</span>
                                            <span className="w-12 text-[10px] text-slate-500 text-right shrink-0">5日</span>
                                        </div>
                                        <div className="grid gap-1.5">
                                            {data.cat_totals.map((c, i) => {
                                                const subData = data.sub_rotation?.[c.category];
                                                return (<React.Fragment key={c.category}>
                                                    <div id={`rot-rank-${c.category}`} className={`flex items-center gap-2 h-6 ${subData ? 'cursor-pointer' : ''}`}
                                                        onClick={() => subData && setExpandedRotCat(prev => prev === c.category ? null : c.category)}>
                                                        <span className="w-14 text-[11px] text-slate-300 text-right shrink-0 truncate">
                                                            {subData ? <span className="text-slate-500 mr-0.5">{expandedRotCat === c.category ? '▾' : '▸'}</span> : null}{c.category}
                                                        </span>
                                                        <div className="flex-1 h-4 bg-slate-800/50 rounded-sm overflow-hidden">
                                                            <div
                                                                className={`h-full rounded-sm ${c.total_pct >= 0 ? 'bg-red-500/40' : 'bg-green-500/40'}`}
                                                                style={{ width: `${Math.min(Math.abs(c.total_pct) / maxAbs * 100, 100)}%` }}
                                                            />
                                                        </div>
                                                        <span className={`w-12 text-[11px] font-mono text-right shrink-0 ${c.total_pct > 0 ? 'text-red-400' : c.total_pct < 0 ? 'text-green-400' : 'text-slate-500'}`}>
                                                            {c.total_pct > 0 ? '+' : ''}{c.total_pct}%
                                                        </span>
                                                        <span className={`w-12 text-[11px] font-mono text-right shrink-0 ${c.pct_5d > 0 ? 'text-red-400/70' : c.pct_5d < 0 ? 'text-green-400/70' : 'text-slate-500'}`}>
                                                            {c.pct_5d > 0 ? '+' : ''}{c.pct_5d}%
                                                        </span>
                                                    </div>
                                                    {expandedRotCat === c.category && subData?.totals?.slice(0, 3).map(st => (
                                                        <div key={st.sub} className="flex items-center gap-2 h-5 pl-3 bg-slate-900/30 border-l-2 border-indigo-500/40 rounded-r">
                                                            <span className="w-14 text-[11px] text-indigo-300/60 text-right shrink-0 truncate cursor-pointer hover:text-indigo-200 transition-colors"
                                                                onClick={(e) => { e.stopPropagation(); onJumpSubCategory && onJumpSubCategory(c.category, st.sub); }}
                                                                title={`点击筛选 ${c.category} → ${st.sub}`}>{st.sub}</span>
                                                            <div className="flex-1 h-3 bg-slate-800/30 rounded-sm overflow-hidden">
                                                                <div
                                                                    className={`h-full rounded-sm ${st.total_pct >= 0 ? 'bg-red-500/30' : 'bg-green-500/30'}`}
                                                                    style={{ width: `${Math.min(Math.abs(st.total_pct) / maxAbs * 100, 100)}%` }}
                                                                />
                                                            </div>
                                                            <span className={`w-12 text-[11px] font-mono text-right shrink-0 ${st.total_pct > 0 ? 'text-red-400/70' : st.total_pct < 0 ? 'text-green-400/70' : 'text-slate-500'}`}>
                                                                {st.total_pct > 0 ? '+' : ''}{st.total_pct}%
                                                            </span>
                                                            <span className={`w-12 text-[11px] font-mono text-right shrink-0 ${st.pct_5d > 0 ? 'text-red-400/50' : st.pct_5d < 0 ? 'text-green-400/50' : 'text-slate-500'}`}>
                                                                {st.pct_5d > 0 ? '+' : ''}{st.pct_5d}%
                                                            </span>
                                                        </div>
                                                    ))}
                                                </React.Fragment>);
                                            })}
                                        </div>
                                    </div>
                                );
                            })()}
                        </>
                    ) : data?.error ? (
                        <div className="text-center text-slate-500 py-4 text-sm">{data.error}</div>
                    ) : (
                        <div className="text-center text-slate-500 py-4 text-sm">暂无数据</div>
                    )}
                </div>
            )}
        </div>
    );
};

// ── ETF Tab 主组件 ──
const EtfTab = ({
    customStocks, setCustomStocks,
    stockReversal,
    onViewKline,
    searchKeyword,
    refreshTrigger,
}) => {
    // ── 自管状态 ──
    const [etfCategory, setEtfCategory] = useState(null);
    const [etfSubCategory, setEtfSubCategory] = useState(null);
    const [etfSubCategories, setEtfSubCategories] = useState([]);
    const [etfSearch, setEtfSearch] = useState('');

    // 外部关键词同步（行业轮动联动）
    useEffect(() => {
        if (searchKeyword?.value != null) {
            setEtfSearch(searchKeyword.value);
            setEtfCategory(null);  // 重置分类，避免分类与搜索冲突
        }
    }, [searchKeyword]);
    const [etfCategories, setEtfCategories] = useState([]);
    const [etfReversal, setEtfReversal] = useState(null);
    const [etfSmart, setEtfSmart] = useState(null);
    const [etfLoading, setEtfLoading] = useState(false);
    const [etfSmartLoading, setEtfSmartLoading] = useState(false);
    const [etfRanking, setEtfRanking] = useState(null);
    const [etfOverview, setEtfOverview] = useState(null);
    const [etfSortKey, setEtfSortKey] = useState('score');
    const [etfSortDir, setEtfSortDir] = useState('desc');

    // ── 原有自管状态 ──
    const [topN, setTopN] = useState(20);
    const [lastMode, setLastMode] = useState(null);

    const [showRanking, setShowRanking] = useState(true);
    const [btnStatus, setBtnStatus] = useState('idle');
    const btnTimerRef = useRef(null);

    // 统一处理 smart screen 返回值
    const handleSmartResult = (res) => {
        setEtfSmart(res);
        if (res?.category_counts) setEtfCategories(res.category_counts);
        if (res?.sub_category_counts) setEtfSubCategories(res.sub_category_counts);
        else setEtfSubCategories([]);
    };

    // 公共筛选执行器（消除 6 处重复 try/catch）
    const fetchEtfSmart = async (category, subCategory = null) => {
        setEtfSmartLoading(true);
        setBtnStatus('loading');
        clearTimeout(btnTimerRef.current);
        try {
            const res = await screenerApi.getEtfSmart(topN, category, subCategory);
            handleSmartResult(res);
            setBtnStatus((res?.etfs?.length || 0) > 0 ? 'success' : 'warning');
        } catch {
            setBtnStatus('error');
        } finally {
            setEtfSmartLoading(false);
            btnTimerRef.current = setTimeout(() => setBtnStatus('idle'), 2000);
        }
    };

    // ── 挂载时加载数据 ──
    useEffect(() => {
        setEtfLoading(true);
        Promise.all([
            screenerApi.getEtfSmart(20).then(handleSmartResult),
            screenerApi.getEtfReversal().then(res => setEtfReversal(res)),
            screenerApi.getEtfRanking(5).then(res => setEtfRanking(res)),
            screenerApi.getEtfOverview().then(res => setEtfOverview(res)),
        ]).catch(() => { }).finally(() => setEtfLoading(false));
    }, [refreshTrigger]); // refreshTrigger 变化时重新加载

    // 个股弱转强行业集合（用于双重确认）
    const stockW2sIndustries = new Set(
        (stockReversal?.weak_to_strong || []).map(s => s.industry).filter(Boolean)
    );

    const r = etfRanking || {};
    const rev = etfReversal || {};
    const noData = '请先在数据中心同步 ETF';

    return (
        <div className="space-y-5">

            {/* ━━━ 第一层：市场概览 + 信号 ━━━ */}
            <EtfOverviewBar etfOverview={etfOverview} />
            <CategoryHeatMap categoryHeat={etfOverview?.category_heat} />

            <RotationHeatmap screenerApi={screenerApi} onJumpSubCategory={(cat, sub) => {
                setEtfCategory(cat);
                setEtfSubCategory(sub);
                fetchEtfSmart(cat, sub);
                setLastMode('filter');
                setTimeout(() => document.getElementById('etf-sub-filter')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
            }} />

            {/* 市场排行与反转信号（可折叠） */}
            <div className="bg-slate-800/40 rounded-xl border border-slate-700/30 p-4">
                <button onClick={() => setShowRanking(v => !v)}
                    className="w-full flex items-center justify-between text-sm font-bold text-white/80">
                    <span>📊 市场排行与反转信号 <span className="text-xs text-slate-500 font-normal">涨跌Top · 弱转强/强转弱</span></span>
                    <span className="text-xs text-slate-400">{showRanking ? '▲ 收起' : '▼ 展开'}</span>
                </button>
                {showRanking && (
                    <div className="mt-3 space-y-3">
                        <div className="grid grid-cols-4 gap-3">
                            <RankCard title="📈 当日涨幅 Top" items={r.today_top} valueKey="pct_chg"
                                bgClass="bg-red-500/5" borderClass="border-red-500/20" textClass="text-red-400" emptyMsg={noData}
                                customStocks={customStocks} setCustomStocks={setCustomStocks} stockW2sIndustries={stockW2sIndustries} onViewKline={onViewKline} />
                            <RankCard title="📉 当日跌幅 Top" items={r.today_bottom} valueKey="pct_chg"
                                bgClass="bg-green-500/5" borderClass="border-green-500/20" textClass="text-green-400" emptyMsg={noData}
                                customStocks={customStocks} setCustomStocks={setCustomStocks} stockW2sIndustries={stockW2sIndustries} onViewKline={onViewKline} />
                            <RankCard title="🔥 5日涨幅 Top" subtitle="近5个交易日" items={r.fiveday_top} valueKey="pct_chg_5d"
                                bgClass="bg-red-500/5" borderClass="border-red-500/20" textClass="text-red-400" emptyMsg={noData}
                                customStocks={customStocks} setCustomStocks={setCustomStocks} stockW2sIndustries={stockW2sIndustries} onViewKline={onViewKline} />
                            <RankCard title="❄️ 5日跌幅 Top" subtitle="近5个交易日" items={r.fiveday_bottom} valueKey="pct_chg_5d"
                                bgClass="bg-green-500/5" borderClass="border-green-500/20" textClass="text-green-400" emptyMsg={noData}
                                customStocks={customStocks} setCustomStocks={setCustomStocks} stockW2sIndustries={stockW2sIndustries} onViewKline={onViewKline} />
                        </div>
                        <div className="grid grid-cols-2 gap-4">
                            <RankCard title="⚡ ETF 弱转强" subtitle="5日最弱→今日最强" items={(rev.weak_to_strong || []).map(s => ({ ...s, pct_chg: s.today_chg }))}
                                valueKey="pct_chg" bgClass="bg-red-500/5" borderClass="border-red-500/20" textClass="text-red-400" emptyMsg={noData}
                                customStocks={customStocks} setCustomStocks={setCustomStocks} stockW2sIndustries={stockW2sIndustries} onViewKline={onViewKline} />
                            <RankCard title="⚠️ ETF 强转弱" subtitle="5日最强→今日最弱" items={(rev.strong_to_weak || []).map(s => ({ ...s, pct_chg: s.today_chg }))}
                                valueKey="pct_chg" bgClass="bg-green-500/5" borderClass="border-green-500/20" textClass="text-green-400" emptyMsg={noData}
                                customStocks={customStocks} setCustomStocks={setCustomStocks} stockW2sIndustries={stockW2sIndustries} onViewKline={onViewKline} />
                        </div>
                    </div>
                )}
            </div>

            <EtfStockLinkCard screenerApi={screenerApi} onViewKline={onViewKline} />

            {/* ━━━ 第三层：筛选操作 ━━━ 对应智能选股的"行业选择 + 策略 + 筛选按钮" */}
            <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-5 shadow-sm">
                {/* 分类筛选 */}
                <h3 className="text-sm font-semibold text-slate-300 mb-3">ETF 分类筛选</h3>
                <div className="flex items-center gap-2 flex-wrap mb-4">
                    <button onClick={() => {
                        setEtfCategory(null); setEtfSubCategory(null); setLastMode('filter');
                        fetchEtfSmart(null);
                    }}
                        className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${!etfCategory ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800/60 text-slate-400 hover:text-white border border-slate-700/50'}`}>
                        全部
                    </button>
                    {etfCategories.map(cat => (
                        <button key={cat.name} onClick={() => {
                            setEtfCategory(cat.name); setEtfSubCategory(null); setLastMode('filter');
                            fetchEtfSmart(cat.name);
                        }}
                            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${etfCategory === cat.name ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-slate-800/60 text-slate-400 hover:text-white border border-slate-700/50'}`}>
                            {cat.name} <span className="text-xs opacity-60">({cat.count})</span>
                        </button>
                    ))}
                    {/* 搜索框（内联在分类按钮后） */}
                    <div className="relative ml-2">
                        <SearchIcon className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
                        <input
                            type="text" value={etfSearch}
                            onChange={e => setEtfSearch(e.target.value)}
                            placeholder="结果中搜索..."
                            className={`w-36 pl-8 ${etfSearch ? 'pr-14' : 'pr-3'} py-1.5 bg-slate-800/60 border border-slate-700/50 rounded-lg text-sm text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500/50 focus:w-48 transition-all`}
                        />
                        {etfSearch && (() => {
                            const kw = etfSearch.toLowerCase();
                            let list = etfSmart?.etfs || [];
                            if (etfCategory) list = list.filter(e => e.category === etfCategory);
                            const cnt = list.filter(e => (e.name || '').toLowerCase().includes(kw) || (e.code || '').includes(kw)).length;
                            return (
                                <>
                                    <span className={`absolute right-8 top-1/2 -translate-y-1/2 text-[10px] font-mono ${cnt > 0 ? 'text-emerald-400' : 'text-red-400'}`}>{cnt}</span>
                                    <button onClick={() => setEtfSearch('')}
                                        className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-xs">✕</button>
                                </>
                            );
                        })()}
                    </div>
                </div>

                {/* 二级分类筛选（选中一级分类且有≥2种子分类时显示） */}
                {etfCategory && etfSubCategories.length >= 2 && (() => {
                    // 从 overview 的 sub_category_heat 中获取当前一级分类的二级涨跌数据
                    const subHeatMap = {};
                    const subHeatList = etfOverview?.sub_category_heat?.[etfCategory] || [];
                    subHeatList.forEach(s => { subHeatMap[s.sub] = s; });
                    return (
                    <div id="etf-sub-filter" className="flex items-center gap-2 flex-wrap mb-4">
                        <span className="text-xs text-slate-500 shrink-0">子分类：</span>
                        <button onClick={() => { setEtfSubCategory(null); fetchEtfSmart(etfCategory, null); }}
                            className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${!etfSubCategory ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'bg-slate-800/60 text-slate-400 hover:text-white border border-slate-700/50'}`}>
                            全部
                        </button>
                        {etfSubCategories.map(sub => {
                            const heat = subHeatMap[sub.name];
                            const pct5d = heat?.avg_pct_5d;
                            return (
                            <button key={sub.name} onClick={() => { setEtfSubCategory(sub.name); fetchEtfSmart(etfCategory, sub.name); }}
                                className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all ${etfSubCategory === sub.name ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' : 'bg-slate-800/60 text-slate-400 hover:text-white border border-slate-700/50'}`}>
                                {sub.name} <span className="opacity-60">({sub.count})</span>
                                {pct5d != null && (
                                    <span className={`ml-1 font-mono ${pct5d > 0 ? 'text-red-400' : pct5d < 0 ? 'text-green-400' : 'text-slate-500'}`}>
                                        {pct5d > 0 ? '+' : ''}{pct5d}%
                                    </span>
                                )}
                            </button>
                            );
                        })}
                    </div>
                    );
                })()}

                {/* 数量参数 */}
                <div className="grid grid-cols-4 gap-5 mb-4">
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-xs text-slate-400">筛选数量</label>
                            <span className="text-sm font-bold text-emerald-400 font-mono">{topN}</span>
                        </div>
                        <input type="range" min={10} max={100} step={5} value={topN}
                            onChange={e => setTopN(Number(e.target.value))}
                            className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-emerald-500 bg-slate-700" />
                        <div className="flex justify-between mt-1">
                            {[10, 20, 50, 100].map(v => (
                                <span key={v} onClick={() => setTopN(v)}
                                    className={`text-[10px] cursor-pointer transition-colors ${topN === v ? 'text-emerald-400 font-bold' : 'text-slate-500 hover:text-slate-300'}`}>{v}</span>
                            ))}
                        </div>
                    </div>
                </div>

                {/* 操作按钮 */}
                <div className="flex items-center gap-3">
                    <button onClick={() => {
                        setLastMode('filter');
                        fetchEtfSmart(etfCategory, etfSubCategory);
                    }}
                        disabled={etfSmartLoading}
                        className={`flex-1 px-5 py-2.5 rounded-xl font-semibold text-sm shadow-lg transition-all flex items-center justify-center gap-2 ${
                            btnStatus === 'success' ? 'bg-gradient-to-r from-emerald-500 to-green-500 text-white'
                                : btnStatus === 'warning' ? 'bg-gradient-to-r from-amber-500 to-yellow-500 text-white'
                                    : btnStatus === 'error' ? 'bg-gradient-to-r from-red-500 to-rose-500 text-white'
                                        : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white hover:shadow-emerald-500/25 disabled:opacity-60'
                            }`}>
                        {etfSmartLoading ? <><RefreshCw className="w-4 h-4 animate-spin" /><span>筛选中...</span></>
                            : btnStatus === 'success' ? <Check className="w-4 h-4" />
                                : <Search className="w-4 h-4" />}
                        {etfSmartLoading ? null
                            : btnStatus === 'success' ? `筛选完成 · ${etfSmart?.etfs?.length || 0} 只`
                                : btnStatus === 'warning' ? '未找到结果'
                                    : btnStatus === 'error' ? '✗ 筛选失败'
                                        : '开始筛选'}
                    </button>
                </div>
                <div className="text-xs text-slate-400 mt-3">
                    {etfCategory ? `🔍 按分类「${etfCategory}」筛选 Top${topN}` : `🧠 全市场综合排名 Top${topN}`}
                </div>
            </div>

            {/* 条件摘要标签 */}
            {etfSmart?.etfs?.length > 0 && (
                <div className="flex items-center gap-2 flex-wrap text-xs mb-2">
                    <span className="text-slate-500">当前条件：</span>
                    <span className="px-2 py-0.5 rounded bg-teal-500/15 text-teal-400 border border-teal-500/20">
                        {lastMode === 'filter' ? `分类: ${etfCategory || '全部'}` : lastMode === 'smart' ? '全市场' : '默认'}
                    </span>
                    <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">Top {topN}</span>
                    <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">共 {etfSmart.etfs.length} 只</span>
                    {etfSmart.trade_date && <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">数据: {etfSmart.trade_date}</span>}
                    {etfCategory && <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/20">显示: {etfCategory}</span>}
                </div>
            )}

            {/* ━━━ 第四层：结果（单一数据源：SmartTable） ━━━ */}
            {etfLoading ? (
                <div className="text-center text-slate-400 py-8"><RefreshCw className="w-5 h-5 animate-spin inline mr-2" />加载中...</div>
            ) : etfSmart?.etfs?.length > 0 ? (
                <EtfSmartTable etfSmart={etfSmart} etfSortKey={etfSortKey} etfSortDir={etfSortDir}
                    setEtfSortKey={setEtfSortKey} setEtfSortDir={setEtfSortDir}
                    customStocks={customStocks} setCustomStocks={setCustomStocks} etfCategory={etfCategory} etfSearch={etfSearch} onViewKline={onViewKline} />
            ) : (
                <div className="text-center text-slate-500 py-8">暂无 ETF 数据，请先在数据中心点击「同步 ETF」</div>
            )}
        </div>
    );
};

export default EtfTab;

