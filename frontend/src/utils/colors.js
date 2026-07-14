/**
 * 全平台涨跌色常量 — 单一来源
 * A 股惯例：红涨绿跌
 *
 * CLASS（-400）用于 JSX/Tailwind 文本，在 DOM 中渲染
 * HEX（-500）用于 Canvas/lightweight-charts，深色背景需要更饱和的颜色
 */

// Tailwind class（DOM 文本色）— 对应 -400 色阶
export const RISE_CLASS = 'text-red-400';       // #f87171
export const FALL_CLASS = 'text-green-400';     // #4ade80
export const FLAT_CLASS = 'text-slate-400';     // #94a3b8

// Hex 值（Canvas 绘制色）— 对应 -500 色阶，更饱和
export const RISE_HEX = '#ef4444';   // red-500
export const FALL_HEX = '#22c55e';   // green-500
export const FLAT_HEX = '#94a3b8';   // slate-400

export const getPctColorClass = (val, fallback = FLAT_CLASS) => {
    if (val == null) return fallback;
    const num = Number(val);
    if (num > 0) return `${RISE_CLASS} font-medium`;
    if (num < 0) return `${FALL_CLASS} font-medium`;
    return fallback;
};
