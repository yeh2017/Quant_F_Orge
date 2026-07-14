import {
    ResponsiveContainer,
    AreaChart,
    Area,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ReferenceLine,
} from 'recharts';

/**
 * 回撤水下图 — 展示组合在每个时间点相对最高净值的回撤比例。
 * data: [{ date, drawdown }]  drawdown 为负数或零（如 -0.05 = -5%）
 */
const DrawdownChart = ({ data, title = '回撤水下图' }) => {
    if (!data || data.length === 0) {
        return (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm py-8">
                暂无回撤数据
            </div>
        );
    }

    const minDD = Math.min(...data.map(d => d.drawdown));

    return (
        <div className="w-full bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-rose-400" />
                {title}
                <span className="text-xs font-normal ml-1">每个时间点相对最高净值的回撤幅度 · 越深风险越大</span>
                <span className="text-xs text-slate-500 font-normal ml-auto">
                    最大回撤 {(minDD * 100).toFixed(2)}%
                </span>
            </h3>
            <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                        <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor="#ef4444" stopOpacity={0.6} />
                            <stop offset="100%" stopColor="#ef4444" stopOpacity={0.05} />
                        </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.08)" />
                    <XAxis
                        dataKey="date"
                        stroke="#64748b"
                        tick={{ fontSize: 10, fill: '#94a3b8' }}
                        tickFormatter={v => v?.slice(5) || v}
                        interval="preserveStartEnd"
                        minTickGap={60}
                    />
                    <YAxis
                        stroke="#64748b"
                        tick={{ fontSize: 10, fill: '#94a3b8' }}
                        tickFormatter={v => `${(v * 100).toFixed(0)}%`}
                        domain={[minDD * 1.15, 0]}
                        width={45}
                    />
                    <ReferenceLine y={0} stroke="#475569" strokeDasharray="3 3" />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#1e293b',
                            borderColor: '#334155',
                            borderRadius: '8px',
                            fontSize: '12px',
                        }}
                        labelStyle={{ color: '#94a3b8' }}
                        formatter={v => [`${(v * 100).toFixed(2)}%`, '回撤']}
                    />
                    <Area
                        type="monotone"
                        dataKey="drawdown"
                        stroke="#ef4444"
                        strokeWidth={1.5}
                        fill="url(#ddGrad)"
                        isAnimationActive={false}
                    />
                </AreaChart>
            </ResponsiveContainer>
        </div>
    );
};

export default DrawdownChart;
