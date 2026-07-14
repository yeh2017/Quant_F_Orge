import { fmtNum } from '../../utils/format';

/**
 * 情绪进度条：-1(利空) ~ +1(利好)
 * A股规则：利好=红色，利空=绿色
 */
export default function SentimentBar({ score = 0, label = '中性', marketType = 'A股' }) {
    const pct = Math.round((score + 1) / 2 * 100); // -1→0%, 0→50%, +1→100%
    const isPositive = score > 0.3;
    const isNegative = score < -0.3;

    // A股：红涨绿跌
    let barColor = '#6B7280'; // 中性灰
    if (marketType === 'A股') {
        if (isPositive) barColor = '#EF4444'; // 红=利好
        if (isNegative) barColor = '#22C55E'; // 绿=利空
    } else {
        if (isPositive) barColor = '#22C55E'; // 全球：绿=利好
        if (isNegative) barColor = '#EF4444'; // 全球：红=利空
    }

    return (
        <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-gray-200 rounded-full overflow-hidden">
                <div
                    className="h-full rounded-full transition-all duration-300"
                    style={{ width: `${pct}%`, backgroundColor: barColor }}
                />
            </div>
            <span className="text-xs font-medium min-w-[60px] text-right"
                style={{ color: barColor }}>
                {score > 0 ? '+' : ''}{fmtNum(score, 2)} {label}
            </span>
        </div>
    );
}
