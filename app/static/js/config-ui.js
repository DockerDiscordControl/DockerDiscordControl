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

            // Update order numbers when checkbox state changes
            updateOrderNumbers();
        }
    });
});

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
    }
    
    // Hide modal
    const modal = document.getElementById('containerInfoModal');
    if (modal && window.bootstrap) {
        const bootstrapModal = bootstrap.Modal.getInstance(modal);
        if (bootstrapModal) {
            bootstrapModal.hide();
        }
    }
    
    // Show success message
    showToast('Container info updated successfully!', 'success');
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
                <i class="bi ${iconClass}"></i> ${message}
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

function openAdminModal() {
    // Load admin users from server
    fetch('/api/admin-users')
        .then(response => response.json())
        .then(data => {
            adminUsers = data.discord_admin_users || [];
            adminNotes = data.admin_notes || {};
            pendingAdminChanges = [];
            renderAdminUsers();
            const modal = new bootstrap.Modal(document.getElementById('adminModal'));
            modal.show();
        })
        .catch(error => {
            console.error('Error loading admin users:', error);
            alert('Failed to load admin users');
        });
}

function renderAdminUsers() {
    const listContainer = document.getElementById('adminUsersList');
    listContainer.innerHTML = '';

    if (adminUsers.length === 0) {
        listContainer.innerHTML = '<div class="text-muted">No admin users configured</div>';
        return;
    }

    adminUsers.forEach((userId, index) => {
        const note = adminNotes[userId] || '';
        const item = document.createElement('div');
        item.className = 'list-group-item list-group-item-action d-flex justify-content-between align-items-center bg-dark text-white';
        item.innerHTML = `
            <div>
                <strong>${userId}</strong>
                ${note ? `<span class="text-muted ms-2">(${note})</span>` : ''}
            </div>
            <button class="btn btn-sm btn-danger" onclick="removeAdminUser(${index})">Remove</button>
        `;
        listContainer.appendChild(item);
    });
}

function addAdminUser() {
    const idInput = document.getElementById('newAdminId');
    const noteInput = document.getElementById('newAdminNote');
    const userId = idInput.value.trim();
    const note = noteInput.value.trim();

    if (!userId) {
        alert('Please enter a Discord User ID');
        return;
    }

    if (!/^\d+$/.test(userId)) {
        alert('Discord User ID must contain only numbers');
        return;
    }

    if (adminUsers.includes(userId)) {
        alert('This user is already an admin');
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
    const data = {
        discord_admin_users: adminUsers,
        admin_notes: adminNotes
    };

    fetch('/api/admin-users', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            const modal = bootstrap.Modal.getInstance(document.getElementById('adminModal'));
            modal.hide();
            alert('Admin users saved successfully');
        } else {
            alert('Failed to save admin users: ' + (result.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error saving admin users:', error);
        alert('Failed to save admin users');
    });
}

// Channel Row Management Functions
function addStatusChannelRow() {
    const tbody = document.querySelector('#status-channels-table tbody');
    const rowCount = tbody.querySelectorAll('tr').length + 1;

    const newRow = document.createElement('tr');
    newRow.id = 'status-channel-row-' + rowCount;
    newRow.innerHTML = `
        <td><input type="text" class="form-control form-control-sm" name="status_channel_name_${rowCount}" placeholder="Channel Name"></td>
        <td>
            <input type="text" class="form-control form-control-sm" name="status_channel_id_${rowCount}" placeholder="Channel ID">
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

    // Re-initialize checkbox handlers for new row
    initializeCheckboxHandlers(newRow);
}

function addControlChannelRow() {
    const tbody = document.querySelector('#control-channels-table tbody');
    const rowCount = tbody.querySelectorAll('tr').length + 1;

    const newRow = document.createElement('tr');
    newRow.id = 'control-channel-row-' + rowCount;
    newRow.innerHTML = `
        <td><input type="text" class="form-control form-control-sm" name="control_channel_name_${rowCount}" placeholder="Channel Name"></td>
        <td>
            <input type="text" class="form-control form-control-sm" name="control_channel_id_${rowCount}" placeholder="Channel ID">
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

    // Re-initialize checkbox handlers for new row
    initializeCheckboxHandlers(newRow);
}

// Helper function to initialize checkbox handlers
function initializeCheckboxHandlers(row) {
    // Auto-refresh checkbox handler
    const refreshCheckbox = row.querySelector('.auto-refresh-checkbox');
    if (refreshCheckbox) {
        refreshCheckbox.addEventListener('change', function() {
            const targetInput = row.querySelector('.interval-minutes-input');
            if (targetInput) {
                targetInput.disabled = !this.checked;
            }
        });
    }

    // Recreate checkbox handler
    const recreateCheckbox = row.querySelector('.recreate-checkbox');
    if (recreateCheckbox) {
        recreateCheckbox.addEventListener('change', function() {
            const targetInput = row.querySelector('.inactivity-minutes-input');
            if (targetInput) {
                targetInput.disabled = !this.checked;
            }
        });
    }

    // Remove button handler
    const removeBtn = row.querySelector('.remove-channel-btn');
    if (removeBtn) {
        removeBtn.addEventListener('click', function() {
            row.remove();
        });
    }
}