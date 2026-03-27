// ============================================================================ //
// DockerDiscordControl (DDC) - Channel Translation JavaScript                //
// ============================================================================ //
// Handles AJAX operations for the Channel Translation inline UI.

let ctPairsData = [];
let ctLanguages = {};
let ctInitialized = false;

// --- Utility ---

function ctEscapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function ctShowAlert(message, type) {
    // Show visible notification to user
    if (typeof showNotification === 'function') {
        showNotification(message, type);
        return;
    }
    if (typeof showAlert === 'function') {
        showAlert(message, type);
        return;
    }
    // Fallback: create a visible alert in the CT section
    const container = document.getElementById('ctCollapseSection');
    if (container) {
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type === 'danger' ? 'danger' : type === 'warning' ? 'warning' : 'success'} alert-dismissible fade show mt-2`;
        alertDiv.innerHTML = `${ctEscapeHtml(message)}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>`;
        container.prepend(alertDiv);
        setTimeout(() => alertDiv.remove(), 5000);
    }
}

async function ctFetch(url, options = {}) {
    // Wrapper that validates HTTP response before parsing JSON
    // Ensure credentials are sent (Basic Auth session)
    options.credentials = 'same-origin';
    const resp = await fetch(url, options);
    if (resp.status === 401) {
        throw new Error('Authentication required — please reload the page and log in');
    }
    if (!resp.ok && resp.status !== 400 && resp.status !== 404) {
        throw new Error(`Server error (HTTP ${resp.status})`);
    }
    return await resp.json();
}

// --- Load Languages ---

async function loadCTLanguages() {
    try {
        const data = await ctFetch('/api/translation/languages');
        ctLanguages = data.languages || {};
        populateLanguageDropdowns();
    } catch (e) {
        console.error('Failed to load languages:', e);
    }
}

function populateLanguageDropdowns() {
    const selects = ['ctTargetLanguage', 'ctTestTargetLang'];
    for (const id of selects) {
        const el = document.getElementById(id);
        if (!el) continue;
        el.innerHTML = '';
        for (const [code, name] of Object.entries(ctLanguages)) {
            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = `${name} (${code})`;
            if (code === 'DE') opt.selected = true;
            el.appendChild(opt);
        }
    }

    // Source language dropdown (with auto-detect option)
    const srcEl = document.getElementById('ctSourceLanguage');
    if (srcEl) {
        srcEl.innerHTML = `<option value="">${t('ct.auto_detect')}</option>`;
        for (const [code, name] of Object.entries(ctLanguages)) {
            const opt = document.createElement('option');
            opt.value = code;
            opt.textContent = `${name} (${code})`;
            srcEl.appendChild(opt);
        }
    }
}

// --- Load Pairs ---

async function loadCTPairs() {
    // Load languages if not yet loaded
    if (Object.keys(ctLanguages).length === 0) {
        await loadCTLanguages();
    }

    try {
        const data = await ctFetch('/api/translation/pairs');
        ctPairsData = data.pairs || [];
        renderCTPairs();
    } catch (e) {
        console.error('Failed to load CT pairs:', e);
        document.getElementById('ctPairsList').innerHTML =
            `<div class="text-center py-3 text-danger bg-dark"><i class="bi bi-exclamation-triangle"></i> ${t('ct.failed_load_pairs')}</div>`;
    }
}

function renderCTPairs() {
    const container = document.getElementById('ctPairsList');
    const searchTerm = (document.getElementById('ctPairSearch')?.value || '').toLowerCase();

    const filtered = ctPairsData.filter(p =>
        !searchTerm || p.name.toLowerCase().includes(searchTerm)
    );

    if (filtered.length === 0) {
        container.innerHTML = `
            <div class="text-center py-4 text-muted">
                <i class="bi bi-translate" style="font-size: 2rem;"></i>
                <div class="mt-2">${searchTerm ? t('ct.no_matching_pairs') : t('ct.no_pairs_configured')}</div>
                <div class="mt-1"><small>${t('ct.click_add_pair')}</small></div>
            </div>`;
        return;
    }

    container.innerHTML = filtered.map(pair => {
        const safeId = ctEscapeHtml(pair.id);
        const safeSrcLang = ctEscapeHtml(pair.source_language || '');
        const safeTgtLang = ctEscapeHtml(pair.target_language || '');
        const langBadge = pair.source_language
            ? `${safeSrcLang} <i class="bi bi-arrow-right"></i> ${safeTgtLang}`
            : `${t('ct.auto')} <i class="bi bi-arrow-right"></i> ${safeTgtLang}`;
        const count = pair.metadata?.translation_count || 0;
        const enabledClass = pair.enabled ? 'border-start border-3 border-primary' : 'opacity-50';
        const embedBadge = pair.translate_embeds
            ? '<span class="badge bg-info ms-1">+Embeds</span>'
            : '';

        return `
            <div class="list-group-item list-group-item-action bg-dark text-light ${enabledClass}" style="cursor:pointer;" onclick="openCTPairEditor('${safeId}')">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>${ctEscapeHtml(pair.name)}</strong>
                        <span class="badge bg-secondary ms-2">${langBadge}</span>
                        ${embedBadge}
                    </div>
                    <div class="d-flex align-items-center gap-2">
                        <small class="text-muted">${count} ${t('ct.translations_count')}</small>
                        <div class="form-check form-switch mb-0" onclick="event.stopPropagation();">
                            <input class="form-check-input" type="checkbox" ${pair.enabled ? 'checked' : ''}
                                onchange="toggleCTPair('${safeId}')">
                        </div>
                    </div>
                </div>
                <small class="text-muted">
                    <i class="bi bi-hash"></i> ${ctEscapeHtml(pair.source_channel_id)}
                    <i class="bi bi-arrow-right mx-1"></i>
                    <i class="bi bi-hash"></i> ${ctEscapeHtml(pair.target_channel_id)}
                </small>
            </div>`;
    }).join('');
}

function filterCTPairs() {
    renderCTPairs();
}

// --- Pair Editor ---

function openCTPairEditor(pairId) {
    const form = document.getElementById('ctPairForm');
    form.reset();
    document.getElementById('ctPairId').value = '';
    document.getElementById('ctDeletePairBtn').style.display = 'none';
    document.getElementById('ctPairEditorTitle').innerHTML = `<i class="bi bi-arrow-left-right"></i> ${t('ct.new_pair_title')}`;
    document.getElementById('ctTranslateEmbeds').checked = true;
    document.getElementById('ctPairEnabled').checked = true;

    if (pairId) {
        const pair = ctPairsData.find(p => p.id === pairId);
        if (pair) {
            document.getElementById('ctPairEditorTitle').innerHTML = `<i class="bi bi-pencil"></i> ${t('ct.edit_pair_title')}`;
            document.getElementById('ctPairId').value = pair.id;
            document.getElementById('ctPairName').value = pair.name;
            document.getElementById('ctSourceChannelId').value = pair.source_channel_id;
            document.getElementById('ctTargetChannelId').value = pair.target_channel_id;
            document.getElementById('ctTargetLanguage').value = pair.target_language;
            document.getElementById('ctSourceLanguage').value = pair.source_language || '';
            document.getElementById('ctTranslateEmbeds').checked = pair.translate_embeds;
            document.getElementById('ctPairEnabled').checked = pair.enabled;
            document.getElementById('ctDeletePairBtn').style.display = 'inline-block';
        }
    }

    const editorModal = new bootstrap.Modal(document.getElementById('ctPairEditorModal'));
    editorModal.show();
}

function closeCTPairEditor() {
    const modal = bootstrap.Modal.getInstance(document.getElementById('ctPairEditorModal'));
    if (modal) modal.hide();
}

// --- Save Pair ---

async function saveCTPair() {
    const pairId = document.getElementById('ctPairId').value;
    const pairData = {
        name: document.getElementById('ctPairName').value.trim(),
        source_channel_id: document.getElementById('ctSourceChannelId').value.trim(),
        target_channel_id: document.getElementById('ctTargetChannelId').value.trim(),
        target_language: document.getElementById('ctTargetLanguage').value,
        source_language: document.getElementById('ctSourceLanguage').value || null,
        translate_embeds: document.getElementById('ctTranslateEmbeds').checked,
        enabled: document.getElementById('ctPairEnabled').checked
    };

    if (!pairData.name) {
        ctShowAlert(t('ct.pair_name_required'), 'danger');
        return;
    }
    if (!pairData.source_channel_id || !/^\d{17,19}$/.test(pairData.source_channel_id)) {
        ctShowAlert(t('ct.source_channel_id_invalid'), 'danger');
        return;
    }
    if (!pairData.target_channel_id || !/^\d{17,19}$/.test(pairData.target_channel_id)) {
        ctShowAlert(t('ct.target_channel_id_invalid'), 'danger');
        return;
    }
    if (pairData.source_channel_id === pairData.target_channel_id) {
        ctShowAlert(t('ct.channels_cannot_be_same'), 'danger');
        return;
    }
    if (!pairData.target_language) {
        ctShowAlert(t('ct.target_language_required'), 'danger');
        return;
    }

    try {
        const url = pairId ? `/api/translation/pairs/${pairId}` : '/api/translation/pairs';
        const method = pairId ? 'PUT' : 'POST';

        const result = await ctFetch(url, {
            method: method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(pairData)
        });

        if (result.success) {
            ctShowAlert(pairId ? t('ct.pair_updated') : t('ct.pair_created'), 'success');
            closeCTPairEditor();
            await loadCTPairs();
        } else {
            ctShowAlert(result.error || t('ct.failed_save_pair'), 'danger');
        }
    } catch (e) {
        ctShowAlert(t('ct.error_saving_pair') + ': ' + e.message, 'danger');
    }
}

// --- Delete Pair ---

async function deleteCTPair() {
    const pairId = document.getElementById('ctPairId').value;
    if (!pairId) return;

    if (!confirm(t('ct.confirm_delete_pair'))) return;

    try {
        const result = await ctFetch(`/api/translation/pairs/${pairId}`, { method: 'DELETE' });

        if (result.success) {
            ctShowAlert(t('ct.pair_deleted'), 'success');
            closeCTPairEditor();
            await loadCTPairs();
        } else {
            ctShowAlert(result.error || t('ct.failed_delete_pair'), 'danger');
        }
    } catch (e) {
        ctShowAlert(t('ct.error_deleting_pair') + ': ' + e.message, 'danger');
    }
}

// --- Toggle Pair ---

async function toggleCTPair(pairId) {
    try {
        const result = await ctFetch(`/api/translation/pairs/${pairId}/toggle`, { method: 'POST' });
        if (result.success) {
            await loadCTPairs();
        } else {
            ctShowAlert(result.error || 'Failed to toggle pair', 'danger');
            await loadCTPairs(); // Reload to reset checkbox state
        }
    } catch (e) {
        ctShowAlert('Error toggling pair', 'danger');
        await loadCTPairs(); // Reload to reset checkbox state
    }
}

// --- Global Toggle ---

async function toggleGlobalCT() {
    const enabled = document.getElementById('ctGlobalToggle').checked;
    try {
        // Load current settings from server, only change enabled flag
        const settingsData = await ctFetch('/api/translation/settings');
        const s = settingsData.settings || {};

        // Build clean settings object (only fields the server expects)
        const result = await ctFetch('/api/translation/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                provider: s.provider || 'deepl',
                deepl_api_url: s.deepl_api_url || 'https://api-free.deepl.com/v2/translate',
                rate_limit_per_minute: s.rate_limit_per_minute || 60,
                max_text_length: s.max_text_length || 5000,
                enabled: enabled
            })
        });
        if (result.success) {
            ctShowAlert(enabled ? t('ct.translation_enabled') : t('ct.translation_disabled'), 'success');
        }
    } catch (e) {
        ctShowAlert(t('ct.error_toggling') + ': ' + e.message, 'danger');
    }
}

// --- Settings ---

async function loadCTSettings() {
    try {
        const data = await ctFetch('/api/translation/settings');
        const s = data.settings || {};

        document.getElementById('ctGlobalToggle').checked = s.enabled || false;
        document.getElementById('ctProvider').value = s.provider || 'deepl';
        const apiKeyField = document.getElementById('ctApiKey');
        apiKeyField.value = ''; // Never show the actual key
        if (s.api_key_configured) {
            apiKeyField.placeholder = '\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022  (saved)';
        } else {
            apiKeyField.placeholder = 'Enter your API key...';
        }
        document.getElementById('ctDeeplUrl').value = s.deepl_api_url || 'https://api-free.deepl.com/v2/translate';
        document.getElementById('ctRateLimit').value = s.rate_limit_per_minute || 60;
        document.getElementById('ctMaxTextLength').value = s.max_text_length || 5000;
        document.getElementById('ctShowOriginalLink').checked = s.show_original_link !== false;
        document.getElementById('ctShowProviderFooter').checked = s.show_provider_footer !== false;
        updateDeeplTierVisibility();

        const statusEl = document.getElementById('ctApiKeyStatus');
        if (s.api_key_configured) {
            const source = s.api_key_source === 'env' ? 'environment variable' : 'config (encrypted)';
            statusEl.className = 'alert alert-success mb-0 py-2';
            statusEl.innerHTML = `<i class="bi bi-check-circle"></i> API key configured via <strong>${ctEscapeHtml(source)}</strong>.` +
                (s.api_key_source === 'config' ? ' Leave empty to keep current key.' : '');
        } else {
            statusEl.className = 'alert alert-warning mb-0 py-2';
            statusEl.innerHTML = '<i class="bi bi-exclamation-triangle"></i> No API key configured. Enter your key and click Save.';
        }
    } catch (e) {
        console.error('Failed to load CT settings:', e);
    }
}

async function saveCTSettings() {
    const apiKeyField = document.getElementById('ctApiKey');
    const apiKeyInput = apiKeyField.value.trim();
    let keySaved = false;

    // Save API key separately if provided
    if (apiKeyInput) {
        try {
            console.log('[CT] Saving API key...');
            const keyResult = await ctFetch('/api/translation/apikey', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ api_key: apiKeyInput })
            });
            console.log('[CT] API key save result:', keyResult);
            if (!keyResult.success) {
                ctShowAlert(keyResult.error || 'Failed to save API key', 'danger');
                return;
            }
            keySaved = true;
        } catch (e) {
            console.error('[CT] API key save error:', e);
            ctShowAlert('Error saving API key: ' + e.message, 'danger');
            return;
        }
    }

    // Save other settings
    const settingsData = {
        provider: document.getElementById('ctProvider').value,
        deepl_api_url: document.getElementById('ctDeeplUrl').value,
        rate_limit_per_minute: parseInt(document.getElementById('ctRateLimit').value) || 60,
        max_text_length: parseInt(document.getElementById('ctMaxTextLength').value) || 5000,
        enabled: document.getElementById('ctGlobalToggle').checked,
        show_original_link: document.getElementById('ctShowOriginalLink').checked,
        show_provider_footer: document.getElementById('ctShowProviderFooter').checked
    };

    try {
        console.log('[CT] Saving settings...', settingsData);
        const result = await ctFetch('/api/translation/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settingsData)
        });
        console.log('[CT] Settings save result:', result);
        if (result.success) {
            ctShowAlert(keySaved ? t('ct.settings_and_key_saved') : t('ct.settings_saved'), 'success');
            if (keySaved) {
                apiKeyField.value = ''; // Only clear after confirmed save
            }
            await loadCTSettings();
        } else {
            ctShowAlert(result.error || 'Failed to save settings', 'danger');
        }
    } catch (e) {
        console.error('[CT] Settings save error:', e);
        ctShowAlert('Error saving settings: ' + e.message, 'danger');
    }
}

function toggleCtApiKeyVisibility() {
    const input = document.getElementById('ctApiKey');
    const icon = document.getElementById('ctApiKeyEyeIcon');
    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'bi bi-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'bi bi-eye';
    }
}

function updateDeeplTierVisibility() {
    const provider = document.getElementById('ctProvider');
    const deeplGroup = document.getElementById('ctDeeplUrlGroup');
    if (provider && deeplGroup) {
        deeplGroup.style.display = provider.value === 'deepl' ? '' : 'none';
    }
}

// Auto-toggle on provider change
document.addEventListener('DOMContentLoaded', function() {
    const provider = document.getElementById('ctProvider');
    if (provider) {
        provider.addEventListener('change', updateDeeplTierVisibility);
    }
});

// --- Test Translation ---

async function testCTTranslation() {
    const text = document.getElementById('ctTestInput').value.trim();
    const targetLang = document.getElementById('ctTestTargetLang').value;

    if (!text) {
        ctShowAlert(t('ct.enter_text_to_translate'), 'warning');
        return;
    }

    const resultDiv = document.getElementById('ctTestResult');
    const resultText = document.getElementById('ctTestResultText');
    const resultMeta = document.getElementById('ctTestResultMeta');

    resultText.innerHTML = `<div class="spinner-border spinner-border-sm" role="status"></div> ${t('ct.translating')}`;
    resultDiv.style.display = 'block';
    resultMeta.textContent = '';

    try {
        const result = await ctFetch('/api/translation/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: text,
                target_language: targetLang
            })
        });

        if (result.success) {
            resultText.textContent = result.translated_text;
            resultText.style.color = '#ffffff';
            resultText.style.fontSize = '1.05em';
            resultText.style.padding = '4px 0';
            resultMeta.textContent = `Detected: ${result.detected_language || '?'} | Provider: ${result.provider} | ${result.characters_used} chars`;
        } else {
            resultText.innerHTML = `<span class="text-danger">${ctEscapeHtml(result.error)}</span>`;
        }
    } catch (e) {
        resultText.innerHTML = `<span class="text-danger">Error: ${ctEscapeHtml(e.message)}</span>`;
    }
}

async function testCTConnection() {
    document.getElementById('ctTestInput').value = 'Hello, this is a test message.';
    document.getElementById('ctTestTargetLang').value = 'DE';
    await testCTTranslation();
}

// --- Collapse Initialization ---

document.addEventListener('DOMContentLoaded', function() {
    const collapseEl = document.getElementById('ctCollapseSection');
    if (!collapseEl) return;

    // Load toggle state IMMEDIATELY (even before section is expanded)
    (async function() {
        try {
            const data = await ctFetch('/api/translation/settings');
            const s = data.settings || {};
            const toggle = document.getElementById('ctGlobalToggle');
            if (toggle) toggle.checked = s.enabled || false;
        } catch (e) {
            console.debug('[CT] Could not load initial toggle state:', e);
        }
    })();

    // Load full data when section is first expanded
    collapseEl.addEventListener('show.bs.collapse', async function() {
        if (!ctInitialized) {
            ctInitialized = true;
            await loadCTLanguages();
            await loadCTPairs();
            await loadCTSettings();
        }
    });

    // Rotate chevron icon on collapse toggle
    collapseEl.addEventListener('show.bs.collapse', function() {
        const icon = document.getElementById('ctCollapseIcon');
        if (icon) icon.className = 'bi bi-chevron-up ms-1 small';
    });
    collapseEl.addEventListener('hide.bs.collapse', function() {
        const icon = document.getElementById('ctCollapseIcon');
        if (icon) icon.className = 'bi bi-chevron-down ms-1 small';
    });
});
