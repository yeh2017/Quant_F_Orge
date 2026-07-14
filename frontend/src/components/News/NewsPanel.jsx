import React, { useState, useEffect, useCallback } from 'react';
import { Newspaper, Zap, RefreshCw, Filter, Clock, ExternalLink } from 'lucide-react';
import { newsApi } from '../../services/api';
import SentimentBar from './SentimentBar';
import { fmtNum } from '../../utils/format';
import { useTabRefresh } from '../../hooks/useTabRefresh';
import { showToast } from '../../utils/toast';

const MARKET_FILTERS = [
    { key: 'all', label: '全部' },
    { key: 'A股', label: 'A股' },
];

const SOURCE_COLORS = {
    tushare: 'bg-amber-100 text-amber-700',
    akshare: 'bg-blue-100 text-blue-700',
    tavily: 'bg-purple-100 text-purple-700',
};

// ── 事件回测统计面板 ──
function EventStatsPanel({ onViewKline }) {
    const [expanded, setExpanded] = useState(false);
    const [stats, setStats] = useState(null);
    const [details, setDetails] = useState([]);
    const [selectedEvent, setSelectedEvent] = useState(null);
    const [loading, setLoading] = useState(false);

    const loadStats = useCallback(async () => {
        if (stats) { setExpanded(e => !e); return; }
        setLoading(true);
        setExpanded(true);
        try {
            const res = await newsApi.getEventStats();
            setStats(res.summary || {});
            setDetails(res.details || []);
        } catch { setStats({}); }
        setLoading(false);
    }, [stats]);

    // 挂载时静默加载数据（不展开），确保收起状态也有预览
    React.useEffect(() => {
        newsApi.getEventStats()
            .then(res => { setStats(res.summary || {}); setDetails(res.details || []); })
            .catch(() => {});
    }, []);

    const entries = stats ? Object.entries(stats).sort((a, b) => b[1].count - a[1].count) : [];

    return (
        <div className="bg-slate-800/40 border border-slate-700/50 rounded-lg overflow-hidden">
            <div className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-slate-700/30 transition-all"
                 onClick={loadStats}>
                <span className="text-sm font-medium text-slate-200 shrink-0">📊 事件回测统计</span>
                <span className="text-xs text-slate-300 shrink-0">统计事件发生后股价涨跌规律</span>
                {!expanded && entries.length > 0 && (() => {
                    const [et, s] = entries[0];
                    const avg5 = s.avg_5d;
                    const color = (avg5 || 0) > 0 ? 'text-amber-400' : (avg5 || 0) < 0 ? 'text-purple-400' : 'text-slate-400';
                    return (
                        <span className="text-xs text-slate-400 truncate flex-1">
                            <span className="text-slate-300">{et}</span> {s.count}条
                            {avg5 != null && <span className={color}> T+5:{avg5 > 0 ? '+' : ''}{avg5}%</span>}
                        </span>
                    );
                })()}
                <span className="text-xs text-slate-400 shrink-0">{expanded ? '收起 ▲' : '展开 ▼'}</span>
            </div>
            {expanded && (
                <div className="px-3 pb-3">
                    {loading ? (
                        <div className="text-xs text-slate-400 py-2">加载中...</div>
                    ) : entries.length === 0 ? (
                        <div className="text-xs text-slate-400 py-2">暂无事件数据（需同步数据或积累更多标注）</div>
                    ) : (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-slate-400 border-b border-slate-700/50">
                                        <th className="text-left py-1.5 pr-3">事件类型</th>
                                        <th className="text-right py-1.5 px-2 cursor-help" title="该类事件去重后数量，＜10 结果不可靠">样本</th>
                                        <th className="text-right py-1.5 px-2 cursor-help" title="事件后次日即时反应">T+1</th>
                                        <th className="text-right py-1.5 px-2 cursor-help" title="事件后第 5 个交易日（约一周）的平均涨跌幅">T+5均值</th>
                                        <th className="text-right py-1.5 px-2 cursor-help" title="T+5 收益为正的比例，≥60% 为绿色">T+5胜率</th>
                                        <th className="text-right py-1.5 px-2 cursor-help" title="事件后第 10 个交易日（约两周）的平均涨跌幅">T+10均值</th>
                                        <th className="text-right py-1.5 px-2 cursor-help" title="T+10 收益为正的比例">T+10胜率</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {entries.map(([et, s]) => {
                                        const isSelected = selectedEvent === et;
                                        const eventDetails = isSelected ? details.filter(d => d.event === et).sort((a, b) => b.date.localeCompare(a.date)) : [];
                                        return (
                                            <React.Fragment key={et}>
                                                <tr className={`border-b border-slate-700/30 cursor-pointer transition-all ${isSelected ? 'bg-slate-700/40' : 'hover:bg-slate-700/20'}`}
                                                    onClick={() => setSelectedEvent(isSelected ? null : et)}>
                                                    <td className="py-1.5 pr-3 text-slate-200 font-medium cursor-help" title={{
                                                        '重组':'并购/资产重组','业绩':'财报/业绩预告','资金':'龙虎榜/大宗/主力',
                                                        '分红':'分红/送转','诉讼':'法律/处罚','人事':'高管变动',
                                                        '产品':'新品发布/技术突破','合作':'战略合作/签约订单',
                                                        '政策':'监管/补贴/行业政策','行业':'行业趋势/产业链变动',
                                                        '大宗交易':'大宗交易折溢价信号','解禁':'限售股解禁流通','龙虎榜':'异动资金龙虎榜上榜'
                                                    }[et] || et}>{isSelected ? '▼ ' : '▶ '}{et}</td>
                                                    <td className="text-right px-2 text-slate-300">
                                                        {s.count}
                                                        {s.count < 10 && <span className="text-amber-400 ml-1" title="样本不足">⚠</span>}
                                                    </td>
                                                    <td className={`text-right px-2 ${(s.avg_1d || 0) > 0 ? 'text-amber-400' : (s.avg_1d || 0) < 0 ? 'text-purple-400' : 'text-slate-400'}`}>
                                                        {s.avg_1d != null ? `${s.avg_1d > 0 ? '+' : ''}${s.avg_1d}%` : '-'}
                                                    </td>
                                                    <td className={`text-right px-2 ${(s.avg_5d || 0) > 0 ? 'text-amber-400' : (s.avg_5d || 0) < 0 ? 'text-purple-400' : 'text-slate-400'}`}>
                                                        {s.avg_5d != null ? `${s.avg_5d > 0 ? '+' : ''}${s.avg_5d}%` : '-'}
                                                    </td>
                                                    <td className={`text-right px-2 ${(s.win_5d || 0) >= 0.6 ? 'text-emerald-400' : (s.win_5d || 0) <= 0.4 ? 'text-red-400' : 'text-slate-400'}`}>
                                                        {s.win_5d != null ? `${Math.round(s.win_5d * 100)}%` : '-'}
                                                    </td>
                                                    <td className={`text-right px-2 ${(s.avg_10d || 0) > 0 ? 'text-amber-400' : (s.avg_10d || 0) < 0 ? 'text-purple-400' : 'text-slate-400'}`}>
                                                        {s.avg_10d != null ? `${s.avg_10d > 0 ? '+' : ''}${s.avg_10d}%` : '-'}
                                                    </td>
                                                    <td className={`text-right px-2 ${(s.win_10d || 0) >= 0.6 ? 'text-emerald-400' : (s.win_10d || 0) <= 0.4 ? 'text-red-400' : 'text-slate-400'}`}>
                                                        {s.win_10d != null ? `${Math.round(s.win_10d * 100)}%` : '-'}
                                                    </td>
                                                </tr>
                                                {isSelected && eventDetails.length > 0 && (
                                                    <tr>
                                                        <td colSpan={7} className="p-0">
                                                            <div className="bg-slate-800/60 px-3 py-2 max-h-[140px] overflow-y-auto">
                                                                {eventDetails.map((d, i) => (
                                                                    <div key={i} className="flex items-center gap-2 text-xs py-0.5">
                                                                        <span className="text-slate-500 shrink-0">{d.date.slice(5)}</span>
                                                                        <span className="text-blue-300 shrink-0 w-20 cursor-pointer hover:underline" onClick={e => { e.stopPropagation(); onViewKline?.(d.code); }}>{d.code}</span>
                                                                        {d.url ? (
                                                                            <a href={d.url} target="_blank" rel="noreferrer" className="text-blue-400 hover:underline truncate flex-1" title={d.title} onClick={e => e.stopPropagation()}>{d.title}</a>
                                                                        ) : (
                                                                            <span className="text-slate-400 truncate flex-1" title={d.title}>{d.title}</span>
                                                                        )}
                                                                        {d.r5d != null && <span className={`shrink-0 ${d.r5d > 0 ? 'text-amber-400' : d.r5d < 0 ? 'text-purple-400' : 'text-slate-400'}`}>T+5:{d.r5d > 0 ? '+' : ''}{d.r5d}%</span>}
                                                                    </div>
                                                                ))}
                                                            </div>
                                                        </td>
                                                    </tr>
                                                )}
                                            </React.Fragment>
                                        );
                                    })}
                                </tbody>
                            </table>
                            <div className="text-xs text-slate-300 mt-2">
                                金色=正收益 · 紫色=负收益 · 绿色=高胜率(&gt;60%) · ⚠ 样本&lt;10 结果不可靠 · 点击行查看明细
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export default function NewsPanel({ isActive, onViewKline, customStocks = [] }) {
    const [news, setNews] = useState([]);
    const [loading, setLoading] = useState(false);
    const [displayCount, setDisplayCount] = useState(50);
    const [refreshing, setRefreshing] = useState(false);
    const [market, setMarket] = useState('all');
    const [days, setDays] = useState(3);
    const [total, setTotal] = useState(0);
    const [autoEnabled, setAutoEnabled] = useState(false);
    const [autoHours, setAutoHours] = useState(4);
    const [nextFetchTime, setNextFetchTime] = useState(null);
    const [countdown, setCountdown] = useState('');
    const [pipelineStats, setPipelineStats] = useState(null);
    const [codeNameMap, setCodeNameMap] = useState({});
    const [codeChangeMap, setCodeChangeMap] = useState({});

    const [searchTerm, setSearchTerm] = useState('');
    const [activeSearch, setActiveSearch] = useState('');  // 已确认的搜索词（触发后端查询）
    const [onlyWithCodes, setOnlyWithCodes] = useState(false);
    const [searching, setSearching] = useState(false);
    const [searchMsg, setSearchMsg] = useState('');
    const skipNextEffect = React.useRef(false);  // 防止 handleWebSearch 触发 useEffect 双重请求
    const searchTimer = React.useRef(null);        // 防抖搜索定时器

    // 加载自动抓取配置
    useEffect(() => {
        newsApi.getAutoConfig().then(cfg => {
            setAutoEnabled(cfg.enabled);
            setAutoHours(cfg.interval_hours);
            if (cfg.next_fetch_time) setNextFetchTime(new Date(cfg.next_fetch_time));
            if (cfg.pipeline_stats) setPipelineStats(cfg.pipeline_stats);
        }).catch(() => {});
    }, []);

    // 倒计时：每秒更新
    useEffect(() => {
        if (!autoEnabled || !nextFetchTime) { setCountdown(''); return; }
        const tick = () => {
            const diff = Math.max(0, Math.floor((nextFetchTime - Date.now()) / 1000));
            if (diff <= 0) { setCountdown('即将执行'); return; }
            const h = Math.floor(diff / 3600);
            const m = Math.floor((diff % 3600) / 60);
            const s = diff % 60;
            setCountdown(h > 0 ? `${h}h${String(m).padStart(2,'0')}m${String(s).padStart(2,'0')}s` : `${m}m${String(s).padStart(2,'0')}s`);
        };
        tick();
        const id = setInterval(tick, 1000);
        return () => clearInterval(id);
    }, [autoEnabled, nextFetchTime]);

    const [toggling, setToggling] = useState(false);
    const toggleAuto = async () => {
        if (toggling) return;
        setToggling(true);
        const next = !autoEnabled;
        setAutoEnabled(next);  // 乐观更新：立即切换 UI
        if (!next) setNextFetchTime(null);
        try {
            const res = await newsApi.setAutoConfig({ enabled: next, interval_hours: autoHours });
            setAutoEnabled(res.enabled);
            setAutoHours(res.interval_hours);
            if (res.next_fetch_time) setNextFetchTime(new Date(res.next_fetch_time));
            else setNextFetchTime(null);
        } catch (e) {
            setAutoEnabled(!next);  // 回滚
            console.error('Toggle auto-fetch failed:', e);
        } finally {
            setToggling(false);
        }
    };

    const changeHours = async (h) => {
        try {
            const res = await newsApi.setAutoConfig({ enabled: autoEnabled, interval_hours: h });
            setAutoEnabled(res.enabled);
            setAutoHours(res.interval_hours);
            if (res.next_fetch_time) setNextFetchTime(new Date(res.next_fetch_time));
        } catch (e) {
            console.error('Change interval failed:', e);
        }
    };

    const fetchNews = useCallback(async (searchOverride) => {
        setLoading(true);
        try {
            const params = { market, days, limit: 500 };
            // searchOverride 优先于 activeSearch（用于 handleWebSearch 直接传入）
            const search = searchOverride !== undefined ? searchOverride : activeSearch;
            if (search) params.search = search;
            const res = await newsApi.getList(params);
            setNews(res.items || []);
            setTotal(res.total || 0);
            setCodeNameMap(res.code_name_map || {});
            setCodeChangeMap(res.code_change_map || {});
        } catch (e) {
            console.error('Failed to load news:', e);
        } finally {
            setLoading(false);
        }
    }, [market, days, activeSearch]);

    useEffect(() => {
        if (skipNextEffect.current) {
            skipNextEffect.current = false;
            return;
        }
        fetchNews(); setDisplayCount(50);
    }, [fetchNews]);

    useTabRefresh(isActive, fetchNews);

    // 自动抓取完成时静默刷新列表 + 更新倒计时（WS 通知）
    useEffect(() => {
        const onAutoFetch = () => {
            fetchNews();
            // 同步更新下次抓取时间（后端已计算新的 next_fetch_time）
            newsApi.getAutoConfig().then(cfg => {
                if (cfg.next_fetch_time) setNextFetchTime(new Date(cfg.next_fetch_time));
            }).catch(() => {});
        };
        window.addEventListener('ws:news_update', onAutoFetch);
        // LLM 完成后实时更新统计
        const onLlmStats = (e) => {
            const stats = e.detail?.stats;
            if (stats) {
                setPipelineStats(prev => prev ? { ...prev, llm_calls_today: stats.calls, llm_cost_today: stats.cost_today } : prev);
            }
        };
        window.addEventListener('ws:llm_stats_update', onLlmStats);
        return () => {
            window.removeEventListener('ws:news_update', onAutoFetch);
            window.removeEventListener('ws:llm_stats_update', onLlmStats);
        };
    }, [fetchNews]);

    const [refreshMsg, setRefreshMsg] = useState('');

    const handleRefresh = async () => {
        if (refreshing) return;
        setRefreshing(true);
        setRefreshMsg('');
        try {
            const codes = customStocks.map(s => s.code);
            const res = await newsApi.refresh(codes);
            await fetchNews();
            const count = res?.count ?? 0;
            const llmTag = res?.llm_enabled ? ' · LLM 分析中' : ' · LLM 未配置';
            setRefreshMsg(count > 0 ? `✅ 新增 ${count} 条新闻${llmTag}` : `✅ 已刷新${llmTag}`);
        } catch (e) {
            console.error('Refresh failed:', e);
            setRefreshMsg('❌ 刷新失败');
        } finally {
            setRefreshing(false);
            setTimeout(() => setRefreshMsg(''), 4000);
            // LLM 在后台线程异步处理，延迟刷新统计
            setTimeout(() => {
                newsApi.getAutoConfig().then(cfg => {
                    if (cfg.pipeline_stats) setPipelineStats(cfg.pipeline_stats);
                }).catch(() => {});
            }, 5000);
        }
    };

    const handleWebSearch = async () => {
        if (searching || !searchTerm.trim()) return;
        setSearching(true);
        setSearchMsg('');
        try {
            const res = await newsApi.search(searchTerm.trim());
            const llm = res?.llm_enabled ? ' · LLM 分析中' : '';
            setSearchMsg(
                res.count === 0  ? '⚠️ 全网未找到相关新闻'
                : res.inserted > 0 ? `✅ 抓到 ${res.count} 条，新入库 ${res.inserted} 条${llm}`
                : `✅ 找到 ${res.count} 条（均已入库）`
            );
            // 直接用搜索词刷新列表，跳过后续 useEffect 触发的重复请求
            const term = searchTerm.trim();
            skipNextEffect.current = (term !== activeSearch);
            setActiveSearch(term);
            await fetchNews(term);
        } catch (e) {
            setSearchMsg(`❌ ${e.message || '搜索失败'}`);
        } finally {
            setSearching(false);
            setTimeout(() => setSearchMsg(''), 5000);
            setTimeout(() => {
                newsApi.getAutoConfig().then(cfg => {
                    if (cfg.pipeline_stats) setPipelineStats(cfg.pipeline_stats);
                }).catch(() => {});
            }, 5000);
        }
    };

    const formatTime = (isoStr) => {
        if (!isoStr) return '时间未知';
        const d = new Date(isoStr);
        const now = new Date();
        const diffMs = now - d;
        const diffMins = Math.floor(diffMs / 60000);
        const dateStr = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        if (diffMins < 60) return `${diffMins}分钟前 ${dateStr}`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}小时前 ${dateStr}`;
        const diffDays = Math.floor(diffHours / 24);
        return `${diffDays}天前 ${dateStr}`;
    };

    // 前端过滤（搜索已交给后端，这里只处理 onlyWithCodes）
    const filteredNews = news.filter(item => {
        if (onlyWithCodes && (!item.related_codes || item.related_codes.length === 0)) return false;
        return true;
    });
    const visibleNews = filteredNews.slice(0, displayCount);

    // 推送摘要
    const [pushing, setPushing] = useState(false);
    const handleSend = async () => {
        setPushing(true);
        try {
            const res = await newsApi.sendSummary();
            if (res?.success) {
                showToast('推送成功', 'success');
            } else {
                showToast('推送失败：请在右上角 ⚙️ 设置中配置推送渠道', 'warning');
            }
        } catch (e) { showToast('推送失败: ' + e.message, 'error'); }
        setPushing(false);
    };





    return (
        <div className="space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between flex-wrap gap-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                    <Newspaper className="w-5 h-5 text-slate-400" />
                    <h2 className="text-lg font-bold text-white">新闻中心</h2>
                    <span className="text-xs text-slate-400 bg-slate-700/50 px-2 py-0.5 rounded">
                        {filteredNews.length}/{total} 条
                    </span>
                    {pipelineStats && (
                        <span className="flex items-center gap-1.5 text-xs text-slate-500">
                            <span className="text-slate-600">|</span>
                            <span title="新闻总数">📰<span className="text-sm text-white">{pipelineStats.news_total?.toLocaleString()}</span></span>
                            <span title={`LLM已标注 ${pipelineStats.llm_enriched?.toLocaleString()} / 可处理 ${pipelineStats.llm_target?.toLocaleString()}`}>
                                🤖<span className="text-sm text-white">{pipelineStats.llm_target > 0 ? Math.round(pipelineStats.llm_enriched / pipelineStats.llm_target * 100) : 0}%</span>
                            </span>
                            <span title="事件总数">📊<span className="text-sm text-white">{pipelineStats.event_total?.toLocaleString()}</span></span>
                            <span title="今日LLM费用">💰<span className="text-sm text-white">¥{(pipelineStats.llm_cost_today || 0).toFixed(2)}</span>/{pipelineStats.llm_calls_today || 0}次</span>
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-2">
                    {/* 自动抓取开关 */}
                    <button
                        onClick={toggleAuto}
                        disabled={toggling}
                        className={`flex items-center gap-1 px-2.5 py-1.5 text-sm rounded-lg transition-all disabled:opacity-50 ${
                            autoEnabled
                                ? 'bg-emerald-600/20 text-emerald-300 hover:bg-emerald-600/30'
                                : 'bg-slate-700/50 text-slate-400 hover:bg-slate-600/50'
                        }`}
                        title={autoEnabled ? `每${autoHours}小时自动抓取` : '自动抓取已关闭'}
                    >
                        <Zap className="w-3.5 h-3.5" />
                        {autoEnabled ? '自动' : '自动关'}
                    </button>
                    {autoEnabled && (
                        <>
                            <select
                                value={autoHours}
                                onChange={e => changeHours(Number(e.target.value))}
                                className="px-1.5 py-1 text-xs bg-slate-800 text-white rounded border border-slate-600 [&>option]:bg-slate-800 [&>option]:text-white"
                            >
                                {[1, 2, 4, 6, 8, 12, 24].map(h => (
                                    <option key={h} value={h}>{h}小时</option>
                                ))}
                            </select>
                            {countdown && (
                                <span className="text-xs text-amber-400/80 font-mono" title="距下次自动抓取">
                                    ⏱{countdown}
                                </span>
                            )}
                        </>
                    )}
                    <button
                        onClick={handleRefresh}
                        disabled={refreshing}
                        className="flex items-center gap-1 px-2.5 py-1.5 text-sm bg-indigo-600/20 text-indigo-300
                                 rounded-lg hover:bg-indigo-600/30 disabled:opacity-50 transition-all"
                    >
                        <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                        {refreshing ? '抓取中...' : '刷新新闻'}
                    </button>
                    {refreshMsg && (
                        <span className="text-xs text-slate-300 animate-pulse">{refreshMsg}</span>
                    )}
                </div>
            </div>

            {/* 事件回测统计面板 */}
            <EventStatsPanel onViewKline={onViewKline} />

            {/* Filters */}
            <div className="flex items-center gap-3 flex-wrap">
                <div className="flex items-center gap-1">
                    <Filter className="w-3.5 h-3.5 text-slate-500" />
                    {MARKET_FILTERS.map(f => (
                        <button
                            key={f.key}
                            onClick={() => setMarket(f.key)}
                            className={`px-3 py-1 text-xs rounded-full transition-all ${
                                market === f.key
                                    ? 'bg-indigo-600/30 text-indigo-300'
                                    : 'bg-slate-700/30 text-slate-400 hover:bg-slate-600/30'
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
                {/* 最大值需与后端 settings.NEWS_RETAIN_DAYS 保持一致 */}
                <select
                    value={days}
                    onChange={e => setDays(Number(e.target.value))}
                    className="px-2 py-1 text-xs bg-slate-800 text-slate-300 rounded border border-slate-600/50"
                >
                    <option value={1}>1天</option>
                    <option value={3}>3天</option>
                    <option value={7}>7天</option>
                    <option value={14}>14天</option>
                    <option value={21}>21天</option>
                </select>
                {/* 搜索框：边打边搜（防抖400ms）+ 回车立即搜 */}
                <input
                    type="text"
                    placeholder="搜索新闻（名称/代码/来源）..."
                    value={searchTerm}
                    onChange={e => {
                        const val = e.target.value;
                        setSearchTerm(val);
                        clearTimeout(searchTimer.current);
                        const term = val.trim();
                        if (!term) {
                            setActiveSearch('');  // 清空即刻恢复
                        } else if (term.length >= 2) {
                            searchTimer.current = setTimeout(() => setActiveSearch(term), 400);
                        }
                    }}
                    onKeyDown={e => {
                        if (e.key === 'Enter') {
                            clearTimeout(searchTimer.current);  // 取消防抖，立即执行
                            setActiveSearch(searchTerm.trim());
                        }
                    }}
                    className="px-2.5 py-1 text-xs bg-slate-700/50 text-slate-300 rounded border border-slate-600/50
                             placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-44"
                />
                <button
                    onClick={() => {
                        if (!searchTerm.trim()) {
                            setSearchMsg('💡 请先输入关键词再搜索');
                            setTimeout(() => setSearchMsg(''), 3000);
                            return;
                        }
                        handleWebSearch();
                    }}
                    disabled={searching}
                    className="px-3.5 py-1.5 text-sm font-medium bg-purple-600/20 text-purple-300 rounded-lg
                             hover:bg-purple-600/30 disabled:opacity-50 transition-all"
                    title="用 Tavily 从全网搜索并入库"
                >
                    {searching ? '搜索中...' : '🌐 全网搜'}
                </button>
                {searchMsg && <span className="text-xs text-slate-300">{searchMsg}</span>}
                {/* 只看关联股票 */}
                <button
                    onClick={() => setOnlyWithCodes(!onlyWithCodes)}
                    className={`px-2.5 py-1 text-xs rounded-full transition-all ${
                        onlyWithCodes
                            ? 'bg-amber-600/30 text-amber-300'
                            : 'bg-slate-700/30 text-slate-400 hover:bg-slate-600/30'
                    }`}
                >
                    📌 有关联股票
                </button>

                <button onClick={() => { if (window.confirm('将今日新闻摘要推送到所有已启用的通知渠道，确认发送？')) handleSend(); }} disabled={pushing}
                    className="ml-auto px-2.5 py-1.5 text-sm bg-emerald-600/20 text-emerald-300 rounded-lg hover:bg-emerald-600/30 disabled:opacity-50 transition-all"
                    title="将今日新闻摘要推送到已启用的通知渠道">
                    {pushing ? '推送中...' : '📤 推送摘要'}
                </button>
            </div>

            {/* News List */}
            {loading ? (
                <div className="text-center py-12 text-slate-400">加载中...</div>
            ) : filteredNews.length === 0 ? (
                <div className="text-center py-12">
                    <Newspaper className="w-12 h-12 text-slate-600 mx-auto mb-3" />
                    <p className="text-slate-400 text-sm">暂无新闻数据</p>
                    <p className="text-slate-500 text-xs mt-1">点击「刷新新闻」抓取最新资讯</p>
                </div>
            ) : (
                <div className="space-y-3">
                    {visibleNews.map(item => (
                        <div key={item.id}
                            className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow"
                        >
                            {/* Top row: source + market + codes + time */}
                            <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                    <span className={`px-2 py-0.5 text-xs font-medium rounded ${
                                        SOURCE_COLORS[item.source] || 'bg-gray-100 text-gray-600'
                                    }`}>
                                        {item.source}
                                    </span>
                                    <span className={`px-2 py-0.5 text-xs font-medium rounded ${
                                        item.market_type === 'A股'
                                            ? 'bg-red-50 text-red-600'
                                            : 'bg-blue-50 text-blue-600'
                                    }`}>
                                        {item.market_type}
                                    </span>
                                </div>
                                <div className="flex items-center gap-2">
                                    {item.related_codes && item.related_codes.length > 0 && (
                                        <div className="flex items-center gap-1">
                                            {item.related_codes.map(code => {
                                                const chg = codeChangeMap[code];
                                                const hasChg = chg !== undefined && chg !== null;
                                                const isUp = chg > 0;
                                                const isDown = chg < 0;
                                                return (
                                                    <span
                                                        key={code}
                                                        onClick={() => onViewKline && onViewKline(code)}
                                                        className={`px-1.5 py-0.5 text-sm rounded cursor-pointer transition-colors ${
                                                            isUp ? 'bg-red-50 text-red-600 hover:bg-red-100'
                                                            : isDown ? 'bg-green-50 text-green-600 hover:bg-green-100'
                                                            : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-100'
                                                        }`}
                                                    >
                                                        {codeNameMap[code] || code}
                                                        {hasChg && (
                                                            <span className="ml-1 font-semibold text-sm">
                                                                {isUp ? '▲' : isDown ? '▼' : '—'}{fmtNum(Math.abs(chg), 1)}%
                                                            </span>
                                                        )}
                                                    </span>
                                                );
                                            })}
                                        </div>
                                    )}
                                    <span className="flex items-center gap-1 text-xs text-gray-500">
                                        <Clock className="w-3 h-3" />
                                        {formatTime(item.publish_time)}
                                    </span>
                                </div>
                            </div>

                            {/* Title */}
                            <h3 className="text-base font-bold text-gray-900 mb-1 leading-snug">
                                {item.url ? (
                                    <a href={item.url} target="_blank" rel="noopener noreferrer"
                                        className="hover:text-indigo-600 transition-colors inline-flex items-center gap-1">
                                        {item.title}
                                        <ExternalLink className="w-3 h-3 text-gray-300" />
                                    </a>
                                ) : (
                                    <a href={`https://www.bing.com/search?q=${encodeURIComponent(item.title)}`}
                                        target="_blank" rel="noopener noreferrer"
                                        className="hover:text-indigo-600 transition-colors cursor-pointer"
                                        title="搜索完整新闻">
                                        {item.title}
                                    </a>
                                )}
                            </h3>

                            {/* Summary */}
                            {item.summary && (
                                <p className="text-[15px] text-gray-500 mb-2 line-clamp-2">{item.summary}</p>
                            )}

                            {/* Sentiment */}
                            <SentimentBar
                                score={item.sentiment_score}
                                label={item.sentiment_label}
                                marketType={item.market_type}
                            />
                        </div>
                    ))}
                    {displayCount < filteredNews.length && (
                        <button
                            onClick={() => setDisplayCount(prev => prev + 50)}
                            className="w-full py-2.5 text-sm text-indigo-400 bg-slate-800/50 rounded-lg
                                     hover:bg-slate-700/50 transition-all mt-2"
                        >
                            加载更多（已显示 {displayCount}/{filteredNews.length}）
                        </button>
                    )}
                </div>
            )}
        </div>
    );
}
