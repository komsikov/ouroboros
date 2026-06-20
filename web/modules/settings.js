import { apiClient, apiFetch, cleanExtensionRoute, extensionRoutePath } from './api_client.js';
import { applyMcpSettings, collectMcpSettings, initMcpSettings } from './mcp_settings.js';
import { refreshModelCatalog } from './settings_catalog.js';
import { bindEffortSegments, syncEffortSegments } from './settings_controls.js';
import { bindLocalModelControls } from './settings_local_model.js';
import { SECRET_KEYS, bindSecretInputs, bindSettingsTabs, renderSettingsPage } from './settings_ui.js';
import { showToast } from './toast.js';
import { escapeHtmlAttr as escapeHtml, formatDualVersion } from './utils.js';

let markSettingsDirty = () => {};
const BASE_SECRET_KEYS = new Set(SECRET_KEYS.map(([key]) => key));
let setupContract = {};
const MODEL_LOCKED_SETTING_KEYS = new Set([
    'OUROBOROS_MODEL',
    'OUROBOROS_MODEL_CODE',
    'OUROBOROS_MODEL_LIGHT',
    'OUROBOROS_MODEL_FALLBACK',
]);

const INPUT_FIELDS = [
    ['s-openai-base-url', 'OPENAI_BASE_URL'], ['s-openai-compatible-base-url', 'OPENAI_COMPATIBLE_BASE_URL'], ['s-cloudru-base-url', 'CLOUDRU_FOUNDATION_MODELS_BASE_URL'],
    ['s-gigachat-scope', 'GIGACHAT_SCOPE'], ['s-gigachat-user', 'GIGACHAT_USER'], ['s-gigachat-base-url', 'GIGACHAT_BASE_URL'], ['s-gigachat-verify-ssl', 'GIGACHAT_VERIFY_SSL_CERTS'],
    ['s-server-host', 'OUROBOROS_SERVER_HOST', '127.0.0.1'], ['s-claude-code-model', 'CLAUDE_CODE_MODEL', 'opus[1m]'],
    ['s-review-models', 'OUROBOROS_REVIEW_MODELS'], ['s-scope-review-models', 'OUROBOROS_SCOPE_REVIEW_MODELS'], ['s-deep-self-review-model', 'OUROBOROS_MODEL_DEEP_SELF_REVIEW'], ['s-skills-repo-path', 'OUROBOROS_SKILLS_REPO_PATH'],
    ['s-clawhub-registry-url', 'OUROBOROS_CLAWHUB_REGISTRY_URL'], ['s-websearch-model', 'OUROBOROS_WEBSEARCH_MODEL'], ['s-gh-repo', 'GITHUB_REPO'],
    ['s-local-source', 'LOCAL_MODEL_SOURCE'], ['s-local-filename', 'LOCAL_MODEL_FILENAME'], ['s-local-chat-format', 'LOCAL_MODEL_CHAT_FORMAT'],
    ['s-subagent-worktree-root', 'OUROBOROS_SUBAGENT_WORKTREE_ROOT'], ['s-subagent-projects-root', 'OUROBOROS_SUBAGENT_PROJECTS_ROOT'],
    ['s-evo-budget', 'OUROBOROS_POST_TASK_EVOLUTION_BUDGET_USD', '0'],
    ['s-evo-objective', 'OUROBOROS_EVOLUTION_PERSISTENT_OBJECTIVE', ''],
];
const VALUE_FIELDS = [
    ['s-effort-task', 'OUROBOROS_EFFORT_TASK', 'medium'], ['s-effort-evolution', 'OUROBOROS_EFFORT_EVOLUTION', 'high'], ['s-effort-review', 'OUROBOROS_EFFORT_REVIEW', 'medium'],
    ['s-effort-consciousness', 'OUROBOROS_EFFORT_CONSCIOUSNESS', 'high'], ['s-effort-scope-review', 'OUROBOROS_EFFORT_SCOPE_REVIEW', 'high'], ['s-effort-deep-self-review', 'OUROBOROS_EFFORT_DEEP_SELF_REVIEW', 'high'],
    ['s-review-enforcement', 'OUROBOROS_REVIEW_ENFORCEMENT', 'advisory'], ['s-task-review-mode', 'OUROBOROS_TASK_REVIEW_MODE', 'auto'], ['s-runtime-mode', 'OUROBOROS_RUNTIME_MODE', 'advanced'],
    ['s-context-mode', 'OUROBOROS_CONTEXT_MODE', 'max'],
];
const NUMBER_FIELDS = [
    ['s-workers', 'OUROBOROS_MAX_WORKERS', 10], ['s-active-subagents', 'OUROBOROS_MAX_ACTIVE_SUBAGENTS_PER_ROOT', 3], ['s-subagent-depth', 'OUROBOROS_MAX_SUBAGENT_DEPTH', 2], ['s-soft-timeout', 'OUROBOROS_SOFT_TIMEOUT_SEC', 600], ['s-hard-timeout', 'OUROBOROS_HARD_TIMEOUT_SEC', 1800],
    ['s-tool-timeout', 'OUROBOROS_TOOL_TIMEOUT_SEC', 600], ['s-local-port', 'LOCAL_MODEL_PORT', 8766], ['s-local-gpu-layers', 'LOCAL_MODEL_N_GPU_LAYERS', -1, true],
    ['s-local-ctx', 'LOCAL_MODEL_CONTEXT_LENGTH', 16384], ['s-gc-retention-days', 'OUROBOROS_GC_RETENTION_DAYS', 7],
    ['s-bg-wakeup-min', 'OUROBOROS_BG_WAKEUP_MIN', 30], ['s-bg-wakeup-max', 'OUROBOROS_BG_WAKEUP_MAX', 7200], ['s-bg-max-rounds', 'OUROBOROS_BG_MAX_ROUNDS', 10],
];

function setupModelSlots() {
    return Array.isArray(setupContract.modelSlots) ? setupContract.modelSlots : [];
}

function byId(id) {
    return document.getElementById(id);
}

function applyInputValue(id, value) {
    byId(id).value = value === undefined || value === null ? '' : value;
}

function applyCheckboxValue(id, value) {
    byId(id).checked = isTruthySetting(value);
}

function isTruthySetting(value) {
    const normalized = String(value ?? '').trim().toLowerCase();
    return value === true || ['true', '1', 'yes', 'on'].includes(normalized);
}

function setStatus(text, tone = 'ok') {
    const status = byId('settings-status');
    status.textContent = text;
    status.dataset.tone = tone;
}

function readInt(id, fallback) {
    const value = parseInt(byId(id).value, 10);
    return Number.isNaN(value) ? fallback : value;
}

function resetSecretClearFlags(root) {
    root.querySelectorAll('.secret-input').forEach((input) => {
        delete input.dataset.forceClear;
        input.type = 'password';
    });
    root.querySelectorAll('.secret-toggle').forEach((button) => {
        button.classList.remove('is-revealed');
        button.setAttribute('aria-label', 'Показать секрет');
        button.title = 'Показать секрет';
    });
}

function applySecretInputs(root, settings) {
    root.querySelectorAll('[data-secret-setting]').forEach((input) => {
        applyInputValue(input.id, settings[input.dataset.secretSetting]);
    });
}


function wireSecretRow(row) {
    const input = row.querySelector('.secret-input');
    const toggle = row.querySelector('[data-row-secret-toggle]');
    const clear = row.querySelector('[data-row-secret-clear]');
    const syncToggle = () => {
        if (!toggle || !input) return;
        const revealed = input.type === 'text';
        toggle.classList.toggle('is-revealed', revealed);
        toggle.setAttribute('aria-label', revealed ? 'Скрыть секрет' : 'Показать секрет');
        toggle.title = revealed ? 'Скрыть секрет' : 'Показать секрет';
    };
    if (input) input.addEventListener('input', () => { if (input.value.trim()) delete input.dataset.forceClear; });
    if (toggle && input) toggle.addEventListener('click', () => { input.type = input.type === 'password' ? 'text' : 'password'; syncToggle(); });
    if (clear && input) clear.addEventListener('click', () => { input.value = ''; input.type = 'password'; input.dataset.forceClear = '1'; syncToggle(); markSettingsDirty(); });
    syncToggle();
}

function customSecretRow(key = '', value = '') {
    const id = `custom-secret-${Math.random().toString(36).slice(2)}`;
    const row = document.createElement('div');
    row.className = 'settings-custom-secret-row';
    row.dataset.customSecretRow = '1';
    row.innerHTML = `
        <div class="form-field settings-custom-secret-key"><label>Key</label><input data-custom-secret-key value="${escapeHtml(key)}" placeholder="SLACK_WEBHOOK_URL" spellcheck="false"></div>
        <div class="form-field settings-custom-secret-value"><label>Value</label><div class="secret-input-row">
            <input id="${id}" data-custom-secret-value class="secret-input" type="password" value="${escapeHtml(value || '')}" placeholder="Значение секрета">
            <button type="button" class="secret-icon-btn secret-toggle" data-row-secret-toggle aria-label="Показать секрет" title="Показать секрет"></button>
            <button type="button" class="secret-icon-btn secret-clear" data-row-secret-clear aria-label="Очистить секрет" title="Очистить секрет"></button>
        </div><div class="settings-inline-note" data-custom-secret-error hidden></div></div>
        <button type="button" class="settings-ghost-btn settings-custom-secret-remove" data-custom-secret-remove>Удалить</button>`;
    wireSecretRow(row);
    row.querySelector('[data-custom-secret-remove]')?.addEventListener('click', () => { row.dataset.removeCustomSecret = '1'; row.hidden = true; markSettingsDirty(); });
    return row;
}

function renderCustomSecrets(root, settings) {
    const host = root.querySelector('#custom-secrets-list');
    if (!host) return;
    host.innerHTML = '';
    const keys = Array.isArray(settings?._meta?.custom_secret_keys) ? settings._meta.custom_secret_keys : [];
    keys.forEach((key) => host.appendChild(customSecretRow(key, settings[key] || '')));
    if (!keys.length) host.innerHTML = '<div class="muted">Пользовательских ключей пока нет.</div>';
}

function renderRequestedSkillSecrets(root, skills, settings) {
    const host = root.querySelector('#skill-requested-secrets');
    if (!host) return;
    const keys = [];
    (Array.isArray(skills) ? skills : []).forEach((skill) => {
        (skill?.grants?.requested_keys || []).forEach((key) => {
            const normalized = String(key || '').trim();
            if (normalized && !BASE_SECRET_KEYS.has(normalized)) keys.push(normalized);
        });
    });
    const unique = Array.from(new Set(keys)).sort((a, b) => a.localeCompare(b));
    if (!unique.length) { host.innerHTML = '<div class="muted">Навыки не запрашивали секреты.</div>'; return; }
    host.innerHTML = '';
    unique.forEach((key, idx) => {
        const id = `requested-secret-${idx}`;
        const el = document.createElement('div');
        el.className = 'settings-requested-secret-row';
        el.innerHTML = `<div class="form-field"><label>${escapeHtml(key)}</label><div class="secret-input-row">
            <input id="${id}" data-secret-setting="${escapeHtml(key)}" class="secret-input" type="password" value="${escapeHtml(settings[key] || '')}" placeholder="Значение секрета">
            <button type="button" class="secret-icon-btn secret-toggle" data-row-secret-toggle aria-label="Показать секрет" title="Показать секрет"></button>
            <button type="button" class="secret-icon-btn secret-clear" data-row-secret-clear aria-label="Очистить секрет" title="Очистить секрет"></button>
        </div></div>`;
        wireSecretRow(el); host.appendChild(el);
    });
}

function renderExtensionSettingsSections(root, sections) {
    const host = root.querySelector('#extension-settings-sections');
    if (!host) return;
    const items = Array.isArray(sections) ? sections : [];
    if (!items.length) {
        host.innerHTML = '<div class="muted">Настройки расширений не зарегистрированы.</div>';
        return;
    }
    const fieldHtml = (field) => {
        const name = escapeHtml(field.name || '');
        const label = escapeHtml(field.label || field.name || '');
        const placeholder = escapeHtml(field.placeholder || '');
        const type = String(field.type || 'text');
        if (type === 'textarea') {
            return `<label class="form-field"><span>${label}</span><textarea name="${name}" placeholder="${placeholder}"></textarea></label>`;
        }
        if (type === 'checkbox') {
            return `<label class="settings-extension-checkbox"><input type="checkbox" name="${name}"><span>${label}</span></label>`;
        }
        return `<label class="form-field"><span>${label}</span><input name="${name}" type="${escapeHtml(type)}" placeholder="${placeholder}"></label>`;
    };
    const componentHtml = (section, component, idx) => {
        const type = String(component.type || '');
        if (type === 'markdown') {
            return `<div class="settings-section-copy">${escapeHtml(component.text || '')}</div>`;
        }
        if (type === 'json') {
            return `<details class="widget-json"><summary>${escapeHtml(component.label || 'JSON')}</summary><pre>${escapeHtml(JSON.stringify(component.value || component.data || {}, null, 2))}</pre></details>`;
        }
        if (type === 'form' || type === 'action') {
            const fields = Array.isArray(component.fields) ? component.fields : [];
            const rawRoute = component.route || component.api_route || '';
            if (!cleanExtensionRoute(rawRoute)) {
                return '<div class="settings-inline-note">Некорректный маршрут настроек расширения.</div>';
            }
            return `
                <form class="settings-extension-form" data-extension-settings-form data-skill="${escapeHtml(section.skill || '')}" data-route="${escapeHtml(rawRoute)}">
                    <div class="form-grid two">${fields.map(fieldHtml).join('')}</div>
                    <button class="btn btn-primary btn-sm" type="submit">${escapeHtml(component.submit_label || component.label || 'Сохранить')}</button>
                    <div class="settings-inline-status" data-extension-settings-status></div>
                </form>
            `;
        }
        return `<div class="settings-inline-note">Неподдерживаемый компонент настроек расширения ${idx + 1}: ${escapeHtml(type || 'неизвестно')}</div>`;
    };
    host.innerHTML = items.map((section) => {
        const title = escapeHtml(section.title || section.section_id || section.key || 'Настройки расширения');
        const skill = escapeHtml(section.skill || '');
        const components = Array.isArray(section.render?.components) ? section.render.components : [];
        return `
            <article class="settings-extension-section">
                <div class="settings-extension-section-head">
                    <strong>${title}</strong>
                    ${skill ? `<span class="settings-inline-note">из ${skill}</span>` : ''}
                </div>
                <div class="settings-extension-components">
                    ${components.length ? components.map((component, idx) => componentHtml(section, component, idx)).join('') : '<div class="muted">Декларативных компонентов нет.</div>'}
                </div>
            </article>
        `;
    }).join('');
    host.querySelectorAll('[data-extension-settings-form]').forEach((form) => {
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const status = form.querySelector('[data-extension-settings-status]');
            const skill = form.dataset.skill || '';
            const route = form.dataset.route || '';
            if (!skill || !route) return;
            const values = {};
            new FormData(form).forEach((value, key) => { values[key] = value; });
            form.querySelectorAll('input[type="checkbox"]').forEach((input) => {
                values[input.name] = input.checked;
            });
            if (status) {
                status.textContent = 'Сохранение...';
                status.dataset.tone = 'muted';
            }
            try {
                const cleanRoute = cleanExtensionRoute(route);
                if (!cleanRoute) throw new Error('invalid extension settings route');
                const resp = await apiFetch(extensionRoutePath(skill, route), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(values),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
                if (status) {
                    status.textContent = data.message || 'Сохранено.';
                    status.dataset.tone = 'ok';
                }
            } catch (err) {
                if (status) {
                    status.textContent = err.message || String(err);
                    status.dataset.tone = 'danger';
                }
            }
        });
    });
}

function collectSecretValue(id, body) {
    const input = byId(id);
    if (!input) return;
    const settingKey = input.dataset.secretSetting;
    if (!settingKey) return;
    if (input.dataset.forceClear === '1') {
        body[settingKey] = '';
        return;
    }
    const value = input.value;
    if (value && !value.includes('...')) body[settingKey] = value;
}

// Fallback picker pills mirror config defaults plus useful direct-provider ids.
const SETTINGS_FALLBACK_MODELS = [
    'google/gemini-3.5-flash',
    'anthropic/claude-sonnet-4.6',
    'anthropic/claude-opus-4.8',
    'anthropic::claude-opus-4-8',
    'anthropic/claude-opus-4.7',
    'anthropic::claude-opus-4-7',
    'anthropic::claude-opus-4-6',
    'anthropic::claude-sonnet-4-6',
    'openai::gpt-5.5',
    'openai::gpt-5.5-mini',
    'openai/gpt-5.5',
    'anthropic/claude-opus-4.6',
];

let settingsModelCatalogItems = SETTINGS_FALLBACK_MODELS.map((value) => ({ value, label: 'Рекомендуемая модель' }));

export function initSettings({ state, setBeforePageLeave, ws } = {}) {
    const page = document.createElement('div');
    page.id = 'page-settings';
    page.className = 'page app-page-glass';
    page.innerHTML = renderSettingsPage();
    document.getElementById('content').appendChild(page);

    const activateSettingsTab = (tabName) => {
        if (typeof page.activateSettingsTab === 'function') {
            page.activateSettingsTab(tabName);
        }
    };
    bindSettingsTabs(page, { state });
    bindSecretInputs(page);
    bindEffortSegments(page);
    bindLocalModelControls({ state });
    // Best-effort About version from /api/health.
    apiFetch('/api/health')
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((d) => {
            const verEl = document.getElementById('about-version');
            if (verEl) verEl.textContent = formatDualVersion(d);
        })
        .catch(() => { /* about version is best-effort */ });
    let currentSettings = {};
    let claudeCodePollStarted = false;
    let extensionRefreshPending = false;
    // Runtime errors must surface even before ANTHROPIC_API_KEY is configured.
    let claudeRuntimeHasError = false;
    let settingsLoaded = false;
    let settingsBaseline = '';
    let settingsDirty = false;
    let fixedInfraModels = false;
    initMcpSettings({ onChange: updateSettingsDirtyState });

    function anthropicKeyConfigured() {
        const input = byId('s-anthropic');
        if (!input) return Boolean(String(currentSettings.ANTHROPIC_API_KEY || '').trim());
        if (input.dataset.forceClear === '1') return false;
        const liveValue = String(input.value || '').trim();
        if (liveValue) return true;
        return Boolean(String(currentSettings.ANTHROPIC_API_KEY || '').trim());
    }

    function shouldShowClaudeRuntimeCard() {
        return anthropicKeyConfigured() || claudeRuntimeHasError;
    }

    function renderClaudeCodeUi() {
        const panel = byId('settings-claude-code-panel');
        const note = byId('settings-claude-code-copy');
        const button = byId('btn-claude-code-install');
        const visible = shouldShowClaudeRuntimeCard();
        if (panel) panel.hidden = !visible;
        if (note) note.hidden = !visible;
        if (!visible) return;
        if (button && button.dataset.busy !== '1' && button.dataset.ready !== '1') {
            button.disabled = false;
            button.textContent = 'Восстановить среду';
        }
    }

    function syncSettingsLoadState() {
        const saveBtn = byId('btn-save-settings');
        if (saveBtn) {
            saveBtn.disabled = !settingsLoaded;
            saveBtn.title = settingsLoaded
                ? ''
                : 'Перед сохранением успешно перезагрузите текущие настройки.';
        }
    }

    function syncRuntimeModeBridgeState() {
        const hasBridge = Boolean(window.pywebview?.api?.request_runtime_mode_change);
        const group = document.querySelector('[data-runtime-mode-group]');
        if (group) {
            group.title = hasBridge
                ? 'Смена режима требует подтверждения нативного лаунчера и перезапуска.'
                : 'Смена режима сохраняется через эндпоинт владельца и применяется после перезапуска.';
        }
        document.querySelectorAll('[data-runtime-mode-group] [data-effort-value]').forEach((button) => {
            button.disabled = false;
        });
    }

    function syncPostTaskEvolutionUi() {
        const mode = byId('s-post-task-evolution-mode')?.value || 'off';
        page.querySelectorAll('[data-evo-every-n-row]').forEach((row) => {
            row.hidden = mode !== 'every_n';
        });
    }

    function snapshotSettingsDraft() {
        return JSON.stringify({
            ...collectBody(),
            OUROBOROS_RUNTIME_MODE_DRAFT: byId('s-runtime-mode')?.value || 'advanced',
            OUROBOROS_CONTEXT_MODE_DRAFT: byId('s-context-mode')?.value || 'max',
        });
    }

    function setSettingsCleanBaseline() {
        settingsBaseline = snapshotSettingsDraft();
        settingsDirty = false;
        const indicator = byId('settings-unsaved-indicator');
        if (indicator) indicator.classList.remove('is-visible');
    }

    function updateSettingsDirtyState() {
        if (!settingsLoaded || !settingsBaseline) return;
        const nextDirty = snapshotSettingsDraft() !== settingsBaseline;
        if (nextDirty === settingsDirty) return;
        settingsDirty = nextDirty;
        const indicator = byId('settings-unsaved-indicator');
        if (indicator) indicator.classList.toggle('is-visible', settingsDirty);
    }

    function discardUnsavedSettingsDraft() {
        closeSettingsModelPickers();
        applySettings(currentSettings || {});
        setSettingsCleanBaseline();
        setStatus('', 'ok');
    }

    function applyClaudeCodeStatus(payload = {}) {
        const button = byId('btn-claude-code-install');
        const status = byId('settings-claude-code-status');
        const ready = Boolean(payload.ready);
        const installed = Boolean(payload.installed);
        const busy = Boolean(payload.busy);
        const error = String(payload.error || '').trim();
        // Backend error state controls visibility without an API key.
        claudeRuntimeHasError = Boolean(error);
        const message = String(payload.message || '').trim()
            || (ready ? 'Среда Claude готова.' : (installed ? 'Среда Claude доступна, но не готова.' : 'Среда Claude недоступна.'));
        const tone = ready ? 'ok' : (error ? 'error' : (installed ? 'muted' : 'error'));
        if (status) {
            status.textContent = message;
            status.dataset.tone = tone;
        }
        if (button) {
            button.dataset.busy = busy ? '1' : '0';
            button.dataset.ready = ready ? '1' : '0';
            button.dataset.installed = installed ? '1' : '0';
            button.disabled = busy;
            button.textContent = busy ? 'Восстановление...' : (ready ? 'Среда в порядке' : 'Восстановить среду');
        }
        renderClaudeCodeUi();
    }

    async function refreshClaudeCodeStatus() {
        // Poll even without API key; backend separates no_api_key from errors.
        try {
            const resp = await apiFetch('/api/claude-code/status', { cache: 'no-store' });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
            applyClaudeCodeStatus(data);
        } catch (error) {
            applyClaudeCodeStatus({
                installed: false,
                ready: false,
                busy: false,
                error: String(error?.message || error || ''),
                message: `Не удалось проверить статус среды Claude: ${String(error?.message || error || '')}`,
            });
        }
    }

    function syncAutoGrantBridgeState() {
        const hasBridge = Boolean(window.pywebview?.api?.request_auto_grant_reviewed_skills_change);
        const checkbox = byId('s-auto-grant-reviewed-skills');
        const label = checkbox?.closest('.local-toggle');
        if (checkbox) checkbox.disabled = false;
        if (label) {
            label.title = hasBridge
                ? 'Requires native confirmation. Applies only after a fresh executable skill review and only to manifest-declared grants for that exact content hash.'
                : 'Uses the owner endpoint. Applies only after a fresh executable skill review and only to manifest-declared grants for that exact content hash.';
        }
    }

    function startClaudeCodePolling() {
        if (claudeCodePollStarted) return;
        claudeCodePollStarted = true;
        refreshClaudeCodeStatus();
        setInterval(() => {
            refreshClaudeCodeStatus();
        }, 3000);
    }

    function applyFixedPolicyUi() {
        const compatibleCard = page.querySelector('[data-provider-card="compatible"]');
        if (compatibleCard) {
            if (!compatibleCard.dataset.fixedLockBound) {
                compatibleCard.addEventListener('toggle', () => {
                    if (!compatibleCard.classList.contains('settings-provider-locked')) return;
                    if (compatibleCard.open) compatibleCard.open = false;
                });
                compatibleCard.dataset.fixedLockBound = '1';
            }
            compatibleCard.classList.toggle('settings-provider-locked', fixedInfraModels);
            compatibleCard.setAttribute('aria-disabled', fixedInfraModels ? 'true' : 'false');
            if (fixedInfraModels && compatibleCard.open) compatibleCard.open = false;
            compatibleCard.querySelectorAll('input, select, textarea, button').forEach((control) => {
                control.disabled = fixedInfraModels;
            });
        }
        const disableModelControl = (input, disabled) => {
            if (!input) return;
            input.disabled = disabled;
            if (!disabled) input.removeAttribute('readonly');
            const picker = input.closest('[data-model-picker]');
            if (picker) picker.classList.toggle('settings-model-locked', disabled);
            const card = input.closest('.settings-model-card');
            if (card) card.classList.toggle('settings-model-locked', disabled);
        };
        setupModelSlots().forEach((slot) => {
            disableModelControl(byId(slot.settingsInputId), fixedInfraModels);
            const toggle = byId(slot.settingsToggleId);
            if (toggle) toggle.disabled = fixedInfraModels;
        });
        const modelStatus = byId('settings-model-catalog-status');
        if (modelStatus && fixedInfraModels) {
            modelStatus.textContent = 'Модели зафиксированы политикой OUROBOROS_FIXED_INFRA_MODELS (режим только чтение).';
            modelStatus.dataset.tone = 'muted';
        }
    }

    function applySettings(s) {
        setupContract = s?._meta?.setup_contract || setupContract || {};
        fixedInfraModels = Boolean(s?._meta?.fixed_infra_models);
        applySecretInputs(page, s);
        INPUT_FIELDS.forEach(([id, key, fallback = '']) => applyInputValue(id, fallback && !s[key] ? fallback : s[key]));
        VALUE_FIELDS.forEach(([id, key, fallback]) => { byId(id).value = s[key] || fallback; });
        setupModelSlots().forEach((slot) => {
            applyInputValue(slot.settingsInputId, s[slot.settingKey]);
            applyCheckboxValue(slot.settingsToggleId, s[`USE_LOCAL_${slot.slot.toUpperCase()}`]);
        });
        applyCheckboxValue('s-auto-grant-reviewed-skills', s.OUROBOROS_AUTO_GRANT_REVIEWED_SKILLS);
        // Owner-facing mutative-subagents control is explicit On/Off. Legacy empty
        // settings still display their effective runtime-mode default.
        const rawMutative = String(s.OUROBOROS_ALLOW_MUTATIVE_SUBAGENTS ?? '').trim().toLowerCase();
        const runtimeMode = String(s.OUROBOROS_RUNTIME_MODE || 'advanced').trim().toLowerCase();
        const mutativeInput = byId('s-allow-mutative-subagents');
        mutativeInput.dataset.rawValue = rawMutative;
        delete mutativeInput.dataset.effortTouched;
        mutativeInput.value =
            ({ true: 'on', false: 'off' }[rawMutative] || (runtimeMode === 'light' ? 'off' : 'on'));
        // Post-task evolution: one owner-facing selector maps to enable + cadence.
        const evoEnabled =
            ({ true: 'on', '1': 'on', on: 'on', false: 'off', '0': 'off', off: 'off' }[
                String(s.OUROBOROS_POST_TASK_EVOLUTION ?? '').trim().toLowerCase()] || 'off') === 'on';
        const evoCadence = String(s.OUROBOROS_POST_TASK_EVOLUTION_CADENCE || 'llm').trim().toLowerCase();
        // Use the SAME strict shape as the backend (^every_n:[1-9]\d*$) so a stale/
        // malformed value (e.g. every_nonsense, every_n:0) displays as llm — never as
        // Every-N:3, which a later Save would silently persist as periodic evolution.
        const everyNMatch = evoCadence.match(/^every_n:([1-9]\d*)$/);
        if (!evoEnabled) {
            byId('s-post-task-evolution-mode').value = 'off';
        } else if (everyNMatch) {
            byId('s-post-task-evolution-mode').value = 'every_n';
            byId('s-evo-cadence-n').value = everyNMatch[1];
        } else {
            byId('s-post-task-evolution-mode').value = 'llm';
        }
        NUMBER_FIELDS.forEach(([id, key, fallback, allowFalsy]) => {
            const value = s[key];
            if (allowFalsy ? value !== null && value !== undefined : value) byId(id).value = value;
            else byId(id).value = fallback;
        });
        (Array.isArray(setupContract.budgetFields) ? setupContract.budgetFields : []).forEach((field) => {
            const id = field.settingsInputId;
            const input = byId(id);
            if (!input) return;
            input.min = field.min || '0.01';
            input.step = field.step || 'any';
            input.value = s[field.settingKey] ?? field.default ?? '';
        });
        applyMcpSettings(s);
        resetSecretClearFlags(page);
        syncEffortSegments(page);
        syncRuntimeModeBridgeState();
        applyFixedPolicyUi();
        syncPostTaskEvolutionUi();
    }

    function _renderNetworkHint(meta) {
        const hint = document.getElementById('settings-lan-hint');
        if (!hint || !meta) return;
        if (meta.reachability === 'loopback_only') {
            hint.innerHTML = 'Bound to <code>localhost</code>: only accessible from this machine. Set Server Bind Host to <code>0.0.0.0</code>, save, and restart for LAN access.';
            hint.dataset.tone = 'info';
            hint.hidden = false;
        } else if (meta.reachability === 'lan_reachable') {
            const url = escapeHtml(meta.recommended_url || '');
            const warning = escapeHtml(meta.warning || '');
            hint.innerHTML = `LAN URL: <a href="${url}" target="_blank" rel="noopener">${url}</a>${warning ? ' — <strong>' + warning + '</strong>' : ''}`;
            hint.dataset.tone = meta.warning ? 'warn' : 'ok';
            hint.hidden = false;
        } else if (meta.reachability === 'host_ip_unknown') {
            const url = escapeHtml(meta.recommended_url || '');
            const warning = escapeHtml(meta.warning || '');
            hint.innerHTML = `Server is listening on non-localhost but LAN IP could not be detected automatically. Try <code>${url}</code>.${warning ? ' <strong>' + warning + '</strong>' : ''}`;
            hint.dataset.tone = 'warn';
            hint.hidden = false;
        } else {
            hint.hidden = true;
        }
    }

    async function loadSettings() {
        const [data, extData] = await Promise.all([
            apiClient.settings(),
            apiClient.extensions().catch(() => ({})),
        ]);
        const sections = Array.isArray(extData?.live?.settings_sections)
            ? extData.live.settings_sections
            : [];
        currentSettings = data;
        applySettings(data);
        renderExtensionSettingsSections(page, sections);
        renderRequestedSkillSecrets(page, extData.skills || [], data);
        renderCustomSecrets(page, data);
        setSettingsCleanBaseline();
        closeSettingsModelPickers();
        _renderNetworkHint(data._meta);
        renderClaudeCodeUi();
        settingsLoaded = true;
        markSettingsDirty = updateSettingsDirtyState;
        syncSettingsLoadState();
        startClaudeCodePolling();
    }

    async function reloadSettingsWithFeedback() {
        setStatus('Загрузка настроек...', 'muted');
        settingsLoaded = false;
        syncSettingsLoadState();
        try {
            await loadSettings();
            try {
                await refreshModelCatalog();
                setStatus('Настройки загружены', 'ok');
            } catch (error) {
                setStatus(
                    `Настройки загружены. Не удалось обновить каталог моделей: ${error.message || error}`,
                    'warn'
                );
            }
        } catch (error) {
            settingsLoaded = false;
            syncSettingsLoadState();
            setStatus(
                `Не удалось загрузить текущие настройки. Сохранение недоступно до успешной перезагрузки: ${error.message || error}`,
                'warn'
            );
        }
    }

    async function refreshSettingsAfterExtensionChange(reason = 'навыки изменились') {
        if (extensionRefreshPending) return;
        if (settingsDirty) {
            setStatus(`Настройки изменились извне (${reason}). Перезагрузите после сохранения или отказа от черновика.`, 'warn');
            return;
        }
        extensionRefreshPending = true;
        try {
            await loadSettings();
            setStatus('Настройки обновлены', 'ok');
        } catch (error) {
            setStatus(`Не удалось обновить настройки: ${error.message || error}`, 'warn');
        } finally {
            extensionRefreshPending = false;
        }
    }

    function collectBody() {
        const fieldValue = (id) => byId(id)?.value || '';
        const mutativeInput = byId('s-allow-mutative-subagents');
        const rawMutative = String(mutativeInput?.dataset?.rawValue ?? '').trim().toLowerCase();
        const mutativeTouched = mutativeInput?.dataset?.effortTouched === '1';
        const body = {
            OUROBOROS_AUTO_GRANT_REVIEWED_SKILLS: byId('s-auto-grant-reviewed-skills')?.checked ? 'true' : 'false',
            OUROBOROS_ALLOW_MUTATIVE_SUBAGENTS: mutativeTouched
                ? ({ on: 'true', off: 'false' }[mutativeInput?.value] ?? '')
                : (rawMutative ? ({ true: 'true', false: 'false' }[rawMutative] ?? rawMutative) : ''),
            ...collectMcpSettings(),
        };
        if (!fixedInfraModels) {
            setupModelSlots().forEach((slot) => {
                body[slot.settingKey] = fieldValue(slot.settingsInputId);
                body[`USE_LOCAL_${slot.slot.toUpperCase()}`] = Boolean(byId(slot.settingsToggleId)?.checked);
            });
        }
        INPUT_FIELDS.forEach(([id, key, fallback = '']) => {
            if (fixedInfraModels && MODEL_LOCKED_SETTING_KEYS.has(key)) return;
            const value = fieldValue(id).trim();
            body[key] = key === 'OUROBOROS_SERVER_HOST' ? value || fallback : value || (key === 'CLAUDE_CODE_MODEL' ? fallback : '');
        });
        VALUE_FIELDS
            .filter(([, key]) => key !== 'OUROBOROS_RUNTIME_MODE' && key !== 'OUROBOROS_CONTEXT_MODE')
            .forEach(([id, key]) => { body[key] = fieldValue(id); });
        NUMBER_FIELDS.forEach(([id, key, fallback]) => { body[key] = readInt(id, fallback); });
        (Array.isArray(setupContract.budgetFields) ? setupContract.budgetFields : []).forEach((field) => {
            const id = field.settingsInputId;
            const input = byId(id);
            if (!input) return;
            const raw = String(input.value || '').trim();
            const parsed = Number(raw);
            const value = Number.isFinite(parsed) && parsed > 0 ? parsed : raw;
            if (String(value) !== String(currentSettings?.[field.settingKey] ?? field.default)) {
                body[field.settingKey] = value;
            }
        });
        // Post-task evolution: compose the legacy enable + cadence settings from
        // the single owner-facing selector.
        const evoCadMode = byId('s-post-task-evolution-mode').value;
        body.OUROBOROS_POST_TASK_EVOLUTION = evoCadMode === 'off' ? 'false' : 'true';
        body.OUROBOROS_POST_TASK_EVOLUTION_CADENCE = evoCadMode === 'every_n'
            ? `every_n:${Math.max(1, parseInt(byId('s-evo-cadence-n').value, 10) || 3)}`
            : 'llm';

        page.querySelectorAll('[data-secret-setting]').forEach((input) => {
            collectSecretValue(input.id, body);
        });
        page.querySelectorAll('[data-custom-secret-row]').forEach((row) => {
            const keyInput = row.querySelector('[data-custom-secret-key]');
            const valueInput = row.querySelector('[data-custom-secret-value]');
            const key = (keyInput?.value || '').trim().toUpperCase();
            const error = row.querySelector('[data-custom-secret-error]');
            if (!key) return;
            if (!/^[A-Z][A-Z0-9_]{2,}$/.test(key)) { if (error) { error.hidden = false; error.textContent = 'Используйте заглавные латинские буквы, цифры и подчёркивания.'; } return; }
            if (row.dataset.removeCustomSecret === '1' || valueInput?.dataset.forceClear === '1') { body[key] = ''; return; }
            const value = valueInput?.value || '';
            if (value && !value.includes('...')) body[key] = value;
        });

        return body;
    }

    async function saveRuntimeModeViaNativeBridgeIfNeeded() {
        const nextMode = byId('s-runtime-mode').value || 'advanced';
        const currentMode = currentSettings?.OUROBOROS_RUNTIME_MODE || 'advanced';
        const bridge = window.pywebview?.api?.request_runtime_mode_change;
        if (nextMode === currentMode) {
            return bridge ? await bridge(nextMode) : await apiClient.ownerRuntimeMode(nextMode);
        }
        const result = bridge
            ? await bridge(nextMode)
            : (confirm(`Сменить режим Ouroboros с ${currentMode} на ${nextMode}? Изменение применится после перезапуска.`)
                ? await apiClient.ownerRuntimeMode(nextMode)
                : { ok: false, error: 'Смена режима отменена.' });
        if (!result || result.ok !== true) {
            throw new Error(result?.error || 'Смена режима была отменена.');
        }
        return result;
    }

    async function saveAutoGrantViaNativeBridgeIfNeeded() {
        const checkbox = byId('s-auto-grant-reviewed-skills');
        if (!checkbox) return null;
        const nextEnabled = Boolean(checkbox.checked);
        const currentEnabled = isTruthySetting(currentSettings?.OUROBOROS_AUTO_GRANT_REVIEWED_SKILLS);
        if (nextEnabled === currentEnabled) return null;
        const bridge = window.pywebview?.api?.request_auto_grant_reviewed_skills_change;
        const result = bridge
            ? await bridge(nextEnabled)
            : (confirm(`${nextEnabled ? 'Включить' : 'Выключить'} авто-выдачу доступа для проверенных навыков? Применяется только после свежей исполнимой проверки для текущего хэша содержимого.`)
                ? await apiClient.ownerAutoGrant(nextEnabled)
                : { ok: false, error: 'Изменение авто-выдачи отменено.' });
        if (!result || result.ok !== true) {
            throw new Error(result?.error || 'Изменение авто-выдачи было отменено.');
        }
        return result;
    }

    async function saveContextModeViaOwnerEndpointIfNeeded() {
        const input = byId('s-context-mode');
        if (!input) return null;
        const next = input.value || 'max';
        const current = currentSettings?.OUROBOROS_CONTEXT_MODE || 'max';
        if (next === current) return null;
        // Owner-only + hot-apply (next task, no restart). Max needs the active model's
        // 1M-token window confirmed; on a 409 needs_ack, share the chat-toggle's ack flow
        // (CW8) — confirm, POST the route-scoped capability-ack, retry — instead of a
        // generic failure.
        try {
            const result = await apiClient.ownerContextMode(next);
            if (!result || result.ok !== true) {
                throw new Error(result?.error || 'Context mode change failed.');
            }
            return result;
        } catch (e) {
            const ack = (e && e.status === 409 && e.body && e.body.needs_ack) ? e.body.needs_ack : null;
            if (!(next === 'max' && ack && ack.model)) {
                throw e;
            }
            const confirmed = window.confirm(
                `${(e.body && e.body.error) || 'Max context mode needs a confirmed 1M-token window.'}\n\n` +
                `Confirm that this model supports a 1,000,000-token context window?\n` +
                `  provider: ${ack.provider || '(default)'}\n  model: ${ack.model}\n` +
                `  base_url: ${ack.base_url || '(default)'}\n\n` +
                `This applies only to this exact model/provider and is removed if you change it.`
            );
            if (!confirmed) {
                throw new Error('Max context mode was not confirmed.');
            }
            // Throws on a non-ok ack (surfaced by the save handler's catch).
            await apiClient.ownerCapabilityAck({
                provider: ack.provider, model: ack.model, base_url: ack.base_url,
                window_tokens: 1000000, note: 'owner-confirmed via settings save',
            });
            const retry = await apiClient.ownerContextMode(next);
            if (!retry || retry.ok !== true) {
                throw new Error(retry?.error || 'Context mode change failed after confirmation.');
            }
            return retry;
        }
    }

    syncSettingsLoadState();
    syncRuntimeModeBridgeState();
    syncAutoGrantBridgeState();
    window.addEventListener('pywebviewready', () => {
        syncRuntimeModeBridgeState();
        syncAutoGrantBridgeState();
    });
    [250, 1000, 2500].forEach((delay) => {
        setTimeout(() => {
            syncRuntimeModeBridgeState();
            syncAutoGrantBridgeState();
        }, delay);
    });
    reloadSettingsWithFeedback();

    if (typeof setBeforePageLeave === 'function') {
        setBeforePageLeave(({ from }) => {
            if (from !== 'settings' || !settingsDirty) return true;
            const leave = confirm('Есть несохранённые изменения настроек. Отбросить их и выйти из Настроек?');
            if (leave) discardUnsavedSettingsDraft();
            return leave;
        });
    }

    byId('s-anthropic')?.addEventListener('input', () => {
        renderClaudeCodeUi();
        if (anthropicKeyConfigured()) {
            startClaudeCodePolling();
            refreshClaudeCodeStatus();
        }
    });

    page.addEventListener('input', updateSettingsDirtyState);
    page.addEventListener('change', updateSettingsDirtyState);
    page.addEventListener('click', (event) => {
        if (event.target.closest('[data-effort-value], .secret-clear, [data-row-secret-clear], [data-custom-secret-remove]')) {
            queueMicrotask(() => {
                syncPostTaskEvolutionUi();
                updateSettingsDirtyState();
            });
        }
    });
    byId('btn-add-custom-secret')?.addEventListener('click', () => {
        const host = byId('custom-secrets-list');
        if (!host) return;
        if (host.querySelector('.muted')) host.innerHTML = '';
        const row = customSecretRow();
        host.appendChild(row);
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.querySelector('[data-custom-secret-key]')?.focus();
        markSettingsDirty();
    });

    window.addEventListener('ouro:skill-lifecycle', (event) => {
        const action = String(event.detail?.action || 'skills changed');
        refreshSettingsAfterExtensionChange(action);
    });
    window.addEventListener('ouro:settings-updated', (event) => {
        if (event.detail?.source === 'settings') return;
        const action = String(event.detail?.reason || 'settings changed');
        refreshSettingsAfterExtensionChange(action);
    });
    if (ws && typeof ws.on === 'function') {
        ws.on('extension_lifecycle', (event) => {
            const action = String(event?.action || 'extension lifecycle');
            refreshSettingsAfterExtensionChange(action);
        });
    }

    window.addEventListener('ouro:page-shown', (event) => {
        if (event.detail?.page === 'settings') refreshSettingsAfterExtensionChange('settings page shown');
    });

    function closeSettingsModelPickers(exceptPicker = null) {
        page.querySelectorAll('[data-model-picker]').forEach((picker) => {
            if (picker === exceptPicker) return;
            const panel = picker.querySelector('.model-picker-results');
            if (!panel) return;
            panel.hidden = true;
            panel.innerHTML = '';
        });
    }

    function renderSettingsModelPicker(input) {
        if (!input || input.disabled) return;
        const picker = input.closest('[data-model-picker]');
        const panel = picker?.querySelector('.model-picker-results');
        if (!picker || !panel) return;
        const needle = String(input.value || '').trim().toLowerCase();
        let items = settingsModelCatalogItems
            .filter((item) => {
                const haystack = `${item.value} ${item.label || ''} ${item.provider || ''}`.toLowerCase();
                return !needle || haystack.includes(needle);
            })
            .slice(0, 8);
        if (!items.length && needle) {
            items = settingsModelCatalogItems.slice(0, 8);
        }
        if (!items.length) {
            panel.hidden = true;
            panel.innerHTML = '';
            return;
        }
        panel.innerHTML = items.map((item) => `
            <button type="button" class="model-picker-item" data-value="${escapeHtml(item.value)}">
                <span class="model-picker-item-value">${escapeHtml(item.value)}</span>
                <span class="model-picker-item-label">${escapeHtml(item.label || item.provider || 'Catalog model')}</span>
            </button>
        `).join('');
        panel.hidden = false;
    }

    page.addEventListener('focusin', (event) => {
        const input = event.target instanceof Element
            ? event.target.closest('[data-model-picker] input')
            : null;
        if (!input) return;
        if (input.disabled) {
            closeSettingsModelPickers();
            return;
        }
        const picker = input.closest('[data-model-picker]');
        closeSettingsModelPickers(picker);
        renderSettingsModelPicker(input);
    });
    page.dataset.modelPickerBound = '1';

    page.addEventListener('input', (event) => {
        const input = event.target instanceof Element
            ? event.target.closest('[data-model-picker] input')
            : null;
        if (!input) return;
        if (input.disabled) return;
        const picker = input.closest('[data-model-picker]');
        closeSettingsModelPickers(picker);
        renderSettingsModelPicker(input);
    });

    page.addEventListener('mousedown', (event) => {
        const item = event.target instanceof Element
            ? event.target.closest('.model-picker-item')
            : null;
        if (item) {
            const picker = item.closest('[data-model-picker]');
            const input = picker?.querySelector('input');
            if (input && !input.disabled) {
                event.preventDefault();
                input.value = item.dataset.value || '';
                closeSettingsModelPickers();
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
            return;
        }
        if (!(event.target instanceof Element) || !event.target.closest('[data-model-picker]')) {
            closeSettingsModelPickers();
        }
    });

    document.addEventListener('settings-model-catalog:updated', (event) => {
        const items = Array.isArray(event.detail?.items) ? event.detail.items : [];
        settingsModelCatalogItems = items.length
            ? items.map((item) => ({
                value: item.value || item.id || '',
                label: item.label || item.provider || 'Catalog model',
                provider: item.provider || '',
            })).filter((item) => item.value)
            : SETTINGS_FALLBACK_MODELS.map((value) => ({ value, label: 'Suggested model' }));
        page.querySelectorAll('[data-model-picker]').forEach((picker) => {
            const panel = picker.querySelector('.model-picker-results');
            if (panel && !panel.hidden) {
                const input = picker.querySelector('input');
                renderSettingsModelPicker(input);
            }
        });
    });

    page.addEventListener('click', (event) => {
        if (event.target.closest('.secret-clear[data-target="s-anthropic"]')) {
            queueMicrotask(() => {
                renderClaudeCodeUi();
                refreshClaudeCodeStatus();
            });
        }
    });

    byId('btn-claude-code-install')?.addEventListener('click', async () => {
        applyClaudeCodeStatus({
            installed: false,
            ready: false,
            busy: true,
            message: 'Восстановление среды Claude...',
            error: '',
        });
        try {
            const resp = await apiFetch('/api/claude-code/install', { method: 'POST' });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
            applyClaudeCodeStatus(data);
            setStatus(data.repaired ? 'Среда Claude восстановлена' : 'Среда Claude в актуальном состоянии', 'ok');
        } catch (error) {
            const message = String(error?.message || error || '');
            applyClaudeCodeStatus({
                installed: false,
                ready: false,
                busy: false,
                error: message,
                message: `Не удалось восстановить среду Claude: ${message}`,
            });
            setStatus('Не удалось восстановить среду Claude', 'warn');
        }
    });

    byId('btn-refresh-model-catalog').addEventListener('click', async () => {
        await refreshModelCatalog();
    });

    byId('btn-reload-settings')?.addEventListener('click', async () => {
        await reloadSettingsWithFeedback();
    });

    byId('btn-save-settings').addEventListener('click', async () => {
        if (!settingsLoaded) {
            setStatus('Перед сохранением успешно перезагрузите текущие настройки.', 'warn');
            return;
        }
        // Validate Every-N cadence before save: malformed N must NOT silently coerce
        // into a valid (e.g. every-task) cadence. Abort with a visible error instead.
        if (byId('s-post-task-evolution-mode')?.value === 'every_n'
            && !/^[1-9]\d*$/.test((byId('s-evo-cadence-n')?.value || '').trim())) {
            setStatus('Every-N cadence needs a whole number ≥ 1.', 'warn');
            return;
        }
        const body = collectBody();

        try {
            const data = await apiClient.saveSettings(body);
            let runtimeModeResult = null;
            let runtimeModeError = '';
            let autoGrantResult = null;
            let autoGrantError = '';
            let contextModeResult = null;
            let contextModeError = '';
            try {
                runtimeModeResult = await saveRuntimeModeViaNativeBridgeIfNeeded();
            } catch (error) {
                runtimeModeError = error.message || String(error);
            }
            try {
                autoGrantResult = await saveAutoGrantViaNativeBridgeIfNeeded();
            } catch (error) {
                autoGrantError = error.message || String(error);
            }
            try {
                contextModeResult = await saveContextModeViaOwnerEndpointIfNeeded();
            } catch (error) {
                contextModeError = error.message || String(error);
            }
            await loadSettings();
            syncAutoGrantBridgeState();
            let statusMsg;
            let statusType = 'ok';
            if (data.no_changes) {
                statusMsg = 'Изменений не обнаружено';
            } else if (data.restart_required) {
                statusMsg = 'Настройки сохранены. Некоторые изменения требуют перезапуска';
                statusType = 'warn';
            } else if (data.immediate_changed && data.next_task_changed) {
                statusMsg = 'Настройки сохранены. Часть изменений применилась сразу; остальные — со следующей задачи';
            } else if (data.immediate_changed) {
                statusMsg = 'Настройки сохранены. Изменения применены сразу';
            } else {
                statusMsg = 'Настройки сохранены. Изменения применятся со следующей задачи';
            }
            if (data.warnings && data.warnings.length) {
                statusMsg += ' ⚠️ ' + data.warnings.join(' | ');
                statusType = 'warn';
            }
            if (data.context_mode_downgraded) {
                // The new model can't sustain Max, so context mode auto-dropped to Low.
                statusMsg = `${statusMsg} ${data.notice || 'Context mode switched to Low.'}`;
                statusType = 'warn';
            }
            if (runtimeModeResult?.restart_required) {
                statusMsg = `${statusMsg} Режим работы сохранён как ${runtimeModeResult.runtime_mode}; требуется перезапуск.`;
                statusType = 'warn';
            }
            if (runtimeModeError) {
                statusMsg = `${statusMsg} Режим работы не был изменён: ${runtimeModeError}`;
                statusType = 'warn';
            }
            if (autoGrantResult) {
                statusMsg = `${statusMsg} Авто-выдача для проверенных навыков ${autoGrantResult.enabled ? 'включена' : 'выключена'}.`;
            }
            if (contextModeResult?.context_mode) {
                statusMsg = `${statusMsg} Context mode saved as ${contextModeResult.context_mode}.`;
            }
            if (contextModeError) {
                statusMsg = `${statusMsg} Context mode was not changed: ${contextModeError}`;
                statusType = 'warn';
            }
            if (autoGrantError) {
                statusMsg = `${statusMsg} Авто-выдача для проверенных навыков не была изменена: ${autoGrantError}`;
                statusType = 'warn';
            }
            setStatus(statusMsg, statusType);
            window.dispatchEvent(new CustomEvent('ouro:settings-updated', { detail: { reason: 'settings saved', source: 'settings' } }));
        } catch (e) {
            setStatus('Не удалось сохранить: ' + e.message, 'warn');
        }
    });

    byId('btn-reset').addEventListener('click', async () => {
        if (!confirm('Будут удалены все рантайм-данные (состояние, память, логи, настройки), затем выполнится перезапуск.\nКод репозитория (агента) будет сохранён.\nНастройки провайдеров придётся ввести заново.\n\nПродолжить?')) return;
        try {
            const res = await apiFetch('/api/reset', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'ok') alert('Удалено: ' + (data.deleted.join(', ') || 'ничего') + '\nПерезапуск...');
            else alert('Ошибка: ' + (data.error || 'неизвестная ошибка'));
        } catch (e) {
            showToast('Сброс не удался: ' + e.message, 'error');
        }
    });

    return {
        activateTab: activateSettingsTab,
        page,
    };
}
