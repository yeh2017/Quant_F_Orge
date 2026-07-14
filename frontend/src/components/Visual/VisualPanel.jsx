import React, { useState, useEffect, useCallback, useRef } from 'react';
import { LineChart, Settings, RefreshCw, TrendingUp, Search, Maximize2, Minimize2, Plus } from 'lucide-react';
import KLineChart from '../Charts/KLineChart';
import DiagnosisCard from './DiagnosisCard';
import { stockApi, bondApi, newsApi } from '../../services/api';
import { classifyAsset, getExchange } from '../../utils/assetType';
import { addToPool, removeFromPool } from '../../utils/poolActions';
import { toLocalDate } from '../../utils/dateUtils';

// debounce 工具
const useDebounce = (callback, delay) => {
    const timerRef = useRef(null);
    useEffect(() => () => clearTimeout(timerRef.current), []);
    return useCallback((...args) => {
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => callback(...args), delay);
    }, [callback, delay]);
};

const VisualPanel = ({ backtestResults, customStocks = [], setCustomStocks, setCustomBonds, initialStock = null, onInitialStockConsumed }) => {
    const [adjustType, setAdjustType] = useState('qfq');
    const [selectedStock, setSelectedStock] = useState('');
    const [stockName, setStockName] = useState('');
    const [klineData, setKlineData] = useState([]);
    const [volumeData, setVolumeData] = useState([]);
    const [klineLoading, setKlineLoading] = useState(false);
    const [klineError, setKlineError] = useState(null);
    const [manualCode, setManualCode] = useState('');

    // 智能搜索状态
    const [searchSuggestions, setSearchSuggestions] = useState([]);
    const [showDropdown, setShowDropdown] = useState(false);
    const [activeIdx, setActiveIdx] = useState(-1);
    const dropdownRef = useRef(null);
    const searchInputRef = useRef(null);
    const [indicator, setIndicator] = useState(null); // 'macd' | 'rsi' | 'boll' | 'donchian' | 'grid' | null
    const [gridParams, setGridParams] = useState({ ma_window: 20, grid_pct: 3, num_grids: 3 });
    const [showMA, setShowMA] = useState(true);
    const [showNewsMarkers, setShowNewsMarkers] = useState(true);
    const [showMargin, setShowMargin] = useState(false);
    const [marginData, setMarginData] = useState([]);
    const [isFullscreen, setIsFullscreen] = useState(false);

    // 技术诊断
    const [diagnosis, setDiagnosis] = useState(null);
    const [diagLoading, setDiagLoading] = useState(false);

    // K线新闻事件标记
    // newsMarkers 改为 useMemo 派生，不再用 useState
    const [stockNews, setStockNews] = useState([]);     // 原始新闻列表（供底部条显示）
    const [newsExpanded, setNewsExpanded] = useState(false);
    const newsFetchedRef = useRef(new Set()); // 已尝试按需抓取的 code，防重复
    const newsTimerRef = useRef(null);        // 按需抓取的延迟重查定时器

    const toggleFullscreen = useCallback(() => setIsFullscreen(prev => !prev), []);

    // ESC 退出全屏
    useEffect(() => {
        if (!isFullscreen) return;
        const handleEsc = (e) => { if (e.key === 'Escape') setIsFullscreen(false); };
        window.addEventListener('keydown', handleEsc);
        return () => window.removeEventListener('keydown', handleEsc);
    }, [isFullscreen]);

    const chartHeight = isFullscreen ? Math.max(600, window.innerHeight - 100) : 560;
    // K线日期范围（默认不限起始，后端自动返回 DB 中所有数据）
    const today = toLocalDate(new Date());
    const [klineStart, setKlineStart] = useState('');
    const [klineEnd, setKlineEnd] = useState(today);
    const [klinePeriod, setKlinePeriod] = useState('D'); // D/W/M/Q

    // 策略 → 默认指标映射（回测完自动切换）
    const STRATEGY_INDICATOR_MAP = {
        macd: 'macd', timing: null, bband: 'boll', turtle: 'donchian',
        volume_breakout: null, grid: null, multifactor: null,
        double_low_cb: null, etf_momentum: null,
    };

    const indicatorOptions = [
        { value: 'macd', label: 'MACD' },
        { value: 'rsi', label: 'RSI' },
        { value: 'kdj', label: 'KDJ' },
        { value: 'boll', label: '布林带' },
        { value: 'donchian', label: '唐奇安' },
        { value: 'grid', label: '网格' },
    ];

    // 回测结果变化时，自动切换到对应指标
    useEffect(() => {
        if (backtestResults?.strategy_type) {
            const st = backtestResults.strategy_type;
            const sp = backtestResults.strategy_params || {};
            // MACD 策略的 RSI 模式 → 切换到 RSI 指标
            if (st === 'macd' && sp.mode === 'rsi') {
                setIndicator('rsi');
            } else {
                const mapped = STRATEGY_INDICATOR_MAP[st];
                if (mapped !== undefined) setIndicator(mapped);
            }
        }
        // 自动跳转到回测日期范围（向前多拉 30 天提供上下文）
        if (backtestResults?.dates?.length > 0) {
            const dates = backtestResults.dates;
            const first = dates[0];
            const last = dates[dates.length - 1];
            const pre = toLocalDate(new Date(new Date(first).getTime() - 30 * 86400000));
            setKlineStart(pre);
            setKlineEnd(last);
        }
    }, [backtestResults]);

    const adjustOptions = [
        { value: 'qfq', label: '前复权', desc: '以最新价格为基准向前调整' },
        { value: 'hfq', label: '后复权', desc: '以上市首日价格为基准向后调整' },
        { value: 'none', label: '不复权', desc: '显示实际交易价格' },
    ];

    // 跨模块跳转：优先使用 initialStock
    useEffect(() => {
        if (initialStock) {
            setSelectedStock(initialStock);
            onInitialStockConsumed?.();
        } else if (customStocks.length > 0 && !selectedStock) {
            setSelectedStock(customStocks[0].code);
        }
    }, [initialStock, customStocks, selectedStock]);

    // 获取 K 线数据 + 股票名称 + 技术诊断
    useEffect(() => {
        if (!selectedStock) return;

        // 先从自选池查名称
        const poolStock = customStocks.find(s => s.code === selectedStock);
        if (poolStock?.name) {
            setStockName(poolStock.name);
        } else {
            // 手动输入时调接口查名称
            stockApi.getInfo(selectedStock).then(info => {
                if (info?.name) setStockName(info.name);
                else setStockName('');
            }).catch(() => setStockName(''));
        }

        // 并行加载技术诊断
        setDiagLoading(true);

        setStockNews([]);
        setNewsExpanded(false);
        clearTimeout(newsTimerRef.current); // 清除前一只股票的延迟重查
        stockApi.getDiagnosis(selectedStock, klineEnd)
            .then(d => setDiagnosis(d))
            .catch(() => setDiagnosis(null))
            .finally(() => setDiagLoading(false));

        // 并行加载新闻事件标记（空结果时按需抓取）
        // 新闻 related_codes 存带后缀格式，code 参数用 contains 子串匹配
        const bareCode = selectedStock.split('.')[0];
        // 查询天数跟随 K 线日期范围（klineStart ~ 今天），钳位 7~365
        // klineStart 为空表示"不限起始"，fallback 90 天（与 NEWS_RETAIN_DAYS 对齐）
        const klineDays = klineStart
            ? Math.min(365, Math.max(7, Math.ceil((Date.now() - new Date(klineStart).getTime()) / 86400000) || 90))
            : 90;
        const loadNewsMarkers = (items) => {
            if (!items?.length) { setStockNews([]); return; }
            setStockNews(items.filter(n => (n.sentiment_score || 0) !== 0));
        };

        newsApi.getList({ code: bareCode, days: klineDays, limit: 200, include_events: true })
            .then(res => {
                if (res?.items?.length) {
                    loadNewsMarkers(res.items);
                } else if (!newsFetchedRef.current.has(bareCode)) {
                    // DB 无该股新闻 → 按需抓取一次
                    newsFetchedRef.current.add(bareCode);
                    newsApi.refresh([selectedStock]).catch(() => {});
                    // AkShare 后台 ~1-3s，等待后重查
                    newsTimerRef.current = setTimeout(() => {
                        newsApi.getList({ code: bareCode, days: klineDays, limit: 200, include_events: true })
                            .then(r => loadNewsMarkers(r?.items))
                            .catch(() => setStockNews([]));
                    }, 3500);
                } else {
                    setStockNews([]);
                }
            })
            .catch(() => setStockNews([]));

        const fetchKlineData = async () => {
            setKlineLoading(true);
            setKlineError(null);
            try {
                const result = await stockApi.getHistory(selectedStock, klineStart, klineEnd, adjustType);
                if (result && result.data && result.data.length > 0) {
                    setKlineData(result.data.map(item => ({
                        time: item.date || item.time,
                        open: parseFloat(item.open),
                        high: parseFloat(item.high),
                        low: parseFloat(item.low),
                        close: parseFloat(item.close),
                        volume: parseFloat(item.volume) || 0,
                        amount: parseFloat(item.amount) || 0,
                        turnover_rate: item.turnover_rate != null ? parseFloat(item.turnover_rate) : null,
                    })));
                    setVolumeData(result.data.map(item => ({
                        time: item.date || item.time,
                        value: parseFloat(item.volume) || 0,
                        color: parseFloat(item.close) >= parseFloat(item.open) ? '#ef4444' : '#22c55e',
                    })));
                } else {
                    setKlineError(result?.message || '无法获取行情数据（请先同步本地数仓）');
                }
            } catch (err) {
                setKlineError(err.message || '获取数据失败');
            } finally {
                setKlineLoading(false);
            }
        };
        fetchKlineData();

        // 并行加载融资余额（仅股票类资产）
        const assetType = classifyAsset(selectedStock);
        if (assetType === 'stock') {
            stockApi.getMargin(selectedStock, klineStart, klineEnd)
                .then(res => setMarginData(res?.data || []))
                .catch(() => setMarginData([]));
        } else {
            setMarginData([]);
        }
    }, [selectedStock, adjustType, klineStart, klineEnd]);

    // 周期分组键：将任意日期映射到所属周期标识（日/周/月/季统一入口）
    const getPeriodKey = (dateStr, period) => {
        if (period === 'D') return dateStr;
        const d = new Date(dateStr);
        if (period === 'W') {
            const day = d.getDay() || 7;
            const mon = new Date(d); mon.setDate(d.getDate() - day + 1);
            return toLocalDate(mon);
        }
        if (period === 'M') return dateStr.slice(0, 7);
        if (period === 'Q') {
            const q = Math.floor(d.getMonth() / 3);
            return `${d.getFullYear()}-Q${q + 1}`;
        }
        return dateStr;
    };

    // 聚合函数：日线 → 周/月/季 K线，同时输出 periodMap 供 marker 对齐
    const resampleKline = (dailyData, period) => {
        if (period === 'D' || !dailyData.length) return { data: dailyData, periodMap: null };
        const groups = {};
        dailyData.forEach(bar => {
            const key = getPeriodKey(bar.time, period);
            if (!groups[key]) groups[key] = [];
            groups[key].push(bar);
        });
        // periodKey → 该周期第一个交易日（K线、marker 共用时间轴）
        const periodMap = new Map();
        for (const [key, bars] of Object.entries(groups)) {
            periodMap.set(key, bars[0].time);
        }
        const data = Object.entries(groups)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([key, bars]) => {
                // 换手率：周期内累加（一周换手 = 每天换手之和）
                const trVals = bars.map(b => b.turnover_rate).filter(v => v != null);
                return {
                    time: bars[0].time,
                    open: bars[0].open,
                    high: Math.max(...bars.map(b => b.high)),
                    low:  Math.min(...bars.map(b => b.low)),
                    close: bars[bars.length - 1].close,
                    volume: bars.reduce((s, b) => s + (b.volume || 0), 0),
                    amount: bars.reduce((s, b) => s + (b.amount || 0), 0),
                    turnover_rate: trVals.length ? trVals.reduce((a, b) => a + b, 0) : null,
                };
            });
        return { data, periodMap };
    };

    const resampleVolume = (dailyVol, dailyBar, period) => {
        if (period === 'D' || !dailyVol.length) return dailyVol;
        const groups = {};
        dailyVol.forEach((v, i) => {
            const key = getPeriodKey(v.time, period);
            if (!groups[key]) groups[key] = { time: v.time, value: 0, lastIdx: i };
            groups[key].value += v.value;
            groups[key].lastIdx = i;
        });
        return Object.values(groups).map(g => ({
            time: g.time,
            value: g.value,
            color: dailyBar[g.lastIdx]?.color || g.color,
        }));
    };

    // 统一搜索（股票 + 可转债，合并结果）
    const searchAll = useCallback(async (keyword) => {
        if (!keyword || keyword.trim().length < 1) {
            setSearchSuggestions([]); setShowDropdown(false); return;
        }
        try {
            const [stockRes, bondRes] = await Promise.allSettled([
                stockApi.search(keyword.trim()),
                bondApi.search(keyword.trim()),
            ]);
            const rawStocks = (stockRes.status === 'fulfilled' ? stockRes.value.results || [] : []);
            const stocks = rawStocks.map(s => ({ ...s, _type: classifyAsset(s.code) === 'etf' ? 'ETF' : '股票' }));
            const bonds = (bondRes.status === 'fulfilled' ? bondRes.value.results || [] : []).map(b => ({ ...b, _type: '转债' }));
            const merged = [...stocks.slice(0, 8), ...bonds.slice(0, 5)];
            setSearchSuggestions(merged);
            setShowDropdown(merged.length > 0);
            setActiveIdx(-1);
        } catch {
            setSearchSuggestions([]); setShowDropdown(false);
        }
    }, []);

    const debouncedSearch = useDebounce(searchAll, 300);

    // 点击外部关闭下拉
    useEffect(() => {
        const handleClick = (e) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target)) setShowDropdown(false);
        };
        document.addEventListener('mousedown', handleClick);
        return () => document.removeEventListener('mousedown', handleClick);
    }, []);

    // 选中建议项
    const selectSuggestion = (item) => {
        setSelectedStock(item.code);
        setManualCode('');
        setShowDropdown(false);
    };

    // 手动搜索（直接输入代码回车）
    const handleManualSearch = () => {
        const code = manualCode.trim().toUpperCase();
        if (code) { setSelectedStock(code); setManualCode(''); setShowDropdown(false); }
    };

    // 键盘导航
    const handleSearchKeyDown = (e) => {
        if (!showDropdown || searchSuggestions.length === 0) {
            if (e.key === 'Enter') handleManualSearch();
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveIdx(prev => Math.min(prev + 1, searchSuggestions.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveIdx(prev => Math.max(prev - 1, 0));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeIdx >= 0) selectSuggestion(searchSuggestions[activeIdx]);
            else handleManualSearch();
        } else if (e.key === 'Escape') {
            setShowDropdown(false);
        }
    };

    // 按周期聚合后的展示数据
    const { data: displayKline, periodMap } = resampleKline(klineData, klinePeriod);
    const displayVolume = resampleVolume(volumeData, klineData, klinePeriod);

    // 新闻标记：根据当前周期动态聚合（日线按天，周线按周，月线按月…）
    const newsMarkers = React.useMemo(() => {
        if (!stockNews.length) return [];
        const byPeriod = {};
        for (const item of stockNews) {
            if (!item.publish_time) continue;
            const date = item.publish_time.slice(0, 10);
            const key = getPeriodKey(date, klinePeriod);
            if (!byPeriod[key]) byPeriod[key] = [];
            byPeriod[key].push(item);
        }
        return Object.entries(byPeriod).map(([key, list]) => {
            const displayTime = periodMap ? periodMap.get(key) : key;
            if (!displayTime) return null;
            const pos = list.filter(n => (n.sentiment_score || 0) > 0).length;
            const neg = list.filter(n => (n.sentiment_score || 0) < 0).length;
            if (!pos && !neg) return null;
            const dominant = pos >= neg;
            // 标记文字：保持简短，事件类型在 tooltip 中展示
            let text = '';
            if (pos && neg) text = `${pos}好${neg}空`;
            else if (pos) text = pos > 1 ? `${pos}利好` : '利好';
            else if (neg) text = neg > 1 ? `${neg}利空` : '利空';

            // tooltip：事件标签 + 情绪箭头（颜色保持黄/紫，不与买卖点冲突）
            const tip = list.map(n => {
                const s = n.sentiment_score || 0;
                const et = n.event_type || '其他';
                const color = s > 0 ? '#f59e0b' : s < 0 ? '#8b5cf6' : '#94a3b8';
                const arrow = s > 0 ? '▲' : s < 0 ? '▼' : '─';
                return `<span style="color:#60a5fa;font-weight:600">[${et}]</span> <span style="color:${color}">${arrow}</span> ${n.nlp_reason || n.title}`;
            }).join('<br>');
            return {
                time: displayTime, position: 'aboveBar',
                color: dominant ? '#f59e0b' : '#8b5cf6',
                shape: 'circle', text, size: 0.5, tooltip: tip,
            };
        }).filter(Boolean);
    }, [stockNews, klinePeriod, periodMap]);

    return (
        <div className="space-y-6">
            {/* 标题和复权选择 */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                    <div className="p-2.5 bg-indigo-500/20 rounded-xl border border-indigo-500/30">
                        <LineChart className="w-6 h-6 text-indigo-400" />
                    </div>
                    可视化分析
                </h2>
                {/* 复权选择器 */}
                <div className="flex items-center gap-3 bg-slate-800/60 backdrop-blur-sm px-4 py-2.5 rounded-xl border border-slate-700/50 shadow-sm">
                    <Settings className="w-4 h-4 text-indigo-400" />
                    <span className="text-sm text-slate-300 font-medium">复权类型</span>
                    <div className="flex gap-1 bg-slate-900/50 p-1 rounded-lg border border-slate-700/50">
                        {adjustOptions.map(opt => (
                            <button key={opt.value} onClick={() => setAdjustType(opt.value)} title={opt.desc}
                                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all duration-300 ${adjustType === opt.value
                                    ? 'bg-indigo-500 text-white shadow-[0_0_10px_rgba(99,102,241,0.3)] scale-105 relative z-10'
                                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'}`}>
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {/* K 线图区块（始终显示，不依赖回测结果）*/}
            <div className={`p-6 rounded-2xl border border-slate-700/50 shadow-lg mb-6 transition-all duration-300 ${
                isFullscreen
                    ? 'fixed inset-0 z-50 bg-slate-900 rounded-none overflow-auto'
                    : 'bg-slate-800/40 backdrop-blur-sm'
            }`}>
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                    <div className="flex items-center gap-3 flex-wrap">
                        <h3 className="text-lg font-bold text-white flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]"></div>
                            行情走势
                            {selectedStock && (
                                <span className="text-indigo-300 font-mono text-sm ml-1">
                                    {stockName ? `${stockName}（${selectedStock}）` : selectedStock}
                                </span>
                            )}
                        </h3>
                        {selectedStock && (setCustomStocks || setCustomBonds) && (() => {
                            const inPool = customStocks.some(s => s.code === selectedStock);
                            return inPool ? (
                                <button onClick={() => removeFromPool(selectedStock, setCustomStocks, setCustomBonds)}
                                    className="text-xs px-2.5 py-1 rounded-lg bg-indigo-900/30 text-indigo-400 border border-indigo-500/30 hover:bg-red-900/30 hover:text-red-400 hover:border-red-500/30 transition-all flex items-center gap-1"
                                    title="点击移出自选池">
                                    ✓ 已选
                                </button>
                            ) : (
                                <button onClick={() => addToPool(selectedStock, stockName, {}, setCustomStocks, setCustomBonds)}
                                    className="text-xs px-2.5 py-1 rounded-lg bg-emerald-600/30 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-600/50 transition-all flex items-center gap-1">
                                    <Plus className="w-3 h-3" /> 加入自选
                                </button>
                            );
                        })()}

                        {/* 自选池下拉 */}
                        {customStocks.length > 0 && (
                            <div className="relative group">
                                <select value={selectedStock} onChange={(e) => setSelectedStock(e.target.value)}
                                    className="appearance-none bg-slate-800 text-white pl-4 pr-10 py-1.5 rounded-lg border border-slate-600/50 hover:border-indigo-500/50 focus:border-indigo-500 focus:outline-none text-sm font-medium cursor-pointer">
                                    {customStocks.map(stock => (
                                        <option key={stock.code} value={stock.code}>{stock.code} - {stock.name}</option>
                                    ))}
                                </select>
                                <div className="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none text-slate-400">
                                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 9l-7 7-7-7"></path></svg>
                                </div>
                            </div>
                        )}

                        {/* 智能搜索框 */}
                        <div className="relative" ref={dropdownRef}>
                            <div className="flex items-center gap-1">
                                <div className="relative">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
                                    <input ref={searchInputRef} type="text" value={manualCode}
                                        onChange={e => { setManualCode(e.target.value); debouncedSearch(e.target.value); }}
                                        onKeyDown={handleSearchKeyDown}
                                        onFocus={() => searchSuggestions.length > 0 && setShowDropdown(true)}
                                        placeholder="代码/名称搜索"
                                        className="bg-slate-900/60 text-white pl-8 pr-2 py-1.5 w-44 rounded-lg border border-slate-600/50 hover:border-indigo-500/50 focus:border-indigo-500 focus:outline-none text-sm" />
                                </div>
                                <button onClick={handleManualSearch}
                                    className="p-1.5 rounded-lg bg-indigo-600/40 hover:bg-indigo-600/70 border border-indigo-500/40 text-indigo-300 transition-all">
                                    <Search className="w-4 h-4" />
                                </button>
                            </div>
                            {showDropdown && searchSuggestions.length > 0 && (
                                <div className="absolute top-full left-0 mt-1 w-72 bg-slate-800 border border-slate-600 rounded-lg shadow-2xl z-50 max-h-[280px] overflow-y-auto">
                                    {searchSuggestions.map((item, idx) => {
                                        const isDelisted = item.listed === false;
                                        return (
                                        <div key={`${item.code}-${item._type}`}
                                            onMouseDown={(e) => { e.preventDefault(); selectSuggestion(item); }}
                                            className={`flex items-center justify-between px-3 py-2 cursor-pointer transition-colors ${
                                                isDelisted ? 'opacity-60' : ''
                                            } ${
                                                idx === activeIdx ? 'bg-indigo-600/40 text-white' : 'text-slate-300 hover:bg-slate-700/80 hover:text-white'
                                            }`}>
                                            <div className="flex items-center gap-2">
                                                <span className={`font-mono font-bold text-xs tracking-wider ${isDelisted ? 'line-through text-slate-500' : ''}`}>{item.code}</span>
                                                <span className={`text-sm truncate max-w-[120px] ${isDelisted ? 'text-slate-500' : ''}`}>{item.name}</span>
                                                {isDelisted && <span className="text-[10px] px-1 py-0.5 rounded bg-red-900/40 text-red-400 border border-red-800/30">已退市</span>}
                                            </div>
                                            <span className={`text-xs px-1.5 py-0.5 rounded ${
                                                item._type === '转债' ? 'bg-purple-900/50 text-purple-300' : item._type === 'ETF' ? 'bg-emerald-900/50 text-emerald-300' : 'bg-blue-900/50 text-blue-300'
                                            }`}>{item._type}</span>
                                        </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>

                        {/* 周期切换 + 日期范围 */}
                        <div className="flex items-center gap-1.5 flex-wrap">
                            {/* 周期按钮 */}
                            {[{label:'日K',val:'D'},{label:'周K',val:'W'},{label:'月K',val:'M'},{label:'季K',val:'Q'}].map(({label,val}) => (
                                <button key={val}
                                    onClick={() => setKlinePeriod(val)}
                                    className={`px-2.5 py-1 text-xs font-bold rounded border transition-all ${klinePeriod === val ? 'bg-indigo-600/50 border-indigo-400/60 text-indigo-200' : 'border-slate-700/50 text-slate-400 hover:border-slate-500 hover:text-slate-200'}`}>
                                    {label}
                                </button>
                            ))}
                            <span className="text-slate-600 text-xs mx-1">|</span>
                            <input type="date" value={klineStart} max={klineEnd}
                                onChange={e => setKlineStart(e.target.value)}
                                style={{ colorScheme: 'dark' }}
                                className="bg-slate-800 text-slate-300 text-xs px-2 py-1 rounded border border-slate-700/50 focus:border-indigo-500 focus:outline-none" />
                            <span className="text-slate-500 text-xs">→</span>
                            <input type="date" value={klineEnd} min={klineStart} max={today}
                                onChange={e => setKlineEnd(e.target.value)}
                                style={{ colorScheme: 'dark' }}
                                className="bg-slate-800 text-slate-300 text-xs px-2 py-1 rounded border border-slate-700/50 focus:border-indigo-500 focus:outline-none" />
                            {/* 指标选择器 */}
                            <span className="text-slate-600 text-xs mx-1">|</span>
                            <button
                                onClick={() => setShowMA(prev => !prev)}
                                className={`px-2.5 py-1 text-xs font-bold rounded border transition-all ${
                                    showMA
                                        ? 'bg-indigo-600/50 border-indigo-400/60 text-indigo-200'
                                        : 'border-slate-700/50 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                                }`}>
                                MA
                            </button>
                            {marginData.length > 0 && (
                                <button
                                    onClick={() => setShowMargin(prev => !prev)}
                                    className={`px-2.5 py-1 text-xs font-bold rounded border transition-all ${
                                        showMargin
                                            ? 'bg-amber-600/50 border-amber-400/60 text-amber-200'
                                            : 'border-slate-700/50 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                                    }`}>
                                    融资
                                </button>
                            )}
                            {indicatorOptions.map(opt => (
                                <button key={opt.value}
                                    onClick={() => setIndicator(prev => prev === opt.value ? null : opt.value)}
                                    className={`px-2.5 py-1 text-xs font-bold rounded border transition-all ${
                                        indicator === opt.value
                                            ? 'bg-amber-600/50 border-amber-400/60 text-amber-200'
                                            : 'border-slate-700/50 text-slate-400 hover:border-slate-500 hover:text-slate-200'
                                    }`}>
                                    {opt.label}
                                </button>
                            ))}
                            {indicator === 'grid' && (
                                <>
                                    <span className="text-slate-600 text-xs mx-0.5">|</span>
                                    <label className="text-white text-xs font-semibold flex items-center gap-0.5">MA
                                        <input type="number" min={5} max={60} step={1} value={gridParams.ma_window}
                                            onChange={e => setGridParams(p => ({ ...p, ma_window: +e.target.value || 20 }))}
                                            className="w-11 bg-slate-900/80 text-white text-xs font-bold px-1.5 py-1 rounded border border-slate-500/50 focus:border-white focus:outline-none text-center" />
                                    </label>
                                    <label className="text-white text-xs font-semibold flex items-center gap-0.5">间距
                                        <input type="number" min={1} max={10} step={0.5} value={gridParams.grid_pct}
                                            onChange={e => setGridParams(p => ({ ...p, grid_pct: +e.target.value || 3 }))}
                                            className="w-12 bg-slate-900/80 text-white text-xs font-bold px-1.5 py-1 rounded border border-slate-500/50 focus:border-white focus:outline-none text-center" />%
                                    </label>
                                    <label className="text-white text-xs font-semibold flex items-center gap-0.5">层数
                                        <input type="number" min={1} max={6} step={1} value={gridParams.num_grids}
                                            onChange={e => setGridParams(p => ({ ...p, num_grids: +e.target.value || 3 }))}
                                            className="w-11 bg-slate-900/80 text-white text-xs font-bold px-1.5 py-1 rounded border border-slate-500/50 focus:border-white focus:outline-none text-center" />
                                    </label>
                                </>
                            )}
                        </div>

                        {klineLoading && (
                            <div className="flex items-center gap-2 text-indigo-400 text-sm font-medium">
                                <RefreshCw className="w-4 h-4 animate-spin" />
                                <span>加载中...</span>
                            </div>
                        )}
                    </div>

                    <div className="flex items-center gap-3">
                        
                        <button onClick={toggleFullscreen}
                            className="p-1.5 rounded-lg border border-slate-600/50 text-slate-400 hover:text-white hover:border-indigo-500/50 hover:bg-indigo-600/20 transition-all"
                            title={isFullscreen ? '退出全屏 (ESC)' : '全屏模式'}>
                            {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                        </button>
                    </div>
                </div>

                {/* 技术诊断卡片 */}
                {selectedStock && (
                    <div className="mb-4">
                        <DiagnosisCard diagnosis={diagnosis} loading={diagLoading} />
                    </div>
                )}

                {klineError ? (
                    <div className="w-full h-[560px] flex items-center justify-center bg-slate-900/30 rounded-xl border border-red-500/20">
                        <div className="text-center flex flex-col items-center">
                            <div className="w-12 h-12 rounded-full bg-red-900/20 flex items-center justify-center mb-3">
                                <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                            </div>
                            <p className="text-red-400 font-medium tracking-wide mb-1">行情数据获取失败</p>
                            <p className="text-xs text-slate-500 font-mono">{klineError}</p>
                        </div>
                    </div>
                ) : klineLoading && klineData.length === 0 ? (
                    <div className="w-full h-[560px] flex items-center justify-center bg-slate-900/30 rounded-xl border border-slate-700/30">
                        <div className="flex flex-col items-center gap-3">
                            <RefreshCw className="w-8 h-8 text-indigo-500/70 animate-spin" />
                            <span className="text-indigo-400/70 text-sm font-medium tracking-wider">正在接驳数据源...</span>
                        </div>
                    </div>
                ) : !selectedStock ? (
                    <div className="w-full h-[560px] flex items-center justify-center bg-slate-900/30 rounded-xl border border-dashed border-slate-700/50">
                        <div className="text-center">
                            <TrendingUp className="w-10 h-10 text-indigo-500/30 mx-auto mb-3" />
                            <p className="text-slate-400 text-sm">从自选池选择股票，或在上方输入代码后按 Enter 搜索</p>
                        </div>
                    </div>
                ) : (
                    <>
                    {/* K 线上方新闻条 */}
                    {stockNews.length > 0 && (
                        <div style={{
                            background: 'rgba(15,23,42,0.6)', borderBottom: '1px solid rgba(148,163,184,0.15)',
                            padding: newsExpanded ? '8px 12px' : '4px 12px',
                            fontSize: '12px', color: '#94a3b8', transition: 'all 0.2s',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', gap: '8px' }}
                                 onClick={() => setNewsExpanded(p => !p)}>
                                <span style={{ color: '#e2e8f0', flexShrink: 0 }}>📰 相关新闻 ({stockNews.length})</span>
                                <button
                                    onClick={(e) => { e.stopPropagation(); setShowNewsMarkers(p => !p); }}
                                    style={{
                                        fontSize: '12px', padding: '1px 6px', borderRadius: '4px', cursor: 'pointer',
                                        border: `1px solid ${showNewsMarkers ? 'rgba(99,102,241,0.5)' : 'rgba(148,163,184,0.3)'}`,
                                        background: showNewsMarkers ? 'rgba(99,102,241,0.2)' : 'transparent',
                                        color: showNewsMarkers ? '#a5b4fc' : '#64748b',
                                    }}
                                    title={showNewsMarkers ? '隐藏K线标记' : '显示K线标记'}
                                >{showNewsMarkers ? '📍标记开' : '📍标记关'}</button>
                                {!newsExpanded && stockNews[0] && (() => {
                                    const n = stockNews[0];
                                    const s = n.sentiment_score || 0;
                                    const color = s > 0 ? '#f59e0b' : s < 0 ? '#8b5cf6' : '#64748b';
                                    const arrow = s > 0 ? '▲' : s < 0 ? '▼' : '─';
                                    const date = n.publish_time?.slice(5, 10) || '';
                                    return (
                                        <span style={{ color: '#94a3b8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1, fontSize: '12px' }}>
                                            <span style={{ color: '#64748b' }}>{date}</span>{' '}
                                            <span style={{ color }}>{arrow}</span>{' '}
                                            {n.nlp_reason || n.title}
                                        </span>
                                    );
                                })()}
                                <span style={{ fontSize: '12px', flexShrink: 0 }}>{newsExpanded ? '收起 ▲' : '展开 ▼'}</span>
                            </div>
                            {newsExpanded && (
                                <div style={{ marginTop: '6px', maxHeight: '120px', overflowY: 'auto' }}>
                                    {stockNews.slice(0, 10).map((n, i) => {
                                        const s = n.sentiment_score || 0;
                                        const color = s > 0 ? '#f59e0b' : s < 0 ? '#8b5cf6' : '#64748b';
                                        const arrow = s > 0 ? '\u25b2' : s < 0 ? '\u25bc' : '\u2500';
                                        const date = n.publish_time?.slice(5, 10) || '';
                                        return (
                                            <div key={i} style={{ padding: '2px 0', display: 'flex', gap: '6px', lineHeight: '1.4' }}>
                                                <span style={{ color: '#64748b', flexShrink: 0 }}>{date}</span>
                                                <span style={{ color, flexShrink: 0 }}>{arrow}</span>
                                                {n.url ? (
                                                    <a href={n.url} target="_blank" rel="noreferrer"
                                                       style={{ color: '#93c5fd', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: 'none' }}
                                                       onMouseEnter={e => e.target.style.textDecoration = 'underline'}
                                                       onMouseLeave={e => e.target.style.textDecoration = 'none'}>
                                                        {n.nlp_reason ? `${n.nlp_reason} — ` : ''}{n.title}
                                                    </a>
                                                ) : (
                                                    <span style={{ color: '#cbd5e1', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                        {n.nlp_reason ? `${n.nlp_reason} — ` : ''}{n.title}
                                                    </span>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    )}
                    <KLineChart
                        data={displayKline}
                        volumeData={displayVolume}
                        markers={(() => {
                            // 回测买卖标记
                            let marks = [];
                            if (backtestResults?.trade_markers && selectedStock) {
                                const tm = backtestResults.trade_markers;
                                // 动态推导后缀（覆盖 .SH/.SZ/.BJ），不再硬编码
                                const code = selectedStock;
                                const bare = code.split('.')[0];
                                const suffixed = code.includes('.') ? code : `${bare}.${getExchange(bare)}`;
                                marks = tm[code] || tm[bare] || tm[suffixed] || [];
                            }
                            // 非日线时，买卖标记也对齐到周期首日
                            if (periodMap && klinePeriod !== 'D') {
                                marks = marks.map(m => {
                                    const key = getPeriodKey(m.time, klinePeriod);
                                    const t = periodMap.get(key);
                                    return t ? { ...m, time: t } : null;
                                }).filter(Boolean);
                            }
                            return [...marks, ...(showNewsMarkers ? newsMarkers : [])];
                        })()}
                        indicator={indicator}
                        showMA={showMA}
                        marginData={showMargin ? marginData : []}
                        strategyType={backtestResults?.strategy_type || null}
                        strategyParams={indicator === 'grid'
                            ? { ...gridParams, ...(backtestResults?.strategy_params || {}) }
                            : (backtestResults?.strategy_params || {})}
                        height={chartHeight}
                    />
                    </>
                )}
            </div>
        </div>
    );
};

export default VisualPanel;
