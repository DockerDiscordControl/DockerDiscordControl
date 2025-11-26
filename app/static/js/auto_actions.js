/**
 * DockerDiscordControl - Auto-Action System (AAS)
 * Frontend Logic for Rule Management & Testing
 */

// State
let currentRuleId = null;
let allContainers = [];
let allChannels = [];  // {id, name, type} for feedback channel selection
let currentRuleData = null;  // Preserve full rule data for editing

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    // Load available containers and channels for dropdowns
    loadContainersForAAS();
    loadChannelsForAAS();

    // Load rules immediately for preview list
    loadAASRules();
    
    // Load global settings on modal open
    const modal = document.getElementById('autoActionsModal');
    if (modal) {
        modal.addEventListener('show.bs.modal', function () {
            loadAASGlobalSettings();
            // loadAASRules() is already called on page load, but refresh it to be sure
            loadAASRules();
        });
    }
});

function loadContainersForAAS() {
    // Get ACTIVE containers from the Docker container list table
    // Respects: 1) Order in table, 2) Only containers with "Active" checkbox checked
    const containerRows = document.querySelectorAll('#docker-container-list tr[data-container-name]');

    if (containerRows.length > 0) {
        allContainers = [];

        // Iterate in DOM order (preserves user-defined order from table)
        containerRows.forEach(row => {
            const containerName = row.getAttribute('data-container-name');
            // Check if the "Active" checkbox is checked (name="selected_servers")
            const activeCheckbox = row.querySelector('input[name="selected_servers"]');

            if (activeCheckbox && activeCheckbox.checked) {
                allContainers.push(containerName);
            }
        });

        console.log(`AAS: Loaded ${allContainers.length} active containers (of ${containerRows.length} total)`);
        return;
    }

    // Fallback: Get only checked server checkboxes (preserves order)
    const serverCheckboxes = document.querySelectorAll('input[name="selected_servers"]:checked');
    if (serverCheckboxes.length > 0) {
        allContainers = Array.from(serverCheckboxes).map(cb => cb.value);
        console.log(`AAS: Loaded ${allContainers.length} active containers from checkboxes`);
        return;
    }

    console.warn('AAS: No active containers found - container selection will be empty');
}

function loadChannelsForAAS() {
    // Get Status Channels and Control Channels from the permissions tables
    allChannels = [];

    // Status Channels
    const statusChannelRows = document.querySelectorAll('#status-channels-table tbody tr');
    statusChannelRows.forEach((row, idx) => {
        const nameInput = row.querySelector(`input[name^="status_channel_name_"]`);
        const idInput = row.querySelector(`input[name^="status_channel_id_"]`);
        if (nameInput && idInput && idInput.value.trim()) {
            allChannels.push({
                id: idInput.value.trim(),
                name: nameInput.value.trim() || `Status Channel ${idx + 1}`,
                type: 'status'
            });
        }
    });

    // Control Channels
    const controlChannelRows = document.querySelectorAll('#control-channels-table tbody tr');
    controlChannelRows.forEach((row, idx) => {
        const nameInput = row.querySelector(`input[name^="control_channel_name_"]`);
        const idInput = row.querySelector(`input[name^="control_channel_id_"]`);
        if (nameInput && idInput && idInput.value.trim()) {
            allChannels.push({
                id: idInput.value.trim(),
                name: nameInput.value.trim() || `Control Channel ${idx + 1}`,
                type: 'control'
            });
        }
    });

    console.log(`AAS: Loaded ${allChannels.length} channels (status + control)`);
}

// --- Rules Management ---

async function loadAASRules() {
    const listContainer = document.getElementById('aasRulesList');
    const previewContainer = document.getElementById('aasPreviewList');
    
    if (!listContainer && !previewContainer) return;
    
    try {
        const response = await fetch('/api/automation/rules');
        const data = await response.json();
        
        if (!data.rules) return;
        
        const html = data.rules.length === 0 ? 
            `<div class="text-center py-4 text-muted">No auto-actions configured yet.</div>` :
            data.rules.map(renderRuleItem).join('');
            
        if (listContainer) listContainer.innerHTML = html;
        
        // Update preview list (limit to 3 items)
        if (previewContainer) {
            const previewHtml = data.rules.length === 0 ?
                `<div class="list-group-item text-center text-muted py-3"><i class="bi bi-info-circle"></i> Click "Manage Auto-Actions" to configure rules.</div>` :
                data.rules.slice(0, 3).map(renderRuleItemPreview).join('') + 
                (data.rules.length > 3 ? `<div class="list-group-item text-center text-muted small">... and ${data.rules.length - 3} more</div>` : '');
            previewContainer.innerHTML = previewHtml;
        }
        
    } catch (error) {
        console.error('Error loading AAS rules:', error);
        if (listContainer) listContainer.innerHTML = `<div class="alert alert-danger">Failed to load rules.</div>`;
    }
}

function renderRuleItem(rule) {
    const badgeClass = rule.enabled ? 'bg-success' : 'bg-secondary';
    const statusText = rule.enabled ? 'Active' : 'Disabled';
    
    return `
    <div class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" onclick="openRuleEditor('${rule.id}')">
        <div>
            <div class="d-flex align-items-center gap-2">
                <h6 class="mb-0">${escapeHtml(rule.name)}</h6>
                <span class="badge ${badgeClass} rounded-pill">${statusText}</span>
                <span class="badge bg-light text-dark border">Priority: ${rule.priority}</span>
            </div>
            <small class="text-muted">
                <i class="bi bi-chat-left-text"></i> ${rule.trigger.keywords.length} Keywords 
                &bull; 
                <i class="bi bi-box-seam"></i> ${rule.action.type} -> ${rule.action.containers.join(', ')}
            </small>
        </div>
        <div class="text-end text-muted small">
            <div>Triggers: ${rule.metadata?.trigger_count || 0}</div>
            <i class="bi bi-chevron-right"></i>
        </div>
    </div>
    `;
}

function renderRuleItemPreview(rule) {
    return `
    <div class="list-group-item d-flex justify-content-between align-items-center">
        <div class="text-truncate">
            <i class="bi bi-robot text-primary"></i> ${escapeHtml(rule.name)}
        </div>
        <span class="badge ${rule.enabled ? 'bg-success' : 'bg-secondary'}">${rule.enabled ? 'ON' : 'OFF'}</span>
    </div>
    `;
}

function filterAASRules() {
    const searchTerm = document.getElementById('aasRuleSearch').value.toLowerCase();
    const ruleItems = document.querySelectorAll('#aasRulesList .list-group-item');

    ruleItems.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(searchTerm) ? '' : 'none';
    });
}

// --- Editor ---

async function openRuleEditor(ruleId = null) {
    currentRuleId = ruleId;
    currentRuleData = null;  // Reset stored rule data
    const modal = new bootstrap.Modal(document.getElementById('aasRuleEditorModal'));
    const deleteBtn = document.getElementById('aasDeleteBtn');
    const title = document.getElementById('aasEditorTitle');
    const form = document.getElementById('aasRuleForm');

    form.reset();
    document.getElementById('aasTestResult').innerHTML = '';

    // Reload containers if list is empty (may have loaded before DOM was ready)
    if (allContainers.length === 0) {
        loadContainersForAAS();
    }

    // Populate containers as checkboxes
    const containerWrapper = document.getElementById('aasRuleTargetContainersWrapper');
    if (allContainers.length > 0) {
        containerWrapper.innerHTML = allContainers.map((c, idx) => `
            <div class="form-check">
                <input class="form-check-input aas-container-checkbox" type="checkbox" value="${escapeHtml(c)}" id="aasContainer_${idx}">
                <label class="form-check-label" for="aasContainer_${idx}">
                    <code class="text-info">${escapeHtml(c)}</code>
                </label>
            </div>
        `).join('');
    } else {
        containerWrapper.innerHTML = '<div class="text-muted text-center py-2"><i class="bi bi-exclamation-triangle"></i> No active containers available</div>';
        console.error('AAS: No containers loaded for rule editor');
    }

    // Reload channels if list is empty (for feedback channel selection)
    if (allChannels.length === 0) {
        loadChannelsForAAS();
    }

    // Populate feedback channels as radio buttons
    const channelWrapper = document.getElementById('aasRuleFeedbackChannelsWrapper');
    let channelHtml = `
        <div class="form-check">
            <input class="form-check-input" type="radio" name="aasFeedbackChannel" value="" id="aasChannel_source" checked>
            <label class="form-check-label" for="aasChannel_source">
                <i class="bi bi-reply text-muted"></i> <em>Reply in source channel</em>
            </label>
        </div>
    `;

    if (allChannels.length > 0) {
        // Group by type
        const statusChannels = allChannels.filter(c => c.type === 'status');
        const controlChannels = allChannels.filter(c => c.type === 'control');

        if (statusChannels.length > 0) {
            channelHtml += `<div class="text-muted small mt-2 mb-1"><i class="bi bi-broadcast"></i> Status Channels</div>`;
            channelHtml += statusChannels.map((ch, idx) => `
                <div class="form-check">
                    <input class="form-check-input" type="radio" name="aasFeedbackChannel" value="${escapeHtml(ch.id)}" id="aasChannel_s${idx}">
                    <label class="form-check-label" for="aasChannel_s${idx}">
                        ${escapeHtml(ch.name)} <code class="text-muted small">${escapeHtml(ch.id)}</code>
                    </label>
                </div>
            `).join('');
        }

        if (controlChannels.length > 0) {
            channelHtml += `<div class="text-muted small mt-2 mb-1"><i class="bi bi-sliders"></i> Control Channels</div>`;
            channelHtml += controlChannels.map((ch, idx) => `
                <div class="form-check">
                    <input class="form-check-input" type="radio" name="aasFeedbackChannel" value="${escapeHtml(ch.id)}" id="aasChannel_c${idx}">
                    <label class="form-check-label" for="aasChannel_c${idx}">
                        ${escapeHtml(ch.name)} <code class="text-muted small">${escapeHtml(ch.id)}</code>
                    </label>
                </div>
            `).join('');
        }
    }

    channelWrapper.innerHTML = channelHtml;

    // Initialize Bootstrap tooltips for info icons
    const tooltipTriggerList = document.querySelectorAll('#aasRuleEditorModal [data-bs-toggle="tooltip"]');
    tooltipTriggerList.forEach(el => new bootstrap.Tooltip(el));

    if (ruleId) {
        // Edit Mode
        title.textContent = 'Edit Auto-Action';
        deleteBtn.style.display = 'block';

        try {
            const response = await fetch('/api/automation/rules');
            const data = await response.json();
            const rule = data.rules.find(r => r.id === ruleId);

            if (rule) {
                currentRuleData = rule;  // Store full rule data for preserving fields
                populateRuleForm(rule);
            }
        } catch (error) {
            console.error('Error loading rule details:', error);
            alert('Failed to load rule details');
            return;
        }
    } else {
        // Create Mode
        title.textContent = 'New Auto-Action';
        deleteBtn.style.display = 'none';
        document.getElementById('aasRuleId').value = '';
    }

    modal.show();
}

function populateRuleForm(rule) {
    document.getElementById('aasRuleId').value = rule.id;
    document.getElementById('aasRuleName').value = rule.name;
    document.getElementById('aasRulePriority').value = rule.priority;

    // Trigger - Monitored Channel IDs (simple text input)
    document.getElementById('aasRuleChannelIds').value = rule.trigger.channel_ids.join(', ');
    document.getElementById('aasRuleUsers').value = rule.trigger.source_filter.allowed_user_ids.join(', ');
    document.getElementById('aasRuleRequiredKeywords').value = (rule.trigger.required_keywords || []).join(', ');
    document.getElementById('aasRuleKeywords').value = rule.trigger.keywords.join(', ');
    document.getElementById('aasRuleMatchMode').value = rule.trigger.match_mode;
    document.getElementById('aasRuleIgnore').value = rule.trigger.ignore_keywords.join(', ');
    document.getElementById('aasRuleRegex').value = rule.trigger.regex_pattern || '';
    document.getElementById('aasRuleIsWebhook').checked = rule.trigger.source_filter.is_webhook === true;
    
    // Action
    document.getElementById('aasRuleActionType').value = rule.action.type;
    document.getElementById('aasRuleDelay').value = rule.action.delay_seconds;

    // Select feedback channel radio button
    const feedbackChannelId = rule.action.notification_channel_id || '';
    const feedbackRadios = document.querySelectorAll('input[name="aasFeedbackChannel"]');
    feedbackRadios.forEach(radio => {
        radio.checked = (radio.value === feedbackChannelId);
    });

    // Check container checkboxes
    const containerCheckboxes = document.querySelectorAll('.aas-container-checkbox');
    containerCheckboxes.forEach(cb => {
        cb.checked = rule.action.containers.includes(cb.value);
    });
    
    // Safety
    document.getElementById('aasRuleCooldown').value = rule.safety.cooldown_minutes;
    document.getElementById('aasRuleOnlyRunning').checked = rule.safety.only_if_running;
}

async function saveAASRule() {
    const ruleId = document.getElementById('aasRuleId').value;
    const isNew = !ruleId;

    // Edge Case: Validate rule name
    const ruleName = document.getElementById('aasRuleName').value.trim();
    if (!ruleName) {
        alert('Please enter a rule name.');
        document.getElementById('aasRuleName').focus();
        return;
    }

    // Gather selected containers from checkboxes
    const containers = Array.from(document.querySelectorAll('.aas-container-checkbox:checked')).map(cb => cb.value);

    if (containers.length === 0) {
        alert('Please select at least one target container.');
        return;
    }

    // Gather monitored channel IDs from text input
    const monitoredChannels = splitCsv(document.getElementById('aasRuleChannelIds').value);

    // Edge Case: Validate at least one channel ID is provided
    if (monitoredChannels.length === 0) {
        alert('Please enter at least one monitored channel ID.');
        document.getElementById('aasRuleChannelIds').focus();
        return;
    }

    // Edge Case: Validate at least one trigger condition is provided
    const requiredKeywords = splitCsv(document.getElementById('aasRuleRequiredKeywords').value);
    const keywords = splitCsv(document.getElementById('aasRuleKeywords').value);
    const regex = document.getElementById('aasRuleRegex').value.trim();
    if (requiredKeywords.length === 0 && keywords.length === 0 && !regex) {
        alert('Please enter at least one required keyword, trigger keyword, or regex pattern.');
        document.getElementById('aasRuleRequiredKeywords').focus();
        return;
    }

    // Preserve allowed_usernames from existing rule (if editing)
    // This field has no UI input, so we preserve it to avoid data loss
    const preservedUsernames = currentRuleData?.trigger?.source_filter?.allowed_usernames || [];

    // Preserve enabled state from existing rule (if editing)
    const isEnabled = currentRuleData ? currentRuleData.enabled : true;

    // Helper to safely parse integers with defaults
    const safeInt = (val, defaultVal) => {
        const parsed = parseInt(val);
        return isNaN(parsed) ? defaultVal : parsed;
    };

    const ruleData = {
        name: document.getElementById('aasRuleName').value.trim(),
        priority: safeInt(document.getElementById('aasRulePriority').value, 10),
        enabled: isEnabled,  // Preserve enabled state on edit, default true on create

        trigger: {
            channel_ids: monitoredChannels,
            required_keywords: requiredKeywords,
            keywords: keywords,
            ignore_keywords: splitCsv(document.getElementById('aasRuleIgnore').value),
            match_mode: document.getElementById('aasRuleMatchMode').value,
            regex_pattern: regex || null,
            source_filter: {
                allowed_user_ids: splitCsv(document.getElementById('aasRuleUsers').value),
                allowed_usernames: preservedUsernames,  // Preserve existing usernames
                is_webhook: document.getElementById('aasRuleIsWebhook').checked ? true : null
            }
        },

        action: {
            type: document.getElementById('aasRuleActionType').value,
            containers: containers,
            delay_seconds: safeInt(document.getElementById('aasRuleDelay').value, 0),
            notification_channel_id: document.querySelector('input[name="aasFeedbackChannel"]:checked')?.value || null
        },

        safety: {
            cooldown_minutes: safeInt(document.getElementById('aasRuleCooldown').value, 1440),
            only_if_running: document.getElementById('aasRuleOnlyRunning').checked
        }
    };
    
    try {
        const url = isNew ? '/api/automation/rules' : `/api/automation/rules/${ruleId}`;
        const method = isNew ? 'POST' : 'PUT';
        
        const response = await fetch(url, {
            method: method,
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(ruleData)
        });
        
        const result = await response.json();
        
        if (result.success) {
            // Close modal and refresh list
            const modalEl = document.getElementById('aasRuleEditorModal');
            const modal = bootstrap.Modal.getInstance(modalEl);
            modal.hide();
            loadAASRules();
            showNotification('Rule saved successfully', 'success');
        } else {
            alert('Error saving rule: ' + result.error);
        }
    } catch (error) {
        console.error('Save error:', error);
        alert('Failed to save rule');
    }
}

async function deleteAASRule() {
    if (!confirm('Are you sure you want to delete this rule?')) return;
    
    try {
        const response = await fetch(`/api/automation/rules/${currentRuleId}`, {
            method: 'DELETE'
        });
        const result = await response.json();
        
        if (result.success) {
            const modalEl = document.getElementById('aasRuleEditorModal');
            const modal = bootstrap.Modal.getInstance(modalEl);
            modal.hide();
            loadAASRules();
            showNotification('Rule deleted', 'warning');
        } else {
            alert('Error deleting rule: ' + result.error);
        }
    } catch (error) {
        alert('Failed to delete rule');
    }
}

// --- Testing (Local - tests current form values, not saved rules) ---

function testAASRule() {
    const testContent = document.getElementById('aasTestContent').value;
    const resultDiv = document.getElementById('aasTestResult');

    if (!testContent) {
        resultDiv.innerHTML = '<span class="text-warning"><i class="bi bi-exclamation-triangle"></i> Please enter text to test.</span>';
        return;
    }

    // Get current form values (not saved values!)
    const requiredKeywords = splitCsv(document.getElementById('aasRuleRequiredKeywords').value);
    const keywords = splitCsv(document.getElementById('aasRuleKeywords').value);
    const ignoreKeywords = splitCsv(document.getElementById('aasRuleIgnore').value);
    const matchMode = document.getElementById('aasRuleMatchMode').value;
    const regexPattern = document.getElementById('aasRuleRegex').value.trim();
    const ruleName = document.getElementById('aasRuleName').value || 'Current Rule';

    // Validate: Need at least one trigger condition
    if (requiredKeywords.length === 0 && keywords.length === 0 && !regexPattern) {
        resultDiv.innerHTML = '<span class="text-warning"><i class="bi bi-exclamation-triangle"></i> Enter required keywords, trigger keywords, or regex first.</span>';
        return;
    }

    const searchText = testContent.toLowerCase();
    let isMatch = false;
    let matchReason = '';

    // 1. Check Ignore Keywords (Blacklist)
    for (const ignore of ignoreKeywords) {
        if (ignore && searchText.includes(ignore.toLowerCase())) {
            resultDiv.innerHTML = `
                <div class="alert alert-warning py-2 px-3 mb-0">
                    <div class="d-flex justify-content-between align-items-center">
                        <strong><i class="bi bi-slash-circle"></i> ${escapeHtml(ruleName)}</strong>
                        <span class="badge bg-warning text-dark">BLOCKED</span>
                    </div>
                    <small>Blocked by ignore keyword: <code>${escapeHtml(ignore)}</code></small>
                </div>
            `;
            return;
        }
    }

    // 2. Check Required Keywords (ALL must match)
    if (requiredKeywords.length > 0) {
        const missingRequired = requiredKeywords.filter(kw => !searchText.includes(kw.toLowerCase()));
        if (missingRequired.length > 0) {
            resultDiv.innerHTML = `
                <div class="alert alert-danger py-2 px-3 mb-0">
                    <div class="d-flex justify-content-between align-items-center">
                        <strong><i class="bi bi-x-circle"></i> ${escapeHtml(ruleName)}</strong>
                        <span class="badge bg-danger">NO MATCH</span>
                    </div>
                    <small>Missing required keyword(s): <code>${missingRequired.join('</code>, <code>')}</code></small>
                </div>
            `;
            return;
        }
    }

    // 3. Check Regex Pattern
    if (regexPattern) {
        try {
            const regex = new RegExp(regexPattern, 'i');
            if (regex.test(testContent)) {
                isMatch = true;
                matchReason = `Regex matched: <code>${escapeHtml(regexPattern)}</code>`;
            }
        } catch (e) {
            resultDiv.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle"></i> Invalid regex: ${escapeHtml(e.message)}</span>`;
            return;
        }
    }

    // 4. Check Trigger Keywords (if regex didn't match or no regex)
    if (!isMatch && keywords.length > 0) {
        const matchedItems = [];
        for (const keyword of keywords) {
            if (keyword && searchText.includes(keyword.toLowerCase())) {
                matchedItems.push(keyword);
            }
        }

        if (matchMode === 'all') {
            // ALL keywords must match
            if (matchedItems.length === keywords.length) {
                isMatch = true;
                matchReason = `All trigger keywords matched: <code>${matchedItems.join('</code>, <code>')}</code>`;
            } else {
                matchReason = `Only ${matchedItems.length}/${keywords.length} trigger keywords matched`;
            }
        } else {
            // ANY keyword must match
            if (matchedItems.length > 0) {
                isMatch = true;
                matchReason = `Trigger keyword matched: <code>${matchedItems[0]}</code>`;
            } else {
                matchReason = 'No trigger keywords matched';
            }
        }
    }

    // 5. If only required keywords (no trigger keywords/regex), that's enough
    if (!isMatch && requiredKeywords.length > 0 && keywords.length === 0 && !regexPattern) {
        isMatch = true;
        matchReason = `Required keyword(s) matched: <code>${requiredKeywords.join('</code>, <code>')}</code>`;
    }

    // 6. Display Result
    if (isMatch) {
        let fullReason = matchReason;
        if (requiredKeywords.length > 0 && keywords.length > 0) {
            fullReason = `Required: <code>${requiredKeywords.join('</code>, <code>')}</code> ✓ + ${matchReason}`;
        }
        resultDiv.innerHTML = `
            <div class="alert alert-success py-2 px-3 mb-0">
                <div class="d-flex justify-content-between align-items-center">
                    <strong><i class="bi bi-check-circle"></i> ${escapeHtml(ruleName)}</strong>
                    <span class="badge bg-success">MATCH</span>
                </div>
                <small>${fullReason}</small>
            </div>
        `;
    } else {
        resultDiv.innerHTML = `
            <div class="alert alert-secondary py-2 px-3 mb-0">
                <div class="d-flex justify-content-between align-items-center">
                    <strong><i class="bi bi-x-circle"></i> ${escapeHtml(ruleName)}</strong>
                    <span class="badge bg-secondary">NO MATCH</span>
                </div>
                <small>${matchReason || 'No trigger conditions matched'}</small>
            </div>
        `;
    }
}

// --- Global Settings & History ---

async function loadAASGlobalSettings() {
    try {
        const response = await fetch('/api/automation/settings');
        const settings = await response.json();

        document.getElementById('aasGlobalToggle').checked = settings.enabled;
        document.getElementById('aasGlobalCooldown').value = settings.global_cooldown_seconds;
        document.getElementById('aasProtectedContainers').value = settings.protected_containers.join(',');

        // Populate audit channel dropdown
        const auditSelect = document.getElementById('aasAuditChannelSelect');
        let auditOptions = '<option value="">(None)</option>';

        // Use allChannels from page load
        if (allChannels.length === 0) {
            loadChannelsForAAS();
        }

        if (allChannels.length > 0) {
            allChannels.forEach(ch => {
                auditOptions += `<option value="${escapeHtml(ch.id)}">${escapeHtml(ch.name)} (${escapeHtml(ch.id)})</option>`;
            });
        }

        auditSelect.innerHTML = auditOptions;
        auditSelect.value = settings.audit_channel_id || '';
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

async function saveAASGlobalSettings() {
    const settings = {
        enabled: document.getElementById('aasGlobalToggle').checked,
        global_cooldown_seconds: parseInt(document.getElementById('aasGlobalCooldown').value),
        audit_channel_id: document.getElementById('aasAuditChannelSelect').value || null,
        protected_containers: splitCsv(document.getElementById('aasProtectedContainers').value)
    };
    
    try {
        const response = await fetch('/api/automation/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(settings)
        });
        const result = await response.json();
        
        if (result.success) {
            showNotification('Global settings saved', 'success');
        } else {
            alert('Error: ' + result.error);
        }
    } catch (error) {
        alert('Failed to save settings');
    }
}

async function toggleGlobalAAS() {
    // Just trigger save, the checkbox state is read there
    saveAASGlobalSettings();
}

async function loadAASHistory() {
    const tbody = document.getElementById('aasHistoryTable');
    if (!tbody) return;
    
    tbody.innerHTML = '<tr><td colspan="5" class="text-center">Loading...</td></tr>';
    
    try {
        const response = await fetch('/api/automation/history?limit=50');
        const data = await response.json();
        
        if (data.history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted">No history available yet.</td></tr>';
            return;
        }
        
        tbody.innerHTML = data.history.map(entry => {
            const date = new Date(entry.timestamp * 1000).toLocaleString();
            const resultBadge = entry.result === 'SUCCESS' ? 'bg-success' : 
                              entry.result === 'SKIPPED' ? 'bg-warning text-dark' : 'bg-danger';
            
            return `
            <tr>
                <td><small>${date}</small></td>
                <td>${escapeHtml(entry.rule_name)}</td>
                <td><code>${escapeHtml(entry.container)}</code></td>
                <td>${entry.action}</td>
                <td>
                    <span class="badge ${resultBadge}">${entry.result}</span>
                    ${entry.details ? `<br><small class="text-muted">${escapeHtml(entry.details)}</small>` : ''}
                </td>
            </tr>
            `;
        }).join('');
        
    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="5" class="text-danger">Error: ${error.message}</td></tr>`;
    }
}

// --- Helpers ---

function splitCsv(val) {
    if (!val) return [];
    return val.split(',').map(s => s.trim()).filter(s => s);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}