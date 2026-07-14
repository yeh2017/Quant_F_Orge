import { useState, useRef, useEffect, useCallback } from 'react';
import { Filter, Layers, Plus, Trash2, AlertCircle, Search } from 'lucide-react';
import { stockApi, bondApi } from '../../services/api';
import { makePoolItem } from '../../utils/poolActions';
import { isValidCode } from '../../utils/assetType';

// debounce 工具
const useDebounce = (callback, delay) => {
    const timerRef = useRef(null);
    useEffect(() => () => clearTimeout(timerRef.current), []);
    return useCallback((...args) => {
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => callback(...args), delay);
    }, [callback, delay]);
};

const StockPoolPanel = ({
    customStocks,
    setCustomStocks,
    customBonds,
    setCustomBonds,
    setAlerts,
    setLoading,
    loading,
    _dataSource = 'baostock'
}) => {
    const [stockInput, setStockInput] = useState('');
    const [bondInput, setBondInput] = useState('');
    const [inputError, setInputError] = useState('');
    const [bondInputError, setBondInputError] = useState('');


    // 搜索建议状态
    const [stockSuggestions, setStockSuggestions] = useState([]);
    const [bondSuggestions, setBondSuggestions] = useState([]);
    const [showStockDropdown, setShowStockDropdown] = useState(false);
    const [showBondDropdown, setShowBondDropdown] = useState(false);
    const [activeStockIdx, setActiveStockIdx] = useState(-1);
    const [activeBondIdx, setActiveBondIdx] = useState(-1);

    const stockDropdownRef = useRef(null);
    const bondDropdownRef = useRef(null);
    const stockInputRef = useRef(null);
    const bondInputRef = useRef(null);

    // 点击外部关闭下拉
    useEffect(() => {
        const handleClick = (e) => {
            if (stockDropdownRef.current && !stockDropdownRef.current.contains(e.target)) {
                setShowStockDropdown(false);
            }
            if (bondDropdownRef.current && !bondDropdownRef.current.contains(e.target)) {
                setShowBondDropdown(false);
            }
        };
        document.addEventListener('mousedown', handleClick);
        return () => document.removeEventListener('mousedown', handleClick);
    }, []);

    // 股票/ETF 代码格式验证（统一使用 assetType.js）
    const isValidStockCode = (code) => isValidCode(code, 'stock') || isValidCode(code, 'etf');

    // 可转债代码格式验证（统一使用 assetType.js）
    const isValidBondCode = (code) => isValidCode(code, 'bond');

    // 搜索股票
    const searchStocks = useCallback(async (keyword) => {
        if (!keyword || keyword.trim().length < 1) {
            setStockSuggestions([]);
            setShowStockDropdown(false);
            return;
        }
        // 如果包含逗号，说明是批量输入，不搜索
        if (/[,，]/.test(keyword)) {
            setShowStockDropdown(false);
            return;
        }
        try {
            const res = await stockApi.search(keyword.trim());
            setStockSuggestions(res.results || []);
            setShowStockDropdown((res.results || []).length > 0);
            setActiveStockIdx(-1);
        } catch {
            setStockSuggestions([]);
            setShowStockDropdown(false);
        }
    }, []);

    // 搜索可转债
    const searchBonds = useCallback(async (keyword) => {
        if (!keyword || keyword.trim().length < 1) {
            setBondSuggestions([]);
            setShowBondDropdown(false);
            return;
        }
        if (/[,，]/.test(keyword)) {
            setShowBondDropdown(false);
            return;
        }
        try {
            const res = await bondApi.search(keyword.trim());
            setBondSuggestions(res.results || []);
            setShowBondDropdown((res.results || []).length > 0);
            setActiveBondIdx(-1);
        } catch {
            setBondSuggestions([]);
            setShowBondDropdown(false);
        }
    }, []);

    const debouncedSearchStocks = useDebounce(searchStocks, 300);
    const debouncedSearchBonds = useDebounce(searchBonds, 300);

    // 选中股票建议
    const selectStockSuggestion = (stock) => {
        setStockInput(stock.code);
        setShowStockDropdown(false);
        setInputError('');
        stockInputRef.current?.focus();
    };

    // 选中可转债建议
    const selectBondSuggestion = (bond) => {
        setBondInput(bond.code);
        setShowBondDropdown(false);
        setBondInputError('');
        bondInputRef.current?.focus();
    };

    const removeCustomSecurity = (code, type) => {
        if (type === 'stock') setCustomStocks(customStocks.filter(s => s.code !== code));
        else setCustomBonds(customBonds.filter(b => b.code !== code));
        setAlerts([{ type: 'info', msg: `✓ 已移除 ${code}` }]);
    };

    // 添加自定义股票
    const addCustomStock = async () => {
        if (!stockInput.trim()) { setInputError('请输入股票代码或名称搜索'); return; }
        setInputError('');
        setLoading(true);
        setShowStockDropdown(false);

        const codes = stockInput.split(/[,，\s\n]+/).filter(c => c.trim());
        const validStocks = [];
        const invalidCodes = [];

        for (const code of codes) {
            const cleanCode = code.trim();
            if (customStocks.find(s => s.code === cleanCode)) {
                invalidCodes.push({ code: cleanCode, error: '已在列表中' }); continue;
            }
            if (!isValidStockCode(cleanCode)) {
                invalidCodes.push({ code: cleanCode, error: '格式无效(股票:60/00/30/68开头 ETF:51/52/15/16等)' }); continue;
            }
            try {
                const info = await stockApi.getInfo(cleanCode);
                validStocks.push(makePoolItem(cleanCode, info.name || `股票-${cleanCode}`, {
                    industry: info.industry || '',
                }));
            } catch { invalidCodes.push({ code: cleanCode, error: 'API查询失败' }); }
        }

        if (validStocks.length > 0) {
            setCustomStocks([...customStocks, ...validStocks]);
            setStockInput('');
            setAlerts([{ type: 'success', msg: `✓ 成功添加 ${validStocks.length} 只股票` }]);
        }
        if (invalidCodes.length > 0) {
            setInputError(invalidCodes.map(e => `${e.code}: ${e.error}`).join('; '));
        }
        setLoading(false);
    };

    // 添加可转债
    const addCustomBond = async () => {
        if (!bondInput.trim()) { setBondInputError('请输入可转债代码或名称搜索'); return; }
        setBondInputError('');
        setLoading(true);
        setShowBondDropdown(false);

        const codes = bondInput.split(/[,，\s\n]+/).filter(c => c.trim());
        const validBonds = [];
        const invalidCodes = [];

        for (const code of codes) {
            const cleanCode = code.trim();
            if (customBonds.find(b => b.code === cleanCode)) {
                invalidCodes.push({ code: cleanCode, error: '已在列表中' }); continue;
            }
            if (!isValidBondCode(cleanCode)) {
                invalidCodes.push({ code: cleanCode, error: '格式无效(可转债:10/11/12/13/40开头)' }); continue;
            }
            try {
                const info = await bondApi.getInfo(cleanCode);
                validBonds.push(makePoolItem(cleanCode, info.name || `转债-${cleanCode}`, {
                    underlyingStock: info.underlying_stock || info.underlying_name || '未知',
                    underlyingCode: info.underlying_code || '',
                    rating: info.rating || '-',
                }));
            } catch { invalidCodes.push({ code: cleanCode, error: 'API查询失败' }); }
        }

        if (invalidCodes.length > 0) {
            setBondInputError(invalidCodes.map(e => `${e.code}: ${e.error}`).join('; '));
        }
        if (validBonds.length > 0) {
            setCustomBonds([...customBonds, ...validBonds]);
            setBondInput('');
            setAlerts([{ type: 'success', msg: `✓ 成功添加 ${validBonds.length} 只可转债` }]);
        }
        setLoading(false);
    };

    // 键盘导航
    const handleStockKeyDown = (e) => {
        if (!showStockDropdown || stockSuggestions.length === 0) {
            if (e.key === 'Enter') addCustomStock();
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveStockIdx(prev => Math.min(prev + 1, stockSuggestions.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveStockIdx(prev => Math.max(prev - 1, 0));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeStockIdx >= 0) selectStockSuggestion(stockSuggestions[activeStockIdx]);
            else addCustomStock();
        } else if (e.key === 'Escape') {
            setShowStockDropdown(false);
        }
    };

    const handleBondKeyDown = (e) => {
        if (!showBondDropdown || bondSuggestions.length === 0) {
            if (e.key === 'Enter') addCustomBond();
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActiveBondIdx(prev => Math.min(prev + 1, bondSuggestions.length - 1));
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveBondIdx(prev => Math.max(prev - 1, 0));
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (activeBondIdx >= 0) selectBondSuggestion(bondSuggestions[activeBondIdx]);
            else addCustomBond();
        } else if (e.key === 'Escape') {
            setShowBondDropdown(false);
        }
    };


    // 下拉建议列表组件
    const SuggestionDropdown = ({ suggestions, activeIdx, onSelect, type }) => (
        <div className="absolute top-full left-0 right-0 mt-1 bg-slate-800 border border-slate-600 rounded-lg shadow-2xl z-50 max-h-[240px] overflow-y-auto">
            {suggestions.map((item, idx) => {
                const isDelisted = item.listed === false;
                return (
                <div
                    key={item.code}
                    onMouseDown={(e) => { e.preventDefault(); onSelect(item); }}
                    className={`flex items-center justify-between px-4 py-2.5 cursor-pointer transition-colors ${
                        isDelisted ? 'opacity-60' : ''
                    } ${idx === activeIdx
                        ? 'bg-blue-600/40 text-white'
                        : 'text-slate-300 hover:bg-slate-700/80 hover:text-white'
                        }`}
                >
                    <div className="flex items-center gap-3">
                        <span className={`font-mono font-bold text-sm tracking-wider ${isDelisted ? 'line-through text-slate-500' : ''}`}>{item.code}</span>
                        <span className={`text-sm ${isDelisted ? 'text-slate-500' : ''}`}>{item.name}</span>
                        {isDelisted && <span className="text-[10px] px-1 py-0.5 rounded bg-red-900/40 text-red-400 border border-red-800/30">已退市</span>}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-slate-500">
                        {type === 'stock' && item.industry && item.industry !== '未知' && (
                            <span className="bg-slate-700/60 px-2 py-0.5 rounded">{item.industry}</span>
                        )}
                        {type === 'bond' && (item.underlyingStock || item.underlying_stock) && (item.underlyingStock || item.underlying_stock) !== '未知' && (
                            <span className="bg-purple-900/40 text-purple-300 px-2 py-0.5 rounded">正股: {item.underlyingStock || item.underlying_stock}</span>
                        )}
                    </div>
                </div>
                );
            })}
        </div>
    );

    return (
        <div className="space-y-6 mt-6">
            {/* 股票输入 */}
            <div className="bg-gradient-to-br from-blue-900/40 to-indigo-900/20 p-6 rounded-xl border border-blue-500/30 shadow-lg shadow-blue-900/20 backdrop-blur-sm transition-all hover:border-blue-500/50">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-white font-bold flex items-center gap-2 text-lg">
                        <div className="p-2 bg-blue-500/20 rounded-lg">
                            <Filter className="w-5 h-5 text-blue-400" />
                        </div>
                        自定义股票池（真实数据查询）
                    </h3>
                    <div className="flex items-center gap-2">
                        <span className="text-xs bg-blue-900/50 text-blue-300 px-3 py-1 rounded-full border border-blue-500/30">
                            {customStocks.length} 只标的
                        </span>
                        {customStocks.length > 0 && (
                            <button onClick={() => setCustomStocks([])}
                                className="text-xs px-2 py-1 rounded-lg bg-red-900/30 text-red-400 border border-red-500/30 hover:bg-red-900/50 transition-all">
                                清空
                            </button>
                        )}
                    </div>
                </div>

                <div className="flex gap-3 mb-2">
                    <div className="relative flex-1" ref={stockDropdownRef}>
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                            <input ref={stockInputRef} type="text" value={stockInput}
                                onChange={(e) => { setStockInput(e.target.value); setInputError(''); debouncedSearchStocks(e.target.value); }}
                                onKeyDown={handleStockKeyDown}
                                onFocus={() => stockSuggestions.length > 0 && setShowStockDropdown(true)}
                                placeholder={'输入代码或名称搜索，如: 600519, 茅台 (支持批量逗号分隔)'}
                                className={`w-full bg-slate-900/80 text-white pl-10 pr-4 py-3 rounded-lg border ${inputError ? 'border-red-500 focus:ring-red-500/20' : 'border-blue-500/30 focus:border-blue-400 focus:ring-blue-400/20'} focus:outline-none focus:ring-2 transition-all shadow-inner`} />
                        </div>
                        {showStockDropdown && stockSuggestions.length > 0 && (
                            <SuggestionDropdown suggestions={stockSuggestions} activeIdx={activeStockIdx} onSelect={selectStockSuggestion} type="stock" />
                        )}
                    </div>
                    <button onClick={addCustomStock} disabled={loading}
                        className="px-6 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white rounded-lg font-semibold transition-all flex items-center gap-2 shadow-lg shadow-blue-900/30 disabled:opacity-60 disabled:cursor-not-allowed min-w-[120px] justify-center group">
                        {loading && stockInput.trim() ? (
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        ) : (
                            <><Plus className="w-5 h-5 group-hover:scale-110 transition-transform" /> 添加</>
                        )}
                    </button>
                </div>

                {/* 错误提示 */}
                <div className={`overflow-hidden transition-all duration-300 ${inputError ? 'max-h-12 mt-2 opacity-100' : 'max-h-0 opacity-0'}`}>
                    <div className="flex items-center gap-1.5 text-red-400 text-sm bg-red-900/20 py-2 px-3 rounded border border-red-900/50">
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        <span className="truncate">{inputError}</span>
                    </div>
                </div>

                {/* 列表区域 */}
                <div className="mt-5">
                    {customStocks.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[280px] overflow-y-auto pr-2">
                            {customStocks.map((stock, idx) => (
                                <div key={idx} className={`group relative p-4 rounded-xl border transition-all shadow-sm flex flex-col gap-2 overflow-hidden ${stock.isKnown ? 'bg-slate-800/60 hover:bg-slate-750 border-slate-700/50 hover:border-blue-500/50 hover:shadow-blue-900/20' : 'bg-yellow-900/20 border-yellow-700/50 hover:border-yellow-500/50'}`}>
                                    <div className={`absolute left-0 top-0 bottom-0 w-1 opacity-60 group-hover:opacity-100 transition-opacity ${stock.isKnown ? 'bg-gradient-to-b from-blue-500 to-indigo-500' : 'bg-yellow-500'}`} />
                                    <div className="flex justify-between items-start pl-2">
                                        <div className="flex items-center gap-2">
                                            <span className="text-xl font-black text-white tracking-wider">{stock.code}</span>
                                            <span className={`text-sm font-medium px-2 py-0.5 rounded border ${stock.isKnown ? 'text-blue-200 bg-blue-900/40 border-blue-800/50' : 'text-yellow-200 bg-yellow-900/40 border-yellow-800/50'}`}>
                                                {stock.name}
                                            </span>
                                        </div>
                                        <button onClick={() => removeCustomSecurity(stock.code, 'stock')}
                                            className="text-slate-500 hover:text-red-400 hover:bg-red-900/20 p-1.5 rounded-lg transition-colors" title="移除">
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                    <div className="flex items-center gap-3 pl-2 mt-1">
                                        {stock.type === 'etf' ? (
                                            <div className="flex items-center gap-1 text-xs text-slate-400">
                                                <div className="w-1.5 h-1.5 rounded-full bg-cyan-400"></div>
                                                <span className="text-cyan-300 font-medium">ETF</span>
                                            </div>
                                        ) : stock.industry && stock.industry !== '未知' ? (
                                            <div className="flex items-center gap-1 text-xs text-slate-400">
                                                <div className="w-1.5 h-1.5 rounded-full bg-indigo-400"></div>
                                                行业: <span className="text-slate-300">{stock.industry}</span>
                                            </div>
                                        ) : null}
                                        {stock.market && stock.market !== '未知' && (
                                            <div className="flex items-center gap-1 text-xs text-slate-400">
                                                <div className="w-1.5 h-1.5 rounded-full bg-teal-400"></div>
                                                市场: <span className="text-slate-300 uppercase">{stock.market}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-10 px-4 bg-slate-800/30 rounded-xl border border-dashed border-slate-700/70 text-slate-500">
                            <Filter className="w-12 h-12 mb-3 text-slate-600 opacity-50" />
                            <p className="text-sm font-medium">暂无自定义股票标的</p>
                            <p className="text-xs mt-1 text-slate-600">输入代码或名称搜索并添加</p>
                        </div>
                    )}
                </div>
            </div>

            {/* 可转债输入 */}
            <div className="bg-gradient-to-br from-purple-900/40 to-pink-900/20 p-6 rounded-xl border border-purple-500/30 shadow-lg shadow-purple-900/20 backdrop-blur-sm transition-all hover:border-purple-500/50">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-white font-bold flex items-center gap-2 text-lg">
                        <div className="p-2 bg-purple-500/20 rounded-lg">
                            <Layers className="w-5 h-5 text-purple-400" />
                        </div>
                        自定义可转债池
                    </h3>
                    <div className="flex items-center gap-2">
                        <span className="text-xs bg-purple-900/50 text-purple-300 px-3 py-1 rounded-full border border-purple-500/30">
                            {customBonds.length} 只标的
                        </span>
                        {customBonds.length > 0 && (
                            <button onClick={() => setCustomBonds([])}
                                className="text-xs px-2 py-1 rounded-lg bg-red-900/30 text-red-400 border border-red-500/30 hover:bg-red-900/50 transition-all">
                                清空
                            </button>
                        )}
                    </div>
                </div>

                <div className="flex gap-3 mb-2">
                    <div className="relative flex-1" ref={bondDropdownRef}>
                        <div className="relative">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
                            <input ref={bondInputRef} type="text" value={bondInput}
                                onChange={(e) => { setBondInput(e.target.value); setBondInputError(''); debouncedSearchBonds(e.target.value); }}
                                onKeyDown={handleBondKeyDown}
                                onFocus={() => bondSuggestions.length > 0 && setShowBondDropdown(true)}
                                placeholder="输入代码或名称搜索，如: 113050, 南银 (支持批量逗号分隔)"
                                className={`w-full bg-slate-900/80 text-white pl-10 pr-4 py-3 rounded-lg border ${bondInputError ? 'border-red-500 focus:ring-red-500/20' : 'border-purple-500/30 focus:border-purple-400 focus:ring-purple-400/20'} focus:outline-none focus:ring-2 transition-all shadow-inner`} />
                        </div>
                        {showBondDropdown && bondSuggestions.length > 0 && (
                            <SuggestionDropdown suggestions={bondSuggestions} activeIdx={activeBondIdx} onSelect={selectBondSuggestion} type="bond" />
                        )}
                    </div>
                    <button onClick={addCustomBond} disabled={loading}
                        className="px-6 py-3 bg-gradient-to-r from-purple-600 to-pink-600 hover:from-purple-500 hover:to-pink-500 text-white rounded-lg font-semibold transition-all flex items-center gap-2 shadow-lg shadow-purple-900/30 disabled:opacity-60 disabled:cursor-not-allowed min-w-[120px] justify-center group">
                        {loading && bondInput.trim() ? (
                            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        ) : (
                            <><Plus className="w-5 h-5 group-hover:scale-110 transition-transform" /> 添加</>
                        )}
                    </button>
                </div>

                {/* 错误提示 */}
                <div className={`overflow-hidden transition-all duration-300 ${bondInputError ? 'max-h-12 mt-2 opacity-100' : 'max-h-0 opacity-0'}`}>
                    <div className="flex items-center gap-1.5 text-red-400 text-sm bg-red-900/20 py-2 px-3 rounded border border-red-900/50">
                        <AlertCircle className="w-4 h-4 shrink-0" />
                        <span className="truncate">{bondInputError}</span>
                    </div>
                </div>

                {/* 列表区域 */}
                <div className="mt-5">
                    {customBonds.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[280px] overflow-y-auto pr-2">
                            {customBonds.map((bond, idx) => (
                                <div key={idx} className="group relative p-4 bg-slate-800/60 hover:bg-slate-750 rounded-xl border border-slate-700/50 hover:border-purple-500/50 transition-all shadow-sm hover:shadow-purple-900/20 flex flex-col gap-2 overflow-hidden">
                                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-purple-500 to-pink-500 opacity-60 group-hover:opacity-100 transition-opacity" />
                                    <div className="flex justify-between items-start pl-2">
                                        <div className="flex items-center gap-2">
                                            <span className="text-xl font-black text-white tracking-wider">{bond.code}</span>
                                            <span className="text-sm font-medium text-purple-200 bg-purple-900/40 px-2 py-0.5 rounded border border-purple-800/50">{bond.name}</span>
                                        </div>
                                        <button onClick={() => removeCustomSecurity(bond.code, 'bond')}
                                            className="text-slate-500 hover:text-red-400 hover:bg-red-900/20 p-1.5 rounded-lg transition-colors" title="移除">
                                            <Trash2 className="w-4 h-4" />
                                        </button>
                                    </div>
                                    <div className="flex items-center gap-3 pl-2 mt-1">
                                        <div className="flex items-center gap-1 text-xs text-slate-400">
                                            <div className="w-1.5 h-1.5 rounded-full bg-blue-400"></div>
                                            正股: <span className="text-slate-300">{bond.underlyingStock || '未知'}</span>
                                        </div>
                                        {bond.rating && bond.rating !== '-' && (
                                            <div className="flex items-center gap-1 text-xs text-slate-400">
                                                <div className="w-1.5 h-1.5 rounded-full bg-yellow-400"></div>
                                                评级: <span className="text-yellow-300 font-bold">{bond.rating}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="flex flex-col items-center justify-center py-10 px-4 bg-slate-800/30 rounded-xl border border-dashed border-slate-700/70 text-slate-500">
                            <Layers className="w-12 h-12 mb-3 text-slate-600 opacity-50" />
                            <p className="text-sm font-medium">暂无自定义可转债标的</p>
                            <p className="text-xs mt-1 text-slate-600">输入代码或名称搜索并添加</p>
                        </div>
                    )}
                </div>


            </div>
        </div>
    );
};

export default StockPoolPanel;
