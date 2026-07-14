import { useState } from 'react';

/**
 * 回看周期选择器 — pill 按钮 + 自定义天数输入
 *
 * @param {Array} presets - [{days, label}] 预设选项
 * @param {number} value - 当前选中的天数
 * @param {function} onChange - (days: number) => void
 * @param {string} activeColor - 选中态 Tailwind 类，如 'bg-indigo-600'
 * @param {string} unit - 显示单位，默认 '天'
 */
const LookbackSelector = ({
    presets,
    value,
    onChange,
    activeColor = 'bg-indigo-600',
    unit = '天',
}) => {
    const [customInput, setCustomInput] = useState('');
    const [showInput, setShowInput] = useState(false);

    const isPreset = presets.some(p => p.days === value);

    const handleCustomSubmit = () => {
        const n = parseInt(customInput, 10);
        if (n > 0 && n <= 3650) {
            onChange(n);
            setShowInput(false);
        }
    };

    return (
        <div className="flex items-center gap-1">
            <span className="text-xs text-slate-500 mr-1">回看：</span>
            {presets.map(p => (
                <button key={p.days} onClick={() => { onChange(p.days); setShowInput(false); setCustomInput(''); }}
                    className={`px-2 py-0.5 rounded text-xs font-medium transition-all ${
                        value === p.days
                            ? `${activeColor} text-white`
                            : 'bg-slate-700/50 text-slate-400 hover:text-white'
                    }`}>{p.label}</button>
            ))}
            {showInput ? (
                <input
                    type="number"
                    min="1"
                    max="3650"
                    value={customInput}
                    onChange={e => setCustomInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleCustomSubmit(); if (e.key === 'Escape') setShowInput(false); }}
                    onBlur={() => { if (customInput) handleCustomSubmit(); else setShowInput(false); }}
                    placeholder={unit}
                    autoFocus
                    className="w-16 px-1.5 py-0.5 rounded text-xs bg-slate-700 border border-slate-500 text-white placeholder-slate-500 focus:border-indigo-400 focus:outline-none"
                />
            ) : (
                <button onClick={() => setShowInput(true)}
                    className={`px-2 py-0.5 rounded text-xs font-medium transition-all ${
                        !isPreset
                            ? `${activeColor} text-white`
                            : 'bg-slate-700/50 text-slate-400 hover:text-white'
                    }`}>
                    {!isPreset ? `${value}${unit}` : '自定义'}
                </button>
            )}
        </div>
    );
};

export default LookbackSelector;
