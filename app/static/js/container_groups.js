// The panel's container groups: what the page shows, decided in one place.
//
// The rules the page has to get right are small but easy to get wrong, so they
// live here and are tested in node (tests/js/container_groups.test.js):
//
// * a group that names containers DDC no longer has must SAY so - a group of
//   seven that quietly became six would act on six and report success;
// * the save button must not offer to save a group without a name;
// * a group with no containers is allowed (it is made first and filled after),
//   but it must be marked, because it is the one group that does nothing.

function groupWarning(group, texts) {
    if (group && Array.isArray(group.missing) && group.missing.length > 0) {
        return { level: 'warning', text: texts.missing.replace('{names}', group.missing.join(', ')) };
    }
    if (group && Array.isArray(group.containers) && group.containers.length === 0) {
        return { level: 'info', text: texts.empty };
    }
    return null;
}

function canSaveGroup(name, containers) {
    return typeof name === 'string' && name.trim().length > 0 && name.trim().length <= 80;
}

if (typeof window !== 'undefined') {
    window.groupWarning = groupWarning;
    window.canSaveGroup = canSaveGroup;
}

// --- the page itself -------------------------------------------------------
// Everything below only runs in a browser; the rules above are what the node
// test checks.
if (typeof document !== 'undefined') {
    document.addEventListener('DOMContentLoaded', () => {
        const list = document.getElementById('groups-list');
        if (!list) return;                       // not the configuration page

        const texts = window.DDC_GROUP_TEXTS || {};
        const nameField = document.getElementById('group-name');
        const containerField = document.getElementById('group-containers');
        const message = document.getElementById('group-message');

        const say = (text, level) => {
            message.textContent = text;
            message.className = 'mt-2 alert alert-' + (level || 'info');
        };

        const chosenContainers = () =>
            Array.from(containerField.selectedOptions).map(option => option.value);

        async function load() {
            let answer;
            try {
                answer = await fetch('/api/groups');
            } catch (error) {
                say(texts.load_failed || 'Groups could not be loaded', 'danger');
                return;
            }
            if (!answer.ok) {
                say(texts.load_failed || 'Groups could not be loaded', 'danger');
                return;
            }
            const groups = (await answer.json()).groups || [];
            list.innerHTML = '';
            if (groups.length === 0) {
                list.innerHTML = '<div class="text-muted" id="groups-empty">' +
                    (texts.none_yet || '') + '</div>';
                return;
            }
            for (const group of groups) {
                const row = document.createElement('div');
                row.className = 'd-flex align-items-center gap-2 mb-2';
                const label = document.createElement('span');
                label.className = 'fw-bold';
                label.textContent = group.name;
                const members = document.createElement('span');
                members.className = 'text-muted small';
                members.textContent = (group.containers || []).join(', ');
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'btn btn-sm btn-outline-danger ms-auto';
                remove.textContent = texts.delete || 'Delete';
                remove.addEventListener('click', () => del(group.name));
                row.append(label, members, remove);
                list.appendChild(row);

                const warning = groupWarning(group, texts);
                if (warning) {
                    const note = document.createElement('div');
                    note.className = 'small text-' +
                        (warning.level === 'warning' ? 'warning' : 'muted');
                    note.textContent = warning.text;
                    list.appendChild(note);
                }
            }
        }

        async function save() {
            const name = nameField.value;
            if (!canSaveGroup(name, chosenContainers())) {
                say(texts.needs_name || 'A group needs a name', 'warning');
                return;
            }
            const answer = await fetch('/api/groups', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name.trim(), containers: chosenContainers() })
            });
            const body = await answer.json().catch(() => ({}));
            if (answer.ok) {
                say(texts.saved || 'Saved', 'success');
                nameField.value = '';
                await load();
            } else {
                say(body.error || 'Error', 'danger');
            }
        }

        async function del(name) {
            const answer = await fetch('/api/groups/' + encodeURIComponent(name),
                                       { method: 'DELETE' });
            const body = await answer.json().catch(() => ({}));
            if (answer.ok) {
                say(texts.deleted || 'Deleted', 'success');
                await load();
            } else {
                say(body.error || 'Error', 'danger');
            }
        }

        document.getElementById('group-save-btn')?.addEventListener('click', save);
        load();
    });
}
