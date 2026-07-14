/**
 * 资产类型分类 — 唯一来源（Single Source of Truth）
 * 所有前端模块只调此处的函数/常量来判断资产类型。
 * 新增资产类型时，只需修改此文件。
 *
 * ⚠️ 后端镜像: backend/utils/asset_type.py
 *    两文件常量必须严格同步，修改一方时务必同步另一方。
 */

// ── A 股代码前缀 ──
export const BOND_PREFIXES = ['10', '11', '12', '13', '40'];
export const ETF_PREFIXES = ['51', '52', '58', '15', '16', '56'];
export const STOCK_PREFIXES = ['60', '00', '30', '68'];

// ── 港股通 / 期货正则 ──
export const HK_PATTERN = /^\d{5}$/;                     // 港股通: 00700
export const FUTURE_PATTERN = /^[A-Za-z]{1,2}\d{3,4}$/;  // 期货: IF2506, rb2510

// ── 期货品种 → 交易所映射 ──
const FUTURE_EXCHANGES = {
  // 中金所 (CFFEX)
  IF: 'CFFEX', IC: 'CFFEX', IM: 'CFFEX', IH: 'CFFEX',
  TS: 'CFFEX', TF: 'CFFEX', T: 'CFFEX',
  // 上期所 (SHFE)
  rb: 'SHFE', hc: 'SHFE', cu: 'SHFE', al: 'SHFE',
  zn: 'SHFE', pb: 'SHFE', ni: 'SHFE', sn: 'SHFE',
  au: 'SHFE', ag: 'SHFE', bu: 'SHFE', ru: 'SHFE',
  fu: 'SHFE', sp: 'SHFE', ss: 'SHFE', wr: 'SHFE',
  // 大商所 (DCE)
  i: 'DCE', j: 'DCE', jm: 'DCE', m: 'DCE',
  y: 'DCE', p: 'DCE', c: 'DCE', cs: 'DCE',
  a: 'DCE', b: 'DCE', jd: 'DCE', l: 'DCE',
  v: 'DCE', pp: 'DCE', eg: 'DCE', eb: 'DCE',
  pg: 'DCE', lh: 'DCE',
  // 郑商所 (CZCE)
  CF: 'CZCE', SR: 'CZCE', TA: 'CZCE', MA: 'CZCE',
  OI: 'CZCE', RM: 'CZCE', FG: 'CZCE', SA: 'CZCE',
  AP: 'CZCE', CJ: 'CZCE', PK: 'CZCE', UR: 'CZCE',
  SF: 'CZCE', SM: 'CZCE', ZC: 'CZCE', PF: 'CZCE',
  // 上海国际能源 (INE)
  sc: 'INE', nr: 'INE', lu: 'INE', bc: 'INE',
};

/**
 * 根据代码特征判断资产类型
 * @param {string} code - 标的代码（带或不带后缀）
 * @returns {'stock' | 'etf' | 'bond' | 'hk_stock' | 'future'}
 */
export function classifyAsset(code) {
  const raw = (code || '').split('.')[0];
  if (FUTURE_PATTERN.test(raw)) return 'future';
  if (HK_PATTERN.test(raw)) return 'hk_stock';
  const prefix = raw.substring(0, 2);
  if (BOND_PREFIXES.includes(prefix)) return 'bond';
  if (ETF_PREFIXES.includes(prefix)) return 'etf';
  return 'stock';
}

export const ASSET_TYPE_LABELS = {
  stock: '股票', etf: 'ETF', bond: '可转债',
  hk_stock: '港股通', future: '期货',
};

/**
 * 期货品种代码 → 交易所
 */
function futureExchange(code) {
  const raw = (code || '').split('.')[0];
  const m = raw.match(/^[A-Za-z]+/);
  if (!m) return '';
  const symbol = m[0];
  return FUTURE_EXCHANGES[symbol] || FUTURE_EXCHANGES[symbol.toUpperCase()] || '';
}

/**
 * 根据代码推导交易所/市场名称
 * @param {string} code - 带后缀的代码（如 600519.SH）或纯代码
 * @returns {string} '沪市' | '深市' | '北交所' | '港交所' | 交易所缩写 | ''
 */
export function getMarket(code) {
  if (!code) return '';
  // 优先用后缀判断
  if (code.endsWith('.SH')) return '沪市';
  if (code.endsWith('.SZ')) return '深市';
  if (code.endsWith('.BJ')) return '北交所';
  if (code.endsWith('.HK')) return '港交所';
  const pure = code.replace(/\.\w+$/, '');
  // 期货
  if (FUTURE_PATTERN.test(pure)) return futureExchange(pure) || '期货';
  // 港股通
  if (HK_PATTERN.test(pure)) return '港交所';
  // A 股
  if (/^(6|51|52|58|10|11)/.test(pure)) return '沪市';
  if (/^(00|30|15|16|56|12|13)/.test(pure)) return '深市';
  if (/^(83|87|43)/.test(pure)) return '北交所';
  return '';
}

/**
 * 根据代码推导交易所缩写（与后端 get_exchange() 同构）
 * @returns {'SH'|'SZ'|'BJ'|'HK'|'CFFEX'|'SHFE'|'DCE'|'CZCE'|'INE'|''}
 */
export function getExchange(code) {
  const pure = (code || '').split('.')[0];
  if (!pure) return '';
  if (FUTURE_PATTERN.test(pure)) return futureExchange(pure);
  if (HK_PATTERN.test(pure)) return 'HK';
  if (/^(83|87|43)/.test(pure)) return 'BJ';
  if (/^(6|51|52|58|10|11)/.test(pure)) return 'SH';
  return 'SZ';
}

/**
 * 校验代码格式是否合法
 * @param {string} code - 纯代码
 * @param {'stock'|'bond'|'hk_stock'|'future'} [type] - 限定校验类型
 */
export function isValidCode(code, type) {
  const pure = (code || '').replace(/\.\w+$/, '');
  // 期货
  if (type === 'future') return FUTURE_PATTERN.test(pure);
  if (FUTURE_PATTERN.test(pure)) return !type; // 无限定类型时，期货也合法
  // 港股通
  if (type === 'hk_stock') return HK_PATTERN.test(pure);
  if (HK_PATTERN.test(pure)) return !type;
  // A 股体系：6 位纯数字
  if (!/^\d{6}$/.test(pure)) return false;
  const prefix = pure.substring(0, 2);
  if (type === 'stock') return STOCK_PREFIXES.includes(prefix);
  if (type === 'bond') return BOND_PREFIXES.includes(prefix);
  return [...STOCK_PREFIXES, ...ETF_PREFIXES, ...BOND_PREFIXES].includes(prefix);
}

