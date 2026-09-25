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
        command_cooldowns: {
            control: parseInt(document.getElementById('cooldown_control').value),
            serverstatus: parseInt(document.getElementById('cooldown_serverstatus').value),
            info: parseInt(document.getElementById('cooldown_info').value),
            help: parseInt(document.getElementById('cooldown_help').value),
            ping: parseInt(document.getElementById('cooldown_ping').value),
            donate: parseInt(document.getElementById('cooldown_donate').value),
            language: parseInt(document.getElementById('cooldown_language').value),
            forceupdate: parseInt(document.getElementById('cooldown_forceupdate').value)
        },
        button_cooldowns: {
            // The admin overview's five. This list is hard-coded while the read
            // loop above is dynamic, so a slider missing HERE is rendered and
            // then dropped on save - it would look adjustable and reset itself.
            admin_overview_admin: parseInt(document.getElementById('button_admin_overview_admin')?.value || 5),
            admin_overview_restart_all: parseInt(document.getElementById('button_admin_overview_restart_all')?.value || 30),
            admin_overview_stop_all: parseInt(document.getElementById('button_admin_overview_stop_all')?.value || 30),
            admin_overview_restart_stack: parseInt(document.getElementById('button_admin_overview_restart_stack')?.value || 20),
            admin_overview_donate: parseInt(document.getElementById('button_admin_overview_donate')?.value || 10),
            start: parseInt(document.getElementById('button_start').value),
            stop: parseInt(document.getElementById('button_stop').value),
            restart: parseInt(document.getElementById('button_restart').value),
            info: parseInt(document.getElementById('button_info').value),
            logs: parseInt(document.getElementById('button_logs').value),
            live_refresh: parseInt(document.getElementById('button_live_refresh').value),
            mech_donate: parseInt(document.getElementById('button_mech_donate').value),
            mech_history: parseInt(document.getElementById('button_mech_history').value),
            mech_details: parseInt(document.getElementById('button_mech_details').value),
            mech_display: parseInt(document.getElementById('button_mech_display').value),
            mech_story: parseInt(document.getElementById('button_mech_story').value),
            mech_music: parseInt(document.getElementById('button_mech_music').value),
            admin: parseInt(document.getElementById('button_admin').value),
            help: parseInt(document.getElementById('button_help').value),
            tasks: parseInt(document.getElementById('button_tasks').value),
            task_delete: parseInt(document.getElementById('button_task_delete').value),
            edit_info: parseInt(document.getElementById('button_edit_info').value),
            protected_info: parseInt(document.getElementById('button_protected_info').value),
            protected_info_edit: parseInt(document.getElementById('button_protected_info_edit').value)
        }
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
