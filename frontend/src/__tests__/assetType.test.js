/**
 * 资产类型分类单测
 * 覆盖：classifyAsset / getMarket / getExchange / isValidCode
 * ⚠️ 与后端 test_asset_type.py 镜像，确保前后端分类一致
 */
import { describe, it, expect } from 'vitest';
import {
  classifyAsset, getMarket, getExchange, isValidCode,
  STOCK_PREFIXES, ETF_PREFIXES, BOND_PREFIXES,
} from '../utils/assetType';

describe('classifyAsset', () => {
  it('股票', () => {
    expect(classifyAsset('000001.SZ')).toBe('stock');
    expect(classifyAsset('600519.SH')).toBe('stock');
    expect(classifyAsset('300750.SZ')).toBe('stock');
    expect(classifyAsset('688981.SH')).toBe('stock');
  });

  it('ETF', () => {
    expect(classifyAsset('510050.SH')).toBe('etf');
    expect(classifyAsset('159915.SZ')).toBe('etf');
    expect(classifyAsset('512000.SH')).toBe('etf');
    expect(classifyAsset('561560.SH')).toBe('etf');
  });

  it('可转债', () => {
    expect(classifyAsset('113050.SH')).toBe('bond');
    expect(classifyAsset('123456.SZ')).toBe('bond');
    expect(classifyAsset('110089.SH')).toBe('bond');
  });

  it('期货', () => {
    expect(classifyAsset('IF2506')).toBe('future');
    expect(classifyAsset('rb2510')).toBe('future');
  });

  it('港股通', () => {
    expect(classifyAsset('00700')).toBe('hk_stock');
    expect(classifyAsset('09988')).toBe('hk_stock');
  });

  it('空值 → stock（兜底）', () => {
    expect(classifyAsset('')).toBe('stock');
    expect(classifyAsset(null)).toBe('stock');
    expect(classifyAsset(undefined)).toBe('stock');
  });
});

describe('getMarket', () => {
  it('带后缀优先', () => {
    expect(getMarket('600519.SH')).toBe('沪市');
    expect(getMarket('000001.SZ')).toBe('深市');
    expect(getMarket('830799.BJ')).toBe('北交所');
  });

  it('纯代码推断', () => {
    expect(getMarket('600519')).toBe('沪市');
    expect(getMarket('000001')).toBe('深市');
  });

  it('期货返回交易所', () => {
    expect(getMarket('IF2506')).toBe('CFFEX');
    expect(getMarket('rb2510')).toBe('SHFE');
  });

  it('空值返回空字符串', () => {
    expect(getMarket('')).toBe('');
    expect(getMarket(null)).toBe('');
  });
});

describe('getExchange', () => {
  it('沪市代码 → SH', () => {
    expect(getExchange('600519')).toBe('SH');
    expect(getExchange('510050')).toBe('SH');
  });

  it('深市代码 → SZ', () => {
    expect(getExchange('000001')).toBe('SZ');
    expect(getExchange('300750')).toBe('SZ');
  });

  it('北交所 → BJ', () => {
    expect(getExchange('830799')).toBe('BJ');
    expect(getExchange('430047')).toBe('BJ');
  });

  it('期货 → 具体交易所', () => {
    expect(getExchange('IF2506')).toBe('CFFEX');
    expect(getExchange('cu2510')).toBe('SHFE');
  });
});

describe('isValidCode', () => {
  it('合法股票代码', () => {
    expect(isValidCode('000001', 'stock')).toBe(true);
    expect(isValidCode('600519', 'stock')).toBe(true);
  });

  it('ETF 代码不是股票', () => {
    expect(isValidCode('510050', 'stock')).toBe(false);
  });

  it('合法可转债', () => {
    expect(isValidCode('113050', 'bond')).toBe(true);
  });

  it('无效格式', () => {
    expect(isValidCode('abc')).toBe(false);
    // 5 位纯数字匹配港股通正则，无限定类型时返回 true
    expect(isValidCode('12345')).toBe(true);
    expect(isValidCode('12345', 'stock')).toBe(false);
  });

  it('期货合法性', () => {
    expect(isValidCode('IF2506', 'future')).toBe(true);
    expect(isValidCode('000001', 'future')).toBe(false);
  });
});

describe('前后端常量一致性', () => {
  it('STOCK_PREFIXES 非空', () => {
    expect(STOCK_PREFIXES.length).toBeGreaterThan(0);
    expect(STOCK_PREFIXES).toContain('60');
    expect(STOCK_PREFIXES).toContain('00');
  });

  it('ETF_PREFIXES 非空', () => {
    expect(ETF_PREFIXES.length).toBeGreaterThan(0);
    expect(ETF_PREFIXES).toContain('51');
    expect(ETF_PREFIXES).toContain('15');
  });

  it('BOND_PREFIXES 非空', () => {
    expect(BOND_PREFIXES.length).toBeGreaterThan(0);
    expect(BOND_PREFIXES).toContain('11');
    expect(BOND_PREFIXES).toContain('12');
  });

  it('三类前缀无交叉', () => {
    const all = [...STOCK_PREFIXES, ...ETF_PREFIXES, ...BOND_PREFIXES];
    expect(new Set(all).size).toBe(all.length);
  });
});
