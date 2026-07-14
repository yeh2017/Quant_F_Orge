// 智能选股器 — 策略模板统一定义
// StockTab 读 filters（筛选条件预填）
// FactorSignals 仅读 DEFAULT_WEIGHTS（均衡预设）

export const EMPTY_FILTERS = {
    pe_max: '', pb_max: '', roe_min: '',
    revenue_yoy_min: '', net_profit_yoy_min: '',
    turnover_rate_min: '', net_inflow_min: '',
    pct_chg_min: '', pct_chg_max: '', gap_up: false,
    holder_chg_max: '', max_list_days: '', volume_ratio_min: '',
    has_block_trade: false, has_unlock: false, has_top_list: false,
    margin_chg_min: '',
};

// FactorSignals 默认因子权重（SSOT）
export const DEFAULT_WEIGHTS = {
    reversal: 0.23, value: 0.17, quality: 0.19, size: 0.12,
    momentum: 0.10, lowvol: 0.08, growth: 0.05, dividend: 0.05,
    concentration: 0.01, leverage: 0.08,
};

export const STRATEGY_TEMPLATES = [
    // ── 基本面驱动（长周期） ──
    { key: 'value', icon: '💎', name: '价值型',
      desc: '低估值 + 高盈利', color: 'amber', freq: '季报',
      filters: { ...EMPTY_FILTERS, pe_max: '25', pb_max: '3', roe_min: '12' } },
    { key: 'growth', icon: '🚀', name: '成长型',
      desc: '高增长 + 高换手', color: 'emerald', freq: '季报',
      filters: { ...EMPTY_FILTERS, roe_min: '8', revenue_yoy_min: '20', net_profit_yoy_min: '15', turnover_rate_min: '2' } },
    { key: 'dividend', icon: '🏆', name: '红利低波',
      desc: '低估值 + 筹码集中', color: 'sky', freq: '季报',
      filters: { ...EMPTY_FILTERS, pe_max: '20', pb_max: '2', roe_min: '10', holder_chg_max: '-5' } },
    { key: 'concentration', icon: '🧲', name: '筹码集中',
      desc: '股东锐减 + 盈利稳健', color: 'violet', freq: '季报',
      filters: { ...EMPTY_FILTERS, pe_max: '30', roe_min: '8', holder_chg_max: '-10' } },

    // ── 事件驱动（周级） ──
    { key: 'event', icon: '🎯', name: '事件博弈',
      desc: '龙虎榜+大宗交易', color: 'indigo', freq: '当日',
      filters: { ...EMPTY_FILTERS, has_top_list: true, has_block_trade: true, pe_max: '40' } },
    { key: 'unlock', icon: '🔓', name: '解禁窗口',
      desc: '解禁后超跌博弈', color: 'purple', freq: '当日',
      filters: { ...EMPTY_FILTERS, has_unlock: true, pct_chg_max: '-2' } },

    // ── 技术面/资金面驱动（短周期） ──
    { key: 'oversold', icon: '📉', name: '超跌反弹',
      desc: '近期超跌 + 基本面健康', color: 'teal', freq: '当日',
      filters: { ...EMPTY_FILTERS, pct_chg_max: '-3', roe_min: '5', pe_max: '40', pb_max: '5' } },
    { key: 'fund', icon: '💰', name: '资金驱动',
      desc: '主力资金 + 高换手', color: 'orange', freq: '当日',
      filters: { ...EMPTY_FILTERS, pe_max: '40', net_inflow_min: '500', turnover_rate_min: '3', volume_ratio_min: '1' } },
    { key: 'anomaly', icon: '⚡', name: '异动捕捉',
      desc: '强势股 + 放量突破', color: 'rose', freq: '当日',
      filters: { ...EMPTY_FILTERS, turnover_rate_min: '3', pct_chg_min: '3', gap_up: true, volume_ratio_min: '1.5' } },
    { key: 'subnew', icon: '🆕', name: '次新股',
      desc: '上市≤1年', color: 'pink', freq: '季报',
      filters: { ...EMPTY_FILTERS, max_list_days: '365' } },
];
