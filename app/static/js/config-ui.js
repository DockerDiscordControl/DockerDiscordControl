// Container Info Modal functionality - Vanilla JavaScript (no jQuery)
document.addEventListener('DOMContentLoaded', function() {
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
        modalLabel.innerHTML = '<i class="bi bi-info-circle"></i> Container Info Configuration - ' + containerName;
    }
    
    // Get current values from form (look for existing hidden inputs)
    const enabledInput = document.querySelector(`input[name="info_enabled_${containerName}"]`);
    const showIpInput = document.querySelector(`input[name="info_show_ip_${containerName}"]`);
    const customIpInput = document.querySelector(`input[name="info_custom_ip_${containerName}"]`);
    const customPortInput = document.querySelector(`input[name="info_custom_port_${containerName}"]`);
    const customTextInput = document.querySelector(`textarea[name="info_custom_text_${containerName}"]`);
    
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
        info_custom_text: document.getElementById('modal-info-custom-text')?.value || ''
    };
    
    // Update the corresponding form inputs (hidden inputs)
    const enabledInput = document.querySelector(`input[name="info_enabled_${containerName}"]`);
    const showIpInput = document.querySelector(`input[name="info_show_ip_${containerName}"]`);
    const customIpInput = document.querySelector(`input[name="info_custom_ip_${containerName}"]`);
    const customPortInput = document.querySelector(`input[name="info_custom_port_${containerName}"]`);
    const customTextInput = document.querySelector(`textarea[name="info_custom_text_${containerName}"]`);
    
    if (enabledInput) enabledInput.value = formData.info_enabled;
    if (showIpInput) showIpInput.value = formData.info_show_ip;
    if (customIpInput) customIpInput.value = formData.info_custom_ip;
    if (customPortInput) customPortInput.value = formData.info_custom_port;
    if (customTextInput) customTextInput.value = formData.info_custom_text;
    
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