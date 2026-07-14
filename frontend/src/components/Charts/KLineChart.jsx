import React, { useRef, useState, useEffect } from 'react';
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers } from 'lightweight-charts';
import { calcMACD, calcRSI, calcBOLL, calcDonchian, calcKDJ } from '../../utils/indicators';
import { fmtNum } from '../../utils/format';

/**
 * 三面板 K 线图组件
 * ┌────────────────────┐
 * │ 主图: K线+MA+叠加   │ 65%
 * ├────────────────────┤
 * │ 成交量: 独立面板     │ 15%
 * ├────────────────────┤
 * │ 指标: MACD/RSI      │ 20%  (可选)
 * └────────────────────┘
 */
const KLineChart = ({
    data,
    volumeData,
    markers = [],
    indicator = null,
    showMA = true,
    marginData = [],
    strategyType = null,
    strategyParams = {},
    colors = { backgroundColor: '#1e1b4b', textColor: 'white' },
    height = 560
}) => {
    const containerRef = useRef(null);
    const legendRef = useRef(null);
    const volLegendRef = useRef(null);
    const indLegendRef = useRef(null);
    const [error, setError] = useState(null);

    const needsIndicator = indicator === 'macd' || indicator === 'rsi' || indicator === 'kdj';
    const needsOverlay = indicator === 'boll' || indicator === 'donchian' || indicator === 'grid';

    // 高度分配
    const mainH = needsIndicator ? Math.round(height * 0.63) : Math.round(height * 0.78);
    const volH = needsIndicator ? Math.round(height * 0.17) : Math.round(height * 0.22);
    const indH = needsIndicator ? Math.round(height * 0.20) : 0;

    const fmt = (n) => fmtNum(n, 2);
    const fmtVol = (vol) => {
        const v = Number(vol);
        if (!vol || isNaN(v)) return '--';
        if (v > 1e8) return (v / 1e8).toFixed(2) + '亿';
        if (v > 1e4) return (v / 1e4).toFixed(2) + '万';
        return v.toString();
    };

    const calculateMA = (period, srcData) => {
        const result = [];
        for (let i = 0; i < srcData.length; i++) {
            if (i < period - 1) continue;
            let sum = 0;
            for (let j = 0; j < period; j++) sum += Number(srcData[i - j].close) || 0;
            result.push({ time: srcData[i].time, value: sum / period });
        }
        return result;
    };

    useEffect(() => {
        if (!data?.length || !containerRef.current) return;

        const normalizeTime = (t) => {
            if (!t) return t;
            const s = String(t);
            if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
            return s.slice(0, 10);
        };
        const chartData = data
            .map(d => ({ ...d, time: normalizeTime(d.time || d.date) }))
            .filter(d => d.time)
            .sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);

        try {
            // ══════════════════ 单实例 + paneIndex ══════════════════
            const chart = createChart(containerRef.current, {
                layout: { background: { color: 'transparent' }, textColor: 'white', attributionLogo: false, panes: { separatorColor: '#334155' } },
                localization: {
                    timeFormatter: (time) => {
                        if (typeof time === 'string') return time;
                        const d = typeof time === 'number' ? new Date(time * 1000) : new Date(time);
                        const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0');
                        const day = String(d.getDate()).padStart(2, '0');
                        return `${y}-${m}-${day}`;
                    },
                },
                width: containerRef.current.clientWidth,
                height: height,
                grid: {
                    vertLines: { color: 'rgba(255,255,255,0.08)' },
                    horzLines: { color: 'rgba(255,255,255,0.08)' },
                },
                timeScale: {
                    borderColor: '#334155',
                    tickMarkFormatter: (time, tickMarkType) => {
                        const d = typeof time === 'number' ? new Date(time * 1000) : new Date(time);
                        const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0');
                        const day = String(d.getDate()).padStart(2, '0'), yy = String(y).slice(2);
                        if (tickMarkType === 0) return `${y}`;
                        if (tickMarkType === 1) return `${yy}/${m}`;
                        return `${yy}/${m}/${day}`;
                    },
                },
                rightPriceScale: { borderColor: '#334155' },
            });

            // ══════════════════ 1. 主图 (pane 0) ══════════════════
            const mainChart = chart; // 兼容下游变量名

            const candleSeries = mainChart.addSeries(CandlestickSeries, {
                upColor: '#ef4444', downColor: '#22c55e', borderVisible: false,
                wickUpColor: '#ef4444', wickDownColor: '#22c55e',
            });
            candleSeries.setData(chartData);

            // 买卖标记
            if (markers?.length > 0) {
                const sorted = markers
                    .map(m => {
                        const t = normalizeTime(m.time);
                        if (!t) return null;
                        // 回测买卖标记（有 type 字段）
                        if (m.type) {
                            const isBuy = m.type === 'buy';
                            let label = isBuy ? 'B' : 'S';
                            if (isBuy && m.weight) label = `B ${m.weight}%`;
                            else if (!isBuy && m.pnl != null) {
                                label = `S ${m.pnl >= 0 ? '+' : ''}${m.pnl}%`;
                            }
                            return {
                                time: t,
                                position: isBuy ? 'belowBar' : 'aboveBar',
                                color: isBuy ? '#ef4444' : '#22c55e',
                                shape: isBuy ? 'arrowUp' : 'arrowDown',
                                text: label, size: 1.5,
                            };
                        }
                        // 自定义标记（新闻事件等，已携带完整属性）
                        return { ...m, time: t };
                    })
                    .filter(Boolean)
                    .sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
                if (sorted.length) createSeriesMarkers(candleSeries, sorted);

                // 悬停 tooltip：有 tooltip 字段的 marker 在 crosshair 经过时显示浮窗
                const tooltipMap = {};
                sorted.forEach(m => {
                    if (m.tooltip) {
                        if (!tooltipMap[m.time]) tooltipMap[m.time] = [];
                        tooltipMap[m.time].push(m);
                    }
                });
                if (Object.keys(tooltipMap).length > 0) {
                    const tip = document.createElement('div');
                    Object.assign(tip.style, {
                        position: 'absolute', display: 'none', zIndex: '100',
                        padding: '6px 10px', borderRadius: '6px', fontSize: '12px',
                        lineHeight: '1.5', maxWidth: '320px', pointerEvents: 'none',
                        background: 'rgba(15,23,42,0.92)', color: '#e2e8f0',
                        border: '1px solid rgba(148,163,184,0.3)',
                        boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                    });
                    containerRef.current.style.position = 'relative';
                    containerRef.current.appendChild(tip);

                    mainChart.subscribeCrosshairMove(param => {
                        if (!param.time || !param.point) { tip.style.display = 'none'; return; }
                        const key = typeof param.time === 'object'
                            ? `${param.time.year}-${String(param.time.month).padStart(2,'0')}-${String(param.time.day).padStart(2,'0')}`
                            : param.time;
                        const items = tooltipMap[key];
                        if (!items) { tip.style.display = 'none'; return; }
                        tip.innerHTML = items.map(m => {
                            const label = m.text || '';
                            const header = label ? `<div style="font-weight:600;color:${m.color};margin-bottom:2px">${label}</div>` : '';
                            return `${header}<div style="margin-bottom:2px">${m.tooltip}</div>`;
                        }).join('');
                        tip.style.display = 'block';
                        const x = param.point?.x ?? 0;
                        tip.style.left = `${Math.min(x + 12, containerRef.current.clientWidth - 330)}px`;
                        tip.style.top = '8px';
                    });
                }
            }

            // 均线（主图有其他叠加线时隐藏，避免线条重叠）
            const hasMainOverlay = (indicator === 'boll' || indicator === 'donchian')
                || (markers?.length > 0 && ['timing', 'volume_breakout', 'grid'].includes(strategyType) && !indicator);
            const maList = [
                { n: 5, color: '#f59e0b', name: 'MA5' },
                { n: 10, color: '#8b5cf6', name: 'MA10' },
                { n: 20, color: '#0ea5e9', name: 'MA20' },
                { n: 30, color: '#f1f5f9', name: 'MA30' },
                { n: 60, color: '#ec4899', name: 'MA60' },
            ];
            const maMap = {};
            if (showMA && !hasMainOverlay) {
                maList.forEach(ma => {
                    const d = calculateMA(ma.n, chartData);
                    if (d.length) {
                        const s = mainChart.addSeries(LineSeries, {
                            color: ma.color, lineWidth: 1.5,
                            crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                        });
                        s.setData(d);
                        maMap[ma.name] = s;
                    }
                });
            }

            // 主图叠加（BOLL / 唐奇安）
            const closes = chartData.map(d => d.close);
            const highs = chartData.map(d => d.high);
            const lows = chartData.map(d => d.low);
            let overlayInfo = null;

            const toLineData = (arr) => arr
                .map((v, i) => v !== null ? { time: chartData[i].time, value: v } : null)
                .filter(Boolean);

            if (indicator === 'boll') {
                const bollPeriod = (strategyType === 'bband' ? strategyParams.window : null) || 20;
                const bollMult = (strategyType === 'bband' ? strategyParams.num_std : null) || 2;
                const b = calcBOLL(closes, bollPeriod, bollMult);
                if (b) {
                    [{ d: b.upper, c: '#f59e0b' }, { d: b.middle, c: '#94a3b8' }, { d: b.lower, c: '#06b6d4' }]
                        .forEach(({ d, c }) => {
                            const s = mainChart.addSeries(LineSeries, {
                                color: c, lineWidth: 1, lineStyle: 2,
                                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                            });
                            s.setData(toLineData(d));
                        });
                    overlayInfo = { type: 'boll', ...b };
                }
            }
            if (indicator === 'donchian') {
                const dcPeriod = (strategyType === 'turtle' ? strategyParams.entry : null) || 20;
                const dc = calcDonchian(highs, lows, dcPeriod);
                if (dc) {
                    [{ d: dc.upper, c: '#f97316' }, { d: dc.lower, c: '#06b6d4' }]
                        .forEach(({ d, c }) => {
                            const s = mainChart.addSeries(LineSeries, {
                                color: c, lineWidth: 1.5, lineStyle: 2,
                                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                            });
                            s.setData(toLineData(d));
                        });
                    overlayInfo = { type: 'donchian', ...dc };
                }
            }

            // ── 策略专属叠加（仅有回测结果时显示）──
            const hasMarkers = markers?.length > 0;
            // 均线择时：快慢均线
            if (hasMarkers && strategyType === 'timing' && !indicator) {
                const fastP = strategyParams.fast_ma || 20;
                const slowP = strategyParams.slow_ma || 60;
                [{ n: fastP, c: '#f59e0b', label: `快MA${fastP}` }, { n: slowP, c: '#8b5cf6', label: `慢MA${slowP}` }]
                    .forEach(({ n, c, label }) => {
                        const d = calculateMA(n, chartData);
                        if (d.length) {
                            const s = mainChart.addSeries(LineSeries, {
                                color: c, lineWidth: 2, lineStyle: 0, title: label,
                                crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false,
                            });
                            s.setData(d);
                        }
                    });
            }

            // 放量突破：N日最高/最低价通道
            if (hasMarkers && strategyType === 'volume_breakout' && !indicator) {
                const priceDays = strategyParams.price_days || 20;
                const highChannel = [], lowChannel = [];
                for (let i = 0; i < chartData.length; i++) {
                    if (i < priceDays) { highChannel.push(null); lowChannel.push(null); continue; }
                    let hMax = -Infinity, lMin = Infinity;
                    for (let j = i - priceDays; j < i; j++) {
                        hMax = Math.max(hMax, chartData[j].high);
                        lMin = Math.min(lMin, chartData[j].low);
                    }
                    highChannel.push(hMax);
                    lowChannel.push(lMin);
                }
                [{ d: highChannel, c: '#f97316', label: `${priceDays}日高` }, { d: lowChannel, c: '#06b6d4', label: `${priceDays}日低` }]
                    .forEach(({ d, c, label }) => {
                        const s = mainChart.addSeries(LineSeries, {
                            color: c, lineWidth: 1.5, lineStyle: 2, title: label,
                            crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false,
                        });
                        s.setData(toLineData(d));
                    });
            }

            // 网格交易：均线中轴 + 上下网格线（带标注）
            let gridInfo = null;
            if (hasMarkers && strategyType === 'grid' && !indicator) {
                const maW = strategyParams.ma_window || 20;
                const gridPct = (strategyParams.grid_pct || 3) / 100;
                const numGrids = strategyParams.num_grids || 4;
                const maData = calculateMA(maW, chartData);
                gridInfo = { maW, gridPct: gridPct * 100, numGrids };
                if (maData.length) {
                    // 中轴均线 — 白色实线（右侧只显示价格）
                    const midS = mainChart.addSeries(LineSeries, {
                        color: '#e2e8f0', lineWidth: 2, lineStyle: 0, title: `MA${maW}`,
                        crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false,
                    });
                    midS.setData(maData);
                    // 上下网格线：关闭右侧价格标签，避免堆叠拥挤
                    for (let g = 1; g <= numGrids; g++) {
                        const isInner = g <= 2;
                        const buyColor = isInner ? 'rgba(34,197,94,0.7)' : 'rgba(34,197,94,0.25)';
                        const sellColor = isInner ? 'rgba(239,68,68,0.7)' : 'rgba(239,68,68,0.25)';
                        const lw = isInner ? 1.5 : 1;
                        const ls = isInner ? 2 : 3; // Dash / DotDash
                        const pctLabel = (g * gridPct * 100).toFixed(0);
                        // 买入线（下方）
                        const buyLine = maData.map(d => ({ time: d.time, value: d.value * (1 - g * gridPct) }));
                        const buyS = mainChart.addSeries(LineSeries, {
                            color: buyColor, lineWidth: lw, lineStyle: ls,
                            title: isInner ? `买${g}(-${pctLabel}%)` : '',
                            crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                        });
                        buyS.setData(buyLine);
                        // 卖出线（上方）
                        const sellLine = maData.map(d => ({ time: d.time, value: d.value * (1 + g * gridPct) }));
                        const sellS = mainChart.addSeries(LineSeries, {
                            color: sellColor, lineWidth: lw, lineStyle: ls,
                            title: isInner ? `卖${g}(+${pctLabel}%)` : '',
                            crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                        });
                        sellS.setData(sellLine);
                    }
                }
            }

            // 网格指标模式（无需回测，用默认参数预览网格线）
            if (indicator === 'grid' && !gridInfo) {
                const maW = strategyParams.ma_window || 20;
                const gridPct = (strategyParams.grid_pct || 3) / 100;
                const numGrids = strategyParams.num_grids || 4;
                const maData = calculateMA(maW, chartData);
                gridInfo = { maW, gridPct: gridPct * 100, numGrids };
                if (maData.length) {
                    const midS = mainChart.addSeries(LineSeries, {
                        color: '#e2e8f0', lineWidth: 2, lineStyle: 0, title: `MA${maW}`,
                        crosshairMarkerVisible: false, lastValueVisible: true, priceLineVisible: false,
                    });
                    midS.setData(maData);
                    for (let g = 1; g <= numGrids; g++) {
                        const isInner = g <= 2;
                        const pctLabel = (g * gridPct * 100).toFixed(0);
                        const buyLine = maData.map(d => ({ time: d.time, value: d.value * (1 - g * gridPct) }));
                        mainChart.addSeries(LineSeries, {
                            color: isInner ? 'rgba(34,197,94,0.7)' : 'rgba(34,197,94,0.25)',
                            lineWidth: isInner ? 1.5 : 1, lineStyle: isInner ? 2 : 3,
                            title: isInner ? `买${g}(-${pctLabel}%)` : '',
                            crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                        }).setData(buyLine);
                        const sellLine = maData.map(d => ({ time: d.time, value: d.value * (1 + g * gridPct) }));
                        mainChart.addSeries(LineSeries, {
                            color: isInner ? 'rgba(239,68,68,0.7)' : 'rgba(239,68,68,0.25)',
                            lineWidth: isInner ? 1.5 : 1, lineStyle: isInner ? 2 : 3,
                            title: isInner ? `卖${g}(+${pctLabel}%)` : '',
                            crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                        }).setData(sellLine);
                    }
                }
            }

            // ── 融资余额叠加（独立右侧 Y 轴）──
            let marginSeries = null;
            const fmtYi = (v) => {
                if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
                if (v >= 1e4) return (v / 1e4).toFixed(0) + '万';
                return v.toFixed(0);
            };
            if (marginData?.length > 0) {
                const normalizedMargin = marginData
                    .map(d => ({ time: normalizeTime(d.date), value: d.rzye }))
                    .filter(d => d.time && d.value)
                    .sort((a, b) => a.time < b.time ? -1 : a.time > b.time ? 1 : 0);
                if (normalizedMargin.length > 0) {
                    marginSeries = mainChart.addSeries(LineSeries, {
                        color: '#f59e0b',
                        lineWidth: 1.5,
                        lineStyle: 2, // Dashed
                        crosshairMarkerVisible: true,
                        lastValueVisible: false,
                        priceLineVisible: false,
                        priceScaleId: 'margin',
                        title: '',
                    });
                    marginSeries.setData(normalizedMargin);
                    // 配置右侧独立 Y 轴
                    mainChart.priceScale('margin').applyOptions({
                        scaleMargins: { top: 0.6, bottom: 0.05 },
                        borderVisible: false,
                        visible: false, // 不显示轴标签，避免拥挤，数值通过 legend 显示
                    });
                }
            }

            // 主图图例
            const updateMainLegend = (param) => {
                const el = legendRef.current;
                if (!el) return;
                let idx = chartData.length - 1;
                if (param?.time) {
                    const fi = chartData.findIndex(d => d.time === param.time);
                    if (fi !== -1) idx = fi;
                }
                const d = chartData[idx];
                const prev = idx > 0 ? chartData[idx - 1] : null;
                const pct = prev ? ((d.close - prev.close) / prev.close * 100) : 0;
                const up = prev ? d.close >= prev.close : d.close >= d.open;
                const pc = prev?.close;  // 昨收基准
                const cOpen  = pc ? (d.open  >= pc ? '#ef4444' : '#22c55e') : '#e2e8f0';
                const cHigh  = pc ? (d.high  >= pc ? '#ef4444' : '#22c55e') : '#e2e8f0';
                const cLow   = pc ? (d.low   >= pc ? '#ef4444' : '#22c55e') : '#e2e8f0';
                const cClose = pc ? (d.close >= pc ? '#ef4444' : '#22c55e') : '#e2e8f0';
                const sign = pct > 0 ? '+' : '';

                let maHtml = '';
                maList.forEach(ma => {
                    if (maMap[ma.name]) {
                        const price = param?.seriesData?.get(maMap[ma.name]);
                        const v = price?.value;
                        if (v) maHtml += `<span style="color:${ma.color};margin-right:10px;">${ma.name}:${fmt(v)}</span>`;
                    }
                });
                let ovHtml = '';
                if (overlayInfo?.type === 'boll' && overlayInfo.upper[idx] != null)
                    ovHtml = `<span style="color:#f59e0b">上轨:${fmt(overlayInfo.upper[idx])}</span> <span style="color:#94a3b8">中轨:${fmt(overlayInfo.middle[idx])}</span> <span style="color:#06b6d4">下轨:${fmt(overlayInfo.lower[idx])}</span>`;
                else if (overlayInfo?.type === 'donchian' && overlayInfo.upper[idx] != null)
                    ovHtml = `<span style="color:#f97316">上轨:${fmt(overlayInfo.upper[idx])}</span> <span style="color:#06b6d4">下轨:${fmt(overlayInfo.lower[idx])}</span>`;

                let gridHtml = '';
                if (gridInfo) {
                    gridHtml = `<span style="color:#e2e8f0">━ MA${gridInfo.maW}中轴</span>　` +
                        `<span style="color:#22c55e">┈ 买入线(↓${gridInfo.gridPct}%×${gridInfo.numGrids}层)</span>　` +
                        `<span style="color:#ef4444">┈ 卖出线(↑${gridInfo.gridPct}%×${gridInfo.numGrids}层)</span>`;
                }

                let marginHtml = '';
                if (marginSeries) {
                    const mv = param?.seriesData?.get(marginSeries);
                    const mVal = mv?.value;
                    if (mVal) marginHtml = `<span style="color:#f59e0b;margin-right:10px">融资:${fmtYi(mVal)}</span>`;
                }

                el.innerHTML = `<div style="font:12px/1.6 monospace;display:flex;flex-wrap:wrap;gap:6px;align-items:center;background:rgba(15,23,42,0.5);padding:3px 8px;border-radius:6px;backdrop-filter:blur(4px);">
                    <span style="color:#cbd5e1;font-weight:700">${d.time}</span>
                    <span style="color:#94a3b8">开盘价:<span style="color:${cOpen}">${fmt(d.open)}</span></span>
                    <span style="color:#94a3b8">最高价:<span style="color:${cHigh}">${fmt(d.high)}</span></span>
                    <span style="color:#94a3b8">最低价:<span style="color:${cLow}">${fmt(d.low)}</span></span>
                    <span style="color:#94a3b8">收盘价:<b style="color:${cClose}">${fmt(d.close)}</b></span>
                    <span style="color:#94a3b8">涨跌幅:<span style="color:${up ? '#ef4444' : '#22c55e'};font-weight:700">${sign}${fmt(pct)}%</span></span>
                    ${d.volume != null ? `<span style="color:#94a3b8">成交量:<span style="color:#e2e8f0">${fmtVol(d.volume)}</span></span>` : ''}
                    ${d.amount != null ? `<span style="color:#94a3b8">成交额:<span style="color:#e2e8f0">${fmtVol(d.amount)}</span></span>` : ''}
                    ${d.turnover_rate != null ? `<span style="color:#94a3b8">换手率:<span style="color:#e2e8f0">${fmt(d.turnover_rate)}%</span></span>` : ''}
                    <div style="width:100%;margin-top:1px">${maHtml}${marginHtml}${ovHtml ? `<span style="margin-left:6px">${ovHtml}</span>` : ''}${gridHtml ? `<span style="margin-left:6px">${gridHtml}</span>` : ''}</div>
                </div>`;
            };
            updateMainLegend(null);
            mainChart.subscribeCrosshairMove(updateMainLegend);
            mainChart.timeScale().fitContent();

            // ══════════════════ 2. 成交量面板 (pane 1) ══════════════════
            if (volumeData?.length > 0) {
                const volSeries = chart.addSeries(HistogramSeries, {
                    priceFormat: { type: 'volume' },
                    color: '#26a69a',
                }, 1);
                const normalizedVol = volumeData.map(v => ({
                    time: normalizeTime(v.time),
                    value: v.value,
                    color: v.color,
                }));
                volSeries.setData(normalizedVol);

                // 均量线 VOL MA5 / MA10
                const calcVolMA = (period) => {
                    const result = [];
                    for (let i = 0; i < normalizedVol.length; i++) {
                        if (i < period - 1) continue;
                        let sum = 0;
                        for (let j = 0; j < period; j++) sum += normalizedVol[i - j].value;
                        result.push({ time: normalizedVol[i].time, value: sum / period });
                    }
                    return result;
                };
                const volMaList = [
                    { n: 5, color: '#f59e0b', name: 'MA5' },
                    { n: 10, color: '#8b5cf6', name: 'MA10' },
                ];
                const volMaMap = {};
                volMaList.forEach(ma => {
                    const d = calcVolMA(ma.n);
                    if (d.length) {
                        const s = chart.addSeries(LineSeries, {
                            color: ma.color, lineWidth: 1, priceScaleId: 'right',
                            priceFormat: { type: 'volume' },
                            crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                        }, 1);
                        s.setData(d);
                        volMaMap[ma.name] = s;
                    }
                });


                // 成交量图例
                const updateVolLegend = (param) => {
                    const el = volLegendRef.current;
                    if (!el) return;
                    let idx = volumeData.length - 1;
                    if (param?.time) {
                        const fi = chartData.findIndex(d => d.time === param.time);
                        if (fi !== -1) idx = fi;
                    }
                    const v = volumeData[idx];
                    let volMaHtml = '';
                    volMaList.forEach(ma => {
                        if (volMaMap[ma.name]) {
                            const price = param?.seriesData?.get(volMaMap[ma.name]);
                            const val = price?.value;
                            if (val) volMaHtml += `<span style="color:${ma.color};font-size:11px;margin-left:8px">${ma.name}:${fmtVol(val)}</span>`;
                        }
                    });
                    el.innerHTML = `<span style="font:11px monospace;color:#fff">VOL</span>
                        <span style="font:11px monospace;color:#e2e8f0;margin-left:6px">${v ? fmtVol(v.value) : '--'}</span>${volMaHtml}`;
                };
                updateVolLegend(null);
                chart.subscribeCrosshairMove(updateVolLegend);
            }

            // ══════════════════ 3. 指标面板 ══════════════════
            const indPaneIdx = (volumeData?.length > 0) ? 2 : 1; // 成交量面板不存在时指标用 pane 1
            if (needsIndicator) {

                if (indicator === 'macd') {
                    const macdFast = (strategyType === 'macd' ? strategyParams.fast : null) || 12;
                    const macdSlow = (strategyType === 'macd' ? strategyParams.slow : null) || 26;
                    const macdSignal = (strategyType === 'macd' ? strategyParams.signal : null) || 9;
                    const macd = calcMACD(closes, macdFast, macdSlow, macdSignal);
                    if (macd) {
                        const histS = chart.addSeries(HistogramSeries, {
                            priceScaleId: 'macd', priceFormat: { type: 'price', precision: 3 },
                        }, indPaneIdx);
                        histS.setData(macd.histogram.map((v, i) => ({
                            time: chartData[i].time, value: v,
                            color: v >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)',
                        })));
                        const difS = chart.addSeries(LineSeries, {
                            color: '#60a5fa', lineWidth: 1.5, priceScaleId: 'macd',
                            lastValueVisible: false, priceLineVisible: false,
                        }, indPaneIdx);
                        difS.setData(macd.dif.map((v, i) => ({ time: chartData[i].time, value: v })));
                        const deaS = chart.addSeries(LineSeries, {
                            color: '#fbbf24', lineWidth: 1.5, priceScaleId: 'macd',
                            lastValueVisible: false, priceLineVisible: false,
                        }, indPaneIdx);
                        deaS.setData(macd.dea.map((v, i) => ({ time: chartData[i].time, value: v })));

                        const updateInd = (param) => {
                            const el = indLegendRef.current;
                            if (!el) return;
                            let idx = chartData.length - 1;
                            if (param?.time) { const fi = chartData.findIndex(d => d.time === param.time); if (fi !== -1) idx = fi; }
                            const d = macd.dif[idx], e = macd.dea[idx], h = macd.histogram[idx];
                            el.innerHTML = `<span style="font:11px monospace;color:#fff">MACD(${macdFast},${macdSlow},${macdSignal})</span>
                                <span style="color:#60a5fa;font-size:11px;margin-left:6px">DIF:${d?.toFixed(3)||'--'}</span>
                                <span style="color:#fbbf24;font-size:11px;margin-left:4px">DEA:${e?.toFixed(3)||'--'}</span>
                                <span style="color:${h>=0?'#ef4444':'#22c55e'};font-size:11px;margin-left:4px">MACD:${h?.toFixed(3)||'--'}</span>`;
                        };
                        updateInd(null);
                        chart.subscribeCrosshairMove(updateInd);
                    }
                }

                if (indicator === 'rsi') {
                    const rsi = calcRSI(closes, 14);
                    if (rsi) {
                        const rsiData = rsi.map((v, i) => v !== null ? { time: chartData[i].time, value: v } : null).filter(Boolean);
                        const rsiS = chart.addSeries(LineSeries, {
                            color: '#a78bfa', lineWidth: 2, priceScaleId: 'rsi',
                            lastValueVisible: false, priceLineVisible: false,
                        }, indPaneIdx);
                        rsiS.setData(rsiData);
                        rsiS.priceScale().applyOptions({ scaleMargins: { top: 0.05, bottom: 0.05 }, autoScale: false });

                        [{ v: 70, c: '#ef444480' }, { v: 30, c: '#22c55e80' }].forEach(ref => {
                            const s = chart.addSeries(LineSeries, {
                                color: ref.c, lineWidth: 1, lineStyle: 2, priceScaleId: 'rsi',
                                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                            }, indPaneIdx);
                            s.setData(chartData.map(d => ({ time: d.time, value: ref.v })));
                        });

                        const updateInd = (param) => {
                            const el = indLegendRef.current;
                            if (!el) return;
                            let idx = chartData.length - 1;
                            if (param?.time) { const fi = chartData.findIndex(d => d.time === param.time); if (fi !== -1) idx = fi; }
                            const val = rsi[idx];
                            const clr = val > 70 ? '#ef4444' : val < 30 ? '#22c55e' : '#a78bfa';
                            const rsiHint = val > 70 ? '<span style="color:#ef4444;font-size:10px;margin-left:4px">超买</span>' : val < 30 ? '<span style="color:#22c55e;font-size:10px;margin-left:4px">超卖</span>' : '';
                            el.innerHTML = `<span style="font:11px monospace;color:#fff">RSI(14)</span>
                                <span style="color:${clr};font-size:13px;font-weight:bold;margin-left:6px">${val?.toFixed(2)||'--'}</span>${rsiHint}`;
                        };
                        updateInd(null);
                        chart.subscribeCrosshairMove(updateInd);
                    }
                }

                if (indicator === 'kdj') {
                    const kdj = calcKDJ(highs, lows, closes);
                    if (kdj) {
                        const kdjLines = [
                            { data: kdj.k, color: '#f59e0b', name: 'K' },
                            { data: kdj.d, color: '#60a5fa', name: 'D' },
                            { data: kdj.j, color: '#a78bfa', name: 'J' },
                        ];
                        kdjLines.forEach(line => {
                            const lineData = line.data.map((v, i) => v !== null ? { time: chartData[i].time, value: v } : null).filter(Boolean);
                            const s = chart.addSeries(LineSeries, {
                                color: line.color, lineWidth: 1.5, priceScaleId: 'kdj',
                                lastValueVisible: false, priceLineVisible: false,
                            }, indPaneIdx);
                            s.setData(lineData);
                        });
                        // 超买超卖参考线
                        [{ v: 80, c: '#ef444460' }, { v: 20, c: '#22c55e60' }].forEach(ref => {
                            const s = chart.addSeries(LineSeries, {
                                color: ref.c, lineWidth: 1, lineStyle: 2, priceScaleId: 'kdj',
                                crosshairMarkerVisible: false, lastValueVisible: false, priceLineVisible: false,
                            }, indPaneIdx);
                            s.setData(chartData.map(d => ({ time: d.time, value: ref.v })));
                        });

                        const updateInd = (param) => {
                            const el = indLegendRef.current;
                            if (!el) return;
                            let idx = chartData.length - 1;
                            if (param?.time) { const fi = chartData.findIndex(d => d.time === param.time); if (fi !== -1) idx = fi; }
                            const kv = kdj.k[idx], dv = kdj.d[idx], jv = kdj.j[idx];
                            const kdjHint = kv > 80 ? '<span style="color:#ef4444;font-size:10px;margin-left:4px">超买</span>' : kv < 20 ? '<span style="color:#22c55e;font-size:10px;margin-left:4px">超卖</span>' : '';
                            el.innerHTML = `<span style="font:11px monospace;color:#fff">KDJ(9,3,3)</span>
                                <span style="color:#f59e0b;font-size:11px;margin-left:6px">K:${kv?.toFixed(1)||'--'}</span>
                                <span style="color:#60a5fa;font-size:11px;margin-left:4px">D:${dv?.toFixed(1)||'--'}</span>
                                <span style="color:#a78bfa;font-size:11px;margin-left:4px">J:${jv?.toFixed(1)||'--'}</span>${kdjHint}`;
                        };
                        updateInd(null);
                        chart.subscribeCrosshairMove(updateInd);
                    }
                }
            }

            // 面板高度分配
            try {
                const panes = chart.panes();
                if (panes[0]) panes[0].setHeight(mainH);
                // pane 索引取决于实际面板数
                const volPaneExists = volumeData?.length > 0;
                if (volPaneExists && panes[1]) panes[1].setHeight(volH);
                const indPane = panes[volPaneExists ? 2 : 1];
                if (indPane && needsIndicator) indPane.setHeight(indH);
            } catch {}

            chart.timeScale().fitContent();

            // resize
            const handleResize = () => {
                if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
            };
            window.addEventListener('resize', handleResize);

            return () => {
                window.removeEventListener('resize', handleResize);
                try { chart.remove(); } catch {}
            };
        } catch (err) {
            console.error('KLineChart init failed:', err);
            setError(err.message);
        }
    }, [data, volumeData, markers, indicator, showMA, marginData, strategyType, strategyParams, colors, height, mainH, volH, indH]);

    if (error) {
        return (
            <div className="w-full h-[400px] flex items-center justify-center bg-slate-800/50 rounded-lg border border-red-500/30">
                <div className="text-red-400 text-center">
                    <p className="mb-2">图表加载失败</p>
                    <p className="text-xs text-gray-500">{error}</p>
                </div>
            </div>
        );
    }

    if (!data?.length) {
        return (
            <div className="w-full h-[400px] flex items-center justify-center bg-slate-800/50 rounded-lg">
                <p className="text-gray-500">暂无K线数据</p>
            </div>
        );
    }

    return (
        <div className="w-full relative" style={{ height }}>
            <div ref={legendRef} className="absolute top-2 left-2 z-10 pointer-events-none" style={{ maxWidth: 'calc(100% - 90px)' }} />
            <div ref={volLegendRef} className="absolute left-2 z-10 pointer-events-none flex items-center" style={{ top: mainH + 2 }} />
            {needsIndicator && (
                <div ref={indLegendRef} className="absolute left-2 z-10 pointer-events-none flex items-center" style={{ top: (volumeData?.length > 0 ? mainH + volH : mainH) + 2 }} />
            )}
            <div ref={containerRef} className="w-full h-full" />
        </div>
    );
};

export default KLineChart;
