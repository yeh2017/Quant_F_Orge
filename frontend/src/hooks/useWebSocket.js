/**
 * 全局 WebSocket Hook
 * 自动连接 + 断线重连 + 心跳 + 事件广播
 *
 * 架构设计：
 * - WS 消息自动 dispatch 为 window CustomEvent（事件名 = `ws:${msg.type}`）
 * - 任何组件通过 window.addEventListener('ws:xxx') 订阅，无需经过 App.jsx
 * - 可选传入 onMessage 回调兼容旧用法
 */
import { useEffect, useRef, useCallback } from 'react';

const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${wsProtocol}//${window.location.host}/api/ws`;
const RECONNECT_DELAY = 3000;
const HEARTBEAT_INTERVAL = 30000;

export default function useWebSocket(onMessage) {
    const wsRef = useRef(null);
    const reconnectTimer = useRef(null);
    const heartbeatTimer = useRef(null);
    const onMessageRef = useRef(onMessage);
    onMessageRef.current = onMessage;

    const connect = useCallback(() => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

        try {
            const ws = new WebSocket(WS_URL);

            ws.onopen = () => {
                console.log('[WS] connected');
                heartbeatTimer.current = setInterval(() => {
                    if (ws.readyState === WebSocket.OPEN) {
                        ws.send(JSON.stringify({ type: 'ping' }));
                    }
                }, HEARTBEAT_INTERVAL);
            };

            ws.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);

                    // 核心机制：广播为 window CustomEvent，任何组件均可订阅
                    if (msg.type) {
                        window.dispatchEvent(new CustomEvent(`ws:${msg.type}`, { detail: msg }));
                    }

                    // 兼容旧用法：仍调用显式回调（如有）
                    if (onMessageRef.current) {
                        onMessageRef.current(msg);
                    }
                } catch (err) {
                    console.warn('[WS] parse error:', err);
                }
            };

            ws.onclose = () => {
                console.log('[WS] disconnected, reconnecting...');
                clearInterval(heartbeatTimer.current);
                reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
            };

            ws.onerror = (err) => {
                console.warn('[WS] error:', err);
                ws.close();
            };

            wsRef.current = ws;
        } catch (err) {
            console.warn('[WS] connect failed:', err);
            reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
        }
    }, []);

    useEffect(() => {
        connect();
        return () => {
            clearTimeout(reconnectTimer.current);
            clearInterval(heartbeatTimer.current);
            if (wsRef.current) {
                wsRef.current.onclose = null;
                wsRef.current.close();
            }
        };
    }, [connect]);

    return wsRef;
}
