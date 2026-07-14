import React from 'react';
import {
    ResponsiveContainer,
    PieChart,
    Pie,
    Cell,
    Tooltip,
    Sector
} from 'recharts';

const COLORS = [
    '#8B5CF6', '#3B82F6', '#10B981', '#F59E0B',
    '#EF4444', '#EC4899', '#6366F1', '#14B8A6',
    '#F97316', '#06B6D4', '#84CC16', '#A855F7'
];

const IndustryExposureChart = ({ data }) => {
    const [activeIndex, setActiveIndex] = React.useState(0);

    if (!data || data.length === 0) {
        return (
            <div className="h-full flex items-center justify-center text-slate-500 text-sm">
                运行因子评估后显示行业分布
            </div>
        );
    }

    const total = data.reduce((s, d) => s + d.value, 0);
    // 计算百分比并按占比降序
    const chartData = data
        .map(d => ({ ...d, pct: total > 0 ? ((d.value / total) * 100).toFixed(1) : 0 }))
        .sort((a, b) => b.value - a.value);

    const CustomTooltip = ({ active, payload }) => {
        if (!active || !payload?.length) return null;
        const d = payload[0].payload;
        return (
            <div className="bg-slate-800/95 backdrop-blur-sm border border-slate-700/50 rounded-lg px-3 py-2 shadow-xl max-w-[200px]">
                <p className="text-white font-bold text-sm">{d.name}</p>
                <p className="text-slate-300 text-xs mt-1">
                    {d.value} 只 · <span className="text-indigo-300 font-medium">{d.pct}%</span>
                </p>
                {d.stocks && d.stocks.length > 0 && (
                    <div className="mt-1.5 pt-1.5 border-t border-slate-700/50">
                        {d.stocks.map((s, i) => (
                            <p key={i} className="text-[11px] text-slate-400 leading-relaxed">{s}</p>
                        ))}
                    </div>
                )}
            </div>
        );
    };


    // 自定义高亮形状 (Hover效果)
    const renderActiveShape = (props) => {
        const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill, payload, percent, _value } = props;
        return (
            <g>
                <text x={cx} y={cy - 6} dy={8} textAnchor="middle" fill="#fff" className="font-bold text-sm">
                    {payload.name}
                </text>
                <text x={cx} y={cy + 10} dy={8} textAnchor="middle" fill={fill} className="text-xs font-mono font-medium">
                    {(percent * 100).toFixed(1)}%
                </text>
                <Sector
                    cx={cx} cy={cy}
                    innerRadius={innerRadius} outerRadius={outerRadius + 8}
                    startAngle={startAngle} endAngle={endAngle}
                    fill={fill}
                    className="drop-shadow-lg filter"
                />
                <Sector
                    cx={cx} cy={cy}
                    startAngle={startAngle} endAngle={endAngle}
                    innerRadius={outerRadius + 10} outerRadius={outerRadius + 15}
                    fill={fill}
                    className="opacity-30"
                />
            </g>
        );
    };



    const onPieEnter = (_, index) => {
        setActiveIndex(index);
    };

    // 行业集中度判断
    const knownData = chartData.filter(d => d.name !== '未知' && d.name !== '其他');
    const knownTotal = knownData.reduce((s, d) => s + d.value, 0);
    const maxPct = knownData.length > 0 ? Math.max(...knownData.map(d => d.value)) / Math.max(knownTotal, 1) * 100 : 0;
    const topIndustry = knownData.length > 0 ? knownData[0].name : '';
    const isDispersed = knownData.length >= 5 && maxPct <= 20;
    const isConcentrated = total >= 3 && maxPct > 30;

    return (
        <div className="w-full h-full flex flex-col pt-2">
            {isConcentrated && (
                <div className="text-center text-xs text-red-400/90 mb-1">⚠ {topIndustry}占比 {maxPct.toFixed(0)}%，注意行业集中风险</div>
            )}
            {isDispersed && (
                <div className="text-center text-xs text-emerald-400/80 mb-1">✓ 行业分散度良好，无集中度风险</div>
            )}
            {!isConcentrated && !isDispersed && knownData.length >= 2 && knownData.length < 5 && maxPct <= 30 && (
                <div className="text-center text-xs text-slate-400/80 mb-1">覆盖 {knownData.length} 个行业</div>
            )}
            <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                    <Pie
                        activeIndex={activeIndex}
                        activeShape={renderActiveShape}
                        data={chartData}
                        cx="50%"
                        cy="50%"
                        innerRadius={55}
                        outerRadius={75}
                        paddingAngle={4}
                        dataKey="value"
                        onMouseEnter={onPieEnter}
                        animationBegin={0}
                        animationDuration={800}
                        animationEasing="ease-out"
                        stroke="none"
                    >
                        {chartData.map((_, idx) => (
                            <Cell
                                key={idx}
                                fill={COLORS[idx % COLORS.length]}
                                className="hover:opacity-100 opacity-85 transition-opacity duration-300 drop-shadow-md"
                            />
                        ))}
                    </Pie>
                    <Tooltip content={<CustomTooltip />} wrapperStyle={{ zIndex: 100 }} />
                </PieChart>
            </ResponsiveContainer>

            {/* 紧凑图例列表 */}
            <div className="flex flex-wrap gap-x-3 gap-y-2 mt-2 px-4 justify-center pb-2">
                {chartData.map((d, idx) => (
                    <div
                        key={d.name}
                        className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded-md transition-all cursor-pointer ${activeIndex === idx ? 'bg-slate-700/50 outline outline-1 outline-slate-700/50' : 'hover:bg-slate-800/30'}`}
                        onMouseEnter={() => setActiveIndex(idx)}
                    >
                        <div className="w-2.5 h-2.5 rounded-full flex-shrink-0 shadow-sm"
                            style={{ backgroundColor: COLORS[idx % COLORS.length] }} />
                        <span className={`transition-colors text-[11px] ${activeIndex === idx ? 'text-slate-100 font-medium' : 'text-slate-400'}`}>
                            {d.name}
                            {d.stocks && d.stocks.length > 0 && (
                                <span className="text-indigo-300 ml-1.5 font-medium">({d.stocks.join(', ')})</span>
                            )}
                        </span>
                        <span className={`font-mono text-[11px] ${activeIndex === idx ? 'text-white' : 'text-slate-500'}`}>
                            {d.pct}%
                        </span>
                    </div>
                ))}
            </div>
        </div>
    );
};

export default IndustryExposureChart;
