/**
 * 数值格式化单测
 * 覆盖：fmtNum / fmtPct / fmtChg / pctColor / fmtAmount / makeAlert
 */
import { describe, it, expect } from 'vitest';
import { fmtNum, fmtPct, fmtChg, pctColor, pnlColor, fmtAmount, makeAlert } from '../utils/format';

describe('fmtNum', () => {
  it('正常格式化', () => {
    expect(fmtNum(3.14159, 2)).toBe('3.14');
    expect(fmtNum(100, 0)).toBe('100');
  });

  it('带后缀', () => {
    expect(fmtNum(1.5, 2, '%')).toBe('1.50%');
  });

  it('null/undefined 返回 fallback', () => {
    expect(fmtNum(null)).toBe('--');
    expect(fmtNum(undefined)).toBe('--');
    expect(fmtNum(null, 2, '', 'N/A')).toBe('N/A');
  });

  it('NaN 字符串返回 fallback', () => {
    expect(fmtNum('abc')).toBe('--');
  });

  it('空字符串 Number("") === 0，返回 0.00', () => {
    expect(fmtNum('')).toBe('0.00');
  });

  it('字符串数字正常转换', () => {
    expect(fmtNum('3.14', 1)).toBe('3.1');
  });

  it('0 不是 null', () => {
    expect(fmtNum(0, 2)).toBe('0.00');
  });
});

describe('fmtPct', () => {
  it('自动加 %', () => {
    expect(fmtPct(12.345)).toBe('12.35%');
  });

  it('null → --', () => {
    expect(fmtPct(null)).toBe('--');
  });
});

describe('fmtChg', () => {
  it('正数带 +', () => {
    expect(fmtChg(1.23)).toBe('+1.23%');
  });

  it('负数带 -', () => {
    expect(fmtChg(-0.45)).toBe('-0.45%');
  });

  it('零不带符号', () => {
    expect(fmtChg(0)).toBe('0.00%');
  });

  it('null → --', () => {
    expect(fmtChg(null)).toBe('--');
  });
});

describe('pctColor / pnlColor', () => {
  it('正数 → 红色', () => {
    expect(pctColor(1)).toBe('text-red-400');
    expect(pnlColor(0.05)).toBe('text-red-400');
  });

  it('负数 → 绿色', () => {
    expect(pctColor(-1)).toBe('text-green-400');
    expect(pnlColor(-0.03)).toBe('text-green-400');
  });

  it('零 → 灰色', () => {
    expect(pctColor(0)).toBe('text-slate-400');
  });

  it('null → 灰色', () => {
    expect(pctColor(null)).toBe('text-slate-400');
    expect(pnlColor(null)).toBe('text-slate-400');
  });
});

describe('fmtAmount', () => {
  it('亿级', () => {
    expect(fmtAmount(123456789)).toBe('1.2亿');
    expect(fmtAmount(1e8)).toBe('1.0亿');
  });

  it('万级', () => {
    expect(fmtAmount(12345)).toBe('1万');
    expect(fmtAmount(99999)).toBe('10万');
  });

  it('小数值原样', () => {
    expect(fmtAmount(999)).toBe('999');
  });

  it('负数保留符号', () => {
    expect(fmtAmount(-2e8)).toBe('-2.0亿');
    expect(fmtAmount(-50000)).toBe('-5万');
  });

  it('null/undefined → --', () => {
    expect(fmtAmount(null)).toBe('--');
    expect(fmtAmount(undefined)).toBe('--');
  });

  it('0 → 0', () => {
    expect(fmtAmount(0)).toBe('0');
  });
});

describe('makeAlert', () => {
  it('success 带 ✓ 前缀', () => {
    const a = makeAlert('success', '操作完成');
    expect(a.type).toBe('success');
    expect(a.msg).toContain('✓');
    expect(a.msg).toContain('操作完成');
  });

  it('error 带 ✗ 前缀', () => {
    const a = makeAlert('error', '失败了');
    expect(a.msg).toContain('✗');
  });

  it('未知类型不崩溃', () => {
    const a = makeAlert('custom', 'test');
    expect(a.type).toBe('custom');
    expect(a.msg).toContain('test');
  });
});
