// Backup & restore of the whole configuration (operator, 2026-09-26).
// Markup: app/templates/_backup_settings.html. Routes:
// app/blueprints/backup_routes.py - each asks for the panel password again.
// The CSRF header is added by the page's fetch wrapper (_base.html).

// What a preview answer says, in words. Pure, so node can run it
// (tests/js/backup_restore.test.js).
function describeBackup(result, t) {
    const s = (result && result.summary) || {};
    return t('web.backup.preview_text')
        .replace('{date}', (result && result.created_at) || '?')
        .replace('{version}', (result && result.ddc_version) || '?')
        .replace('{containers}', s.containers || 0)
        .replace('{tasks}', s.tasks || 0)
        .replace('{rules}', s.rules || 0)
        .replace('{groups}', s.groups || 0);
}

// The message for a refused request: the reason the server gave, never raw HTML.
function backupErrorText(status, body, t) {
    if (status === 403) { return t('web.backup.wrong_password'); }
    if (status === 429) { return t('web.backup.rate_limited'); }
    if (body && body.error === 'refused') {
        return t('web.backup.refused').replace('{reason}', body.reason || '');
    }
    if (body && body.error === 'no_file') { return t('web.backup.no_file'); }
    return t('web.backup.failed');
}

function _backupForm(extra) {
    const form = new FormData();
    form.append('password', (document.getElementById('backupPassword') || {}).value || '');
    Object.entries(extra || {}).forEach(([key, value]) => form.append(key, value));
    return form;
}

async function _backupFail(response) {
    let body = null;
    try { body = await response.json(); } catch (e) { body = null; }
    showNotification(backupErrorText(response.status, body, t), 'error');
}

async function downloadBackup() {
    try {
        const response = await fetch('/api/config/backup', { method: 'POST', body: _backupForm() });
        if (!response.ok) { await _backupFail(response); return; }
        const blob = await response.blob();
        const match = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') || '');
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = match ? match[1] : 'ddc-backup.zip';
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(link.href);
    } catch (error) {
        console.error('Backup failed:', error);
        showNotification(t('web.backup.failed'), 'error');
    }
}

async function previewRestore() {
    const file = (document.getElementById('restoreFile') || {}).files;
    if (!file || !file[0]) { showNotification(t('web.backup.no_file'), 'error'); return; }
    const box = document.getElementById('restorePreview');
    box.classList.add('d-none');
    try {
        const response = await fetch('/api/config/restore/preview',
            { method: 'POST', body: _backupForm({ backup: file[0] }) });
        if (!response.ok) { await _backupFail(response); return; }
        document.getElementById('restorePreviewText').textContent = describeBackup(await response.json(), t);
        box.classList.remove('d-none');
    } catch (error) {
        console.error('Restore preview failed:', error);
        showNotification(t('web.backup.failed'), 'error');
    }
}

async function applyRestore() {
    try {
        const response = await fetch('/api/config/restore/apply', { method: 'POST', body: _backupForm() });
        if (!response.ok) { await _backupFail(response); return; }
        showNotification(t('web.backup.restarting'), 'success');
        setTimeout(() => window.location.reload(), 30000);
    } catch (error) {
        console.error('Restore failed:', error);
        showNotification(t('web.backup.failed'), 'error');
    }
}

if (typeof window !== 'undefined') {
    window.describeBackup = describeBackup;
    window.backupErrorText = backupErrorText;
}
