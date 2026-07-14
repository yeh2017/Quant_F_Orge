import React, { useState, useCallback } from 'react';
import { Filter } from 'lucide-react';
import { screenerApi } from '../../services/api';
import EtfTab from './EtfTab';
import BondTab from './BondTab';
import StockTab from './StockTab';
import { useTabRefresh } from '../../hooks/useTabRefresh';

const ScreenerPanel = ({ isActive, customStocks, setCustomStocks, customBonds, setCustomBonds, setAlerts, refreshTrigger, onViewKline }) => {
    // 顶部 Tab
    const [screenTab, setScreenTab] = useState('stock');
    const [etfSearchKeyword, setEtfSearchKeyword] = useState(null);


    // ── 市场数据（stock/etf 共享） ──
    const [industries, setIndustries] = useState([]);
    const [heat, setHeat] = useState({});
    const [heat5d, setHeat5d] = useState({});
    const [heatDate, setHeatDate] = useState(null);
    const [rankings, setRankings] = useState(null);
    const [l1ToSubs, setL1ToSubs] = useState({});
    const [heatSource, setHeatSource] = useState(null);
    const [regime, setRegime] = useState(null);
    const [stockReversal, setStockReversal] = useState(null);

    const loadMarketData = useCallback(() => {
        screenerApi.getIndustries()
            .then(res => setIndustries(res.industries || []))
            .catch(() => {});
        screenerApi.getIndustryHeat()
            .then(res => {
                setHeat(res.heat || {});
                setHeat5d(res.heat_5d || {});
                setHeatDate(res.trade_date);
                if (res.rankings) setRankings(res.rankings);
                if (res.l1_to_subs) setL1ToSubs(res.l1_to_subs);
                if (res.source) setHeatSource(res.source);
            })
            .catch(() => {});
        screenerApi.getMarketRegime()
            .then(res => setRegime(res))
            .catch(() => {});
        screenerApi.getStockReversal()
            .then(res => setStockReversal(res))
            .catch(() => {});
    }, []);

    React.useEffect(() => { loadMarketData(); }, [loadMarketData]);
    useTabRefresh(isActive, loadMarketData);

    return (
        <div className="space-y-6">
            {/* 标题 + Tab */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                        <div className="p-2.5 bg-emerald-500/20 rounded-xl border border-emerald-500/30">
                            <Filter className="w-6 h-6 text-emerald-400" />
                        </div>
                        {screenTab === 'stock' ? '智能选股器' : screenTab === 'etf' ? 'ETF 筛选' : '可转债筛选'}
                    </h2>
                    <div className="flex bg-slate-800/80 rounded-lg border border-slate-700/50 p-0.5">
                        {[{id: 'stock', label: '📊 智能选股'}, {id: 'etf', label: '🏦 ETF 筛选'}, {id: 'bond', label: '📜 可转债'}].map(t => (
                            <button key={t.id}
                                onClick={() => { setScreenTab(t.id); setAlerts([]); }}
                                className={`px-4 py-1.5 rounded-md text-sm font-medium transition-all ${
                                    screenTab === t.id
                                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                        : 'text-slate-400 hover:text-white'
                                }`}>
                                {t.label}
                            </button>
                        ))}
                    </div>
                </div>
                <span className="text-xs text-white/60">
                    基于本地数仓 SQL 联表查询 · 毫秒级响应
                    {heatDate && <span className="ml-2">· 热度: {heatDate}</span>}
                    {heatSource && <span className={`ml-2 px-1.5 py-0.5 rounded text-[10px] ${heatSource === 'index' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'}`}>
                        {heatSource === 'index' ? '申万指数' : '个股均值'}
                    </span>}
                </span>
            </div>

            {/* ===== ETF 筛选 Tab ===== */}
            <div style={{ display: screenTab === 'etf' ? 'block' : 'none' }}>
                <EtfTab

                    customStocks={customStocks} setCustomStocks={setCustomStocks}
                    stockReversal={stockReversal}
                    onViewKline={onViewKline}
                    searchKeyword={etfSearchKeyword}
                    refreshTrigger={refreshTrigger}
                />
            </div>

            {/* ===== 可转债筛选 Tab ===== */}
            <div style={{ display: screenTab === 'bond' ? 'block' : 'none' }}>
                <BondTab customBonds={customBonds} setCustomBonds={setCustomBonds} onViewKline={onViewKline} refreshTrigger={refreshTrigger} />
            </div>

            {/* ===== 股票筛选 Tab ===== */}
            <div style={{ display: screenTab === 'stock' ? 'block' : 'none' }}>
                <StockTab
                    industries={industries} heat={heat} heat5d={heat5d}
                    rankings={rankings} l1ToSubs={l1ToSubs} regime={regime} stockReversal={stockReversal} heatDate={heatDate}
                    customStocks={customStocks} setCustomStocks={setCustomStocks}
                    setAlerts={setAlerts} onViewKline={onViewKline}
                    onJumpEtf={(keyword) => { setEtfSearchKeyword({ value: keyword, ts: Date.now() }); setScreenTab('etf'); }}
                />
            </div>
        </div>
    );
};

export default ScreenerPanel;
