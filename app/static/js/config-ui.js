// HTML escaping utility to prevent XSS
function escapeHtmlConfigUI(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

// Container Info Modal functionality - Vanilla JavaScript (no jQuery)
document.addEventListener('DOMContentLoaded', function() {
    // Initialize order numbers on page load
    updateOrderNumbers();

    // Handle order change buttons (+ and -)
    document.addEventListener('click', function(event) {
        if (event.target.classList.contains('move-up-btn')) {
            moveRow(event.target, 'up');
        } else if (event.target.classList.contains('move-down-btn')) {
            moveRow(event.target, 'down');
        }
    });

    // Handle info button clicks
    document.addEventListener('click', function(event) {
        if (event.target.closest('.info-btn')) {
            const button = event.target.closest('.info-btn');
            const containerName = button.getAttribute('data-container');
            openContainerInfoModal(containerName);
        }
    });

    // Refresh / Recreate unlock their minutes field - delegated, so it holds for
    // the rows the template renders as well as the ones the + button adds.
    // Until 2026-09-26 only added rows had a listener: the template renders a
    // saved row's minutes field disabled while its box is unticked, and the
    // handler that once covered those rows (panel.js) was bound to a table id
    // that no longer exists. Ticking the box left the field locked, and the
    // save sent the stale value.
    document.addEventListener('change', function(event) {
        const box = event.target;
        if (box && box.matches && box.matches('.auto-refresh-checkbox, .recreate-checkbox')) {
            const row = box.closest('tr');
            const field = row && row.querySelector(box.getAttribute('data-target-input'));
            if (field) {
                field.disabled = !box.checked;
            }
        }
    });

    // Handle channel remove buttons (event delegation for both template-rendered and JS-added rows)
    document.addEventListener('click', function(event) {
        const removeBtn = event.target.closest('.remove-channel-btn');
        if (removeBtn) {
            const rowId = removeBtn.getAttribute('data-row-id');
            const row = document.getElementById(rowId);
            if (row) {
                row.remove();
            }
        }
    });
    
    // Handle character counter for modal textarea
    const modalTextarea = document.getElementById('modal-info-custom-text');
    if (modalTextarea) {
        modalTextarea.addEventListener('input', function() {
            const length = this.value.length;
            const counter = document.getElementById('modal-char-counter');
            if (counter) {
                counter.textContent = length;

                // Change color based on character count
                if (length > 225) {
                    counter.classList.add('text-warning');
                } else {
                    counter.classList.remove('text-warning');
                }
            }
        });
    }

    // Handle character counter for protected content textarea
    const protectedTextarea = document.getElementById('modal-info-protected-content');
    if (protectedTextarea) {
        protectedTextarea.addEventListener('input', function() {
            const length = this.value.length;
            const counter = document.getElementById('modal-protected-char-counter');
            if (counter) {
                counter.textContent = length;

                // Change color based on character count
                if (length > 225) {
                    counter.classList.add('text-warning');
                } else {
                    counter.classList.remove('text-warning');
                }
            }
        });
    }

    // Handle protected info checkbox toggle
    const protectedCheckbox = document.getElementById('modal-info-protected-enabled');
    const protectedFields = document.getElementById('protected-info-fields');
    if (protectedCheckbox && protectedFields) {
        protectedCheckbox.addEventListener('change', function() {
            protectedFields.style.display = this.checked ? 'block' : 'none';
            if (!this.checked) {
                // Clear fields when disabled
                const contentField = document.getElementById('modal-info-protected-content');
                const passwordField = document.getElementById('modal-info-protected-password');
                if (contentField) contentField.value = '';
                if (passwordField) passwordField.value = '';
                const counter = document.getElementById('modal-protected-char-counter');
                if (counter) counter.textContent = '0';
            }
        });
    }
    
    // Handle save button click
    const saveButton = document.getElementById('saveContainerInfo');
    if (saveButton) {
        saveButton.addEventListener('click', function() {
            saveContainerInfo();
        });
    }

    // Show the access-token field only for token protocols (e.g. Satisfactory)
    const queryProtocolSelect = document.getElementById('modal-query-protocol');
    if (queryProtocolSelect) {
        queryProtocolSelect.addEventListener('change', updateQueryTokenVisibility);
    }

    // Manual game-query re-test button (3 tries, 60s apart)
    const retestBtn = document.getElementById('modal-query-retest-btn');
    if (retestBtn) {
        retestBtn.addEventListener('click', function() {
            const name = document.getElementById('modal-container-name')?.value;
            if (name) startQueryRetest(name);
        });
    }
    // Stop the re-test status poll when the modal is dismissed (Save, X, ESC, backdrop)
    const infoModalEl = document.getElementById('containerInfoModal');
    if (infoModalEl) {
        infoModalEl.addEventListener('hidden.bs.modal', resetQueryRetestUI);
    }
    
    // Handle container selection checkbox changes
    document.addEventListener('change', function(event) {
        if (event.target.classList.contains('server-checkbox')) {
            const containerRow = event.target.closest('tr');
            const isChecked = event.target.checked;

            // Enable/disable info button based on selection
            const infoBtn = containerRow.querySelector('.info-btn');
            if (infoBtn) {
                infoBtn.disabled = !isChecked;
            }

            // Enable/disable other form controls in the row
            const displayNameInput = containerRow.querySelector('.display-name-input');
            const actionCheckboxes = containerRow.querySelectorAll('.action-checkbox');

            if (displayNameInput) {
                displayNameInput.disabled = !isChecked;
            }

            actionCheckboxes.forEach(checkbox => {
                checkbox.disabled = !isChecked;
            });

            // The "Spieler" (query) checkbox is gated by support detection, not just selection:
            // keep it locked unless the container is proven queryable (or already enabled).
            const queryCb = containerRow.querySelector('.query-enabled-checkbox');
            if (queryCb) {
                // unlocked = proven queryable, already enabled, or a token protocol (Satisfactory)
                const unlocked = queryCb.dataset.queryUnlocked === 'true' || queryCb.checked;
                queryCb.disabled = !isChecked || !unlocked;
            }

            // Update order numbers when checkbox state changes
            updateOrderNumbers();
            // Selecting/deselecting a container can change the glow (enabled state)
            const q0 = containerRow.querySelector('.query-enabled-checkbox');
            if (q0 && q0.dataset.container) updateInfoGlow(q0.dataset.container);
        } else if (event.target.classList.contains('query-enabled-checkbox')) {
            // Toggling the "Spieler" checkbox turns the "needs config" glow on/off live
            if (event.target.dataset.container) updateInfoGlow(event.target.dataset.container);
        }
    });
});

// Protocols that need a per-server credential (mirrors GameQueryService.TOKEN_PROTOCOLS)
const QUERY_TOKEN_PROTOCOLS = ['satisfactory', 'palworld'];

// Show/hide the credential field based on the selected query protocol, and swap its
// label/help text per protocol (Satisfactory app token vs Palworld admin password).
function updateQueryTokenVisibility() {
    const select = document.getElementById('modal-query-protocol');
    const wrap = document.getElementById('modal-query-token-wrap');
    if (!select || !wrap) return;
    const proto = select.value;
    const isToken = QUERY_TOKEN_PROTOCOLS.includes(proto);
    wrap.style.display = isToken ? 'block' : 'none';
    if (isToken) {
        const cap = proto.charAt(0).toUpperCase() + proto.slice(1);
        const lbl = wrap.dataset['label' + cap];
        const help = wrap.dataset['help' + cap];
        const lblEl = document.getElementById('modal-query-token-label');
        const helpEl = document.getElementById('modal-query-token-help');
        if (lblEl && lbl) lblEl.textContent = lbl;
        if (helpEl && help) helpEl.textContent = help;
    }
}

// --- Manual game-query re-test (3 tries, 60s apart) ---
let _queryRetestTimer = null;

function _setRetestStatus(text, cls) {
    const el = document.getElementById('modal-query-retest-status');
    if (el) { el.textContent = text || ''; el.className = 'form-text mb-0 ' + (cls || ''); }
}

function resetQueryRetestUI() {
    if (_queryRetestTimer) { clearInterval(_queryRetestTimer); _queryRetestTimer = null; }
    const btn = document.getElementById('modal-query-retest-btn');
    if (btn) btn.disabled = false;
    _setRetestStatus('', '');
}

function unlockQueryCheckbox(containerName) {
    const sel = (window.CSS && CSS.escape) ? CSS.escape(containerName) : containerName;
    const cb = document.querySelector('.query-enabled-checkbox[data-container="' + sel + '"]');
    if (!cb) return;
    cb.dataset.queryUnlocked = 'true';
    const row = cb.closest('tr');
    const serverCb = row ? row.querySelector('.server-checkbox') : null;
    cb.disabled = serverCb ? !serverCb.checked : false;
}

// The Info button glows only when the player option is ENABLED for this container AND a token
// protocol (Satisfactory/Palworld) is selected/guessed but no token/password is set yet.
function updateInfoGlow(containerName) {
    const infoBtn = document.querySelector('button.info-btn[data-container="' + containerName + '"]');
    if (!infoBtn) return;
    const enabledCb = document.querySelector('.query-enabled-checkbox[data-container="' + containerName + '"]');
    const enabled = !!(enabledCb && enabledCb.checked);
    let proto = (document.querySelector('input[name="query_protocol_' + containerName + '"]')?.value) || 'source';
    if (proto === 'source' && infoBtn.dataset.guessedProtocol) proto = infoBtn.dataset.guessedProtocol;
    const token = (document.querySelector('input[name="query_token_' + containerName + '"]')?.value || '').trim();
    infoBtn.classList.toggle('info-btn-needs-config', enabled && QUERY_TOKEN_PROTOCOLS.includes(proto) && !token);
}

function startQueryRetest(containerName) {
    const btn = document.getElementById('modal-query-retest-btn');
    const msgTesting = (btn && btn.dataset.msgTesting) || 'Testing…';
    const msgSupported = (btn && btn.dataset.msgSupported) || 'Supported';
    const msgUnsupported = (btn && btn.dataset.msgUnsupported) || 'No response';
    if (_queryRetestTimer) { clearInterval(_queryRetestTimer); _queryRetestTimer = null; }
    if (btn) btn.disabled = true;
    _setRetestStatus(msgTesting, 'text-info');
    fetch('/api/game-query/retest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ container: containerName })
    }).then(r => r.json()).then(res => {
        if (!res || !res.success) {
            _setRetestStatus((res && res.error) || 'Error', 'text-danger');
            if (btn) btn.disabled = false;
            return;
        }
        let elapsed = 0;
        _queryRetestTimer = setInterval(function() {
            elapsed += 3;
            fetch('/api/game-query/support-status?container=' + encodeURIComponent(containerName))
                .then(r => r.json()).then(function(st) {
                    if (_queryRetestTimer === null) return;   // poll already stopped: ignore late responses
                    if (st && st.testing) {
                        _setRetestStatus(msgTesting + ' (' + elapsed + 's)', 'text-info');
                        return;
                    }
                    clearInterval(_queryRetestTimer); _queryRetestTimer = null;
                    if (btn) btn.disabled = false;
                    if (st && st.supported) {
                        _setRetestStatus('✓ ' + msgSupported, 'text-success');
                        unlockQueryCheckbox(containerName);
                    } else {
                        _setRetestStatus('✗ ' + msgUnsupported, 'text-danger');
                    }
                }).catch(function() {});
            if (elapsed > 230) { clearInterval(_queryRetestTimer); _queryRetestTimer = null; if (btn) btn.disabled = false; }
        }, 3000);
    }).catch(function() {
        _setRetestStatus('Error', 'text-danger');
        if (btn) btn.disabled = false;
    });
}

// Function to open container info modal
function openContainerInfoModal(containerName) {
    // Set container name in modal
    const modalContainerName = document.getElementById('modal-container-name');
    const modalLabel = document.getElementById('containerInfoModalLabel');
    
    if (modalContainerName) {
        modalContainerName.value = containerName;
    }
    
    if (modalLabel) {
        // Security: Prevent XSS by using textContent for user-controlled containerName
        // First set the static HTML (icon + base text)
        modalLabel.innerHTML = '<i class="bi bi-info-circle"></i> Container Info Configuration - ';
        // Then append containerName as text (auto-escapes HTML)
        modalLabel.appendChild(document.createTextNode(containerName));
    }
    
    // Get current values from form (look for existing hidden inputs)
    const enabledInput = document.querySelector(`input[name="info_enabled_${containerName}"]`);
    const showIpInput = document.querySelector(`input[name="info_show_ip_${containerName}"]`);
    const customIpInput = document.querySelector(`input[name="info_custom_ip_${containerName}"]`);
    const customPortInput = document.querySelector(`input[name="info_custom_port_${containerName}"]`);
    const customTextInput = document.querySelector(`textarea[name="info_custom_text_${containerName}"]`);
    const protectedEnabledInput = document.querySelector(`input[name="info_protected_enabled_${containerName}"]`);
    const protectedContentInput = document.querySelector(`textarea[name="info_protected_content_${containerName}"]`);
    const protectedPasswordInput = document.querySelector(`input[name="info_protected_password_${containerName}"]`);
    
    // Set modal values (convert string values to boolean)
    const modalEnabled = document.getElementById('modal-info-enabled');
    const modalShowIp = document.getElementById('modal-info-show-ip');
    const modalCustomIp = document.getElementById('modal-info-custom-ip');
    const modalCustomPort = document.getElementById('modal-info-custom-port');
    const modalCustomText = document.getElementById('modal-info-custom-text');
    
    if (modalEnabled && enabledInput) {
        modalEnabled.checked = enabledInput.value === '1';
    }
    
    if (modalShowIp && showIpInput) {
        modalShowIp.checked = showIpInput.value === '1';
    }
    
    if (modalCustomIp && customIpInput) {
        modalCustomIp.value = customIpInput.value || '';
    }
    
    if (modalCustomPort && customPortInput) {
        modalCustomPort.value = customPortInput.value || '';
    }
    
    if (modalCustomText && customTextInput) {
        modalCustomText.value = customTextInput.value || '';

        // Update character counter
        const textLength = modalCustomText.value.length;
        const counter = document.getElementById('modal-char-counter');
        if (counter) {
            counter.textContent = textLength;
        }
    }

    // Set protected field values
    const modalProtectedEnabled = document.getElementById('modal-info-protected-enabled');
    const modalProtectedContent = document.getElementById('modal-info-protected-content');
    const modalProtectedPassword = document.getElementById('modal-info-protected-password');
    const protectedFields = document.getElementById('protected-info-fields');

    if (modalProtectedEnabled && protectedEnabledInput) {
        modalProtectedEnabled.checked = protectedEnabledInput.value === '1';
        // Show/hide protected fields based on checkbox state
        if (protectedFields) {
            protectedFields.style.display = modalProtectedEnabled.checked ? 'block' : 'none';
        }
    }

    if (modalProtectedContent && protectedContentInput) {
        modalProtectedContent.value = protectedContentInput.value || '';

        // Update character counter for protected content
        const protectedLength = modalProtectedContent.value.length;
        const protectedCounter = document.getElementById('modal-protected-char-counter');
        if (protectedCounter) {
            protectedCounter.textContent = protectedLength;
        }
    }

    if (modalProtectedPassword && protectedPasswordInput) {
        modalProtectedPassword.value = protectedPasswordInput.value || '';
    }

    // Populate player-count (opengsq) override fields from hidden inputs
    const queryProtocolInput = document.querySelector(`input[name="query_protocol_${containerName}"]`);
    const queryHostInput = document.querySelector(`input[name="query_host_${containerName}"]`);
    const queryPortInput = document.querySelector(`input[name="query_port_${containerName}"]`);
    const queryTokenInput = document.querySelector(`input[name="query_token_${containerName}"]`);
    const modalQueryProtocol = document.getElementById('modal-query-protocol');
    const modalQueryHost = document.getElementById('modal-query-host');
    const modalQueryPort = document.getElementById('modal-query-port');
    const modalQueryToken = document.getElementById('modal-query-token');
    if (modalQueryProtocol && queryProtocolInput) {
        modalQueryProtocol.value = queryProtocolInput.value || 'source';
        // If the protocol is still the default and the container name/image suggests a
        // specific game (e.g. Satisfactory / Palworld / Minecraft), pre-select it so the
        // user is nudged to configure it (and the token field shows for token protocols).
        const infoBtnForGuess = document.querySelector(`button.info-btn[data-container="${containerName}"]`);
        const guessed = infoBtnForGuess && infoBtnForGuess.dataset.guessedProtocol;
        if (guessed && (!modalQueryProtocol.value || modalQueryProtocol.value === 'source')) {
            modalQueryProtocol.value = guessed;
        }
    }
    if (modalQueryHost && queryHostInput) {
        modalQueryHost.value = queryHostInput.value || '';
    }
    if (modalQueryPort && queryPortInput) {
        // Port 0 means auto-detect -> show as empty for clarity
        const pv = queryPortInput.value;
        modalQueryPort.value = (pv && pv !== '0') ? pv : '';
    }
    if (modalQueryToken && queryTokenInput) {
        modalQueryToken.value = queryTokenInput.value || '';
    }
    // The token field is only relevant for token protocols (Satisfactory)
    updateQueryTokenVisibility();
    // Clear any leftover re-test status/spinner from a previously opened container
    resetQueryRetestUI();

    // Show modal using Bootstrap
    const modal = document.getElementById('containerInfoModal');
    if (modal && window.bootstrap) {
        try {
            const bootstrapModal = new bootstrap.Modal(modal);
            bootstrapModal.show();
        } catch (error) {
            console.error('Error showing modal:', error);
        }
    } else {
        console.error('Modal element or Bootstrap not found');
    }
}

// Function to save container info
function saveContainerInfo() {
    const containerName = document.getElementById('modal-container-name')?.value;
    if (!containerName) {
        console.error('Container name not found');
        return;
    }
    
    const formData = {
        container_name: containerName,
        info_enabled: document.getElementById('modal-info-enabled')?.checked ? '1' : '0',
        info_show_ip: document.getElementById('modal-info-show-ip')?.checked ? '1' : '0',
        info_custom_ip: document.getElementById('modal-info-custom-ip')?.value || '',
        info_custom_port: document.getElementById('modal-info-custom-port')?.value || '',
        info_custom_text: document.getElementById('modal-info-custom-text')?.value || '',
        info_protected_enabled: document.getElementById('modal-info-protected-enabled')?.checked ? '1' : '0',
        info_protected_content: document.getElementById('modal-info-protected-content')?.value || '',
        info_protected_password: document.getElementById('modal-info-protected-password')?.value || ''
    };
    
    // Update the corresponding form inputs (hidden inputs)
    const enabledInput = document.querySelector(`input[name="info_enabled_${containerName}"]`);
    const showIpInput = document.querySelector(`input[name="info_show_ip_${containerName}"]`);
    const customIpInput = document.querySelector(`input[name="info_custom_ip_${containerName}"]`);
    const customPortInput = document.querySelector(`input[name="info_custom_port_${containerName}"]`);
    const customTextInput = document.querySelector(`textarea[name="info_custom_text_${containerName}"]`);
    const protectedEnabledInput = document.querySelector(`input[name="info_protected_enabled_${containerName}"]`);
    const protectedContentInput = document.querySelector(`textarea[name="info_protected_content_${containerName}"]`);
    const protectedPasswordInput = document.querySelector(`input[name="info_protected_password_${containerName}"]`);

    if (enabledInput) enabledInput.value = formData.info_enabled;
    if (showIpInput) showIpInput.value = formData.info_show_ip;
    if (customIpInput) customIpInput.value = formData.info_custom_ip;
    if (customPortInput) customPortInput.value = formData.info_custom_port;
    if (customTextInput) customTextInput.value = formData.info_custom_text;
    if (protectedEnabledInput) protectedEnabledInput.value = formData.info_protected_enabled;
    if (protectedContentInput) protectedContentInput.value = formData.info_protected_content;
    if (protectedPasswordInput) protectedPasswordInput.value = formData.info_protected_password;

    // Persist player-count (opengsq) override fields back to hidden inputs
    const queryProtocolInput = document.querySelector(`input[name="query_protocol_${containerName}"]`);
    const queryHostInput = document.querySelector(`input[name="query_host_${containerName}"]`);
    const queryPortInput = document.querySelector(`input[name="query_port_${containerName}"]`);
    const queryTokenInput = document.querySelector(`input[name="query_token_${containerName}"]`);
    if (queryProtocolInput) queryProtocolInput.value = document.getElementById('modal-query-protocol')?.value || 'source';
    if (queryHostInput) queryHostInput.value = document.getElementById('modal-query-host')?.value || '';
    // Empty port -> 0 (auto-detect)
    if (queryPortInput) queryPortInput.value = document.getElementById('modal-query-port')?.value || '0';
    if (queryTokenInput) queryTokenInput.value = document.getElementById('modal-query-token')?.value || '';

    // Update button styling based on enabled state
    const infoButton = document.querySelector(`button.info-btn[data-container="${containerName}"]`);
    if (infoButton) {
        const isEnabled = formData.info_enabled === '1';
        if (isEnabled) {
            infoButton.classList.remove('btn-outline-secondary');
            infoButton.classList.add('btn-outline-info');
        } else {
            infoButton.classList.remove('btn-outline-info');
            infoButton.classList.add('btn-outline-secondary');
        }
        // A token protocol is a valid queryable config -> unlock the Spieler checkbox in-session
        const qProto = document.getElementById('modal-query-protocol')?.value;
        if (QUERY_TOKEN_PROTOCOLS.includes(qProto)) {
            unlockQueryCheckbox(containerName);
        }
        // Refresh the yellow "needs config" glow (enabled + token protocol + no token)
        updateInfoGlow(containerName);
    }

    // SAY THAT THE FORM CHANGED. Everything above was written with
    // element.value = …, which fires no event, so the form's delegated
    // listener never heard it: the operator configured a container, got no
    // "unsaved changes" banner, and leaving the page dropped the lot. The
    // toast below says the dialog is done, not that the settings are stored.
    markConfigurationChanged();

    // Hide modal
    const modal = document.getElementById('containerInfoModal');
    if (modal && window.bootstrap) {
        const bootstrapModal = bootstrap.Modal.getInstance(modal);
        if (bootstrapModal) {
            bootstrapModal.hide();
        }
    }

    // Show success message
    showToast(t('config.container_info_updated'), 'success');
}

// THE ONE showNotification of the settings page. Until 2026-09-26 three
// scripts each declared a global one, the last loaded won, and that was
// advanced_settings_modal.js with a body of console.log - so every message of
// the channel-translation editor and the auto-action dialog, errors included,
// reached the browser console and nobody else. The callers pass Bootstrap's
// 'danger' as well as 'error'; both are an error here.
function showNotification(message, type = 'info') {
    showToast(message, type === 'danger' ? 'error' : type);
}

// Toast notification function
function showToast(message, type = 'info') {
    const toastClass = type === 'success' ? 'text-success' : type === 'error' ? 'text-danger' : 'text-info';
    const iconClass = type === 'success' ? 'bi-check-circle' : type === 'error' ? 'bi-exclamation-triangle' : 'bi-info-circle';

    const toast = document.createElement('div');
    toast.className = 'position-fixed top-0 end-0 p-3';
    toast.style.zIndex = '1055';

    toast.innerHTML = `
        <div class="toast show" role="alert">
            <div class="toast-body ${toastClass}">
                <i class="bi ${iconClass}"></i> ${escapeHtmlConfigUI(message)}
            </div>
        </div>
    `;

    document.body.appendChild(toast);

    // Auto-remove after 3 seconds
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => {
            if (document.body.contains(toast)) {
                document.body.removeChild(toast);
            }
        }, 300);
    }, 3000);
}

// Function to move container rows up or down
function moveRow(button, direction) {
    const row = button.closest('tr');
    const tbody = row.parentElement;
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const currentIndex = rows.indexOf(row);

    if (direction === 'up' && currentIndex > 0) {
        // Move row up
        tbody.insertBefore(row, rows[currentIndex - 1]);
    } else if (direction === 'down' && currentIndex < rows.length - 1) {
        // Move row down
        if (currentIndex === rows.length - 2) {
            // If second to last, append to end
            tbody.appendChild(row);
        } else {
            // Otherwise insert after next row
            tbody.insertBefore(row, rows[currentIndex + 2]);
        }
    }

    // Update order numbers and buttons
    updateOrderNumbers();
    updateMoveButtons();

    // Mark configuration as changed
    markConfigurationChanged();
}

// Function to update order numbers in the table
function updateOrderNumbers() {
    const tbody = document.getElementById('docker-container-list');
    if (!tbody) return;

    const rows = tbody.querySelectorAll('tr[data-container-name]');
    let activeCount = 0;

    rows.forEach((row, index) => {
        const orderSpan = row.querySelector('.order-number');
        const checkbox = row.querySelector('.server-checkbox');

        if (orderSpan) {
            if (checkbox && checkbox.checked) {
                activeCount++;
                orderSpan.textContent = activeCount;
                orderSpan.style.display = 'inline';
            } else {
                orderSpan.textContent = '';
                orderSpan.style.display = 'none';
            }
        }

        // Add hidden input for order
        let orderInput = row.querySelector('input[name^="order_"]');
        if (!orderInput) {
            orderInput = document.createElement('input');
            orderInput.type = 'hidden';
            orderInput.name = `order_${row.getAttribute('data-container-name')}`;
            row.appendChild(orderInput);
        }
        orderInput.value = index;
    });
}

// Function to update move buttons (enable/disable based on position)
function updateMoveButtons() {
    const tbody = document.getElementById('docker-container-list');
    if (!tbody) return;

    const rows = tbody.querySelectorAll('tr[data-container-name]');

    rows.forEach((row, index) => {
        const upBtn = row.querySelector('.move-up-btn');
        const downBtn = row.querySelector('.move-down-btn');

        if (upBtn) {
            upBtn.disabled = (index === 0);
        }
        if (downBtn) {
            downBtn.disabled = (index === rows.length - 1);
        }
    });
}

// Function to mark configuration as changed
function markConfigurationChanged() {
    // This would trigger any unsaved changes warnings
    const event = new Event('change', { bubbles: true });
    document.getElementById('docker-container-list').dispatchEvent(event);
}

// Admin Users Management Functions
let adminUsers = [];
let adminNotes = {};
let pendingAdminChanges = [];
// Per-admin container assignment. A user id that is ABSENT means every
// container - that is the default and it must stay one, so the UI never writes
// an entry the operator did not make. An empty array means "none".
let adminContainers = {};
let availableContainers = [];
// Whether the state above came from a SUCCESSFUL read. An empty admin list is
// a legitimate thing to have; an empty admin list because the read failed is
// not, and the two are indistinguishable once assigned (review E22). Only a
// completed load sets this, and only this lets a save go out.
let adminDataLoaded = false;

function openAdminModal() {
    // Load admin users from server
    fetch('/api/admin-users')
        .then(response => {
            // fetch() rejects on a network failure and on nothing else - not on
            // a 500, and not on a 200 carrying {"success": false}. Both used to
            // fall through to the success path below, where an error body reads
            // exactly like "there are no admins": the modal opened saying so,
            // and the next Save wrote that empty list over the real one
            // (review E22).
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.json();
        })
        .then(data => {
            if (!data || data.success === false) {
                throw new Error(data && data.error ? data.error : 'unreadable admin data');
            }
            adminUsers = data.discord_admin_users || [];
            adminNotes = data.admin_notes || {};
            adminContainers = data.admin_containers || {};
            availableContainers = data.available_containers || [];
            pendingAdminChanges = [];
            adminDataLoaded = true;
            renderAdminUsers();
            const modal = new bootstrap.Modal(document.getElementById('adminModal'));
            modal.show();
        })
        .catch(error => {
            adminDataLoaded = false;
            console.error('Error loading admin users:', error);
            alert(t('admin.failed_load_users'));
        });
}

function renderAdminUsers() {
    const listContainer = document.getElementById('adminUsersList');
    listContainer.innerHTML = '';

    if (adminUsers.length === 0) {
        listContainer.innerHTML = `<div class="text-muted">${t('admin.no_users_configured')}</div>`;
        return;
    }

    adminUsers.forEach((userId, index) => {
        const note = adminNotes[userId] || '';
        const assigned = adminContainers[userId];        // undefined = every container
        const item = document.createElement('div');
        item.className = 'list-group-item bg-dark text-white';
        item.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <strong>${escapeHtmlConfigUI(userId)}</strong>
                    ${note ? `<span class="text-muted ms-2">(${escapeHtmlConfigUI(note)})</span>` : ''}
                </div>
                <button class="btn btn-sm btn-danger" onclick="removeAdminUser(${index})">${t('admin.remove_btn')}</button>
            </div>
            <div class="mt-2 small">${renderAdminContainers(userId, assigned)}</div>
        `;
        listContainer.appendChild(item);
    });
}

// What an operator READS for one assignable thing. The value stored is the one
// the bot compares - `group:Gameserver` - and a checkbox labelled that, among
// plain container names, is the same complaint the operator made about the
// Discord dropdown: nothing says which of them is a group, and the prefix is
// not a name anybody typed. Only the prefix makes a group, so a container
// called "mygroup:thing" is left alone.
function adminAssignmentLabel(name) {
    // The prefix lives in here, not beside it: the node case runs this one
    // function on its own, and a constant outside it would not travel along.
    const prefix = 'group:';
    const text = String(name == null ? '' : name);
    if (!text.startsWith(prefix)) { return text; }
    // The same mark the bot uses (cogs/group_control.py GROUP_EMOJI); it
    // cannot be imported from there, so a test compares the two.
    return '📁 ' + text.slice(prefix.length);
}

// The container assignment of one admin. Three states, and they are NOT the
// same thing: no entry at all (every container, the default), a list, and an
// empty list (none). The UI has to be able to say all three, because the rule
// distinguishes them - see SPEC.md B2.
function renderAdminContainers(userId, assigned) {
    if (!availableContainers.length) {
        return `<span class="text-muted">${t('admin.no_containers_to_assign')}</span>`;
    }
    const scoped = Array.isArray(assigned);
    const safeId = escapeHtmlConfigUI(userId);
    const boxes = availableContainers.map(name => {
        const checked = (!scoped || assigned.indexOf(name) !== -1) ? 'checked' : '';
        const disabled = scoped ? '' : 'disabled';
        return `<label class="me-3 text-nowrap">
            <input type="checkbox" ${checked} ${disabled}
                   data-admin="${safeId}" data-name="${escapeHtmlConfigUI(name)}"
                   onchange="toggleAdminContainerFrom(this)">
            ${escapeHtmlConfigUI(adminAssignmentLabel(name))}
        </label>`;
    }).join('');
    const summary = scoped
        ? (assigned.length
            ? `${assigned.length} ${t('admin.of')} ${availableContainers.length}`
            : `<span class="text-warning">${t('admin.controls_nothing')}</span>`)
        : `<span class="text-success">${t('admin.all_containers')}</span>`;
    return `
        <div class="d-flex align-items-center flex-wrap">
            <label class="me-3 text-nowrap">
                <input type="checkbox" ${scoped ? '' : 'checked'}
                       onchange="setAdminUnscoped('${safeId}', this.checked)">
                <strong>${t('admin.all_containers')}</strong>
            </label>
            <span class="text-muted me-3">${summary}</span>
        </div>
        <div class="mt-1">${boxes}</div>`;
}

// "Every container" is the ABSENCE of an entry, not a full list: a list would
// freeze today's containers and silently exclude the next one somebody adds.
function setAdminUnscoped(userId, unscoped) {
    if (unscoped) {
        delete adminContainers[userId];
    } else {
        adminContainers[userId] = availableContainers.slice();
    }
    renderAdminUsers();
}

// THE NAME TRAVELS IN A data- ATTRIBUTE, NOT IN THE HANDLER'S SOURCE. Until
// 2026-09-26 it was pasted into onchange="toggleAdminContainer('...', '<name>')"
// after HTML escaping - and the parser decodes &#039; back to ' before the
// JavaScript runs. A group called "Bob's" made the box a syntax error, and a
// crafted name ran script. An attribute value is data; the parser hands it
// over as the text it was (tests/js/admin_assignment_names.test.js).
function toggleAdminContainerFrom(box) {
    toggleAdminContainer(box.dataset.admin, box.dataset.name, box.checked);
}

function toggleAdminContainer(userId, name, checked) {
    if (!Array.isArray(adminContainers[userId])) {
        return;    // unscoped: the boxes are disabled, nothing to change
    }
    const current = adminContainers[userId];
    const at = current.indexOf(name);
    if (checked && at === -1) {
        current.push(name);
    } else if (!checked && at !== -1) {
        current.splice(at, 1);
    }
    renderAdminUsers();
}

function addAdminUser() {
    const idInput = document.getElementById('newAdminId');
    const noteInput = document.getElementById('newAdminNote');
    const userId = idInput.value.trim();
    const note = noteInput.value.trim();

    if (!userId) {
        alert(t('admin.enter_user_id'));
        return;
    }

    if (!/^\d+$/.test(userId)) {
        alert(t('admin.user_id_numbers_only'));
        return;
    }

    if (adminUsers.includes(userId)) {
        alert(t('admin.user_already_admin'));
        return;
    }

    adminUsers.push(userId);
    if (note) {
        adminNotes[userId] = note;
    }

    pendingAdminChanges.push({action: 'add', userId, note});

    idInput.value = '';
    noteInput.value = '';
    renderAdminUsers();
}

function removeAdminUser(index) {
    if (index >= 0 && index < adminUsers.length) {
        const userId = adminUsers[index];
        adminUsers.splice(index, 1);
        delete adminNotes[userId];

        pendingAdminChanges.push({action: 'remove', userId});
        renderAdminUsers();
    }
}

function saveAdminUsers() {
    // Never write a list that was never read (review E22). This POST replaces
    // the whole document - admins, notes and the per-admin container
    // assignment - so saving from state that a failed load left empty deletes
    // all three. openAdminModal() is the only thing that sets this flag, and
    // only on a payload it checked.
    if (!adminDataLoaded) {
        console.error('Refusing to save admin users: the list was never loaded');
        alert(t('admin.failed_load_users'));
        return;
    }

    // Assignments for people who are no longer admins would be refused by the
    // route, and rightly - this mapping narrows a right and cannot be written
    // for somebody who has none.
    const containers = {};
    Object.keys(adminContainers).forEach(userId => {
        if (adminUsers.indexOf(userId) !== -1) {
            containers[userId] = adminContainers[userId];
        }
    });

    const data = {
        discord_admin_users: adminUsers,
        admin_notes: adminNotes,
        admin_containers: containers
    };

    // /api/admin-users is registered on the app itself, not on a blueprint, so it is not
    // CSRF-exempt and needs the token from the meta tag in _base.html.
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');

    fetch('/api/admin-users', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfMeta ? csrfMeta.content : ''
        },
        body: JSON.stringify(data)
    })
    .then(response => {
        // Error pages (e.g. a rejected CSRF token) are HTML, not JSON - surface the status instead
        // of failing in response.json() with a generic message.
        const contentType = response.headers.get('content-type') || '';
        if (!contentType.includes('application/json')) {
            return { success: false, error: `HTTP ${response.status} ${response.statusText}` };
        }
        return response.json();
    })
    .then(result => {
        if (result.success) {
            const modal = bootstrap.Modal.getInstance(document.getElementById('adminModal'));
            modal.hide();
            alert(t('admin.saved_successfully'));
        } else {
            // ddcServerErrorMessage (_base.html) translates a rejected CSRF check
            const detail = (typeof window.ddcServerErrorMessage === 'function')
                ? window.ddcServerErrorMessage(result, t('common.unknown_error'))
                : (result.error || t('common.unknown_error'));
            alert(t('admin.failed_save') + ': ' + detail);
        }
    })
    .catch(error => {
        console.error('Error saving admin users:', error);
        alert(t('admin.failed_save'));
    });
}

// Channel Row Management Functions
function getNextRowIndex(tbody, prefix) {
    // Find the highest existing index to avoid duplicate field names after row deletion
    let maxIndex = 0;
    tbody.querySelectorAll(`input[name^="${prefix}"]`).forEach(input => {
        const match = input.name.match(/_(\d+)$/);
        if (match) maxIndex = Math.max(maxIndex, parseInt(match[1]));
    });
    return maxIndex + 1;
}

function addStatusChannelRow() {
    const tbody = document.querySelector('#status-channels-table tbody');
    const rowCount = getNextRowIndex(tbody, 'status_channel_id_');

    const newRow = document.createElement('tr');
    newRow.id = 'status-channel-row-' + rowCount;
    newRow.innerHTML = `
        <td><input type="text" class="form-control form-control-sm" name="status_channel_name_${rowCount}" placeholder="${t('channel.name_placeholder')}"></td>
        <td>
            <input type="text" class="form-control form-control-sm" name="status_channel_id_${rowCount}" placeholder="${t('channel.id_placeholder')}">
            <input type="hidden" name="old_status_channel_id_${rowCount}" value="">
        </td>
        <td class="text-center">
            <div class="form-check">
                <input class="form-check-input" type="checkbox" name="status_post_initial_${rowCount}" value="1">
                <label class="form-check-label visually-hidden">Initial</label>
            </div>
        </td>
        <td class="text-center" style="border-left: 3px solid #0dcaf0;">
            <div class="form-check">
                <input class="form-check-input auto-refresh-checkbox" type="checkbox" name="status_enable_auto_refresh_${rowCount}" value="1" data-target-input=".interval-minutes-input">
                <label class="form-check-label visually-hidden">Refresh</label>
            </div>
        </td>
        <td><input type="number" class="form-control form-control-sm interval-minutes-input" name="status_update_interval_minutes_${rowCount}" value="1" min="1" style="width: 70px;" disabled></td>
        <td class="text-center" style="border-left: 3px solid #0dcaf0;">
            <div class="form-check">
                <input class="form-check-input recreate-checkbox" type="checkbox" name="status_recreate_messages_${rowCount}" value="1" data-target-input=".inactivity-minutes-input">
                <label class="form-check-label visually-hidden">Recreate on Inactivity</label>
            </div>
        </td>
        <td><input type="number" class="form-control form-control-sm inactivity-minutes-input" name="status_inactivity_timeout_${rowCount}" value="1" min="1" style="width: 70px;" disabled></td>
        <td class="text-center" style="border-left: 3px solid #0dcaf0;">
            <button type="button" class="btn btn-sm btn-danger remove-channel-btn" data-row-id="status-channel-row-${rowCount}">
                <i class="bi bi-trash"></i>
            </button>
        </td>
    `;

    tbody.appendChild(newRow);
}

function addControlChannelRow() {
    const tbody = document.querySelector('#control-channels-table tbody');
    const rowCount = getNextRowIndex(tbody, 'control_channel_id_');

    const newRow = document.createElement('tr');
    newRow.id = 'control-channel-row-' + rowCount;
    newRow.innerHTML = `
        <td><input type="text" class="form-control form-control-sm" name="control_channel_name_${rowCount}" placeholder="${t('channel.name_placeholder')}"></td>
        <td>
            <input type="text" class="form-control form-control-sm" name="control_channel_id_${rowCount}" placeholder="${t('channel.id_placeholder')}">
            <input type="hidden" name="old_control_channel_id_${rowCount}" value="">
        </td>
        <td class="text-center">
            <div class="form-check">
                <input class="form-check-input" type="checkbox" name="control_post_initial_${rowCount}" value="1">
                <label class="form-check-label visually-hidden">Initial</label>
            </div>
        </td>
        <td class="text-center" style="border-left: 3px solid #0dcaf0;">
            <div class="form-check">
                <input class="form-check-input auto-refresh-checkbox" type="checkbox" name="control_enable_auto_refresh_${rowCount}" value="1" data-target-input=".interval-minutes-input">
                <label class="form-check-label visually-hidden">Refresh</label>
            </div>
        </td>
        <td><input type="number" class="form-control form-control-sm interval-minutes-input" name="control_update_interval_minutes_${rowCount}" value="1" min="1" style="width: 70px;" disabled></td>
        <td class="text-center" style="border-left: 3px solid #0dcaf0;">
            <div class="form-check">
                <input class="form-check-input recreate-checkbox" type="checkbox" name="control_recreate_messages_${rowCount}" value="1" data-target-input=".inactivity-minutes-input">
                <label class="form-check-label visually-hidden">Recreate on Inactivity</label>
            </div>
        </td>
        <td><input type="number" class="form-control form-control-sm inactivity-minutes-input" name="control_inactivity_timeout_${rowCount}" value="1" min="1" style="width: 70px;" disabled></td>
        <td class="text-center" style="border-left: 3px solid #0dcaf0;">
            <button type="button" class="btn btn-sm btn-danger remove-channel-btn" data-row-id="control-channel-row-${rowCount}">
                <i class="bi bi-trash"></i>
            </button>
        </td>
    `;

    tbody.appendChild(newRow);
}
