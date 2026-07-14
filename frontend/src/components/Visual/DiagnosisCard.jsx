/**
 * 技术诊断卡片 — 7 维 + 综合评分
 * 紧凑一行布局，嵌入 VisualPanel K 线图上方
 */
import React from 'react';
import { TrendingUp, TrendingDown, BarChart3, Activity, Target } from 'lucide-react';




// 单维度小卡片
const DimCard = ({ icon: Icon, title, state, detail, color }) => (
    <div className="flex flex-col gap-0.5 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/40 min-w-[100px] flex-1">
        <div className="flex items-center gap-1.5">
            <Icon className="w-3.5 h-3.5" style={{ color }} />
            <span className="text-xs text-white/70 font-medium">{title}</span>
        </div>
        <span className="text-sm font-bold truncate" style={{ color }}>{state}</span>
        {detail && <span className="text-xs text-white/60 truncate">{detail}</span>}
    </div>
);

const DiagnosisCard = ({ diagnosis, loading }) => {
    if (loading) {
        return (
            <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-slate-800/40 border border-slate-700/30 animate-pulse">
                <div className="w-16 h-16 rounded-full bg-slate-700/50" />
                {[...Array(5)].map((_, i) => (
                    <div key={i} className="flex-1 h-14 rounded-lg bg-slate-700/30" />
                ))}
            </div>
        );
    }

    if (!diagnosis) return null;

    const d = diagnosis;
    const trendIcon = d.trend.level >= 3 ? TrendingUp : TrendingDown;

    // 均线 detail
    const maDetail = [
        d.ma.golden_cross && '🟡金叉',
        d.ma.death_cross && '💀死叉',
        `乖离${d.ma.bias_20 > 0 ? '+' : ''}${d.ma.bias_20}%`,
    ].filter(Boolean).join(' ');

    // 支撑压力摘要
    const levelDetail = [
        d.levels.supports?.[0] && `支${d.levels.supports[0].level}`,
        d.levels.resistances?.[0] && `压${d.levels.resistances[0].level}`,
    ].filter(Boolean).join(' / ');

    return (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-slate-800/40 border border-slate-700/30 backdrop-blur-sm">
            <div className="flex items-center gap-2 shrink-0">
                <div>
                    <div className={`text-lg font-bold ${d.composite.score >= 60 ? 'text-red-400' : d.composite.score >= 40 ? 'text-slate-400' : 'text-green-400'}`}>{d.composite.label}</div>
                    {d.date && (
                        <div className={`text-xs ${d.stale ? 'text-amber-400' : 'text-white/80'}`}>
                            {d.stale ? '⚠ ' : ''}{d.date}
                        </div>
                    )}
                </div>
                <div className="shrink-0 text-center">
                    <div className={`text-2xl font-black font-mono ${d.composite.score >= 60 ? 'text-red-400' : d.composite.score >= 40 ? 'text-slate-400' : 'text-green-400'}`}>{d.composite.score}</div>
                    <div className="text-xs text-white/80">综合分</div>
                </div>
            </div>

            <div className="flex gap-1.5 flex-1 overflow-x-auto">
                <DimCard icon={trendIcon} title="趋势" state={d.trend.state}
                    detail={d.ma.arrangement} color={d.trend.color} />
                <DimCard icon={BarChart3} title="量能" state={d.volume.state}
                    detail={`量比 ${d.volume.ratio}x`}
                    color={['放量上涨','温和放量'].includes(d.volume.state) ? '#ef4444' : ['缩量回调','放量下跌'].includes(d.volume.state) ? '#22c55e' : '#9ca3af'} />
                <DimCard icon={Activity} title="MACD" state={d.macd.state}
                    detail={`DIF ${d.macd.dif} / DEA ${d.macd.dea}`}
                    color={d.macd.state.includes('零轴上') ? '#ef4444' : d.macd.state.includes('零轴下') ? '#22c55e' : '#9ca3af'} />
                <DimCard icon={Activity} title="RSI" state={d.rsi.state}
                    detail={`RSI6 ${d.rsi.rsi6} / RSI14 ${d.rsi.rsi14}`}
                    color={d.rsi.rsi14 > 60 ? '#ef4444' : d.rsi.rsi14 < 40 ? '#22c55e' : '#9ca3af'} />
                {d.kdj && (
                    <DimCard icon={Activity} title="KDJ" state={d.kdj.state}
                        detail={`K ${d.kdj.k}`}
                        color={d.kdj.k > 80 ? '#ef4444' : d.kdj.k < 20 ? '#22c55e' : '#9ca3af'} />
                )}
                <DimCard icon={Target} title="支撑/压力" state={levelDetail || '—'}
                    detail={maDetail} color="#818cf8" />
            </div>

        </div>
    );
};

export default DiagnosisCard;
