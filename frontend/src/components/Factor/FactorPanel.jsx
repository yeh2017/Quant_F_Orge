import { useState, useEffect, useRef } from 'react';
import { Brain, Filter, Zap } from 'lucide-react';
import { factorApi } from '../../services/api';
import { LOOKBACK_PRESETS, getLookbackRange } from '../../utils/dateUtils';
import LookbackSelector from '../shared/LookbackSelector';
import IndustryExposureChart from '../Charts/IndustryExposureChart';
import FactorCardGrid from './FactorCardGrid';
import FactorScoreTable from './FactorScoreTable';
import IcAnalysisPanel from './IcAnalysisPanel';
import IcDecayChart from './IcDecayChart';
import FactorResearchSection from './FactorResearchSection';

// 静态 fallback（仅在 API 不可用时使用）
const DEFAULT_FACTORS = [
    { name: '反转因子', key: 'reversal', items: ['1月收益反转', '超跌反弹'], desc: 'A股短期反转效应显著' },
    { name: '价值因子', key: 'value', items: ['PE', 'PB', 'PS'], desc: 'PE/PB越低越有价值' },
    { name: '质量因子', key: 'quality', items: ['ROE', 'ROA', '毛利率'], desc: '衡量公司盈利能力' },
    { name: '规模因子', key: 'size', items: ['市值对数', '小市值溢价'], desc: '小市值超额收益显著' },
    { name: '动量因子', key: 'momentum', items: ['12-1月收益', '中期趋势'], desc: '经典学术动量' },
    { name: '低波因子', key: 'lowvol', items: ['波动率', 'Beta'], desc: '低波动风险调整收益更优' },
    { name: '成长因子', key: 'growth', items: ['营收增长', '利润增长'], desc: '评估公司成长性' },
    { name: '红利因子', key: 'dividend', items: ['股息率TTM', '分红稳定性'], desc: '高股息长期跑赢大盘' },
    { name: '筹码集中', key: 'concentration', items: ['股东户数变化率'], desc: '股东减少代表筹码集中' },
];

// 因子评分缓存 TTL
const CACHE_TTL_MS = 5 * 60 * 1000;

const FactorPanel = ({
    selectedFactors,
    setSelectedFactors,
    loading,
    setLoading,
    setAlerts,
    customStocks = [],
    setCustomStocks,
    onViewKline,
    onGoToBacktest,
}) => {
    const [factors, setFactors] = useState(DEFAULT_FACTORS);
    const [factorWeights, setFactorWeights] = useState({});
    const [factorScores, setFactorScores] = useState([]);
    const [industryExposure, setIndustryExposure] = useState({});
    const [showAllResults, setShowAllResults] = useState(false);
    const [showWeightPanel, setShowWeightPanel] = useState(false);
    const [lookbackDays, setLookbackDays] = useState(365);
    const [dataRangeInfo, setDataRangeInfo] = useState(null);

    // IC 归因
    const [icData, setIcData] = useState(null);
    const [icLoading, setIcLoading] = useState(false);
    const [showIcSection, setShowIcSection] = useState(false);

    // IC 衰减
    const [icDecayData, setIcDecayData] = useState(null);
    const [icDecayLoading, setIcDecayLoading] = useState(false);
    const [showIcDecay, setShowIcDecay] = useState(false);

    // 因子评分缓存（同参数 5 分钟内不重复请求）
    const factorCacheRef = useRef({ key: '', ts: 0 });

    // 挂载时从后端获取因子定义 + 最新评分快照
    useEffect(() => {
        factorApi.getMeta()
            .then(data => {
                if (data?.cards?.length > 0) {
                    setFactors(data.cards);
                }
                if (data?.weights) {
                    setFactorWeights(data.weights);
                }
            })
            .catch(() => {});

        // 读取最新快照，避免切 Tab 后丢失评分结果
        factorApi.getLatestSnapshot()
            .then(data => {
                if (data?.scores?.length > 0) {
                    setFactorScores(prev => {
                        if (prev.length > 0) return prev; // 已有评分不覆盖
                        return data.scores;
                    });
                }
            })
            .catch(() => {});
    }, []);

    // 因子计算
    const calculateFactors = async () => {
        if (customStocks.length === 0) {
            if (setAlerts) setAlerts([{ type: 'error', msg: '请先添加股票' }]);
            return;
        }

        // 缓存命中检查
        const codes = customStocks.map(s => s.code);
        const cacheKey = JSON.stringify({ codes, lookbackDays, selectedFactors, factorWeights });
        const now = Date.now();
        if (cacheKey === factorCacheRef.current.key && now - factorCacheRef.current.ts < CACHE_TTL_MS && factorScores.length > 0) {
            const remainSec = Math.round((CACHE_TTL_MS - (now - factorCacheRef.current.ts)) / 1000);
            if (setAlerts) setAlerts([{ type: 'info', msg: `参数未变，使用缓存结果（${remainSec}s 后过期，修改参数或等待后重新计算）` }]);
            return;
        }

        if (setLoading) setLoading(true);
        try {
            const { startDate, endDate } = getLookbackRange(lookbackDays);
            const result = await factorApi.calculate(codes, {
                selectedFactors,
                startDate,
                endDate,
                factorWeights: Object.keys(factorWeights).length > 0 ? factorWeights : undefined,
            });
            setFactorScores(result.factor_scores || []);
            setIndustryExposure(result.industry_exposure || {});

            // 更新缓存
            factorCacheRef.current = { key: cacheKey, ts: Date.now() };

            // 数据充足性反馈
            if (result.actual_start_date && result.actual_end_date) {
                const actStart = new Date(result.actual_start_date);
                const actEnd = new Date(result.actual_end_date);
                const requestedDays = lookbackDays;
                const actualDays = Math.round((actEnd - actStart) / 86400000);
                setDataRangeInfo({
                    actualStart: result.actual_start_date,
                    actualEnd: result.actual_end_date,
                    actualDays,
                    requestedDays,
                    sufficient: actualDays >= requestedDays * 0.8,
                });
            }

            if (setAlerts) {
                const newAlerts = [];
                if (result.errors?.length > 0) {
                    result.errors.forEach(err => newAlerts.push({ type: 'warning', msg: err }));
                    newAlerts.push({ type: 'success', msg: `✓ 成功计算 ${result.total} 只股票，但有 ${result.errors.length} 个异常` });
                } else {
                    newAlerts.push({ type: 'success', msg: `✓ 因子计算完成 - 全通过 (${result.total} 只)` });
                }
                setAlerts(newAlerts);
            }
        } catch (e) {
            if (setAlerts) setAlerts([{ type: 'error', msg: `✗ 因子计算失败: ${e.message}` }]);
        }
        if (setLoading) setLoading(false);
    };

    // IC 归因分析
    const runIcAnalysis = async () => {
        setIcLoading(true);
        try {
            const codes = factorScores.length > 0
                ? factorScores.map(s => s.code)
                : [];
            if (codes.length < 10) {
                setIcData({ error: '请先执行因子评估（至少需要 10 只股票）' });
                setIcLoading(false);
                return;
            }
            const { startDate, endDate } = getLookbackRange(lookbackDays);
            const result = await factorApi.icAnalysis(codes, { startDate, endDate });
            setIcData(result);
        } catch (e) {
            setIcData({ error: e.message });
        }
        setIcLoading(false);
    };

    // IC 衰减切换
    const toggleIcDecay = () => {
        setShowIcDecay(v => !v);
        if (!icDecayData && !icDecayLoading) {
            setIcDecayLoading(true);
            factorApi.getIcDecay()
                .then(data => { if (!data.error) setIcDecayData(data); else setAlerts([{ type: 'error', msg: data.error }]); })
                .catch(e => setAlerts([{ type: 'error', msg: `IC衰减加载失败: ${e.message}` }]))
                .finally(() => setIcDecayLoading(false));
        }
    };

    return (
        <div className="space-y-6">
            {/* 标题栏 */}
            <div className="flex items-center justify-between mb-6">
                <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                    <div className="p-2.5 bg-indigo-500/20 rounded-xl border border-indigo-500/30">
                        <Brain className="w-6 h-6 text-indigo-400" />
                    </div>
                    因子深度诊断
                </h2>
            </div>

            {/* 评估对象提示 */}
            <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-3 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm">
                    <span className="text-slate-400">评估对象：</span>
                    {customStocks.length > 0 ? (
                        <span className="text-indigo-300 font-medium">
                            自选池 <span className="text-white font-bold">{customStocks.length}</span> 只股票
                        </span>
                    ) : (
                        <span className="text-amber-400">自选池为空 — 请先在选股器中添加股票</span>
                    )}
                </div>
                <LookbackSelector
                    presets={LOOKBACK_PRESETS}
                    value={lookbackDays}
                    onChange={d => { setLookbackDays(d); setDataRangeInfo(null); }}
                    activeColor="bg-indigo-600"
                />
            </div>

            {/* 数据充足性提示 */}
            {dataRangeInfo && (
                <div className={`text-xs px-3 py-1.5 rounded-lg border flex items-center gap-2 ${
                    dataRangeInfo.sufficient
                        ? 'bg-slate-800/30 border-slate-700/30 text-slate-400'
                        : 'bg-amber-900/20 border-amber-500/30 text-amber-400'
                }`}>
                    <span>实际范围: {dataRangeInfo.actualStart} ~ {dataRangeInfo.actualEnd}</span>
                    <span>({dataRangeInfo.actualDays}天)</span>
                    {!dataRangeInfo.sufficient && (
                        <span className="font-medium">⚠️ 数据不足（请求{dataRangeInfo.requestedDays}天）</span>
                    )}
                </div>
            )}

            {/* 因子卡片 */}
            <FactorCardGrid
                factors={factors}
                selectedFactors={selectedFactors}
                setSelectedFactors={setSelectedFactors}
                factorWeights={factorWeights}
                setFactorWeights={setFactorWeights}
                showWeightPanel={showWeightPanel}
                setShowWeightPanel={setShowWeightPanel}
            />

            {/* 执行评估按钮 */}
            <button onClick={calculateFactors} disabled={loading || customStocks.length === 0}
                className="w-full relative group overflow-hidden bg-gradient-to-r from-purple-600 via-pink-600 to-purple-600 bg-[length:200%_auto] hover:bg-[position:right_center] text-white py-4 rounded-xl font-bold shadow-lg shadow-purple-900/30 transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2">
                <div className="absolute inset-0 bg-white/20 opacity-0 group-hover:opacity-100 transition-opacity"></div>
                {loading ? (
                    <><div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /><span className="tracking-wide text-lg">正在进行量化多因子评分...</span></>
                ) : (
                    <><Filter className="w-5 h-5 group-hover:scale-110 transition-transform" /> <span className="tracking-wider text-lg">执行多因子深度评估</span></>
                )}
            </button>

            {/* 结果区域 */}
            {factorScores.length > 0 && (
                <div className="grid grid-cols-1 xl:grid-cols-3 gap-6 mt-6">
                    <FactorScoreTable
                        factorScores={factorScores}
                        factors={factors}
                        selectedFactors={selectedFactors}
                        customStocks={customStocks}
                        setCustomStocks={setCustomStocks}
                        onViewKline={onViewKline}
                        showAllResults={showAllResults}
                        setShowAllResults={setShowAllResults}
                    />

                    <div className="xl:col-span-1 bg-slate-800/40 backdrop-blur-sm border border-slate-700/50 p-6 rounded-2xl shadow-lg flex flex-col justify-between min-h-[300px]">
                        <h3 className="text-white font-bold flex items-center gap-2 text-md w-full mb-4">
                            <div className="w-1.5 h-1.5 rounded-full bg-pink-400 shadow-[0_0_8px_rgba(244,114,182,0.8)]"></div>
                            行业暴露度
                        </h3>
                        <div className="w-full flex-1 relative bg-slate-900/30 rounded-xl overflow-hidden py-4 border border-slate-700/30">
                            <IndustryExposureChart
                                data={Object.entries(industryExposure || {}).map(([name, info]) => ({
                                    name,
                                    value: typeof info === 'object' ? info.count : info,
                                    stocks: typeof info === 'object' ? info.stocks : []
                                }))}
                            />
                        </div>
                    </div>
                </div>
            )}

            {/* 一键回测快捷入口 */}
            {factorScores.length > 0 && onGoToBacktest && (
                <button onClick={onGoToBacktest}
                    className="w-full bg-gradient-to-r from-amber-600/80 to-orange-600/80 hover:from-amber-500 hover:to-orange-500 text-white py-3 rounded-xl font-bold shadow-lg transition-all flex items-center justify-center gap-2 group">
                    <Zap className="w-5 h-5 group-hover:scale-110 transition-transform" />
                    <span className="tracking-wide">带当前因子配置 → 策略回测</span>
                </button>
            )}

            {/* IC 归因分析 */}
            <IcAnalysisPanel
                icData={icData}
                icLoading={icLoading}
                showIcSection={showIcSection}
                setShowIcSection={setShowIcSection}
                onRunAnalysis={runIcAnalysis}
                setSelectedFactors={setSelectedFactors}
                setFactorWeights={setFactorWeights}
                setShowWeightPanel={setShowWeightPanel}
            />

            {/* IC 衰减曲线 */}
            <IcDecayChart
                icDecayData={icDecayData}
                icDecayLoading={icDecayLoading}
                showIcDecay={showIcDecay}
                onToggle={toggleIcDecay}
            />

            {/* 因子研究（分层回测） */}
            <FactorResearchSection />
        </div>
    );
};

export default FactorPanel;
