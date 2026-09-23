// -*- coding: utf-8 -*-
// Searching the container table.
//
// The table renders one row per container - 26 on the operator's server - and
// finding one meant reading all 26 names. This hides the rows that do not
// match what is typed.
//
// It does NOT bring its own matching rule. matchingContainers() lives in
// container_groups.js, which _scripts.html loads first, and has four node
// cases on it (tests/js/container_groups.test.js): matches anywhere in the
// name, ignores case, an empty search shows everything rather than nothing.
// A second copy here would be a second thing to get wrong, and the two search
// boxes on this page would start disagreeing about what "matches" means.
//
// If that helper is missing - a script that failed to load - nothing is
// filtered and every row stays visible. The safe state for a search is
// showing too much, never too little.

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const field = document.getElementById('container-search');
        const table = document.getElementById('docker-container-list');
        if (!field || !table) { return; }
        const noMatch = document.getElementById('container-search-no-match');

        const rows = () => Array.from(table.querySelectorAll('tr[data-container-name]'));

        const apply = () => {
            const match = window.matchingContainers;
            if (typeof match !== 'function') { return; }
            const names = rows().map(row => row.dataset.containerName);
            const visible = new Set(match(names, field.value));
            for (const row of rows()) {
                row.hidden = !visible.has(row.dataset.containerName);
            }
            if (noMatch) { noMatch.hidden = visible.size > 0; }
        };

        field.addEventListener('input', apply);
        apply();
    });
}
