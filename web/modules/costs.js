import { formatUsd2 } from './utils.js';
import { apiFetch } from './api_client.js';

export function initCosts({ state, mount }) {
    const page = document.createElement('div');
    page.id = 'page-costs';
    page.className = 'settings-embedded-content settings-costs-panel';
    page.innerHTML = `
        <div class="costs-scroll">
            <div class="costs-budget-card">
                <div class="costs-budget-head">
                    <h3 class="costs-budget-title">Бюджет</h3>
                    <button class="btn btn-default btn-sm costs-budget-refresh" id="btn-refresh-costs">Обновить</button>
                </div>
                <div class="costs-budget-fields">
                    <div class="form-field">
                        <label>Общий бюджет ($)</label>
                        <input id="s-budget" type="number" min="1" value="10">
                    </div>
                    <div class="form-field">
                        <label>Лимит на задачу ($)</label>
                        <input id="s-per-task-cost" type="number" min="1" value="20">
                        <div class="settings-inline-note">Мягкий порог. При его превышении Ouroboros получит запрос на завершение задачи вместо принудительного прекращения.</div>
                    </div>
                </div>
                <button class="btn btn-save costs-budget-save" id="btn-save-budget">Сохранить бюджет</button>
                <div id="budget-save-status" class="settings-inline-status"></div>
            </div>
            <div class="costs-stats-grid">
                <div class="stat-card"><div class="label">Всего потрачено</div><div class="value" id="cost-total">$0.00</div></div>
                <div class="stat-card"><div class="label">Всего вызовов</div><div class="value" id="cost-calls">0</div></div>
                <div class="stat-card"><div class="label">Топ модели</div><div class="value cost-top-model" id="cost-top-model">-</div></div>
            </div>
            <div class="costs-tables-grid">
                <div>
                    <h3 class="costs-table-label">По модели</h3>
                    <table class="cost-table" id="cost-by-model"><thead><tr><th>Модель</th><th>Вызовы</th><th>Стоимость</th><th></th></tr></thead><tbody></tbody></table>
                </div>
                <div>
                    <h3 class="costs-table-label">По API-ключу</h3>
                    <table class="cost-table" id="cost-by-key"><thead><tr><th>Ключ</th><th>Вызовы</th><th>Стоимость</th><th></th></tr></thead><tbody></tbody></table>
                </div>
                <div>
                    <h3 class="costs-table-label">По категории модели</h3>
                    <table class="cost-table" id="cost-by-model-cat"><thead><tr><th>Категория</th><th>Вызовы</th><th>Стоимость</th><th></th></tr></thead><tbody></tbody></table>
                </div>
                <div>
                    <h3 class="costs-table-label">По категории задачи</h3>
                    <table class="cost-table" id="cost-by-task-cat"><thead><tr><th>Категория</th><th>Вызовы</th><th>Стоимость</th><th></th></tr></thead><tbody></tbody></table>
                </div>
            </div>
        </div>
    `;
    mount.appendChild(page);

    function renderBreakdownTable(tableId, data, totalCost) {
        const tbody = document.querySelector('#' + tableId + ' tbody');
        tbody.innerHTML = '';
        const cell = (className, text, attrs = {}) => {
            const td = document.createElement('td');
            td.className = className;
            td.textContent = text;
            Object.entries(attrs).forEach(([key, value]) => td.setAttribute(key, value));
            return td;
        };
        for (const [name, info] of Object.entries(data)) {
            const pct = totalCost > 0 ? (info.cost / totalCost * 100) : 0;
            const tr = document.createElement('tr');
            const bar = document.createElement('progress');
            bar.className = 'cost-bar';
            bar.max = 100;
            bar.value = Math.min(100, pct);
            const tdBar = document.createElement('td');
            tdBar.className = 'cost-bar-cell';
            tdBar.appendChild(bar);
            tr.append(
                cell('cost-cell-name', name, { title: name }),
                cell('cost-cell-right', info.calls),
                cell('cost-cell-right', formatUsd2(info.cost)),
                tdBar,
            );
            tbody.appendChild(tr);
        }
        if (Object.keys(data).length === 0) {
            const tr = document.createElement('tr');
            tr.appendChild(cell('cost-empty-cell', 'Нет данных', { colspan: '4' }));
            tbody.appendChild(tr);
        }
    }

    async function loadCosts() {
        try {
            const resp = await apiFetch('/api/cost-breakdown');
            const d = await resp.json();
            document.getElementById('cost-total').textContent = formatUsd2(d.total_cost || 0);
            document.getElementById('cost-calls').textContent = d.total_calls || 0;
            const models = Object.entries(d.by_model || {});
            document.getElementById('cost-top-model').textContent = models.length > 0 ? models[0][0] : '-';
            renderBreakdownTable('cost-by-model', d.by_model || {}, d.total_cost);
            renderBreakdownTable('cost-by-key', d.by_api_key || {}, d.total_cost);
            renderBreakdownTable('cost-by-model-cat', d.by_model_category || {}, d.total_cost);
            renderBreakdownTable('cost-by-task-cat', d.by_task_category || {}, d.total_cost);
        } catch {}
    }

    async function loadBudget() {
        try {
            const resp = await apiFetch('/api/settings', { cache: 'no-store' });
            const s = await resp.json().catch(() => ({}));
            if (s.TOTAL_BUDGET != null) document.getElementById('s-budget').value = s.TOTAL_BUDGET;
            if (s.OUROBOROS_PER_TASK_COST_USD != null) document.getElementById('s-per-task-cost').value = s.OUROBOROS_PER_TASK_COST_USD;
        } catch {}
    }

    document.getElementById('btn-refresh-costs').addEventListener('click', loadCosts);

    document.getElementById('btn-save-budget').addEventListener('click', async () => {
        const statusEl = document.getElementById('budget-save-status');
        const budget = parseFloat(document.getElementById('s-budget').value) || 10;
        const perTask = parseFloat(document.getElementById('s-per-task-cost').value) || 20;
        try {
            const resp = await apiFetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ TOTAL_BUDGET: budget, OUROBOROS_PER_TASK_COST_USD: perTask }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
            let msg;
            if (data.no_changes) {
                msg = 'Без изменений.';
            } else if (data.restart_required) {
                msg = 'Сохранено. Требуется перезапуск.';
            } else if (data.immediate_changed && data.next_task_changed) {
                msg = 'Сохранено. Общий бюджет применён сразу; лимит на задачу применится со следующей задачи.';
            } else if (data.immediate_changed) {
                msg = 'Сохранено. Применено сразу.';
            } else {
                msg = 'Сохранено. Применится со следующей задачи.';
            }
            if (data.warnings && data.warnings.length) msg += ' ⚠️ ' + data.warnings.join(' | ');
            statusEl.textContent = msg;
        } catch (e) {
            statusEl.textContent = 'Ошибка: ' + e.message;
        }
        setTimeout(() => { statusEl.textContent = ''; }, 4000);
    });

    function refreshCostsPanel() {
        loadCosts();
        loadBudget();
    }

    window.addEventListener('ouro:dashboard-subtab-shown', (event) => {
        if (event.detail?.tab === 'costs' && state.activePage === 'dashboard') refreshCostsPanel();
    });
}
