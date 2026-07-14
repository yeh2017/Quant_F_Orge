/**
 * K线技术指标计算工具
 * 纯前端计算，基于 OHLCV 数据
 */

// EMA 指数移动平均
function ema(data, period) {
    const k = 2 / (period + 1);
    const result = [data[0]];
    for (let i = 1; i < data.length; i++) {
        result.push(data[i] * k + result[i - 1] * (1 - k));
    }
    return result;
}

// SMA 简单移动平均
function sma(data, period) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) { result.push(null); continue; }
        let sum = 0;
        for (let j = 0; j < period; j++) sum += data[i - j];
        result.push(sum / period);
    }
    return result;
}

/**
 * MACD 指标
 * @returns {{ dif: number[], dea: number[], histogram: number[] }}
 */
export function calcMACD(closes, fast = 12, slow = 26, signal = 9) {
    if (closes.length < slow + signal) return null;
    const emaFast = ema(closes, fast);
    const emaSlow = ema(closes, slow);
    const dif = emaFast.map((v, i) => v - emaSlow[i]);
    const dea = ema(dif, signal);
    const histogram = dif.map((v, i) => (v - dea[i]) * 2);
    return { dif, dea, histogram };
}

/**
 * RSI 指标
 * @returns {number[]}
 */
export function calcRSI(closes, period = 14) {
    if (closes.length < period + 1) return null;
    const gains = [];
    const losses = [];
    for (let i = 1; i < closes.length; i++) {
        const diff = closes[i] - closes[i - 1];
        gains.push(diff > 0 ? diff : 0);
        losses.push(diff < 0 ? -diff : 0);
    }
    const result = [null]; // 第一根没有 RSI
    let avgGain = gains.slice(0, period).reduce((a, b) => a + b, 0) / period;
    let avgLoss = losses.slice(0, period).reduce((a, b) => a + b, 0) / period;

    for (let i = 0; i < period - 1; i++) result.push(null);

    const rs = avgGain / (avgLoss || 1e-9);
    result.push(100 - 100 / (1 + rs));

    for (let i = period; i < gains.length; i++) {
        avgGain = (avgGain * (period - 1) + gains[i]) / period;
        avgLoss = (avgLoss * (period - 1) + losses[i]) / period;
        const rs = avgGain / (avgLoss || 1e-9);
        result.push(100 - 100 / (1 + rs));
    }
    return result;
}

/**
 * 布林带
 * @returns {{ upper: number[], middle: number[], lower: number[] }}
 */
export function calcBOLL(closes, period = 20, multiplier = 2) {
    if (closes.length < period) return null;
    const middle = sma(closes, period);
    const upper = [];
    const lower = [];
    for (let i = 0; i < closes.length; i++) {
        if (middle[i] === null) { upper.push(null); lower.push(null); continue; }
        let sumSq = 0;
        for (let j = 0; j < period; j++) sumSq += (closes[i - j] - middle[i]) ** 2;
        const std = Math.sqrt(sumSq / period);
        upper.push(middle[i] + multiplier * std);
        lower.push(middle[i] - multiplier * std);
    }
    return { upper, middle, lower };
}

/**
 * 唐奇安通道
 * @returns {{ upper: number[], lower: number[] }}
 */
export function calcDonchian(highs, lows, period = 20) {
    if (highs.length < period) return null;
    const upper = [];
    const lower = [];
    for (let i = 0; i < highs.length; i++) {
        if (i < period - 1) { upper.push(null); lower.push(null); continue; }
        let maxH = -Infinity, minL = Infinity;
        for (let j = 0; j < period; j++) {
            maxH = Math.max(maxH, highs[i - j]);
            minL = Math.min(minL, lows[i - j]);
        }
        upper.push(maxH);
        lower.push(minL);
    }
    return { upper, lower };
}

/**
 * KDJ 随机指标
 * RSV = (C - Ln) / (Hn - Ln) × 100
 * K = SMA(RSV, m1)   D = SMA(K, m2)   J = 3K - 2D
 * @returns {{ k: number[], d: number[], j: number[] }}
 */
export function calcKDJ(highs, lows, closes, n = 9, m1 = 3, m2 = 3) {
    if (closes.length < n) return null;
    const rsv = [];
    for (let i = 0; i < closes.length; i++) {
        if (i < n - 1) { rsv.push(null); continue; }
        let hn = -Infinity, ln = Infinity;
        for (let j = 0; j < n; j++) {
            hn = Math.max(hn, highs[i - j]);
            ln = Math.min(ln, lows[i - j]);
        }
        rsv.push(hn === ln ? 50 : ((closes[i] - ln) / (hn - ln)) * 100);
    }
    // SMA 递推：K = (RSV + (m1-1)*K_prev) / m1，初始值 50
    const k = [], d = [], jArr = [];
    let kPrev = 50, dPrev = 50;
    for (let i = 0; i < closes.length; i++) {
        if (rsv[i] === null) { k.push(null); d.push(null); jArr.push(null); continue; }
        const kVal = (rsv[i] + (m1 - 1) * kPrev) / m1;
        const dVal = (kVal + (m2 - 1) * dPrev) / m2;
        const jVal = 3 * kVal - 2 * dVal;
        k.push(kVal); d.push(dVal); jArr.push(jVal);
        kPrev = kVal; dPrev = dVal;
    }
    return { k, d, j: jArr };
}
