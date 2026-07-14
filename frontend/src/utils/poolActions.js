/**
 * 自选池统一添加逻辑 — 单一入口
 * 所有面板的"加入自选"都应调用此函数，确保字段完整性一致
 */
import { stockApi, bondApi } from '../services/api';
import { classifyAsset, getMarket } from './assetType';

/**
 * 构建完整的自选池 item（调 API 补全详情）
 * @param {string} code   - 证券代码
 * @param {string} [name] - 名称（可选，兜底用）
 * @param {object} [knownFields] - 已知字段（如 industry/market/category），有则不再调 API
 * @returns {Promise<{item: object, assetType: string}>}
 */
export async function buildPoolItem(code, name = '', knownFields = {}) {
  const assetType = classifyAsset(code);
  const base = {
    code,
    name: name || code,
    type: assetType,
    market: getMarket(code),
    addedAt: new Date().toLocaleTimeString(),
  };

  // 已有完整字段时跳过 API 调用（如 ResultTable 数据源自带）
  if (assetType === 'bond') {
    if (knownFields.underlyingStock) {
      return { item: { ...base, isKnown: true, ...knownFields }, assetType };
    }
    try {
      const info = await bondApi.getInfo(code);
      return {
        item: {
          ...base,
          name: info?.name || base.name,
          isKnown: !!info?.name,
          underlyingStock: info?.underlying_stock || '未知',
          underlyingCode: info?.underlying_code || '',
          rating: info?.rating || '-',
        },
        assetType,
      };
    } catch {
      return { item: { ...base, isKnown: false, underlyingStock: '未知', underlyingCode: '', rating: '-' }, assetType };
    }
  }

  // stock / etf
  if (knownFields.industry) {
    return { item: { ...base, isKnown: true, ...knownFields }, assetType };
  }
  try {
    const info = await stockApi.getInfo(code);
    return {
      item: {
        ...base,
        name: info?.name || base.name,
        isKnown: !!info?.name,
        industry: info?.industry || '',
      },
      assetType,
    };
  } catch {
    return { item: { ...base, isKnown: false, industry: '' }, assetType };
  }
}

/**
 * 添加到自选池（统一入口）
 * @param {string} code
 * @param {string} name
 * @param {object} knownFields - 已知字段，避免重复 API 调用
 * @param {Function} setCustomStocks
 * @param {Function} setCustomBonds
 */
export async function addToPool(code, name, knownFields, setCustomStocks, setCustomBonds) {
  const { item, assetType } = await buildPoolItem(code, name, knownFields);
  if (assetType === 'bond' && setCustomBonds) {
    setCustomBonds(prev => [...prev, item]);
  } else if (setCustomStocks) {
    setCustomStocks(prev => [...prev, item]);
  }
  return item;
}

/**
 * 从自选池移除（统一入口，自动按资产类型分流）
 */
export function removeFromPool(code, setCustomStocks, setCustomBonds) {
  const assetType = classifyAsset(code);
  if (assetType === 'bond' && setCustomBonds) {
    setCustomBonds(prev => prev.filter(s => s.code !== code));
  } else if (setCustomStocks) {
    setCustomStocks(prev => prev.filter(s => s.code !== code));
  }
}

/**
 * 同步构建 item（数据源已自带字段时使用，不调 API）
 */
export function makePoolItem(code, name, extraFields = {}) {
  const assetType = classifyAsset(code);
  return {
    code,
    name: name || code,
    type: assetType,
    isKnown: !!name,
    addedAt: new Date().toLocaleTimeString(),
    ...extraFields,
    // 始终从代码推断市场，不依赖调用方传值
    market: getMarket(code),
  };
}
