import { apiFetch } from './api_client.js';
function removeOverlay() {
    document.getElementById('onboarding-overlay')?.remove();
}

function mountOverlay(html) {
    removeOverlay();
    const overlay = document.createElement('div');
    overlay.id = 'onboarding-overlay';
    overlay.className = 'onboarding-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Настройка Ouroboros');
    overlay.innerHTML = `
        <div class="onboarding-overlay-backdrop"></div>
        <iframe class="onboarding-frame" title="Настройка Ouroboros" sandbox="allow-same-origin allow-scripts allow-forms"></iframe>
    `;
    const frame = overlay.querySelector('.onboarding-frame');
    if (frame) frame.srcdoc = html;
    document.body.appendChild(overlay);
}

function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (ch) => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
    }[ch]));
}

function showRestartRequiredOverlay(runtimeMode) {
    const mode = escapeHtml(runtimeMode || 'advanced');
    const overlay = document.getElementById('onboarding-overlay') || document.createElement('div');
    overlay.id = 'onboarding-overlay';
    overlay.className = 'onboarding-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Требуется перезапуск Ouroboros');
    overlay.innerHTML = `
        <div class="onboarding-overlay-backdrop"></div>
        <section class="onboarding-restart-card">
            <h2>Требуется перезапуск</h2>
            <p>Режим работы сохранён как <code>${mode}</code> для следующего запуска. Перезапустите Ouroboros, чтобы применить его, прежде чем продолжать в этом режиме.</p>
            <button type="button" class="btn btn-primary" data-onboarding-continue>Продолжить в текущем режиме</button>
        </section>
    `;
    if (!overlay.parentElement) document.body.appendChild(overlay);
    overlay.querySelector('[data-onboarding-continue]')?.addEventListener('click', () => {
        removeOverlay();
        window.location.reload();
    });
}

export async function initOnboardingOverlay() {
    function handleMessage(event) {
        if (event?.data?.type !== 'ouroboros:onboarding-complete') return;
        if (event.data.restart_required) {
            showRestartRequiredOverlay(event.data.runtime_mode);
            return;
        }
        removeOverlay();
        window.location.reload();
    }

    window.addEventListener('message', handleMessage);

    try {
        const response = await apiFetch('/api/onboarding', { cache: 'no-store' });
        if (response.status === 204) return;
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const html = await response.text();
        if (html.trim()) mountOverlay(html);
    } catch (error) {
        console.error('Failed to load onboarding overlay:', error);
    }
}
