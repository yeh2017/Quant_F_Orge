/**
 * 数值格式化 — 唯一来源（Single Source of Truth）
 * 所有前端模块只调此处的函数来格式化数值。
 */

/**
 * 通用数值格式化
 * @param {number|null|undefined} value - 待格式化的值
 * @param {number} [decimals=2] - 小数位数
 * @param {string} [suffix=''] - 后缀（如 '%'）
 * @param {string} [fallback='--'] - 空值兜底显示
 * @returns {string}
 */
export function fmtNum(value, decimals = 2, suffix = '', fallback = '--') {
  if (value == null || isNaN(Number(value))) return fallback;
  return `${Number(value).toFixed(decimals)}${suffix}`;
}

/**
 * 百分比格式化（带 % 后缀）
 * @param {number|null|undefined} value
 * @param {number} [decimals=2]
 * @param {string} [fallback='--']
 */
export function fmtPct(value, decimals = 2, fallback = '--') {
  return fmtNum(value, decimals, '%', fallback);
}

/**
 * 带正号的涨跌幅格式化（+1.23% / -0.45%）
 * @param {number|null|undefined} value
 * @param {number} [decimals=2]
 */
export function fmtChg(value, decimals = 2, fallback = '--') {
  if (value == null || isNaN(Number(value))) return fallback;
  const v = Number(value);
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(decimals)}%`;
}

/**
 * 涨跌颜色 CSS 类（A 股 红涨绿跌）
 * @param {number|null|undefined} value
 * @returns {string} Tailwind CSS 类名
 */
export function pctColor(value) {
  if (value == null) return 'text-slate-400';
  const v = Number(value);
  if (v > 0) return 'text-red-400';
  if (v < 0) return 'text-green-400';
  return 'text-slate-400';
}

/**
 * 策略损益颜色 CSS 类（A 股：盈利=红，亏损=绿）
 * 用于回测收益、组合优化、风险分析等"盈亏"场景
 * @param {number|null|undefined} value
 * @returns {string} Tailwind CSS 类名
 */
export function pnlColor(value) {
  if (value == null) return 'text-slate-400';
  const v = Number(value);
  if (v > 0) return 'text-red-400';
  if (v < 0) return 'text-green-400';
  return 'text-slate-400';
}

/**
 * 大数值格式化（万/亿）
 * @param {number|null|undefined} value - 原始值
 * @param {string} [fallback='--']
 */
export function fmtAmount(value, fallback = '--') {
  if (value == null || isNaN(Number(value))) return fallback;
  const v = Math.abs(Number(value));
  if (v >= 1e8) return `${(Number(value) / 1e8).toFixed(1)}亿`;
  if (v >= 1e4) return `${(Number(value) / 1e4).toFixed(0)}万`;
  return `${Number(value).toFixed(0)}`;
}

/* ── Alert 通知 ────────────────────────── */
const ALERT_ICONS = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };

/**
 * 统一 Alert 通知构造器
 * @param {'success'|'error'|'warning'|'info'} type
 * @param {string} msg - 消息正文（无需手动加前缀图标）
 * @returns {{ type: string, msg: string }}
 */
export function makeAlert(type, msg) {
  const icon = ALERT_ICONS[type] || '';
  return { type, msg: `${icon} ${msg}` };
}
