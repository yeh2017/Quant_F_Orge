import React, { useState, useEffect, useRef } from 'react';
import { RefreshCw, Zap, Filter, Search, Check } from 'lucide-react';
import { bondFactorApi } from '../../services/api';
import { makePoolItem } from '../../utils/poolActions';

// ── 评级排序映射 ──
const RATING_ORDER = { 'AAA': 7, 'AA+': 6, 'AA': 5, 'AA-': 4, 'A+': 3, 'A': 2, 'A-': 1, 'BBB': 0 };
const RATING_OPTIONS = ['不限', 'AAA', 'AA+', 'AA', 'AA-', 'A+'];
const round3 = (v) => Math.round(v * 1000) / 1000;




// 构建加入自选池的 extraFields
const buildBondExtra = (b) => ({
    underlyingStock: b.underlying_name || b.underlying_code || '',
    underlyingCode: b.underlying_code || '',
    rating: b.rating || '-',
    premium_ratio: b.premium_ratio,
    double_low_score: b.double_low_score,
    close_price: b.close_price,
});

// ── 可转债列定义（固定列：代码/名称/操作 不在此列表中） ──
const BOND_COLUMN_DEFS = [
    { key: 'double_low_score', label: '双低分',     group: '核心', sortable: true },
    { key: 'close_price',      label: '最新价',     group: '行情', sortable: true },
    { key: 'pct_chg',          label: '涨跌%',      group: '行情', sortable: true },
    { key: 'amount',           label: '成交额(万)',  group: '行情', sortable: true },
    { key: 'turnover_rate',    label: '换手率%',    group: '行情', sortable: true },
    { key: 'convert_price',    label: '转股价',     group: '核心', sortable: true },
    { key: 'put_trigger',      label: '回售触发价',   group: '条款', sortable: true },
    { key: 'call_trigger',     label: '强赎触发价',   group: '条款', sortable: true },
    { key: 'convert_value',    label: '转股价值',   group: '核心', sortable: true },
    { key: 'premium_ratio',    label: '转股溢价率%', group: '核心', sortable: true },
    { key: 'remaining_size',   label: '剩余规模',   group: '补充', sortable: true },
    { key: 'rating',           label: '评级',       group: '基本', sortable: false },
    { key: 'pure_bond_value',  label: '纯债价值',   group: '补充', sortable: true },
    { key: 'underlying_name',  label: '正股',       group: '正股', sortable: false },
    { key: 'underlying_close', label: '正股价',     group: '正股', sortable: true },
    { key: 'underlying_pct_chg', label: '正股涨跌%',  group: '正股', sortable: true },
    { key: 'underlying_roe',   label: '正股ROE',    group: '正股', sortable: true },
    { key: 'mature_date',      label: '到期日',     group: '基本', sortable: false },
];

// 默认隐藏：纯债价值、正股ROE、回售触发价、强赎触发价
const BOND_DEFAULT_HIDDEN = new Set(['pure_bond_value', 'underlying_roe', 'put_trigger', 'call_trigger']);
const BOND_DEFAULT_VISIBLE = new Set(BOND_COLUMN_DEFS.filter(c => !BOND_DEFAULT_HIDDEN.has(c.key)).map(c => c.key));
const BOND_COL_STORAGE_KEY = 'bond_screener_visible_cols';
const BOND_VALID_KEYS = new Set(BOND_COLUMN_DEFS.map(c => c.key));

const loadBondVisibleCols = () => {
    const SCHEMA_VERSION = 4; // v4=新增回售/强赎触发价列
    try {
        const saved = localStorage.getItem(BOND_COL_STORAGE_KEY);
        if (saved) {
            const parsed = JSON.parse(saved).filter(k => BOND_VALID_KEYS.has(k));
            if (parsed.length > 0) {
                const result = new Set(parsed);
                const savedVer = parseInt(localStorage.getItem(BOND_COL_STORAGE_KEY + '_ver') || '0');
                if (savedVer < SCHEMA_VERSION) {
                    // 一次性合并：把新增的默认可见列补入
                    for (const k of BOND_DEFAULT_VISIBLE) {
                        if (!result.has(k)) result.add(k);
                    }
                    localStorage.setItem(BOND_COL_STORAGE_KEY, JSON.stringify([...result]));
                    localStorage.setItem(BOND_COL_STORAGE_KEY + '_ver', String(SCHEMA_VERSION));
                }
                return result;
            }
        }
    } catch { /* ignore */ }
    localStorage.setItem(BOND_COL_STORAGE_KEY + '_ver', String(SCHEMA_VERSION));
    return new Set(BOND_DEFAULT_VISIBLE);
};

// ── 双低排行结果表 ──
const BondResultTable = ({ data, tradeDate, customBonds, setCustomBonds, sortKey, sortDir, onSort, onViewKline }) => {
    // ── Hooks 必须在所有条件返回之前 ──
    const [visibleCols, setVisibleCols] = React.useState(loadBondVisibleCols);
    const [showColPicker, setShowColPicker] = React.useState(false);
    const colPickerRef = React.useRef(null);
    const isV = (k) => visibleCols.has(k);
    const toggleCol = (k) => {
        const next = new Set(visibleCols);
        next.has(k) ? next.delete(k) : next.add(k);
        setVisibleCols(next);
        localStorage.setItem(BOND_COL_STORAGE_KEY, JSON.stringify([...next]));
    };
    // 点击外部关闭
    React.useEffect(() => {
        const handler = (e) => { if (colPickerRef.current && !colPickerRef.current.contains(e.target)) setShowColPicker(false); };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    if (!data?.length) return null;

    const toggleSort = (key) => {
        if (sortKey === key) onSort(key, sortDir === 'asc' ? 'desc' : 'asc');
        else onSort(key, (key === 'double_low_score' || key === 'premium_ratio') ? 'asc' : 'desc');
    };
    const arrow = (key) => sortKey === key ? (sortDir === 'desc' ? ' ▼' : ' ▲') : '';

    const getVal = (item, key) => {
        if (key === 'put_trigger') return item.convert_price ? item.convert_price * 0.7 : 0;
        if (key === 'call_trigger') return item.convert_price ? item.convert_price * 1.3 : 0;
        return item[key] ?? 0;
    };

    const sorted = [...data].sort((a, b) => {
        const va = getVal(a, sortKey), vb = getVal(b, sortKey);
        return sortDir === 'desc' ? vb - va : va - vb;
    });

    const SortTh = ({ k, label, align = 'right', title }) => (
        <th onClick={() => toggleSort(k)} title={title}
            className={`text-${align} py-2 px-2 cursor-pointer select-none hover:text-white transition-colors whitespace-nowrap ${sortKey === k ? 'text-purple-400' : ''}`}>
            {label}{arrow(k)}
        </th>
    );

    const [addAllStatus, setAddAllStatus] = React.useState(null);
    const addAllTimerRef = React.useRef(null);

    const addAll = () => {
        const existCodes = new Set(customBonds.map(b => b.code));
        const newBonds = sorted
            .filter(b => !existCodes.has(b.code))
            .map(b => makePoolItem(b.code, b.name || `转债-${b.code}`, buildBondExtra(b)));
        clearTimeout(addAllTimerRef.current);
        if (newBonds.length > 0) {
            setCustomBonds(prev => [...prev, ...newBonds]);
            setAddAllStatus(`✓ 已加入 ${newBonds.length} 只`);
        } else {
            setAddAllStatus('全部已在自选池中');
        }
        addAllTimerRef.current = setTimeout(() => setAddAllStatus(null), 2000);
    };

    // 前端分页（PAGE_SIZE=50，与 StockTab/EtfTab 一致）
    const PAGE_SIZE = 50;
    const [currentPage, setCurrentPage] = React.useState(1);
    const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
    const paged = sorted.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

    // 排序/数据量变化时重置到第 1 页
    React.useEffect(() => { setCurrentPage(1); }, [sortKey, sortDir, data.length]);

    const pageNumbers = (() => {
        const pages = [];
        let start = Math.max(1, currentPage - 2);
        let end = Math.min(totalPages, start + 4);
        start = Math.max(1, end - 4);
        for (let i = start; i <= end; i++) pages.push(i);
        return pages;
    })();

    // 金额格式化
    const fmtSize = (v) => v != null ? `${v.toFixed(1)}亿` : '-';

    return (
        <div className="bg-slate-800/60 rounded-xl border border-purple-500/20 p-4">
            <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-semibold text-purple-400">
                    📊 双低排行 · {data.length} 只
                </h4>
                <div className="flex items-center gap-2">
                    <button onClick={addAll}
                        className={`text-xs px-3 py-1.5 rounded-lg transition-all border ${addAllStatus?.startsWith('✓')
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
                            title="自定义显示列">☰ 列 ({visibleCols.size}/{BOND_COLUMN_DEFS.length})</button>
                        {showColPicker && (
                            <div className="absolute right-0 top-9 z-50 w-52 bg-slate-800 border border-slate-600/50 rounded-xl shadow-2xl p-3">
                                <div className="flex items-center justify-between mb-2 pb-2 border-b border-slate-700/50">
                                    <span className="text-xs text-slate-400 font-medium">显示列</span>
                                    <div className="flex gap-1.5">
                                        <button onClick={() => { const all = new Set(BOND_COLUMN_DEFS.map(c => c.key)); setVisibleCols(all); localStorage.setItem(BOND_COL_STORAGE_KEY, JSON.stringify([...all])); }}
                                            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600">全选</button>
                                        <button onClick={() => { setVisibleCols(new Set(BOND_DEFAULT_VISIBLE)); localStorage.removeItem(BOND_COL_STORAGE_KEY); }}
                                            className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600">默认</button>
                                    </div>
                                </div>
                                <div className="max-h-64 overflow-y-auto space-y-0.5">
                                    {[...new Set(BOND_COLUMN_DEFS.map(c => c.group))].map(group => (
                                        <div key={group}>
                                            <div className="text-[10px] text-slate-500 font-medium mt-1.5 mb-0.5">{group}</div>
                                            {BOND_COLUMN_DEFS.filter(c => c.group === group).map(col => (
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
                            <th className="text-left py-2 px-2 whitespace-nowrap">代码</th>
                            <th className="text-left py-2 px-2 whitespace-nowrap">名称</th>
                            {isV('double_low_score') && <SortTh k="double_low_score" label="双低分" title="双低分 = 转债价格 + 溢价率，越低越具性价比。<130 为低估区间" />}
                            {isV('close_price') && <SortTh k="close_price" label="最新价" />}
                            {isV('pct_chg') && <SortTh k="pct_chg" label="涨跌%" />}
                            {isV('amount') && <SortTh k="amount" label="成交额(万)" />}
                            {isV('turnover_rate') && <SortTh k="turnover_rate" label="换手率%" />}
                            {isV('convert_price') && <SortTh k="convert_price" label="转股价" title="转债转换为股票的价格，越低越有利于转股" />}
                            {isV('put_trigger') && <SortTh k="put_trigger" label="回售触发价" title="转股价×70%，正股跌破此价持续30日可触发回售" />}
                            {isV('call_trigger') && <SortTh k="call_trigger" label="强赎触发价" title="转股价×130%，正股超过此价持续15/20日触发强赎" />}
                            {isV('convert_value') && <SortTh k="convert_value" label="转股价值" title="正股价/转股价×100，≥130注意强赎风险，≤80有下修博弈机会" />}
                            {isV('premium_ratio') && <SortTh k="premium_ratio" label="转股溢价率%" title="(转债价-转股价值)/转股价值×100%，越低股性越强" />}
                            {isV('remaining_size') && <SortTh k="remaining_size" label="剩余规模" title="未转股的剩余债券规模(亿元)，规模越小流动性越差" />}
                            {isV('rating') && <th className="text-center py-2 px-2 whitespace-nowrap">评级</th>}
                            {isV('pure_bond_value') && <SortTh k="pure_bond_value" label="纯债价值" title="假设不转股的债券价值，是转债的安全底线" />}
                            {isV('underlying_name') && <th className="text-left py-2 px-2 whitespace-nowrap">正股</th>}
                            {isV('underlying_close') && <SortTh k="underlying_close" label="正股价" />}
                            {isV('underlying_pct_chg') && <SortTh k="underlying_pct_chg" label="正股涨跌%" />}
                            {isV('underlying_roe') && <SortTh k="underlying_roe" label="正股ROE" />}
                            {isV('mature_date') && <th className="text-center py-2 px-2 whitespace-nowrap">到期日</th>}
                            <th className="text-center py-2 px-2 whitespace-nowrap">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {paged.map(b => {
                            const inPool = customBonds.some(cb => cb.code === b.code);
                            const ratingColor = (RATING_ORDER[b.rating] ?? -1) >= 5
                                ? 'text-emerald-400' : (RATING_ORDER[b.rating] ?? -1) >= 4
                                    ? 'text-yellow-400' : 'text-slate-400';
                            return (
                                <tr key={b.code} className="border-b border-slate-800/50 hover:bg-slate-700/30 transition-colors">
                                    <td className="py-2 px-2 text-white font-mono text-xs">{b.code}</td>
                                    <td className="py-2 px-2 text-slate-300 whitespace-nowrap">
                                        {b.name}
                                        {b.issue_date && ((Date.now() - new Date(b.issue_date)) / 86400000) < 365 && (
                                            <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-rose-900/40 text-rose-400 border border-rose-500/30"
                                                title={`上市日期 ${b.issue_date}`}>新</span>
                                        )}
                                        {b.convert_value != null && b.convert_value >= 130 && (
                                            <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30" title={`转股价值 ${b.convert_value?.toFixed(1)}，注意强赎风险`}>强赎</span>
                                        )}
                                        {b.convert_value != null && b.convert_value <= 80 && (
                                            <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30" title={`转股价值 ${b.convert_value?.toFixed(1)}，下修博弈机会`}>下修</span>
                                        )}
                                    </td>
                                    {isV('double_low_score') && <td className="py-2 px-2 text-right text-amber-400 font-semibold font-mono">
                                        {b.double_low_score?.toFixed(1) ?? '-'}
                                    </td>}
                                    {isV('close_price') && <td className="py-2 px-2 text-right text-white font-mono">
                                        {b.close_price?.toFixed(2) ?? '-'}
                                    </td>}
                                    {isV('pct_chg') && <td className={`py-2 px-2 text-right font-mono ${b.pct_chg > 0 ? 'text-red-400' : b.pct_chg < 0 ? 'text-emerald-400' : 'text-slate-400'}`}>
                                        {b.pct_chg != null ? `${b.pct_chg > 0 ? '+' : ''}${b.pct_chg}%` : '-'}
                                    </td>}
                                    {isV('amount') && <td className="py-2 px-2 text-right text-slate-400 font-mono">
                                        {b.amount != null ? b.amount.toLocaleString(undefined, { maximumFractionDigits: 0 }) : '-'}
                                    </td>}
                                    {isV('turnover_rate') && <td className="py-2 px-2 text-right text-slate-400 font-mono">
                                        {b.turnover_rate != null ? `${b.turnover_rate}%` : '-'}
                                    </td>}
                                    {isV('convert_price') && <td className="py-2 px-2 text-right text-slate-400 font-mono">
                                        {b.convert_price?.toFixed(2) ?? '-'}
                                    </td>}
                                    {isV('put_trigger') && (() => {
                                        const pt = b.convert_price ? round3(b.convert_price * 0.7) : null;
                                        const near = pt && b.underlying_close && b.underlying_close <= pt * 1.1;
                                        return <td className={`py-2 px-2 text-right font-mono ${near ? 'text-amber-400' : 'text-slate-400'}`}
                                            title={near ? '正股已接近回售触发线' : ''}>{pt ?? '-'}</td>;
                                    })()}
                                    {isV('call_trigger') && (() => {
                                        const ct = b.convert_price ? round3(b.convert_price * 1.3) : null;
                                        const near = ct && b.underlying_close && b.underlying_close >= ct * 0.9;
                                        return <td className={`py-2 px-2 text-right font-mono ${near ? 'text-red-400' : 'text-slate-400'}`}
                                            title={near ? '正股已接近强赎触发线' : ''}>{ct ?? '-'}</td>;
                                    })()}
                                    {isV('convert_value') && <td className={`py-2 px-2 text-right font-mono ${b.convert_value != null && b.convert_value >= 130 ? 'text-red-400' : b.convert_value != null && b.convert_value <= 80 ? 'text-emerald-400' : 'text-slate-400'}`}
                                        title={b.convert_value != null && b.convert_value >= 130 ? '⚠️ 注意强赎风险（转股价值≥130）' : b.convert_value != null && b.convert_value <= 80 ? '🟢 下修博弈机会（转股价值≤80）' : ''}>
                                        {b.convert_value?.toFixed(1) ?? '-'}
                                    </td>}
                                    {isV('premium_ratio') && <td className={`py-2 px-2 text-right font-mono ${(b.premium_ratio ?? 0) > 30 ? 'text-red-400' : (b.premium_ratio ?? 0) < 10 ? 'text-emerald-400' : 'text-slate-300'}`}>
                                        {b.premium_ratio?.toFixed(1) ?? '-'}%
                                    </td>}
                                    {isV('remaining_size') && <td className="py-2 px-2 text-right text-slate-400 font-mono">
                                        {fmtSize(b.remaining_size)}
                                    </td>}
                                    {isV('rating') && <td className={`py-2 px-2 text-center font-bold ${ratingColor}`}>
                                        {b.rating || '-'}
                                    </td>}
                                    {isV('pure_bond_value') && <td className="py-2 px-2 text-right text-slate-400 font-mono">
                                        {b.pure_bond_value?.toFixed(2) ?? '-'}
                                    </td>}
                                    {isV('underlying_name') && <td className="py-2 px-2 text-left text-xs whitespace-nowrap">
                                        {b.underlying_code && onViewKline ? (
                                            <span className="text-slate-300 hover:text-indigo-400 cursor-pointer transition-colors"
                                                onClick={() => onViewKline(b.underlying_code)}
                                                title={`查看正股 ${b.underlying_name || b.underlying_code} K线`}>
                                                {b.underlying_name || b.underlying_code.split('.')[0]}
                                            </span>
                                        ) : (
                                            <span className="text-slate-300">{b.underlying_name || b.underlying_code?.split('.')[0] || '-'}</span>
                                        )}
                                    </td>}
                                    {isV('underlying_close') && <td className="py-2 px-2 text-right text-white font-mono">
                                        {b.underlying_close?.toFixed(2) ?? '-'}
                                    </td>}
                                    {isV('underlying_pct_chg') && <td className={`py-2 px-2 text-right font-mono ${(b.underlying_pct_chg ?? 0) > 0 ? 'text-red-400' : (b.underlying_pct_chg ?? 0) < 0 ? 'text-emerald-400' : 'text-slate-400'}`}>
                                        {b.underlying_pct_chg != null ? `${b.underlying_pct_chg > 0 ? '+' : ''}${b.underlying_pct_chg}%` : '-'}
                                    </td>}
                                    {isV('underlying_roe') && <td className={`py-2 px-2 text-right font-mono ${(b.underlying_roe ?? 0) > 15 ? 'text-emerald-400' : (b.underlying_roe ?? 0) > 0 ? 'text-slate-300' : 'text-red-400'}`}>
                                        {b.underlying_roe?.toFixed(1) ?? '-'}%
                                    </td>}
                                    {isV('mature_date') && <td className="py-2 px-2 text-center text-xs text-slate-400 whitespace-nowrap">
                                        {b.mature_date?.slice(0, 7) || '-'}
                                    </td>}
                                    <td className="py-2 px-2 text-center">
                                        <div className="flex items-center justify-center gap-1">
                                            {onViewKline && <button onClick={() => onViewKline(b.code)}
                                                className="text-[10px] px-1.5 py-1 rounded bg-indigo-600/30 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/50 transition-all"
                                                title={`查看 ${b.name} K线图`}>📈</button>}
                                            {inPool
                                                ? <button onClick={() => setCustomBonds(prev => prev.filter(cb => cb.code !== b.code))}
                                                    className="text-[10px] px-1.5 py-1 rounded border bg-indigo-900/30 text-indigo-400 border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30 transition-all"
                                                    title="点击移出自选池">✓</button>
                                                : <button onClick={() => setCustomBonds(prev => [...prev, makePoolItem(b.code, b.name, buildBondExtra(b))])}
                                                    className="text-[10px] px-1.5 py-1 rounded bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/50 transition-all"
                                                    title="加入自选池">➕</button>}
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
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
                                        ? 'bg-purple-500/20 border-purple-500/50 text-purple-400 font-bold'
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


// ── BondTab 主组件 ──
const BondTab = ({ customBonds, setCustomBonds, onViewKline, refreshTrigger }) => {
    // 筛选条件
    const [maxPrice, setMaxPrice] = useState(130);
    const [maxPremium, setMaxPremium] = useState(30);
    const [minRating, setMinRating] = useState('不限');
    const [limit, setLimit] = useState(50);
    const [activePreset, setActivePreset] = useState(null);
    // 上次筛选模式：'smart'=一键智能, 'filter'=按条件筛选, 'preset'=策略预设, null=未筛选
    const [lastMode, setLastMode] = useState(null);
    // 上次筛选使用的参数快照
    const [lastParams, setLastParams] = useState(null);
    const [smartMode, setSmartMode] = useState(true);
    const [btnStatus, setBtnStatus] = useState('idle');
    const btnTimerRef = useRef(null);

    // 结果
    const [result, setResult] = useState([]);
    const [tradeDate, setTradeDate] = useState(null);
    const [loading, setLoading] = useState(false);
    const [sortKey, setSortKey] = useState('double_low_score');
    const [sortDir, setSortDir] = useState('asc');
    const [newBondOnly, setNewBondOnly] = useState(false);
    const [hasSearched, setHasSearched] = useState(false);

    // 独立概览（全市场统计，不依赖筛选结果）
    const [overview, setOverview] = useState(null);  // null=加载中, {total:0}=无数据, {total:N}=有数据
    useEffect(() => {
        bondFactorApi.getOverview().then(setOverview).catch(() => setOverview({ total: 0 }));
    }, [refreshTrigger]);

    // 策略预设定义
    const PRESETS = [
        {
            id: 'conservative', label: '🛡️ 保守型', desc: '低价+低溢价+高评级',
            params: { maxPrice: 110, maxPremium: 15, minRating: 'AA', limit: 30 },
            color: 'emerald'
        },
        {
            id: 'balanced', label: '⚖️ 均衡型', desc: '经典双低策略',
            params: { maxPrice: 130, maxPremium: 30, minRating: 'AA-', limit: 50 },
            color: 'blue'
        },
        {
            id: 'aggressive', label: '🔥 进攻型', desc: '放宽条件捕捉弹性',
            params: { maxPrice: 150, maxPremium: 50, minRating: '不限', limit: 80 },
            color: 'orange'
        },
        {
            id: 'all', label: '📋 浏览', desc: '无限制查看',
            params: { maxPrice: null, maxPremium: null, minRating: '不限', limit: 500, includeAll: true },
            color: 'slate'
        },
    ];

    const fetchWithParams = async (p) => {
        setLoading(true);
        setBtnStatus('loading');
        clearTimeout(btnTimerRef.current);
        try {
            const options = { limit: p.limit };
            if (p.maxPrice) options.max_price = p.maxPrice;
            if (p.maxPremium) options.max_premium = p.maxPremium;
            if (p.minRating && p.minRating !== '不限') options.min_rating = p.minRating;
            if (p.includeAll) options.include_all = true;
            const res = await bondFactorApi.getSnapshot(options);
            let raw = res.data || [];
            if (p.newBondOnly) {
                const cutoff = Date.now() - 365 * 86400000;
                raw = raw.filter(b => b.issue_date && new Date(b.issue_date).getTime() >= cutoff);
            }
            setResult(raw);
            setTradeDate(res.trade_date || null);
            setHasSearched(true);
            setLastParams(p);
            setBtnStatus(raw.length > 0 ? 'success' : 'warning');
        } catch {
            setBtnStatus('error');
        }
        setLoading(false);
        btnTimerRef.current = setTimeout(() => setBtnStatus('idle'), 2000);
    };

    const applyPreset = (preset) => {
        const p = preset.params;
        setMaxPrice(p.maxPrice ?? 200);
        setMaxPremium(p.maxPremium ?? 100);
        setMinRating(p.minRating);
        setLimit(p.limit);
        setActivePreset(preset.id);
        setLastMode('preset');
        setSmartMode(false); // 点击预设自动切到条件模式
        fetchWithParams(p);
    };

    const fetchData = () => {
        setActivePreset(null);
        setLastMode('filter');
        fetchWithParams({ maxPrice, maxPremium, minRating, limit });
    };

    // 预设按钮颜色映射
    const presetColors = {
        emerald: { active: 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300', idle: 'bg-slate-800/60 border-slate-700/50 text-slate-300 hover:border-emerald-500/30 hover:text-emerald-300' },
        blue: { active: 'bg-blue-500/20 border-blue-500/50 text-blue-300', idle: 'bg-slate-800/60 border-slate-700/50 text-slate-300 hover:border-blue-500/30 hover:text-blue-300' },
        orange: { active: 'bg-orange-500/20 border-orange-500/50 text-orange-300', idle: 'bg-slate-800/60 border-slate-700/50 text-slate-300 hover:border-orange-500/30 hover:text-orange-300' },
        slate: { active: 'bg-slate-500/20 border-slate-400/50 text-slate-200', idle: 'bg-slate-800/60 border-slate-700/50 text-slate-300 hover:border-slate-500/30 hover:text-slate-200' },
    };

    const bondUpRatio = overview?.total ? Math.round((overview.up || 0) / overview.total * 100) : 0;

    return (
        <div className="space-y-5">

            {/* ━━━ 第一层：全市场概览（独立API，不依赖筛选） ━━━ */}
            {overview?.total > 0 ? (
                <div className="bg-purple-500/5 border border-purple-500/20 rounded-xl p-4 flex items-center gap-6">
                    <div className="flex items-center gap-2 shrink-0">
                        <span className="text-lg">📜</span>
                        <div>
                            <div className="text-lg font-bold text-purple-400">可转债市场概览 <span className="text-sm font-normal text-white/60">· {overview.total} 只</span></div>
                            <div className="text-xs text-white/80">{overview.trade_date || '—'}</div>
                        </div>
                    </div>
                    <div className="w-px h-10 bg-slate-700/50 shrink-0" />
                    <div className="flex-1 grid grid-cols-6 gap-4">
                        <div>
                            <div className="flex items-center justify-between mb-1">
                                <span className="text-sm text-white/90">市场广度</span>
                                <span className={`text-xs font-mono font-bold ${bondUpRatio >= 55 ? 'text-green-400' : bondUpRatio >= 45 ? 'text-amber-400' : 'text-red-400'}`}>
                                    {bondUpRatio}
                                </span>
                            </div>
                            <div className="h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                                <div className={`h-full rounded-full transition-all duration-500 ${bondUpRatio >= 55 ? 'bg-green-500' : bondUpRatio >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                                    style={{ width: `${bondUpRatio}%` }} />
                            </div>
                            <div className="text-xs text-white/80 mt-0.5">
                                涨{overview.up || 0} / 跌{overview.down || 0} / 平{overview.flat || 0}
                            </div>
                            {overview.avg_pct != null && (
                                <div className={`text-lg font-bold font-mono mt-0.5 ${overview.avg_pct > 0 ? 'text-red-400' : overview.avg_pct < 0 ? 'text-green-400' : 'text-slate-400'}`}>
                                    {overview.avg_pct > 0 ? '+' : ''}{overview.avg_pct}%
                                </div>
                            )}
                        </div>
                        <div>
                            <div className="text-sm text-white/90">成交额</div>
                            <div className="text-2xl font-black font-mono text-cyan-400">{overview.total_amount ?? '-'}</div>
                            <div className="text-xs text-white/60">
                                亿元{overview.amount_date && overview.amount_date !== overview.trade_date && (
                                    <span className="ml-1 text-amber-400" title="成交额日期与因子日期不同步">({overview.amount_date})</span>
                                )}
                            </div>
                        </div>
                        <div>
                            <div className="text-sm text-white/90">平均双低分</div>
                            <div className={`text-2xl font-black font-mono ${overview.avg_double_low < 130 ? 'text-emerald-400' : 'text-amber-400'}`}>{overview.avg_double_low}</div>
                            <div className="text-xs text-white/60">&lt;130 为低估区间</div>
                        </div>
                        <div>
                            <div className="text-sm text-white/90">溢价率中位数</div>
                            <div className={`text-2xl font-black font-mono ${(overview.median_premium ?? 99) < 20 ? 'text-emerald-400' : 'text-amber-400'}`}>{overview.median_premium ?? '-'}%</div>
                            <div className="text-xs text-white/60">&lt;20% 为合理区间</div>
                        </div>
                        <div>
                            <div className="text-sm text-white/90">价格中位数</div>
                            <div className="text-2xl font-black font-mono text-white">{overview.median_price ?? '-'}</div>
                            <div className="text-xs text-white/60">&lt;110 保本: {overview.safe_count} 只</div>
                        </div>
                        <div>
                            <div className="text-sm text-white/90">条款信号</div>
                            <div className="flex items-baseline gap-3 mt-1">
                                <span className="text-red-400 font-mono font-bold text-lg" title="转股价值≥130，注意强赎风险">
                                    {overview.redeem_risk_count ?? '-'}
                                </span>
                                <span className="text-[10px] text-red-400/70">强赎</span>
                                <span className="text-emerald-400 font-mono font-bold text-lg" title="转股价值≤80，下修博弈机会">
                                    {overview.revision_chance_count ?? '-'}
                                </span>
                                <span className="text-[10px] text-emerald-400/70">下修</span>
                            </div>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="bg-slate-800/30 border border-slate-700/30 rounded-xl p-4 flex items-center gap-4">
                    <span className="text-lg">📜</span>
                    <div>
                        <div className="text-sm font-bold text-slate-400">可转债市场概览</div>
                        <div className="text-xs text-slate-500">{overview === null ? '加载中...' : '请先在数据中心同步可转债数据'}</div>
                    </div>
                </div>
            )}

            {/* ━━━ 第二层：筛选条件 ━━━ */}
            <div className="bg-slate-900/50 backdrop-blur-md border border-slate-700/50 rounded-2xl p-5 shadow-sm">
                {/* 策略预设 */}
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                    <Zap className="w-4 h-4 text-amber-400" /> 策略预设
                </h3>
                <div className="grid grid-cols-4 gap-3 mb-5">
                    {PRESETS.map(p => {
                        const isActive = activePreset === p.id;
                        const colors = presetColors[p.color];
                        const desc = p.params.includeAll
                            ? (newBondOnly && p.id === 'all' ? '上市≤1年 · 新债' : '无限制 · 全部')
                            : `价格≤${p.params.maxPrice} · 溢价≤${p.params.maxPremium}% · 评级≥${p.params.minRating === '不限' ? '不限' : p.params.minRating}`;
                        if (p.id === 'all') {
                            return (
                                <div key={p.id} className={`p-3 rounded-xl border transition-all text-left ${isActive ? colors.active : colors.idle} ${loading ? 'opacity-60' : ''}`}>
                                    <div className="text-sm font-bold">{p.label}</div>
                                    <div className="flex mt-1.5 rounded-lg bg-slate-900/60 border border-slate-700/40 overflow-hidden">
                                        <button disabled={loading}
                                            onClick={() => { setNewBondOnly(false); applyPreset({ ...p, params: { ...p.params, newBondOnly: false } }); }}
                                            className={`flex-1 text-xs py-1.5 transition-all ${
                                                isActive && !newBondOnly
                                                    ? 'bg-slate-500/30 text-white font-bold'
                                                    : 'text-slate-500 hover:text-slate-300'
                                            }`}>全部</button>
                                        <div className="w-px bg-slate-700/40" />
                                        <button disabled={loading}
                                            onClick={() => { setNewBondOnly(true); applyPreset({ ...p, params: { ...p.params, newBondOnly: true } }); }}
                                            className={`flex-1 text-xs py-1.5 transition-all ${
                                                isActive && newBondOnly
                                                    ? 'bg-pink-500/25 text-pink-300 font-bold'
                                                    : 'text-slate-500 hover:text-pink-300'
                                            }`}>🆕 新债</button>
                                    </div>
                                    <div className="text-xs mt-1 text-slate-200 font-mono truncate" title={desc}>{desc}</div>
                                </div>
                            );
                        }
                        return (
                            <button key={p.id} onClick={() => applyPreset(p)} disabled={loading}
                                className={`p-3 rounded-xl border transition-all text-left disabled:opacity-60 ${isActive ? colors.active : colors.idle}`}>
                                <div className="text-sm font-bold">{p.label}</div>
                                <div className="text-xs text-slate-400 mt-0.5">{p.desc}</div>
                                <div className="text-xs mt-1 text-slate-200 font-mono truncate" title={desc}>
                                    {desc}
                                </div>
                            </button>
                        );
                    })}
                </div>

                {/* 手动参数 */}
                <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                    <Filter className="w-4 h-4" /> 自定义条件
                </h3>
                <div className="grid grid-cols-4 gap-5 mb-4">
                    {/* 价格上限 slider */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-xs text-slate-400">价格上限</label>
                            <span className="text-sm font-bold text-purple-400 font-mono">{maxPrice}</span>
                        </div>
                        <input type="range" min={90} max={200} step={5} value={maxPrice}
                            onChange={e => { setMaxPrice(Number(e.target.value)); setActivePreset(null); setSmartMode(false); }}
                            className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-purple-500 bg-slate-700" />
                        <div className="flex justify-between mt-1">
                            {[100, 110, 130, 150].map(v => (
                                <span key={v} onClick={() => { setMaxPrice(v); setActivePreset(null); setSmartMode(false); }}
                                    className={`text-[10px] cursor-pointer transition-colors ${maxPrice === v ? 'text-purple-400 font-bold' : 'text-slate-500 hover:text-slate-300'}`}>{v}</span>
                            ))}
                        </div>
                    </div>
                    {/* 溢价率上限 slider */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-xs text-slate-400">溢价率上限(%)</label>
                            <span className="text-sm font-bold text-purple-400 font-mono">{maxPremium}%</span>
                        </div>
                        <input type="range" min={0} max={100} step={5} value={maxPremium}
                            onChange={e => { setMaxPremium(Number(e.target.value)); setActivePreset(null); setSmartMode(false); }}
                            className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-purple-500 bg-slate-700" />
                        <div className="flex justify-between mt-1">
                            {[15, 30, 50, 80].map(v => (
                                <span key={v} onClick={() => { setMaxPremium(v); setActivePreset(null); setSmartMode(false); }}
                                    className={`text-[10px] cursor-pointer transition-colors ${maxPremium === v ? 'text-purple-400 font-bold' : 'text-slate-500 hover:text-slate-300'}`}>{v}%</span>
                            ))}
                        </div>
                    </div>
                    {/* 最低评级 slider */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-xs text-slate-400">最低评级</label>
                            <span className="text-sm font-bold text-purple-400">{minRating}</span>
                        </div>
                        <input type="range" min={0} max={RATING_OPTIONS.length - 1} step={1}
                            value={RATING_OPTIONS.indexOf(minRating)}
                            onChange={e => { setMinRating(RATING_OPTIONS[Number(e.target.value)]); setActivePreset(null); setSmartMode(false); }}
                            className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-purple-500 bg-slate-700" />
                        <div className="flex justify-between mt-1">
                            {RATING_OPTIONS.map((r, i) => (
                                <span key={r} onClick={() => { setMinRating(r); setActivePreset(null); setSmartMode(false); }}
                                    className={`text-[10px] cursor-pointer transition-colors ${minRating === r ? 'text-purple-400 font-bold' : 'text-slate-500 hover:text-slate-300'}`}>{r}</span>
                            ))}
                        </div>
                    </div>
                    {/* 数量上限 slider */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <label className="text-xs text-slate-400">数量上限</label>
                            <span className="text-sm font-bold text-purple-400 font-mono">{limit}</span>
                        </div>
                        <input type="range" min={10} max={200} step={10} value={limit}
                            onChange={e => { setLimit(Number(e.target.value)); setActivePreset(null); setSmartMode(false); }}
                            className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-purple-500 bg-slate-700" />
                        <div className="flex justify-between mt-1">
                            {[30, 50, 100, 200].map(v => (
                                <span key={v} onClick={() => { setLimit(v); setActivePreset(null); setSmartMode(false); }}
                                    className={`text-[10px] cursor-pointer transition-colors ${limit === v ? 'text-purple-400 font-bold' : 'text-slate-500 hover:text-slate-300'}`}>{v}</span>
                            ))}
                        </div>
                    </div>
                </div>
                {/* 操作按钮 */}
                <div className="flex items-center gap-3">
                    <label className="flex items-center gap-2 cursor-pointer select-none shrink-0" title="使用系统推荐的价格、溢价率、评级条件一键筛选">
                        <input type="checkbox" checked={smartMode} onChange={e => { setSmartMode(e.target.checked); if (e.target.checked) setActivePreset(null); }}
                            className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-amber-500 focus:ring-amber-500/30 cursor-pointer" />
                        <span className={`text-sm font-medium ${smartMode ? 'text-amber-400' : 'text-slate-400'}`}>🧠 推荐条件</span>
                    </label>
                    <button onClick={() => {
                        if (smartMode) {
                            setActivePreset('smart');
                            setLastMode('smart');
                            setMaxPrice(200); setMaxPremium(100); setMinRating('不限'); setLimit(200);
                            fetchWithParams({ maxPrice: 200, maxPremium: 100, minRating: '不限', limit: 200 });
                        } else {
                            fetchData();
                        }
                    }} disabled={loading}
                        className={`flex-1 px-5 py-2.5 rounded-xl font-semibold text-sm shadow-lg transition-all disabled:opacity-60 flex items-center justify-center gap-2 ${btnStatus === 'success' ? 'bg-gradient-to-r from-emerald-500 to-green-500 text-white'
                            : btnStatus === 'warning' ? 'bg-gradient-to-r from-amber-500 to-yellow-500 text-white'
                                : btnStatus === 'error' ? 'bg-gradient-to-r from-red-500 to-rose-500 text-white'
                                    : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white hover:shadow-emerald-500/25'
                            }`}>
                        {loading ? <><RefreshCw className="w-4 h-4 animate-spin" /><span>筛选中...</span></>
                            : btnStatus === 'success' ? <Check className="w-4 h-4" />
                                : <Search className="w-4 h-4" />}
                        {loading ? null
                            : btnStatus === 'success' ? `筛选完成 · ${result.length} 只`
                                : btnStatus === 'warning' ? '未找到结果'
                                    : btnStatus === 'error' ? '✗ 筛选失败'
                                        : '开始筛选'}
                    </button>
                </div>
                <div className="text-xs text-slate-400 mt-3">
                    {smartMode
                        ? '🧠 推荐条件：放宽筛选范围，按双低分排序'
                        : `🔍 条件模式：价格≤${maxPrice} · 溢价率≤${maxPremium}% · 评级≥${minRating} · 数量${limit}`
                    }
                </div>
            </div>

            {/* 条件摘要标签 */}
            {hasSearched && lastParams && (
                <div className="flex items-center gap-2 flex-wrap text-xs mb-3">
                    <span className="text-slate-500">当前条件：</span>
                    <span className="px-2 py-0.5 rounded bg-purple-500/15 text-purple-400 border border-purple-500/20">
                        {lastMode === 'smart' ? '🧠 推荐条件' : lastMode === 'preset' ? '📋 策略预设' : '🔍 条件筛选'}
                    </span>
                    {lastParams.maxPrice < 200 && <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">价格≤{lastParams.maxPrice}</span>}
                    {lastParams.maxPremium < 100 && <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">溢价率≤{lastParams.maxPremium}%</span>}
                    {lastParams.minRating && lastParams.minRating !== '不限' && <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">评级≥{lastParams.minRating}</span>}
                    {lastParams.newBondOnly && <span className="px-2 py-0.5 rounded bg-pink-500/15 text-pink-400 border border-pink-500/20">🆕 上市≤1年</span>}
                    <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">数量: {lastParams.limit}</span>
                    <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">共 {result.length} 只</span>
                    {tradeDate && <span className="px-2 py-0.5 rounded bg-slate-700/50 text-slate-400 border border-slate-600/30">数据: {tradeDate}</span>}
                </div>
            )}

            {/* ━━━ 第三层：双低排行结果表 ━━━ */}
            {loading ? (
                <div className="text-center text-slate-400 py-8">
                    <RefreshCw className="w-5 h-5 animate-spin inline mr-2" />加载中...
                </div>
            ) : result.length > 0 ? (
                <BondResultTable
                    data={result} tradeDate={tradeDate}
                    customBonds={customBonds} setCustomBonds={setCustomBonds}
                    sortKey={sortKey} sortDir={sortDir}
                    onSort={(k, d) => { setSortKey(k); setSortDir(d); }}
                    onViewKline={onViewKline}
                />
            ) : hasSearched ? (
                <div className="text-center text-slate-500 py-8">暂无符合条件的可转债，请调整筛选参数</div>
            ) : null}
        </div>
    );
};

export default BondTab;

