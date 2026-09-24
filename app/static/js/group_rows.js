// A group as a row in the container table.
//
// OPERATOR DECISION (2026-09-24), in two steps. First: the "apply to group"
// bar was hard to read - pick a group in a dropdown, tick four boxes somewhere
// else, press Apply. A group behaves like a container, so it is shown like
// one: its own row, same table, same columns, below the containers and set
// apart from them.
//
// Then the correction that matters more. A group is NOT a shortcut for ticking
// boxes on its members, and not a summary of them either. It is DECOUPLED from
// the single-container control: a container that is switched off in DDC, or
// that may only be stopped on its own, can sit in a group that is allowed to
// do anything else. So this row edits the GROUP's own Active and its own four
// actions, which live in groups.json beside its name and members
// (services/config/group_service.py), and it never reads or writes a
// container's boxes.
//
// THAT IS WHY THERE IS NO APPLY AND NO SAVE HERE. The container table is saved
// with the settings form; a group is its own file behind /api/groups, the same
// route the group dialog uses. A tick is sent straight away, and the row says
// so if it does not arrive.

const GROUP_ACTIONS = ['status', 'start', 'stop', 'restart'];

// The group's permission list after one box was clicked. Pure, and it reads no
// container: nothing about a container decides what its group may do.
function withPermission(actions, action, checked) {
    const had = new Set(actions || []);
    if (checked) {
        // Only the four the columns offer. The service refuses anything else,
        // and a refusal arriving after the tick is drawn is the worst of both.
        if (GROUP_ACTIONS.includes(action)) { had.add(action); }
    } else {
        had.delete(action);
    }
    // Always in column order: stored in click order it would come back
    // shuffled, and a diff of groups.json would show a change nobody made.
    return GROUP_ACTIONS.filter(known => had.has(known));
}

// Whether the search above the table should show this group.
//
// THE GAP (2026-09-24): the search filtered the container rows and left the
// group rows standing, whatever was typed. With one group that is invisible;
// with twenty it is a table that ignores its own search box.
//
// A GROUP ALSO MATCHES BY ITS MEMBERS. The question behind typing a container
// name is "where is this thing", and a group holding it is part of the
// answer - the row even lists the members underneath, so a match there is
// visible rather than mysterious.
function groupMatches(group, query) {
    const wanted = (query || '').trim().toLowerCase();
    if (!wanted) { return true; }          // an empty search shows everything
    const names = [group.name].concat(group.containers || []);
    return names.some(name => String(name).toLowerCase().includes(wanted));
}

if (typeof window !== 'undefined') {
    window.withPermission = withPermission;
    window.groupMatches = groupMatches;
}

// --- the page itself -------------------------------------------------------

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const body = document.getElementById('group-rows');
        if (!body) { return; }                     // not the configuration page
        const texts = window.DDC_GROUP_ROW_TEXTS || {};
        const message = document.getElementById('group-rows-message');
        const pager = typeof window.ddcPager === 'function'
            ? window.ddcPager('group-rows-pager', 7) : null;
        let groups = [];

        const say = (text, level) => {
            if (!message) { return; }
            message.textContent = text || '';
            message.className = 'form-text mb-0' + (text ? ' text-' + (level || 'muted') : '');
        };

        // Built out of nodes, never innerHTML: a group's name is typed by the
        // operator and goes straight back onto his own page.
        function cell(...nodes) {
            const td = document.createElement('td');
            td.append(...nodes);
            return td;
        }

        function line(tag, className, text) {
            const element = document.createElement(tag);
            element.className = className;
            element.textContent = text;
            return element;
        }

        function icon(name, className) {
            const element = document.createElement('i');
            element.className = 'bi bi-' + name + (className ? ' ' + className : '');
            element.setAttribute('aria-hidden', 'true');
            return element;
        }

        // The whole group, as /api/groups wants it back. Sending only what
        // changed would replace the containers with nothing: the route reads a
        // missing list as an empty one, which is how a group of seven becomes
        // a group of none.
        async function save(group, changed) {
            const wanted = Object.assign({}, group, changed);
            let answer;
            try {
                answer = await fetch('/api/groups', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: wanted.name,
                        containers: wanted.containers || [],
                        active: wanted.active,
                        allowed_actions: wanted.allowed_actions || []
                    })
                });
            } catch (error) {
                answer = null;
            }
            if (!answer || !answer.ok) {
                // The boxes are redrawn from what the server last confirmed,
                // so a tick that did not arrive does not stay on screen as if
                // it had. Silence here is what made the old bar untrustworthy.
                say(texts.save_failed || 'Not saved', 'danger');
                render();
                return;
            }
            Object.assign(group, changed);
            say(texts.saved || '', 'success');
            render();
        }

        function checkboxCell(group, action) {
            const td = document.createElement('td');
            td.className = 'text-center';
            const box = document.createElement('input');
            box.type = 'checkbox';
            box.className = 'form-check-input';
            // NO name attribute: this box belongs to groups.json, and the
            // settings save collects every named field inside #config-form.
            box.dataset.group = group.name;
            box.dataset.action = action;
            box.checked = action === 'active'
                ? group.active !== false
                : (group.allowed_actions || []).includes(action);
            box.setAttribute('aria-label', `${group.name}: ${action}`);
            box.addEventListener('change', () => {
                if (action === 'active') {
                    save(group, { active: box.checked });
                } else {
                    save(group, {
                        allowed_actions: withPermission(
                            group.allowed_actions, action, box.checked)
                    });
                }
            });
            td.appendChild(box);
            return td;
        }

        function row(group) {
            const tr = document.createElement('tr');
            tr.className = 'group-row';
            tr.dataset.groupName = group.name;

            tr.appendChild(cell(icon('collection', 'text-warning')));
            tr.appendChild(checkboxCell(group, 'active'));

            const members = group.containers || [];
            const gone = group.missing || [];
            const name = cell(line('code', 'text-warning', group.name),
                              document.createElement('br'),
                              line('small', 'text-light',
                                   members.join(', ') || (texts.empty || '')));
            if (gone.length) {
                // A group naming a container the host no longer has would act
                // on fewer than the operator thinks and report success.
                name.append(document.createElement('br'),
                            line('small', 'text-danger', (texts.missing || '{names}')
                                .replace('{names}', gone.join(', '))));
            }
            name.className = 'sticky-name-column';
            tr.appendChild(name);

            tr.appendChild(cell(line('span', 'text-muted small',
                (texts.member_count || '{count}').replace('{count}', members.length))));
            for (const action of GROUP_ACTIONS) { tr.appendChild(checkboxCell(group, action)); }
            tr.appendChild(cell());     // players is a per-container thing

            const edit = document.createElement('button');
            edit.type = 'button';       // without it, it submits the settings form
            edit.className = 'btn btn-sm btn-outline-warning';
            edit.title = texts.edit || '';
            edit.setAttribute('aria-label', `${texts.edit || 'edit'}: ${group.name}`);
            edit.appendChild(icon('pencil'));
            edit.setAttribute('data-bs-toggle', 'modal');
            edit.setAttribute('data-bs-target', '#containerGroupsModal');
            edit.addEventListener('click', () => {
                document.dispatchEvent(
                    new CustomEvent('ddc:edit-group', { detail: group.name }));
            });
            const tools = cell(edit);
            tools.className = 'text-center';
            tr.appendChild(tools);
            return tr;
        }

        const search = document.getElementById('container-search');

        function render() {
            body.innerHTML = '';
            const query = search ? search.value : '';
            const shown = [];
            for (const group of groups) {
                const tr = row(group);
                body.appendChild(tr);
                // Hidden, not left out: the pager is handed the MATCHES, so
                // its pages are pages of the search result rather than of
                // everything with the misses left as gaps (paging.js).
                if (groupMatches(group, query)) {
                    shown.push(tr);
                } else {
                    tr.hidden = true;
                }
            }
            if (pager) { pager.show(shown); }
        }

        async function load() {
            try {
                const answer = await fetch('/api/groups');
                groups = answer.ok ? ((await answer.json()).groups || []) : [];
                if (!answer.ok) { say(texts.load_failed || '', 'danger'); }
            } catch (error) {
                say(texts.load_failed || '', 'danger');
                groups = [];
            }
            render();
        }

        // A group made, changed or deleted in the dialog shows up here at once.
        // Without this the rows stayed as they were until the page was
        // reloaded - which is exactly the bug the operator hit with the old
        // dropdown on 2026-09-24.
        document.addEventListener('ddc:groups-changed', load);
        // The same box the containers listen to: one search over one table.
        search?.addEventListener('input', () => {
            if (pager) { pager.reset(); }
            render();
        });
        load();
    });
}
