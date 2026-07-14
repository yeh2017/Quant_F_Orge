import { useState, useEffect } from 'react';
import { Loader2, X } from 'lucide-react';

const GlobalLoading = ({ loading, text = "处理中...", step = null, totalSteps = null, onCancel = null }) => {
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        if (!loading) {
            setElapsed(0);
            return;
        }
        const timer = setInterval(() => setElapsed(e => e + 1), 1000);
        return () => clearInterval(timer);
    }, [loading]);

    if (!loading) return null;

    const formatTime = (s) => s < 60 ? `${s}秒` : `${Math.floor(s / 60)}分${s % 60}秒`;
    const progress = step && totalSteps ? Math.round((step / totalSteps) * 100) : null;

    return (
        <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center">
            <div className="bg-slate-800 p-8 rounded-2xl border border-slate-700 shadow-2xl flex flex-col items-center min-w-[280px]">
                <Loader2 className="w-12 h-12 text-indigo-500 animate-spin mb-4" />
                <h3 className="text-xl font-medium text-white">{text}</h3>
                {step && totalSteps && (
                    <div className="w-full mt-4">
                        <div className="flex justify-between text-sm text-slate-400 mb-1">
                            <span>步骤 {step}/{totalSteps}</span>
                            <span>{progress}%</span>
                        </div>
                        <div className="w-full bg-slate-700 rounded-full h-2">
                            <div
                                className="bg-gradient-to-r from-indigo-500 to-purple-500 h-2 rounded-full transition-all duration-300"
                                style={{ width: `${progress}%` }}
                            />
                        </div>
                    </div>
                )}
                <p className="text-slate-400 mt-3 text-sm">已用时 {formatTime(elapsed)}</p>
                {onCancel && (
                    <button
                        onClick={onCancel}
                        className="mt-4 px-4 py-2 bg-red-600/20 text-red-400 rounded-lg text-sm hover:bg-red-600/30 flex items-center gap-1"
                    >
                        <X className="w-4 h-4" /> 取消
                    </button>
                )}
            </div>
        </div>
    );
};

export default GlobalLoading;

