import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';

/**
 * 通用错误边界 — 子组件 JS 崩溃时显示降级 UI，不影响其他面板。
 */
class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        console.error(`[ErrorBoundary] ${this.props.name || 'Unknown'} crashed:`, error, info);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="flex flex-col items-center justify-center py-20 text-center">
                    <div className="p-4 bg-red-500/10 rounded-2xl border border-red-500/30 mb-4">
                        <AlertCircle className="w-10 h-10 text-red-400" />
                    </div>
                    <h3 className="text-lg font-semibold text-white mb-2">
                        {this.props.name || '模块'}加载异常
                    </h3>
                    <p className="text-sm text-slate-400 mb-4 max-w-md">
                        {this.state.error?.message || '发生了未知错误'}
                    </p>
                    <button
                        onClick={() => this.setState({ hasError: false, error: null })}
                        className="flex items-center gap-2 px-4 py-2 bg-slate-700/50 hover:bg-slate-600/50 text-slate-200 rounded-lg border border-slate-600/50 transition-colors text-sm"
                    >
                        <RefreshCw className="w-4 h-4" />
                        重试
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}

export default ErrorBoundary;
