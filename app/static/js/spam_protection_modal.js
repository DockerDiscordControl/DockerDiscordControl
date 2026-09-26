// Moved out of _spam_protection_modal.html on 2026-09-23.
// It was 128 lines inside a template that every panel page includes, and _base.html sends those pages with Cache-Control: no-cache - so it crossed the wire again on every load.
// A static file is not covered by that meta tag.
// No Jinja in here; pinned by tests/spec/test_the_page_is_not_mostly_one_script.py

// Whether the settings on screen are the ones the server holds.
//
// Review E22 in the admin dialog, one endpoint further on: fetch() rejects on
// a network failure and on nothing else - not on the 500 this route answers a
// read failure with (review D9). The error body fell into the success path,
// the dialog stayed open showing the HTML start values, and Save posted all of
// them: every command and button cooldown reset to the template's numbers.
// Nothing may be written back until a read has succeeded.
let spamSettingsLoaded = false;

// Load spam protection settings when modal opens
document.getElementById('spamProtectionModal').addEventListener('shown.bs.modal', function () {
    spamSettingsLoaded = false;
    fetch('/api/spam-protection')
        .then(response => {
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            return response.json();
        })
        .then(data => {
            if (!data || !data.global_settings) {
                throw new Error('unreadable spam protection settings');
            }
            // Set global settings
            document.getElementById('spamProtectionEnabled').checked = data.global_settings.enabled;
            document.getElementById('cooldownMessage').checked = data.global_settings.cooldown_message;
            document.getElementById('logViolations').checked = data.global_settings.log_violations;
            document.getElementById('maxCommandsPerMinute').value = data.global_settings.max_commands_per_minute;
            document.getElementById('maxButtonsPerMinute').value = data.global_settings.max_buttons_per_minute;

            // Set command cooldowns
            for (const [cmd, cooldown] of Object.entries(data.command_cooldowns)) {
                const element = document.getElementById('cooldown_' + cmd);
                if (element) element.value = cooldown;
            }

            // Set button cooldowns
            for (const [btn, cooldown] of Object.entries(data.button_cooldowns || {})) {
                const element = document.getElementById('button_' + btn);
                if (element) element.value = cooldown;
            }
            spamSettingsLoaded = true;
        })
        .catch(error => {
            console.error('Error loading spam protection settings:', error);
            alert(t('web.spam.error_loading'));
        });
});

// Every cooldown field in the dialog, by the prefix its id carries - the same
// fields the load fills, so the two halves cannot drift apart.
function readCooldowns(prefix) {
    const found = {};
    // Inside the dialog, not the page: the panel is one long document and an
    // id that happened to start the same way elsewhere would be saved as a
    // cooldown. Nothing does today - all 27 are in here - which is exactly
    // when to fence it.
    const dialog = document.getElementById('spamProtectionModal');
    if (!dialog) {
        return found;
    }
    dialog.querySelectorAll(`[id^="${prefix}"]`).forEach(field => {
        const name = field.id.slice(prefix.length);
        const value = parseInt(field.value, 10);
        if (name && !Number.isNaN(value)) {
            found[name] = value;
        }
    });
    return found;
}

function saveSpamProtection() {
    if (!spamSettingsLoaded) {
        // The form is showing its own start values, not the server's. Saving
        // here is what cost the settings in the admin dialog (review E22).
        alert(t('web.spam.refuse_save_unloaded'));
        return;
    }
    // Trigger unsaved changes warning to show that settings have changed
    if (typeof showUnsavedChangesAlert === 'function') {
        showUnsavedChangesAlert(false); // Spam protection settings don't require restart
    }
    const settings = {
        global_settings: {
            enabled: document.getElementById('spamProtectionEnabled').checked,
            cooldown_message: document.getElementById('cooldownMessage').checked,
            log_violations: document.getElementById('logViolations').checked,
            max_commands_per_minute: parseInt(document.getElementById('maxCommandsPerMinute').value),
            max_buttons_per_minute: parseInt(document.getElementById('maxButtonsPerMinute').value)
        },
        // READ FROM THE DIALOG, NOT FROM A LIST. These were twenty-four
        // names typed out here while the LOAD above is a loop over whatever
        // the server sent - and five of them have no field in the markup:
        // admin_overview_admin, _restart_all, _stop_all, _restart_stack and
        // _donate. The save reached for those with `?.value || 5` and wrote a
        // number out of this source file, so the operator could not see them,
        // could not change them, and every Save pinned them into his
        // configuration (2026-09-26). The comment that stood here had warned
        // about the same shape pointing the other way - "a slider missing HERE
        // is rendered and then dropped on save" - which is what a list does:
        // it goes stale exactly like the thing it guards.
        //
        // Nothing is lost by not sending one: spam_protection_service merges
        // the saved settings over its own defaults, so a cooldown the dialog
        // does not show keeps the default it always had.
        command_cooldowns: readCooldowns('cooldown_'),
        button_cooldowns: readCooldowns('button_')
    };

    fetch('/api/spam-protection', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Close modal and show success message
            const modal = bootstrap.Modal.getInstance(document.getElementById('spamProtectionModal'));
            modal.hide();

            // Use same notification system as saveConfigAjax
            const notification = document.getElementById('save-notification');
            if (notification) {
                notification.className = 'alert alert-success';
                notification.style.display = 'block';
                notification.innerHTML = '<i class="bi bi-check-circle"></i> ' + t('web.spam.saved_success');

                // Auto dismiss after 3 seconds
                setTimeout(() => {
                    notification.style.display = 'none';
                    notification.innerHTML = '';
                    notification.className = '';
                }, 3000);
            }
        } else {
            alert(t('web.spam.error_saving') + ': ' + (data.error || t('web.common.unknown_error')));
        }
    })
    .catch(error => {
        console.error('Error saving spam protection settings:', error);
        alert(t('web.spam.error_saving'));
    });
}

// Save spam protection settings
document.getElementById('saveSpamProtection').addEventListener('click', saveSpamProtection);
