// Override/define global showToast - auto-dismiss + X button
function showToast(message, type = 'info') {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:10px;';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-msg">${message}</span>
        <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
    `;
    toast.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px;border-radius:8px;min-width:250px;max-width:380px;box-shadow:0 4px 12px rgba(0,0,0,0.15);animation:slideIn 0.3s ease;';

    // Colors by type
    const colors = { success:'#22c55e', error:'#ef4444', warning:'#f59e0b', info:'#3b82f6' };
    toast.style.background = colors[type] || colors.info;
    toast.style.color = '#fff';

    container.appendChild(toast);

    // Auto-dismiss after 5 seconds with fade
    setTimeout(() => {
        toast.style.transition = 'opacity 0.5s ease';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
    }, 5000);
}
