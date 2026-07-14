import { useEffect, useRef } from 'react';

/**
 * 当 tab 变为激活状态时触发回调（跳过首次挂载）。
 * 用于 display:none/block 切换的 SPA tab 架构中，
 * 确保面板在重新可见时刷新数据。
 *
 * @param {boolean} isActive - 当前 tab 是否激活
 * @param {Function} onActivate - 激活时执行的回调
 */
export function useTabRefresh(isActive, onActivate) {
    const prevActive = useRef(isActive);
    const mounted = useRef(false);

    useEffect(() => {
        // 跳过首次挂载（首次由组件自身的 useEffect([], []) 处理）
        if (!mounted.current) {
            mounted.current = true;
            return;
        }
        // 检测从 inactive → active 的切换
        if (isActive && !prevActive.current) {
            onActivate();
        }
        prevActive.current = isActive;
    }, [isActive, onActivate]);
}
