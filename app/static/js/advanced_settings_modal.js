// Moved out of _advanced_settings_modal.html on 2026-09-23.
// It was 501 lines inside a template that every panel page includes, and _base.html sends those pages with Cache-Control: no-cache - so it crossed the wire again on every load.
// A static file is not covered by that meta tag.
// No Jinja in here; pinned by tests/spec/test_the_page_is_not_mostly_one_script.py

function updateCacheTTL() {
    const intervalInput = document.getElementById('env_DDC_DOCKER_CACHE_DURATION');
    const ttlDisplay = document.getElementById('calculated_cache_ttl');
    
    if (intervalInput && ttlDisplay) {
        const interval = parseInt(intervalInput.value) || 30;
        const calculatedTTL = Math.round(interval * 2.5);
        ttlDisplay.value = calculatedTTL + 's';
    }
}

// Update cache TTL when modal is shown and field has a value
document.addEventListener('DOMContentLoaded', function() {
    // Update TTL on initial load
    updateCacheTTL();
    
    // Initialize Bootstrap tooltips
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    
    // Listen for when the advanced settings modal is shown
    const advancedModal = document.getElementById('advancedSettingsModal');
    if (advancedModal) {
        advancedModal.addEventListener('shown.bs.modal', function() {
            updateCacheTTL();
            updateKeyStatus();
            // Load current difficulty and manual override status
            loadDifficultyMultiplier();
            // Re-initialize tooltips in case they weren't ready before
            const modalTooltips = this.querySelectorAll('[data-bs-toggle="tooltip"]');
            [...modalTooltips].forEach(tooltip => {
                if (!bootstrap.Tooltip.getInstance(tooltip)) {
                    new bootstrap.Tooltip(tooltip);
                }
            });
        });
    }
});

function saveAdvancedSettings() {
    // Copy advanced settings values to main form before saving
    const mainForm = document.getElementById('config-form');
    const advancedModal = document.getElementById('advancedSettingsModal');
    
    if (mainForm && advancedModal) {
        // Get all input fields from the advanced settings modal
        const advancedInputs = advancedModal.querySelectorAll('input[name^="env_"], input[name="donation_disable_key"], input[name="mech_difficulty_multiplier"]');
        
        console.log(`Found ${advancedInputs.length} advanced inputs to copy`);
        
        // Specifically check for donation key
        const donationKeyInput = advancedModal.querySelector('input[name="donation_disable_key"]');
        if (donationKeyInput) {
            console.log(`Donation key input found with value: "${donationKeyInput.value}"`);
        } else {
            console.log('WARNING: Donation key input NOT FOUND!');
        }
        
        advancedInputs.forEach(input => {
            // Find or create corresponding hidden input in main form
            let mainInput = mainForm.querySelector(`input[name="${input.name}"]`);
            
            if (!mainInput) {
                // Create hidden input if it doesn't exist
                mainInput = document.createElement('input');
                mainInput.type = 'hidden';
                mainInput.name = input.name;
                mainForm.appendChild(mainInput);
            }
            
            // Copy value
            if (input.type === 'checkbox') {
                mainInput.value = input.checked ? '1' : '0';
            } else {
                mainInput.value = input.value;
            }
            
            console.log(`Copied ${input.name} = ${mainInput.value} to main form`);
        });
    }
    
    // Save mech difficulty setting via API
    const difficultySlider = document.getElementById('mech_difficulty_multiplier');
    if (difficultySlider) {
        saveMechDifficulty(parseFloat(difficultySlider.value));
    }
    
    // Trigger unsaved changes warning to show that settings have changed
    if (typeof showUnsavedChangesAlert === 'function') {
        showUnsavedChangesAlert(true);
    }
    
    // Use the existing save function
    if (typeof saveConfigAjax === 'function') {
        saveConfigAjax();
    }
    
    // Close the modal after saving
    setTimeout(() => {
        const modal = document.getElementById('advancedSettingsModal');
        if (modal) {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) {
                bsModal.hide();
            }
        }
    }, 1000); // Give time for save to complete
}

function updateKeyStatus() {
    const keyInput = document.getElementById('donation_disable_key');
    const keyStatus = document.getElementById('keyStatus');
    
    if (keyInput && keyStatus) {
        const keyValue = keyInput.value.trim();
        if (!keyValue) {
            keyStatus.textContent = t('web.advanced.key_status_default');
            keyStatus.className = 'text-muted';
        } else if (validateKeyFormat(keyValue)) {
            keyStatus.textContent = '✅ ' + t('web.advanced.key_status_valid');
            keyStatus.className = 'text-success';
        } else {
            keyStatus.textContent = '❌ ' + t('web.advanced.key_status_invalid');
            keyStatus.className = 'text-danger';
        }
    }
}

function decryptKey(encryptedKey, cryptoKey = 'NothingToEncrypt') {
    try {
        // Decode base64
        const encrypted = atob(encryptedKey);
        
        // Convert string to bytes (compatible with older browsers)
        const keyBytes = [];
        for (let i = 0; i < cryptoKey.length; i++) {
            keyBytes.push(cryptoKey.charCodeAt(i));
        }
        
        let decrypted = '';
        for (let i = 0; i < encrypted.length; i++) {
            const encByte = encrypted.charCodeAt(i);
            const keyByte = keyBytes[i % keyBytes.length];
            decrypted += String.fromCharCode(encByte ^ keyByte);
        }
        
        return decrypted;
    } catch (e) {
        console.error('Key decryption failed:', e);
        return '';
    }
}

function validateKeyFormat(key) {
    // Encrypted donation keys - use decryptKey() to get actual keys
    const encryptedKeys = [
        'Cis3RTk8KHldcSVWX0AoPHlCOVsnP0oNNQAoTkBJQkE=',          // Professional license
        'Cis3RSUnIRE7DCMmX0E2TQ9CRzhbJUpjPgkjTjAxKDdjXURaXA==',    // Lifetime license
        'CiA3Iyw8ShAmFi0sID1dNxo9OEVQKVMWQnA0LSVUICYLIj09JA==',    // Full product name
        'Cis3RSohKhkqFy0qMzVdPwJXMUVdPDMHQnMjMiRUND0dLjYkLA==',    // Commercial license
        'Cis3RVteVWFCACA3NysgJgc8MUVaNy9tQgcjKCpURzIfI1k4OyE='     // Enterprise edition
    ];
    
    // Decrypt and check
    try {
        const validKeys = encryptedKeys.map(encrypted => decryptKey(encrypted));
        console.log('Decrypted keys:', validKeys.slice(0, 2)); // Show first 2 for debugging
        const result = validKeys.some(validKey => validKey.toUpperCase() === key.toUpperCase());
        console.log('Key validation result:', result, 'for key:', key);
        return result;
    } catch (e) {
        console.error('validateKeyFormat error:', e);
        return false;
    }
}

function updateDonationStatus(isValid) {
    const statusAlert = document.getElementById('donationStatusAlert');
    const headerBadge = document.getElementById('donationHeaderBadge');
    
    if (isValid) {
        // Show success status
        if (!statusAlert) {
            const alertHtml = `
                <div class="alert alert-success mb-3" role="alert" id="donationStatusAlert">
                    <i class="bi bi-check-circle-fill"></i> <strong>${t('web.advanced.donation_system_will_disable')}</strong><br>
                    <small>${t('web.advanced.donation_save_to_apply')}</small>
                </div>`;
            const cardBody = document.getElementById('donationCardBody');
            if (cardBody) {
                cardBody.insertAdjacentHTML('afterbegin', alertHtml);
            }
        }
        if (!headerBadge) {
            const badgeHtml = `<span class="badge bg-success ms-2" id="donationHeaderBadge">
                <i class="bi bi-check-circle-fill"></i> ${t('web.advanced.premium_active')}
            </span>`;
            const header = document.getElementById('donationCardHeader');
            if (header && !header.querySelector('#donationHeaderBadge')) {
                header.insertAdjacentHTML('beforeend', badgeHtml);
            }
        }
    } else {
        // Remove success status if key is invalid/removed
        if (statusAlert) statusAlert.remove();
        if (headerBadge) headerBadge.remove();
    }
}

function validateDonationKey() {
    const keyInput = document.getElementById('donation_disable_key');
    const keyStatus = document.getElementById('keyStatus');
    
    if (!keyInput || !keyStatus) return;
    
    const key = keyInput.value.trim();
    if (!key) {
        keyStatus.textContent = '❌ ' + t('web.advanced.key_enter_first');
        keyStatus.className = 'text-danger';
        updateDonationStatus(false);
        return;
    }

    if (validateKeyFormat(key)) {
        keyStatus.textContent = '✅ ' + t('web.advanced.key_validated');
        keyStatus.className = 'text-success';
        updateDonationStatus(true);

        // Show success message
        setTimeout(() => {
            keyStatus.textContent = '✅ ' + t('web.advanced.key_status_valid');
        }, 2000);
    } else {
        keyStatus.textContent = '❌ ' + t('web.advanced.key_invalid_purchase');
        keyStatus.className = 'text-danger';
        updateDonationStatus(false);
    }
}

// Update key status when typing and add event listener
document.addEventListener('DOMContentLoaded', function() {
    const keyInput = document.getElementById('donation_disable_key');
    if (keyInput) {
        keyInput.addEventListener('input', updateKeyStatus);
    }
    
    // Initialize difficulty slider
    loadDifficultyMultiplier();
});

// ======= Mech Evolution Difficulty Functions =======

function onSliderChange() {
    // This is called by user interaction with the slider
    updateDifficultyDisplay();
    enableManualOverride();
}

function updateDifficultyDisplay() {
    const slider = document.getElementById('mech_difficulty_multiplier');
    const difficultyValue = document.getElementById('difficultyValue');
    const levelCostPreview = document.getElementById('levelCostPreview');
    const levelCostDetails = document.getElementById('levelCostDetails');

    if (slider && difficultyValue) {
        const multiplier = parseFloat(slider.value);
        difficultyValue.textContent = multiplier.toFixed(2) + 'x';

        // Update slider thumb color based on difficulty
        if (multiplier < 0.75) {
            slider.style.accentColor = '#28a745'; // Green for easy
        } else if (multiplier <= 1.25) {
            slider.style.accentColor = '#ffc107'; // Yellow for normal
        } else {
            slider.style.accentColor = '#dc3545'; // Red for hard
        }

        // Update level cost preview with current multiplier
        if (window.baseMechData && levelCostPreview && levelCostDetails) {
            const base = window.baseMechData;
            // The server's cost is exact for the saved multiplier; other slider positions are estimated.
            const newCost = multiplier === base.difficulty_multiplier
                ? base.next_level_cost
                : Math.round(base.base_cost * multiplier);

            if (base.is_max_level) {
                levelCostPreview.textContent = t('web.advanced.max_level_reached');
                levelCostDetails.textContent = '(' + t('web.advanced.all_evolutions_done') + ')';
            } else {
                levelCostPreview.textContent = `${base.next_level_name} ${t('web.advanced.costs_prefix')}: $${newCost}`;
                levelCostDetails.textContent = `(${t('web.advanced.base_cost_prefix')}: $${base.base_cost})`;
            }
        }
    }

    // Note: Manual override auto-enabling is now handled in onSliderChange() for user interactions
}

function setDifficulty(value) {
    const slider = document.getElementById('mech_difficulty_multiplier');
    if (slider) {
        slider.value = value;
        updateDifficultyDisplay();
        // Auto-enable manual override when buttons are used (user interaction)
        enableManualOverride();
    }
}

async function loadDifficultyMultiplier() {
    try {
        const response = await fetch('/api/mech/difficulty');
        if (response.ok) {
            const data = await response.json();
            const slider = document.getElementById('mech_difficulty_multiplier');

            // Shape: see MechWebService._get_difficulty() (services/web/mech_web_service.py)
            if (slider && data.success !== false && data.multiplier !== undefined) {
                const multiplier = parseFloat(data.multiplier) || 1.0;
                const evo = data.simple_evolution || {};
                slider.value = multiplier;

                // Load manual override toggle status for standalone toggle
                const manualOverrideToggle = document.getElementById('mech_manual_difficulty_override_standalone');
                if (manualOverrideToggle && data.manual_override !== undefined) {
                    manualOverrideToggle.checked = data.manual_override;

                    // Set initial disabled state based on manual override status
                    const manualOverride = data.manual_override;
                    slider.disabled = !manualOverride;

                    // Also disable/enable difficulty buttons
                    const buttons = document.querySelectorAll('button[onclick*="setDifficulty"]');
                    buttons.forEach(btn => btn.disabled = !manualOverride);
                }

                // Store base data for the cost preview. The service only returns costs already scaled
                // by the multiplier, so the base cost is derived from them.
                const currentLevel = evo.current_level || 1;
                const nextLevelInfo = (evo.achieved_levels || {})[String(currentLevel + 1)];
                const nextLevelCost = evo.next_level_cost || 0;
                window.baseMechData = {
                    current_level: currentLevel,
                    next_level: currentLevel + 1,
                    next_level_name: nextLevelInfo ? nextLevelInfo.name : '',
                    next_level_cost: nextLevelCost,
                    base_cost: Math.round(nextLevelCost / multiplier),
                    difficulty_multiplier: multiplier,
                    is_max_level: !nextLevelInfo || nextLevelCost === 0,
                    manual_override: !!data.manual_override
                };

                // Initial display update (value label, slider colour, cost preview)
                updateDifficultyDisplay();
            }
        }
    } catch (error) {
        console.log('Could not load difficulty multiplier:', error);
        // Use default values
        updateDifficultyDisplay();
    }
}

async function saveMechDifficulty(difficultyMultiplier) {
    try {
        // Get manual override toggle status from standalone toggle
        const manualOverrideToggle = document.getElementById('mech_manual_difficulty_override_standalone');
        const manualOverride = manualOverrideToggle ? manualOverrideToggle.checked : false;

        const response = await fetch('/api/mech/difficulty', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                difficulty_multiplier: difficultyMultiplier,
                manual_override: manualOverride
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                console.log('Mech difficulty saved successfully:', data.message);

                // Show success feedback
                showNotification(t('web.advanced.mech_difficulty_updated') + ': ' + data.message, 'success');
            } else {
                console.error('Failed to save mech difficulty:', data.error);
                showNotification(t('web.advanced.mech_difficulty_failed') + ': ' + data.error, 'error');
            }
        } else {
            console.error('HTTP error saving mech difficulty:', response.status);
            showNotification(t('web.advanced.mech_difficulty_failed'), 'error');
        }
    } catch (error) {
        console.error('Error saving mech difficulty:', error);
        showNotification(t('web.advanced.mech_difficulty_error'), 'error');
    }
}

function showNotification(message, type = 'info') {
    // Simple notification function - could be enhanced with toasts
    const alertClass = type === 'success' ? 'alert-success' :
                      type === 'error' ? 'alert-danger' : 'alert-info';

    // You could implement proper toast notifications here
    console.log(`[${type.toUpperCase()}] ${message}`);
}

// ======= Manual Difficulty Override Functions =======

async function saveMechOverrideToggle() {
    try {
        const manualOverrideToggle = document.getElementById('mech_manual_difficulty_override_standalone');
        const manualOverride = manualOverrideToggle ? manualOverrideToggle.checked : false;

        // UX: Reset slider to normal (1.0x) when manual override is disabled
        const difficultySlider = document.getElementById('mech_difficulty_multiplier');
        let difficultyMultiplier;

        if (!manualOverride) {
            // Manual override OFF → Reset to normal (automatic mode)
            difficultyMultiplier = 1.0;
            if (difficultySlider) {
                difficultySlider.value = 1.0;
                difficultySlider.disabled = true; // Disable slider when override is OFF
                updateDifficultyDisplay(); // Update UI to show 1.0x
            }
            // Disable difficulty buttons too
            const buttons = document.querySelectorAll('button[onclick*="setDifficulty"]');
            buttons.forEach(btn => btn.disabled = true);
        } else {
            // Manual override ON → Use current slider value
            difficultyMultiplier = difficultySlider ? parseFloat(difficultySlider.value) : 1.0;
            if (difficultySlider) {
                difficultySlider.disabled = false; // Enable slider when override is ON
            }
            // Enable difficulty buttons too
            const buttons = document.querySelectorAll('button[onclick*="setDifficulty"]');
            buttons.forEach(btn => btn.disabled = false);
        }

        console.log(`Saving manual override toggle: ${manualOverride} with difficulty: ${difficultyMultiplier}`);

        const response = await fetch('/api/mech/difficulty', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                difficulty_multiplier: difficultyMultiplier,
                manual_override: manualOverride
            })
        });

        if (response.ok) {
            const data = await response.json();
            if (data.success) {
                console.log('Manual override toggle saved successfully:', data.message);

                // Show brief visual feedback
                const label = manualOverrideToggle?.closest('.form-check')?.querySelector('.form-check-label');
                if (label) {
                    const originalColor = label.style.color;
                    label.style.color = '#28a745'; // Green for success
                    setTimeout(() => {
                        label.style.color = originalColor;
                    }, 500);
                }
            } else {
                console.error('Failed to save manual override:', data.error);
            }
        } else {
            console.error('HTTP error saving manual override:', response.status);
        }
    } catch (error) {
        console.error('Error saving manual override toggle:', error);
    }
}

function enableManualOverride() {
    const manualOverrideToggle = document.getElementById('mech_manual_difficulty_override_standalone');
    if (manualOverrideToggle && !manualOverrideToggle.checked) {
        manualOverrideToggle.checked = true;
        console.log('Manual difficulty override automatically enabled due to user interaction');

        // Save immediately via dedicated API
        saveMechOverrideToggle();

        // Visual feedback
        const label = manualOverrideToggle.closest('.form-check').querySelector('.form-check-label');
        if (label) {
            label.style.color = '#ffc107';
            setTimeout(() => {
                label.style.color = '';
            }, 1000);
        }
    }
}
