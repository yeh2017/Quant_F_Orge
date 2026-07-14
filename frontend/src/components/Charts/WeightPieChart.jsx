import { ResponsiveContainer, PieChart, Pie, Cell, Tooltip } from 'recharts';

const COLORS = [
    '#6366f1', '#8b5cf6', '#a78bfa', '#c084fc',
    '#818cf8', '#7c3aed', '#4f46e5', '#6d28d9',
    '#5b21b6', '#4c1d95', '#3730a3', '#312e81',
];

/**
 * 权重饼图 — 展示组合中各股票的配置权重。
 * holdings: [{ code, name, weight }]  weight 为小数（0~1）
 */
const WeightPieChart = ({ holdings, title = '持仓权重分布' }) => {
    if (!holdings || holdings.length === 0) return null;

    const data = holdings
        .filter(h => h.weight > 0.001)
        .map(h => ({
            name: h.name || h.code,
            value: Math.round(h.weight * 1000) / 10, // 转为百分比（一位小数）
        }));

    return (
        <div className="w-full bg-slate-800/40 border border-slate-700/50 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-slate-300 mb-2 flex items-center gap-2">
                <div className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                {title}
            </h3>
            <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                    <Pie
                        data={data}
                        cx="50%"
                        cy="50%"
                        innerRadius={55}
                        outerRadius={90}
                        paddingAngle={2}
                        dataKey="value"
                        stroke="none"
                        isAnimationActive={false}
                        label={({ name, value, cx, cy, midAngle, outerRadius }) => {
                            if (value < 5) return null;
                            const RADIAN = Math.PI / 180;
                            const radius = outerRadius + 14;
                            const x = cx + radius * Math.cos(-midAngle * RADIAN);
                            const y = cy + radius * Math.sin(-midAngle * RADIAN);
                            return <text x={x} y={y} fill="#ffffff" fontSize={12} textAnchor={x > cx ? 'start' : 'end'} dominantBaseline="central">{name} {value}%</text>;
                        }}
                        labelLine={false}
                    >
                        {data.map((_, i) => (
                            <Cell key={i} fill={COLORS[i % COLORS.length]} />
                        ))}
                    </Pie>
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#1e293b',
                            borderColor: '#334155',
                            borderRadius: '8px',
                            fontSize: '12px',
                            color: '#ffffff',
                        }}
                        formatter={v => [`${v}%`, '权重']}
                    />

                </PieChart>
            </ResponsiveContainer>
        </div>
    );
};

export default WeightPieChart;
