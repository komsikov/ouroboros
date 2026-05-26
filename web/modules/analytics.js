const YANDEX_COUNTER_ID = 108712410;

const onceEvents = new Set();
const pendingEvents = [];
let flushTimer = null;
let warnedMissingYm = false;

function metricsDebugEnabled() {
    try {
        const query = new URLSearchParams(window.location.search || '');
        if (query.get('_ouro_metrics_debug') === '1') return true;
        return window.localStorage.getItem('ouro_metrics_debug') === '1';
    } catch {
        return false;
    }
}

function debugLog(message, payload) {
    if (!metricsDebugEnabled()) return;
    if (payload !== undefined) {
        console.info(`[metrics] ${message}`, payload);
        return;
    }
    console.info(`[metrics] ${message}`);
}

function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = window.setTimeout(() => {
        flushTimer = null;
        flushPendingEvents();
    }, 1000);
}

function flushPendingEvents() {
    const ym = window.ym;
    if (typeof ym !== 'function') {
        scheduleFlush();
        return;
    }
    while (pendingEvents.length) {
        const item = pendingEvents.shift();
        if (!item) break;
        sendGoal(item.goal, item.options, true);
    }
}

function sendGoal(goal, options = {}, fromQueue = false) {
    const ym = window.ym;
    if (typeof ym !== 'function') {
        if (!warnedMissingYm) {
            warnedMissingYm = true;
            console.warn('[metrics] window.ym is not available yet; events are queued.');
        }
        pendingEvents.push({ goal, options });
        scheduleFlush();
        return;
    }

    try {
        if (options && options.params && typeof options.params === 'object') {
            ym(YANDEX_COUNTER_ID, 'reachGoal', goal, options.params);
        } else {
            ym(YANDEX_COUNTER_ID, 'reachGoal', goal);
        }
        debugLog(`reachGoal sent: ${goal}${fromQueue ? ' (from queue)' : ''}`);
    } catch (error) {
        console.warn('[metrics] reachGoal failed', error);
    }
}

export function trackMetric(eventName, options = {}) {
    const goal = String(eventName || '').trim();
    if (!goal) return;
    const once = options && options.once === true;
    if (once && onceEvents.has(goal)) return;
    if (once) onceEvents.add(goal);
    sendGoal(goal, options, false);
}

window.ouroTrackMetric = trackMetric;