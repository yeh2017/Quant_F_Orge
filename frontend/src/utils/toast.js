/**
 * 全局 Toast 通知系统
 * 用于 API 错误等全局提示，无需组件依赖。
 */

const TOAST_CONTAINER_ID = 'global-toast-container';
const TOAST_DURATION = 5000;

function getOrCreateContainer() {
  let container = document.getElementById(TOAST_CONTAINER_ID);
  if (!container) {
    container = document.createElement('div');
    container.id = TOAST_CONTAINER_ID;
    Object.assign(container.style, {
      position: 'fixed',
      top: '20px',
      right: '20px',
      zIndex: '99999',
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      pointerEvents: 'none',
    });
    document.body.appendChild(container);
  }
  return container;
}

const STYLES = {
  error: { bg: '#1a1a2e', border: '#e74c3c', icon: '❌' },
  warning: { bg: '#1a1a2e', border: '#f39c12', icon: '⚠️' },
  success: { bg: '#1a1a2e', border: '#2ecc71', icon: '✅' },
  info: { bg: '#1a1a2e', border: '#3498db', icon: 'ℹ️' },
};

export function showToast(message, type = 'error', duration = TOAST_DURATION) {
  const container = getOrCreateContainer();
  const style = STYLES[type] || STYLES.error;

  const toast = document.createElement('div');
  Object.assign(toast.style, {
    background: style.bg,
    border: `1px solid ${style.border}`,
    borderLeft: `4px solid ${style.border}`,
    color: '#e0e0e0',
    padding: '12px 16px',
    borderRadius: '8px',
    fontSize: '14px',
    maxWidth: '400px',
    boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
    pointerEvents: 'auto',
    cursor: 'pointer',
    opacity: '0',
    transform: 'translateX(100%)',
    transition: 'all 0.3s ease',
    fontFamily: "'Inter', sans-serif",
  });

  toast.textContent = `${style.icon} ${message}`;
  toast.onclick = () => removeToast(toast);
  container.appendChild(toast);

  // 入场动画
  requestAnimationFrame(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateX(0)';
  });

  // 自动消失
  setTimeout(() => removeToast(toast), duration);
}

function removeToast(toast) {
  toast.style.opacity = '0';
  toast.style.transform = 'translateX(100%)';
  setTimeout(() => toast.remove(), 300);
}
