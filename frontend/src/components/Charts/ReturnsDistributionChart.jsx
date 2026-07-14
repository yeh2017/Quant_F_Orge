import {
    ResponsiveContainer,
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
} from 'recharts';

const ReturnsDistributionChart = ({ data }) => {
    if (!data || data.length === 0) {
        return (
            <div className="h-full flex items-center justify-center text-gray-500">
                暂无数据
            </div>
        );
    }

    return (
        <div className="w-full h-[300px] bg-gray-900/50 p-4 rounded-lg border border-gray-800">
            <h3 className="text-gray-200 mb-4 font-semibold">
                收益分布
                <span className="text-xs font-normal ml-2">每日涨跌幅的频率分布 · 左尾越厚尾部风险越大</span>
            </h3>
            <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis
                        dataKey="range"
                        stroke="#9CA3AF"
                        tick={{ fontSize: 12 }}
                    />
                    <YAxis
                        stroke="#9CA3AF"
                        tick={{ fontSize: 12 }}
                    />
                    <Tooltip
                        cursor={{ fill: '#374151', opacity: 0.3 }}
                        contentStyle={{
                            backgroundColor: '#1F2937',
                            borderColor: '#374151',
                            color: '#F3F4F6'
                        }}
                    />
                    <Bar
                        dataKey="frequency"
                        name="出现天数"
                        fill="#3B82F6"
                        radius={[4, 4, 0, 0]}
                    />
                </BarChart>
            </ResponsiveContainer>
        </div>
    );
};

export default ReturnsDistributionChart;
