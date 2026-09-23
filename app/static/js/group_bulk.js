// -*- coding: utf-8 -*-
// Acting on one of the operator's container groups from the container table.
//
// The groups reach the scheduled tasks and the auto-action rule targets; this
// is the third place they have to work, and it was the one that knew nothing
// about them. With 26 containers, giving a group of seven the same permissions
// meant 35 tick boxes one at a time.
//
// These are the operator's own groups from /api/groups, NOT the Compose stack
// label - he asked for that explicitly, and 0 of his 26 containers carry one.
//
// The bar FILLS IN the form; it never saves. The operator sees what changed
// and presses Save as before, so nothing can half-apply.

function bulkPlan(groupContainers, rowNames) {
    // groupContainers null/undefined means "no group picked", which is not the
    // same as a group with no containers: one is a slip, the other is a group
    // worth warning about.
    if (!groupContainers) {
        return { rows: [], missing: [], chosen: false };
    }
    const onPage = new Set(rowNames);
    return {
        rows: groupContainers.filter(name => onPage.has(name)),
        // Named, not dropped: the group resolves against the containers DDC
        // steers, the table lists what the host has now. Quietly acting on
        // five of seven and reporting success is the failure to avoid.
        missing: groupContainers.filter(name => !onPage.has(name)),
        chosen: true
    };
}

function bulkMessage(plan, texts) {
    if (!plan.chosen) {
        return { level: 'info', text: texts.pick_group };
    }
    if (plan.missing.length) {
        const applied = texts.applied.replace('{count}', plan.rows.length);
        const gone = texts.not_on_page.replace('{names}', plan.missing.join(', '));
        return { level: 'warning', text: applied + ' ' + gone };
    }
    if (!plan.rows.length) {
        return { level: 'warning', text: texts.nothing };
    }
    return { level: 'success', text: texts.applied.replace('{count}', plan.rows.length) };
}

if (typeof window !== 'undefined') {
    window.bulkPlan = bulkPlan;
    window.bulkMessage = bulkMessage;
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const picker = document.getElementById('bulk-group');
        const table = document.getElementById('docker-container-list');
        if (!picker || !table) { return; }
        const texts = window.DDC_BULK_TEXTS || {};
        const line = document.getElementById('bulk-group-message');

        const say = (message) => {
            if (!line) { return; }
            line.className = 'mt-2 text-' + (message.level === 'success' ? 'success'
                : message.level === 'warning' ? 'warning' : 'muted');
            line.textContent = message.text;
        };

        const rowNames = () => Array.from(table.querySelectorAll('tr[data-container-name]'))
            .map(row => row.dataset.containerName);

        const chosenGroup = () => {
            const name = picker.value;
            if (!name) { return null; }
            const group = (window.DDC_BULK_GROUPS || []).find(g => g.name === name);
            return group ? group.containers : [];
        };

        const wanted = (action) => {
            const box = document.getElementById('bulk-allow-' + action);
            return !!(box && box.checked);
        };

        const set = (box, checked) => {
            if (!box || box.disabled) { return; }
            box.checked = checked;
            // The page enables the permission boxes and marks the form dirty
            // off these events; setting .checked alone does neither.
            box.dispatchEvent(new Event('change', { bubbles: true }));
        };

        const apply = (active) => {
            const plan = bulkPlan(chosenGroup(), rowNames());
            plan.rows.forEach(name => {
                const row = table.querySelector(`tr[data-container-name="${name}"]`);
                if (!row) { return; }
                set(row.querySelector('input[name="selected_servers"]'), active);
                ['status', 'start', 'stop', 'restart'].forEach(action => {
                    set(row.querySelector(`input[name="allow_${action}_${name}"]`),
                        active && wanted(action));
                });
            });
            say(bulkMessage(plan, texts));
        };

        const applyButton = document.getElementById('bulk-apply-btn');
        const removeButton = document.getElementById('bulk-remove-btn');
        if (applyButton) { applyButton.addEventListener('click', () => apply(true)); }
        if (removeButton) { removeButton.addEventListener('click', () => apply(false)); }

        fetch('/api/groups')
            .then(answer => answer.json())
            .then(body => {
                window.DDC_BULK_GROUPS = body.groups || [];
                window.DDC_BULK_GROUPS.forEach(group => {
                    const option = document.createElement('option');
                    option.value = group.name;
                    // "name (5)", the same shape the task form's picker uses:
                    // a <select> cannot carry the collection icon, so the size
                    // is what says this is a group and how far it reaches.
                    option.textContent = group.name +
                        ' (' + (group.containers || []).length + ')';
                    picker.appendChild(option);
                });
            })
            .catch(() => {
                // Silent here on purpose: the groups section on the same page
                // reports a failed /api/groups with its own message, and two
                // alerts for one failure read like two failures.
                window.DDC_BULK_GROUPS = [];
            });
    });
}
