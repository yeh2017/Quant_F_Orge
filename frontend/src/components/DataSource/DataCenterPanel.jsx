import React, { useState, useEffect } from 'react';
import { Database, Download, RefreshCw, Clock } from 'lucide-react';
import { dataCenterApi, systemApi } from '../../services/api';

// 同步范围选项（与后端 scope key 一一对应，minPoints 对应 Tushare 积分门槛）
const SCOPE_OPTIONS = [
    { key: 'stock',     label: 'A股行情+因子', icon: '📈', minPoints: 120 },
    { key: 'etf',       label: 'ETF',          icon: '🏛', minPoints: 120 },
    { key: 'bond',      label: '可转债',       icon: '🪙', minPoints: 5000 },
    { key: 'financial', label: '财务数据',     icon: '📊', minPoints: 120 },
    { key: 'moneyflow', label: '资金流向',     icon: '📉', minPoints: 5000 },
    { key: 'margin',    label: '融资融券',     icon: '💱', minPoints: 5000 },
    { key: 'events',    label: '大宗/解禁/龙虎', icon: '📃', minPoints: 5000 },
    { key: 'industry',  label: '行业指数',     icon: '🏭', minPoints: 120 },
];

const DataCenterPanel = ({ startDate, endDate, setStartDate, setEndDate, syncing, syncProgress, onSync, isActive, settingsVersion }) => {
    const [targetMode, setTargetMode] = useState('all');
    const [forceRefill, setForceRefill] = useState(false); // 强制忽略水位回填历史
    const [scope, setScope] = useState(Object.fromEntries(SCOPE_OPTIONS.map(o => [o.key, true])));
    const toggleScope = (key) => setScope(prev => ({ ...prev, [key]: !prev[key] }));
    const [tusharePoints, setTusharePoints] = useState(
        () => parseInt(localStorage.getItem('tushare_points')) || 2000
    );

    // 判断某项是否因积分不足被锁定
    const isLocked = (key) => {
        const opt = SCOPE_OPTIONS.find(o => o.key === key);
        return opt ? opt.minPoints > tusharePoints : false;
    };

    // pool 模式自动精简 scope（仅 A股+财务+资金流向），all 模式恢复全选
    // 两种模式都排除积分不足的项
    const handleModeChange = (mode) => {
        setTargetMode(mode);
        if (mode === 'pool') {
            setScope(Object.fromEntries(SCOPE_OPTIONS.map(o => [
                o.key, !isLocked(o.key) && ['stock', 'financial', 'moneyflow', 'margin'].includes(o.key)
            ])));
        } else {
            setScope(Object.fromEntries(SCOPE_OPTIONS.map(o => [o.key, !isLocked(o.key)])));
        }
    };
    // allSelected/noneSelected 只考虑可用项（积分锁定项不参与）
    const availableOptions = SCOPE_OPTIONS.filter(o => !isLocked(o.key));
    const allSelected = availableOptions.length > 0 && availableOptions.every(o => scope[o.key]);
    const noneSelected = availableOptions.every(o => !scope[o.key]);
    const [lastUpdateDate, setLastUpdateDate] = useState('加载中...');
    const [dbStats, setDbStats] = useState(null);
    const [elapsed, setElapsed] = useState(null);
    const timerRef = React.useRef(null);
    const startTimeRef = React.useRef(null);


    useEffect(() => { fetchStatus(); }, []);
    // tab 切换回数据中台时重新读取积分等级（设置页修改后立即生效，无需重启）
    useEffect(() => {
        if (isActive) fetchStatus();
    }, [isActive]);
    // 设置弹窗关闭后刷新积分（弹窗是 Modal 覆盖在当前 tab 上，isActive 不变化）
    useEffect(() => {
        if (settingsVersion > 0) fetchStatus();
    }, [settingsVersion]);
    useEffect(() => {
        if (syncProgress.status === 'completed') {
            fetchStatus();

            // 全量同步成功后自动取消 force_refill
            if (forceRefill) setForceRefill(false);
        }
    }, [syncProgress.status]);
    // 监听主同步状态：syncing=true 时启动计时，结束时停止
    useEffect(() => {
        if (syncing) {
            startMainTimer();
        } else {
            stopMainTimer();
        }
    }, [syncing]);

    // 清理定时器
    useEffect(() => () => {
        if (timerRef.current) clearInterval(timerRef.current);
    }, []);

    const fmtTime = (sec) => {
        if (sec === null || sec === undefined) return null;
        sec = Math.round(sec);
        if (sec < 60) return `${sec}s`;
        return `${Math.floor(sec / 60)}m ${sec % 60}s`;
    };

    // ETA 倒计时：已用时间 × (剩余进度 / 当前进度)
    const calcEta = (elapsedSec, pct) => {
        if (elapsedSec === null || !pct || pct <= 0) return null;
        if (pct >= 100) return 0;
        if (pct < 3) return null; // 进度太低，估算不准
        return Math.round(elapsedSec * (100 - pct) / pct);
    };

    const startMainTimer = () => {
        startTimeRef.current = Date.now();
        setElapsed(0);
        if (timerRef.current) clearInterval(timerRef.current);
        timerRef.current = setInterval(() => {
            setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
        }, 1000);
    };

    const stopMainTimer = () => {
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    };

    const fetchStatus = async () => {
        try {
            const status = await dataCenterApi.getStatus();
            setLastUpdateDate(status.last_update_date || '暂无数据');
            setDbStats(status);
            // 空库（新用户首次打开）→ 自动勾选"强制补历史"
            if (!status.stock_basic?.total_stocks) {
                setForceRefill(true);
            }
        } catch {
            setLastUpdateDate('连接失败');
        }
        // 读取用户积分等级
        try {
            const cfg = await systemApi.getConfig();
            const pts = parseInt(cfg?.env?.TUSHARE_POINTS) || 2000;
            setTusharePoints(pts);
            localStorage.setItem('tushare_points', String(pts));
        } catch { /* 读不到时保持默认值 */ }
    };

    return (
        <div className="bg-slate-800/80 backdrop-blur-md rounded-2xl border border-indigo-500/30 overflow-hidden shadow-2xl relative">
            <div className="absolute top-0 inset-x-0 h-1 bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500"></div>

            <div className="p-6">
                {/* Header */}
                <div className="flex items-center justify-between mb-6">
                    <div className="flex items-center gap-3">
                        <div className="p-3 bg-indigo-500/20 rounded-xl border border-indigo-500/30">
                            <Database className="w-7 h-7 text-indigo-400" />
                        </div>
                        <div>
                            <h2 className="text-2xl font-bold text-white tracking-wide">本地量化数据中台</h2>
                            <p className="text-sm text-indigo-300">本地化数据仓库加速回测，告别请求超时</p>
                        </div>
                    </div>
                    <div className="flex gap-3">
                        <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 flex flex-col items-center min-w-[130px]">
                            <span className="text-xs text-slate-400 mb-1 flex items-center gap-1"><Clock className="w-3 h-3" /> 行情更新至</span>
                            <span className={`text-lg font-bold ${lastUpdateDate.includes('202') ? 'text-emerald-400' : 'text-amber-400'}`}>
                                {lastUpdateDate}
                            </span>
                        </div>
                        {dbStats && (
                            <>
                                <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 flex flex-col items-center min-w-[90px]">
                                    <span className="text-xs text-slate-400 mb-1 flex items-center gap-1">📈 股票数</span>
                                    <span className="text-lg font-bold text-blue-400">{dbStats.stock_basic?.total_stocks || 0}</span>
                                </div>
                                <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 flex flex-col items-center min-w-[90px]">
                                    <span className="text-xs text-slate-400 mb-1 flex items-center gap-1">🏛 ETF数</span>
                                    <span className="text-lg font-bold text-teal-400">{dbStats.etf?.basic_count || 0}</span>
                                </div>
                                <div className="bg-slate-900/60 border border-slate-700/50 rounded-lg p-3 flex flex-col items-center min-w-[90px]">
                                    <span className="text-xs text-slate-400 mb-1 flex items-center gap-1">🪙 可转债</span>
                                    <span className="text-lg font-bold text-orange-400">{(dbStats.bond?.stock_count || 0).toLocaleString()}</span>
                                </div>
                            </>
                        )}
                    </div>
                </div>



                {/* Controls */}
                <div className="space-y-4">
                    {/* 第1行：日期 + 同步目标 */}
                    <div className="flex gap-4 items-stretch">
                        <div className="flex-1 grid grid-cols-2 gap-4">
                            <div className="bg-slate-900/40 rounded-xl p-4 border border-slate-700/50">
                                <label className="block text-xs text-slate-400 mb-2">拉取范围 (开始)</label>
                                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                                    style={{ colorScheme: 'dark' }}
                                    className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-200 text-sm focus:outline-none focus:border-indigo-500"
                                    disabled={syncing} />
                            </div>
                            <div className="bg-slate-900/40 rounded-xl p-4 border border-slate-700/50">
                                <label className="block text-xs text-slate-400 mb-2">拉取范围 (结束)</label>
                                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
                                    style={{ colorScheme: 'dark' }}
                                    className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-200 text-sm focus:outline-none focus:border-indigo-500"
                                    disabled={syncing} />
                            </div>
                        </div>
                        <div className="min-w-[260px] bg-slate-900/40 rounded-xl p-4 border border-slate-700/50">
                            <label className="block text-xs text-slate-400 mb-2">同步目标</label>
                            <select value={targetMode} onChange={(e) => handleModeChange(e.target.value)}
                                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-slate-200 text-sm focus:outline-none focus:border-indigo-500"
                                disabled={syncing}>
                                <option value="all">A股全市场 (全量/耗时)</option>
                                <option value="pool">仅自选池股票 (极速/自动精简同步范围)</option>
                            </select>
                        </div>
                    </div>

                    {/* 第2行：同步范围 + 操作按钮 */}
                    <div className="flex gap-4 items-stretch">
                        {/* 同步范围勾选 */}
                        <div className="flex-1 bg-slate-900/40 rounded-xl p-4 border border-slate-700/50">
                            <div className="flex items-center justify-between mb-3">
                                <label className="text-xs text-slate-400">同步范围（可多选）</label>
                                <div className="flex gap-1.5">
                                    {(() => {
                                        const DAILY_SCOPE = { stock: true, etf: true, bond: true, financial: false, moneyflow: false, margin: true, events: true, industry: true };
                                        // 排除积分锁定项
                                        const effectiveDaily = Object.fromEntries(
                                            SCOPE_OPTIONS.map(o => [o.key, !!DAILY_SCOPE[o.key] && !isLocked(o.key)])
                                        );
                                        const isDailyActive = SCOPE_OPTIONS.every(o => !!scope[o.key] === !!effectiveDaily[o.key]);
                                        return (
                                            <button
                                                onClick={() => setScope({ ...effectiveDaily })}
                                                className={`text-[11px] px-2.5 py-1 rounded-lg border transition-all font-medium ${
                                                    isDailyActive
                                                        ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-400'
                                                        : 'bg-slate-800 text-slate-300 border-slate-600/50 hover:bg-slate-700'
                                                }`}
                                                disabled={syncing}
                                                title="A股+ETF+可转债+行业（跳过财务和资金流向）"
                                            >📅 日常数据</button>
                                        );
                                    })()}
                                    <button
                                        onClick={() => setScope(Object.fromEntries(SCOPE_OPTIONS.map(o => [o.key, !isLocked(o.key)])))}
                                        className={`text-[11px] px-2.5 py-1 rounded-lg border transition-all font-medium ${
                                            allSelected
                                                ? 'bg-indigo-500/20 border-indigo-500/30 text-indigo-400'
                                                : 'bg-slate-800 text-slate-300 border-slate-600/50 hover:bg-slate-700'
                                        }`}
                                        disabled={syncing}
                                    >全选</button>
                                    <button
                                        onClick={() => setScope(Object.fromEntries(SCOPE_OPTIONS.map(o => [o.key, false])))}
                                        className={`text-[11px] px-2.5 py-1 rounded-lg border transition-all font-medium ${
                                            noneSelected
                                                ? 'bg-slate-500/20 border-slate-500/30 text-slate-300'
                                                : 'bg-slate-800/60 text-slate-400 border-slate-600/50 hover:bg-slate-700/60'
                                        }`}
                                        disabled={syncing}
                                    >清空</button>
                                </div>
                            </div>
                            <div className="grid grid-cols-4 gap-2">
                                {SCOPE_OPTIONS.map(({ key, label, icon, minPoints }) => {
                                    const pointsLocked = minPoints > tusharePoints;
                                    return (
                                    <label
                                        key={key}
                                        title={pointsLocked ? `需要 Tushare ≥${minPoints} 积分` : label}
                                        className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border cursor-pointer transition-all text-sm ${
                                            pointsLocked
                                                ? 'bg-slate-800/20 border-slate-700/20 text-slate-600 cursor-not-allowed opacity-50'
                                                : scope[key]
                                                    ? 'bg-indigo-500/20 border-indigo-500/40 text-indigo-200'
                                                    : 'bg-slate-800/40 border-slate-700/30 text-slate-500'
                                        } ${syncing ? 'opacity-50 cursor-not-allowed' : !pointsLocked ? 'hover:border-indigo-400/60' : ''}`}
                                    >
                                        <input
                                            type="checkbox"
                                            checked={!pointsLocked && scope[key]}
                                            onChange={() => !pointsLocked && toggleScope(key)}
                                            disabled={syncing || pointsLocked}
                                            className="w-3.5 h-3.5 rounded accent-indigo-400"
                                        />
                                        <span>{icon}</span>
                                        <span className="truncate">{label}</span>
                                        {pointsLocked && (
                                            <span className="text-[10px] text-amber-400/70 ml-auto whitespace-nowrap">≥{minPoints}分</span>
                                        )}
                                    </label>
                                    );
                                })}
                            </div>
                        </div>

                        {/* 操作区：强制补历史 + 按钮 */}
                        <div className="flex flex-col justify-end gap-3 min-w-[260px]">
                            <label className="flex items-center gap-2 cursor-pointer group">
                                <input type="checkbox" checked={forceRefill} onChange={e => setForceRefill(e.target.checked)}
                                    className="w-4 h-4 rounded accent-amber-400 cursor-pointer" />
                                <span className="text-xs text-amber-300 group-hover:text-amber-200 transition-colors">
                                    ⚡ 强制补历史（忽略水位全量重拉）
                                </span>
                            </label>

                            <button onClick={() => {
                                // 发送前过滤掉积分锁定的项，确保后端不会尝试不可用的数据
                                const effectiveScope = Object.fromEntries(
                                    Object.entries(scope).map(([k, v]) => [k, v && !isLocked(k)])
                                );
                                onSync(targetMode, forceRefill, effectiveScope);
                            }} disabled={syncing || noneSelected}
                                title={forceRefill ? "⚠️ 将忽略水位，从开始日期全量重拉所有数据" : "按勾选范围同步数据。全选 = 全量同步"}
                                className={`w-full relative group overflow-hidden text-white py-4 rounded-xl font-bold shadow-lg transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2 ${
                                    forceRefill
                                        ? 'bg-gradient-to-r from-amber-600 via-orange-600 to-red-600 shadow-red-900/40 ring-2 ring-amber-400/50'
                                        : 'bg-gradient-to-r from-blue-600 via-indigo-600 to-purple-600 shadow-indigo-900/40'
                                }`}>
                                <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                                {syncing ? (
                                    <><RefreshCw className="w-5 h-5 animate-spin" /> <span className="tracking-wide text-lg">正在同步...</span></>
                                ) : (
                                    <><Download className="w-5 h-5 group-hover:-translate-y-1 transition-transform" /> <span className="tracking-wider text-lg">
                                        {forceRefill ? '⚠️ 强制历史数据重拉' : allSelected ? '🚀 一键全量同步' : '🚀 同步已选数据'}
                                    </span></>
                                )}
                            </button>
                        </div>
                    </div>



                    {/* 同步进度条 */}
                    {syncProgress.status !== 'ready' && (() => {
                        const pct = syncProgress.percent;
                        const isError = syncProgress.status === 'error';
                        const isDone = syncProgress.status === 'completed';
                        const eta = (isDone || isError) ? null : calcEta(elapsed, pct);

                        const textColor = isError ? 'text-rose-400'
                            : isDone ? 'text-emerald-400'
                            : 'text-indigo-300';
                        const barColor = isError ? 'bg-rose-500'
                            : isDone ? 'bg-emerald-500'
                            : 'bg-gradient-to-r from-indigo-500 to-purple-500 relative';

                        return (
                            <div className="bg-slate-900/60 rounded-xl p-4 border border-indigo-500/20">
                                <div className="flex justify-between items-center text-sm mb-2">
                                    <span className={`${textColor} flex-1 truncate pr-2`}>
                                        {syncProgress.message}
                                    </span>
                                    <div className="flex items-center gap-2 shrink-0">
                                        {elapsed !== null && (
                                            <span className="text-xs text-slate-400 font-mono flex items-center gap-1">
                                                <Clock className="w-3 h-3" />
                                                {isDone || isError
                                                    ? `耗时 ${fmtTime(elapsed)}`
                                                    : eta !== null
                                                        ? `剩余 ${fmtTime(eta)}`
                                                        : '估算中…'}
                                            </span>
                                        )}
                                        <span className="text-white font-mono">{pct}%</span>
                                    </div>
                                </div>
                                <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                                    <div
                                        className={`h-full transition-all duration-300 ease-out ${barColor}`}
                                        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
                                    >
                                        {!isDone && !isError && (
                                            <div className="absolute inset-0 bg-white/20 animate-pulse"></div>
                                        )}
                                    </div>
                                </div>
                                {syncProgress.steps?.length > 0 && (
                                    <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                                        {syncProgress.steps.map((step, i) => (
                                            <span key={i} className={`text-xs ${
                                                step.startsWith('✅') ? 'text-emerald-400' :
                                                step.startsWith('❌') ? 'text-rose-400' :
                                                step.startsWith('⏭') ? 'text-slate-500' :
                                                'text-slate-400'
                                            }`}>{step}</span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        );
                    })()}
                </div>

            </div>
        </div>
    );
};

export default DataCenterPanel;
