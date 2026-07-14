import { useState, useEffect } from 'react';
import { Shield, TrendingDown, Activity, RefreshCw, AlertTriangle } from 'lucide-react';
import { riskApi } from '../../services/api';
import { LOOKBACK_PRESETS, getLookbackRange } from '../../utils/dateUtils';
import LookbackSelector from '../shared/LookbackSelector';
import DrawdownChart from '../Charts/DrawdownChart';
import ReturnsDistributionChart from '../Charts/ReturnsDistributionChart';
import { fmtNum } from '../../utils/format';

const MetricCard = ({ label, sub, value, color = 'text-white', tooltip }) => (
    <div className="bg-slate-800/60 backdrop-blur-sm border border-slate-700/50 p-3.5 rounded-xl hover:border-indigo-500/30 transition-all group">
        <div className="flex flex-col gap-0.5 mb-1.5">
            <span className="text-slate-100 font-bold text-sm">{label}</span>
            <span className="text-indigo-400/80 font-mono text-[10px] uppercase tracking-wider">{sub}</span>
        </div>
        <div className={`text-2xl font-black tracking-tight group-hover:text-indigo-100 transition-colors ${color}`}>
            {value ?? '-'}
        </div>
        {tooltip && <div className="text-slate-400 text-xs mt-1.5 leading-relaxed">{tooltip}</div>}
    </div>
);

const RiskPanel = ({ riskAnalysis: backtestRisk, customStocks = [], onResult, cumReturns, dates }) => {
    const [riskData, setRiskData] = useState(backtestRisk || null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [showDrawdown, setShowDrawdown] = useState(false);
    const [lookbackDays, setLookbackDays] = useState(365);
    const [dataRangeInfo, setDataRangeInfo] = useState(null);

    // 当回测风险数据更新时同步
    useEffect(() => {
        if (backtestRisk) setRiskData(backtestRisk);
    }, [backtestRisk]);

    const fmt = (v, suffix = '%', decimals = 2) => fmtNum(v, decimals, suffix, '-');

    const runAnalysis = async () => {
        const codes = customStocks.map(s => s.code);
        if (!codes.length) {
            setError('请先在自定义池中添加股票');
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const { startDate, endDate } = getLookbackRange(lookbackDays);
            const res = await riskApi.analyze(codes, startDate, endDate);
            setRiskData(res.risk);
            if (onResult) onResult(res.risk);
            // 数据充足性反馈
            if (res.actual_start_date && res.actual_end_date) {
                const a0 = new Date(res.actual_start_date);
                const a1 = new Date(res.actual_end_date);
                const actualDays = Math.round((a1 - a0) / 86400000);
                setDataRangeInfo({
                    actualStart: res.actual_start_date,
                    actualEnd: res.actual_end_date,
                    actualDays,
                    requestedDays: lookbackDays,
                    sufficient: actualDays >= lookbackDays * 0.8,
                    dataPoints: res.data_points,
                });
            }
        } catch (e) {
            setError(e.message || '风险分析失败');
        }
        setLoading(false);
    };

    const empty = !riskData;
    const r = riskData || {};

    return (
        <div className="space-y-6">
            {/* 标题栏 */}
            <div className="flex items-center justify-between mb-2">
                <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                    <div className="p-2.5 bg-purple-500/20 rounded-xl border border-purple-500/30">
                        <Shield className="w-6 h-6 text-purple-400" />
                    </div>
                    风险分析
                    <span className="text-sm font-normal text-slate-500 ml-1">基于自选池{customStocks.length > 0 ? ` ${customStocks.length} 只标的` : ''}的历史数据</span>
                </h2>
                <div className="flex items-center gap-3">
                    <LookbackSelector
                        presets={LOOKBACK_PRESETS}
                        value={lookbackDays}
                        onChange={d => { setLookbackDays(d); setDataRangeInfo(null); }}
                        activeColor="bg-purple-600"
                    />
                    <button onClick={runAnalysis} disabled={loading}
                        className="flex items-center gap-2 px-4 py-2 bg-purple-600/30 hover:bg-purple-600/50 border border-purple-500/40 text-purple-200 rounded-lg text-sm font-medium transition-all disabled:opacity-50">
                        {loading ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                        {loading ? '分析中…' : '独立运行风险分析'}
                    </button>
                </div>
            </div>

            {/* 数据充足性提示 */}
            {dataRangeInfo && (
                <div className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-2 ${
                    dataRangeInfo.sufficient
                        ? 'bg-slate-800/30 border-slate-700/30 text-slate-400'
                        : 'bg-amber-900/20 border-amber-500/30 text-amber-400'
                }`}>
                    <span>实际范围: {dataRangeInfo.actualStart} ~ {dataRangeInfo.actualEnd}</span>
                    <span>({dataRangeInfo.dataPoints}个交易日)</span>
                    {!dataRangeInfo.sufficient && (
                        <span className="font-medium">⚠️ 数据不足（请求{dataRangeInfo.requestedDays}天）</span>
                    )}
                </div>
            )}

            {error && (
                <div className="flex items-center gap-2 p-3 bg-red-900/30 border border-red-500/40 rounded-lg text-red-300 text-sm">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
                </div>
            )}

            {empty && !loading && (
                <div className="text-center py-12">
                    <Shield className="w-16 h-16 text-purple-400 mx-auto mb-4 opacity-30" />
                    <p className="text-slate-400 mb-2">尚无风险数据</p>
                    <p className="text-slate-500 text-sm">点击「独立运行风险分析」或先完成回测</p>
                </div>
            )}

            {!empty && (
                <>
                    {/* 核心指标网格 */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <MetricCard label="在险价值 95%" sub="VaR 95%" value={fmt(r.var_95)}
                            color="text-rose-400" tooltip="95%置信度下，单日最大可能损失" />
                        <MetricCard label="条件在险价值" sub="CVaR 95%" value={fmt(r.cvar_95)}
                            color="text-orange-400" tooltip="超过VaR阈值时的平均损失（尾部风险）" />
                        <MetricCard label="最大回撤" sub="Max Drawdown" value={fmt(r.max_drawdown)}
                            color="text-red-400" tooltip="历史最大峰谷回撤幅度" />
                        <MetricCard label="年化波动率" sub="Volatility" value={fmt(r.volatility)}
                            color="text-amber-400" tooltip="收益率的年化标准差" />
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                        <MetricCard label="夏普比率" sub="Sharpe Ratio" value={fmt(r.sharpe_ratio, '', 2)}
                            color={r.sharpe_ratio >= 1 ? 'text-red-400' : 'text-sky-400'}
                            tooltip=">1 优秀，>2 非常好" />
                        <MetricCard label="索提诺比率" sub="Sortino Ratio" value={fmt(r.sortino_ratio, '', 2)}
                            color="text-teal-400" tooltip="仅考虑下行风险的夏普比率" />
                        <MetricCard label="卡玛比率" sub="Calmar Ratio" value={fmt(r.calmar_ratio, '', 2)}
                            color="text-cyan-400" tooltip="年化收益 / 最大回撤，>1为优" />
                        <MetricCard label="年化收益" sub="Annual Return" value={fmt(r.annual_return)}
                            color={r.annual_return >= 0 ? 'text-red-400' : 'text-green-400'}
                            tooltip="几何平均年化收益率" />
                    </div>

                    {/* Beta / Alpha / TE */}
                    {(r.beta != null || r.alpha != null) && (
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                            <MetricCard label="贝塔系数" sub="Beta" value={fmt(r.beta, '', 2)}
                                color="text-indigo-400" tooltip="与沪深300的相关性，1=同涨跌" />
                            <MetricCard label="阿尔法" sub="Alpha (年化)" value={fmt(r.alpha)}
                                color={r.alpha >= 0 ? 'text-red-400' : 'text-green-400'}
                                tooltip="超越基准的年化超额收益" />
                            <MetricCard label="跟踪误差" sub="Tracking Error" value={fmt(r.tracking_error)}
                                color="text-purple-400" tooltip="超额收益的年化标准差" />
                            <MetricCard label="信息比率" sub="Information Ratio" value={fmt(r.information_ratio, '', 2)}
                                color="text-fuchsia-400" tooltip="超额收益 / 跟踪误差，>0.5为优" />
                        </div>
                    )}

                    {/* 回撤水下图 */}
                    {cumReturns?.length > 0 && (
                        <DrawdownChart
                            data={(() => {
                                let peak = -Infinity;
                                return cumReturns.map((v, i) => {
                                    if (v > peak) peak = v;
                                    return {
                                        date: dates?.[i] || `Day ${i + 1}`,
                                        drawdown: peak > 0 ? (v - peak) / peak : 0,
                                    };
                                });
                            })()}
                        />
                    )}

                    {/* 收益率分布图 */}
                    {cumReturns?.length > 1 && (
                        <ReturnsDistributionChart
                            data={(() => {
                                const returns = [];
                                for (let i = 1; i < cumReturns.length; i++) returns.push((cumReturns[i] / cumReturns[i - 1] - 1) * 100);
                                if (!returns.length) return [];
                                const STEP = 0.5;
                                const minBin = Math.floor(Math.min(...returns) / STEP) * STEP;
                                const maxBin = Math.ceil(Math.max(...returns) / STEP) * STEP;
                                const bins = {};
                                for (let b = minBin; b <= maxBin; b += STEP) bins[b.toFixed(1)] = 0;
                                returns.forEach(r => { const k = (Math.floor(r / STEP) * STEP).toFixed(1); if (bins[k] !== undefined) bins[k]++; });
                                return Object.entries(bins).map(([range, frequency]) => ({ range: `${range}%`, frequency }))
                                    .sort((a, b) => parseFloat(a.range) - parseFloat(b.range));
                            })()}
                        />
                    )}

                    {/* 回撤区间分解 */}
                    {r.drawdown_periods?.length > 0 && (
                        <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
                            <button onClick={() => setShowDrawdown(!showDrawdown)}
                                className="w-full flex items-center justify-between text-white font-semibold text-base mb-0">
                                <div className="flex items-center gap-2">
                                    <TrendingDown className="w-5 h-5 text-rose-400" />
                                    历史回撤区间分解（Top {r.drawdown_periods.length}）
                                    <span className="text-xs font-normal ml-2">最大的几次从峰值到谷底的亏损 · 含持续天数与修复时间</span>
                                </div>
                                <span className="text-xs text-slate-400">{showDrawdown ? '收起' : '展开'}</span>
                            </button>
                            {showDrawdown && (
                                <div className="mt-4 space-y-3">
                                    {r.drawdown_periods.map((p, i) => (
                                        <div key={i} className="bg-slate-900/50 rounded-lg p-4 border border-slate-700/30">
                                            <div className="flex items-center justify-between mb-2">
                                                <span className="text-rose-400 font-bold text-lg">
                                                    -{p.drawdown.toFixed(2)}%
                                                </span>
                                                <span className="text-slate-400 text-xs">
                                                    持续 {p.duration_days} 天
                                                </span>
                                            </div>
                                            <div className="grid grid-cols-3 gap-2 text-xs text-slate-400">
                                                <div>📅 开始: <span className="text-slate-200">{p.start || '-'}</span></div>
                                                <div>📉 谷底: <span className="text-slate-200">{p.trough || '-'}</span></div>
                                                <div>✅ 修复: <span className="text-slate-200">{p.end || '未修复'}</span></div>
                                            </div>
                                            {/* 回撤进度条 */}
                                            <div className="mt-2 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                                                <div className="h-full bg-gradient-to-r from-rose-500 to-orange-400 rounded-full"
                                                    style={{ width: `${Math.min(p.drawdown, 100)}%` }} />
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
};

export default RiskPanel;
