// Watchdog maintenance: pause the watchdog for one container, for a while
// (operator, 2026-09-26). Markup: the Maintenance tab of _auto_actions_modal.html.
// Routes: app/blueprints/automation_routes.py. Service:
// services/automation/maintenance.py. The same pauses are set from Discord.

// One pause, as a list entry the page can hold: text only, never markup.
// Pure, so node can run it (tests/js/maintenance.test.js).
function maintenanceEntry(container, pause, t, formatTime) {
    const until = formatTime(new Date(pause.until * 1000));
    return t('web.maintenance.until').replace('{container}', container).replace('{time}', until);
}

async function loadMaintenance() {
    try {
        const response = await fetch('/api/watchdog/maintenance');
        const data = await response.json();
        const select = document.getElementById('maintenanceContainer');
        select.innerHTML = '';
        (data.containers || []).forEach(name => {
            const option = document.createElement('option');
            option.value = name;
            option.textContent = name;
            select.appendChild(option);
        });
        const list = document.getElementById('maintenanceList');
        list.innerHTML = '';
        const entries = Object.entries(data.pauses || {});
        if (!entries.length) {
            const empty = document.createElement('li');
            empty.className = 'list-group-item text-muted';
            empty.textContent = t('web.maintenance.none');
            list.appendChild(empty);
            return;
        }
        entries.forEach(([container, pause]) => {
            const item = document.createElement('li');
            item.className = 'list-group-item d-flex justify-content-between align-items-center';
            const text = document.createElement('span');
            text.textContent = maintenanceEntry(container, pause, t, d => d.toLocaleString());
            const end = document.createElement('button');
            end.type = 'button';
            end.className = 'btn btn-sm btn-outline-success';
            end.textContent = t('web.maintenance.end');
            end.addEventListener('click', () => endMaintenance(container));
            item.appendChild(text);
            item.appendChild(end);
            list.appendChild(item);
        });
    } catch (error) {
        console.error('Loading the maintenance pauses failed:', error);
        showNotification(t('web.maintenance.failed'), 'error');
    }
}

async function startMaintenance() {
    const container = document.getElementById('maintenanceContainer').value;
    const minutes = parseInt(document.getElementById('maintenanceMinutes').value, 10);
    const response = await fetch('/api/watchdog/maintenance', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ container, minutes }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.success) {
        showNotification(t('web.maintenance.failed'), 'error');
        return;
    }
    showNotification(t('web.maintenance.started').replace('{container}', container), 'success');
    loadMaintenance();
}

async function endMaintenance(container) {
    const response = await fetch('/api/watchdog/maintenance/' + encodeURIComponent(container),
        { method: 'DELETE' });
    if (!response.ok) {
        showNotification(t('web.maintenance.failed'), 'error');
        return;
    }
    showNotification(t('web.maintenance.ended').replace('{container}', container), 'success');
    loadMaintenance();
}

if (typeof window !== 'undefined') {
    window.maintenanceEntry = maintenanceEntry;
}
