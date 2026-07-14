import {
    ResponsiveContainer,
    LineChart,
    Line,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
} from 'recharts';

const NetValueChart = ({ data }) => {
    if (!data || data.length === 0) {
        return (
            <div className="h-full flex items-center justify-center text-gray-500">
                暂无数据
            </div>
        );
    }

    return (
        <div className="w-full h-[300px] bg-gray-900/50 p-4 rounded-lg border border-gray-800">
            <h3 className="text-gray-200 mb-4 font-semibold flex items-center gap-2">
                策略净值 vs 基准
            </h3>
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                    <XAxis
                        dataKey="date"
                        stroke="#9CA3AF"
                        tick={{ fontSize: 12 }}
                        tickMargin={10}
                    />
                    <YAxis
                        stroke="#9CA3AF"
                        tick={{ fontSize: 12 }}
                        domain={['auto', 'auto']}
                        tickFormatter={(value) => value.toFixed(2)}
                    />
                    <Tooltip
                        contentStyle={{
                            backgroundColor: '#1F2937',
                            borderColor: '#374151',
                            color: '#F3F4F6'
                        }}
                        itemStyle={{ color: '#F3F4F6' }}
                        labelStyle={{ color: '#D1D5DB' }}
                    />
                    <Legend wrapperStyle={{ paddingTop: '10px' }} />
                    <Line
                        type="monotone"
                        dataKey="value"
                        name="策略净值"
                        stroke="#8B5CF6"
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 6 }}
                    />
                    <Line
                        type="monotone"
                        dataKey="benchmark"
                        name="基准净值"
                        stroke="#6B7280"
                        strokeWidth={2}
                        strokeDasharray="5 5"
                        dot={false}
                    />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
};

export default NetValueChart;
