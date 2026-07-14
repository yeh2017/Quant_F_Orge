/**
 * 日期工具函数
 * 全局唯一的日期格式化 + 回看周期预设
 */

// 本地日期格式化（避免 toISOString 的 UTC 时区偏差）
export const toLocalDate = (d) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

// 回看周期预设（自然日）
export const LOOKBACK_PRESETS = [
    { label: '1月',  days: 30 },
    { label: '3月',  days: 90 },
    { label: '半年', days: 180 },
    { label: '1年',  days: 365 },
    { label: '2年',  days: 730 },
    { label: '3年',  days: 1095 },
];

// 组合优化专用预设（交易日）
export const TRADING_DAY_PRESETS = [
    { label: '1月',  days: 22 },
    { label: '3月',  days: 63 },
    { label: '半年', days: 126 },
    { label: '1年',  days: 252 },
    { label: '2年',  days: 504 },
    { label: '3年',  days: 756 },
];

// 根据回看天数计算 startDate/endDate
export const getLookbackRange = (days) => {
    const end = new Date();
    const start = new Date(Date.now() - days * 86400000);
    return { startDate: toLocalDate(start), endDate: toLocalDate(end) };
};
