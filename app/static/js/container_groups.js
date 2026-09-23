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

// Saving REPLACES the containers of a group with that name. Adding an eighth
// container to a group of seven by typing the name and picking one would
// therefore leave a group of one - and say "Saved" in green. This decides when
// to ask, and what to say.
function replacementWarning(name, existingGroups, editing, texts) {
    const wanted = (name || '').trim().toLowerCase();
    if (!wanted || editing) return null;      // editing a loaded group is not a surprise
    const existing = (existingGroups || []).find(
        g => (g.name || '').trim().toLowerCase() === wanted);
    if (!existing) return null;
    return (texts.replace || '')
        .replace('{name}', existing.name)
        .replace('{count}', String((existing.containers || []).length));
}

// The picker: 26 containers in a Ctrl-click multi-select was one stray click
// away from losing the whole selection, so it is a checkbox list with a search
// box. These two decide what the box shows and what the count says.
function matchingContainers(names, query) {
    const wanted = (query || '').trim().toLowerCase();
    if (!wanted) return (names || []).slice();   // empty search shows everything
    return (names || []).filter(name => name.toLowerCase().includes(wanted));
}

// The picked containers can be scrolled out of sight, or filtered out of the
// box entirely, so this number is the only thing that says what will be saved.
function selectionSummary(chosen, total, texts) {
    return (texts.chosen_count || '{chosen}/{total}')
        .replace('{chosen}', String(chosen))
        .replace('{total}', String(total));
}

if (typeof window !== 'undefined') {
    window.matchingContainers = matchingContainers;
    window.selectionSummary = selectionSummary;
    window.groupWarning = groupWarning;
    window.canSaveGroup = canSaveGroup;
    window.replacementWarning = replacementWarning;
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

        const boxes = () => Array.from(
            containerField.querySelectorAll('input.group-container-box'));
        const chosenContainers = () =>
            boxes().filter(box => box.checked).map(box => box.value);

        const searchField = document.getElementById('group-search');
        const counter = document.getElementById('group-chosen-count');
        const noMatch = document.getElementById('group-no-match');

        const showCount = () => {
            if (counter) {
                counter.textContent = selectionSummary(
                    chosenContainers().length, boxes().length, texts);
            }
        };

        // Seven to a page here too, over the search result (paging.js).
        const pager = typeof window.ddcPager === 'function'
            ? window.ddcPager('group-pager', 7) : null;

        const applySearch = () => {
            const wanted = new Set(matchingContainers(
                boxes().map(box => box.value), searchField ? searchField.value : ''));
            const matching = [];
            for (const item of containerField.querySelectorAll('.group-container-item')) {
                const hit = wanted.has(item.dataset.containerName);
                item.hidden = !hit;
                if (hit) { matching.push(item); }
            }
            if (noMatch) { noMatch.hidden = matching.length > 0; }
            if (pager) { pager.show(matching); }
        };

        // All / none act on what the search SHOWS, not on everything: with a
        // filter typed in, a button that silently ticked the hidden ones too
        // would be the opposite of what the box says.
        const setVisible = (checked) => {
            for (const box of boxes()) {
                const item = box.closest('.group-container-item');
                if (item && !item.hidden) { box.checked = checked; }
            }
            showCount();
        };

        let knownGroups = [];
        let editing = null;       // the group loaded into the form, if any

        const loadIntoForm = (group) => {
            // Clicking a group EDITS it: without this the only way to change a
            // group was to type its name again, which replaces its containers.
            editing = group.name;
            nameField.value = group.name;
            const members = new Set(group.containers || []);
            for (const box of boxes()) { box.checked = members.has(box.value); }
            showCount();
            nameField.focus();
        };

        // THE BUG THE OPERATOR HIT (2026-09-24): he made a group in this dialog
        // and the rest of the page did not know about it until a reload, because
        // everything else reads /api/groups once on load. Saying so here is one
        // line; making every reader poll would be a page that never settles.
        const announce = () =>
            document.dispatchEvent(new CustomEvent('ddc:groups-changed'));

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
            knownGroups = groups;
            list.innerHTML = '';
            if (groups.length === 0) {
                list.innerHTML = '<div class="text-muted" id="groups-empty">' +
                    (texts.none_yet || '') + '</div>';
                return;
            }
            for (const group of groups) {
                const row = document.createElement('div');
                row.className = 'd-flex align-items-center gap-2 mb-2';
                // Marked the way the rule editor and the task list mark a
                // group: the collection icon, amber instead of the containers'
                // blue, and the member count. The one page that is ABOUT
                // groups was the one that marked them not at all.
                const icon = document.createElement('i');
                icon.className = 'bi bi-collection text-warning';
                const label = document.createElement('button');
                label.type = 'button';
                label.className = 'btn btn-link fw-bold p-0 text-decoration-none text-warning';
                label.textContent = group.name;
                label.title = texts.edit || '';
                const size = document.createElement('span');
                size.className = 'text-muted small';
                size.textContent = '(' + (group.containers || []).length + ')';
                label.addEventListener('click', () => loadIntoForm(group));
                const members = document.createElement('span');
                members.className = 'text-muted small';
                members.textContent = (group.containers || []).join(', ');
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'btn btn-sm btn-outline-danger ms-auto';
                remove.textContent = texts.delete || 'Delete';
                remove.addEventListener('click', () => {
                    // Asked, not just done: a group is quick to make and easy
                    // to hit by accident next to the name.
                    const question = (texts.confirm_delete || '{name}?')
                        .replace('{name}', group.name);
                    if (confirm(question)) del(group.name);
                });
                row.append(icon, label, size, members, remove);
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
            const warning = replacementWarning(name, knownGroups, editing === name.trim(), texts);
            if (warning && !confirm(warning)) {
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
                editing = null;
                for (const box of boxes()) box.checked = false;
                showCount();
                await load();
                announce();
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
                announce();
            } else {
                say(body.error || 'Error', 'danger');
            }
        }

        document.getElementById('group-save-btn')?.addEventListener('click', save);
        searchField?.addEventListener('input', () => {
            if (pager) { pager.reset(); }
            applySearch();
        });
        applySearch();   // the first page, before anything is typed
        document.getElementById('group-select-all')?.addEventListener(
            'click', () => setVisible(true));
        document.getElementById('group-select-none')?.addEventListener(
            'click', () => setVisible(false));
        containerField.addEventListener('change', showCount);
        // The pencil on a group's row in the container table opens this dialog
        // on that group, rather than leaving the operator to find it in the list.
        document.addEventListener('ddc:edit-group', (event) => {
            const wanted = (knownGroups || []).find(g => g.name === event.detail);
            if (wanted) { loadIntoForm(wanted); }
        });
        showCount();
        load();
    });
}
