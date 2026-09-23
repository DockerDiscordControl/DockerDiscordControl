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

        // Seven rows to a page. The pager is handed the rows that MATCH, so the
        // pages are pages of the search result rather than of everything with
        // the misses left as gaps.
        const pager = typeof window.ddcPager === 'function'
            ? window.ddcPager('container-pager', 7) : null;

        const apply = () => {
            const match = window.matchingContainers;
            if (typeof match !== 'function') { return; }
            const names = rows().map(row => row.dataset.containerName);
            const wanted = new Set(match(names, field.value));
            const matching = [];
            for (const row of rows()) {
                const hit = wanted.has(row.dataset.containerName);
                row.hidden = !hit;
                if (hit) { matching.push(row); }
            }
            if (noMatch) { noMatch.hidden = matching.length > 0; }
            if (pager) { pager.show(matching); }
        };

        // A new search starts at the first page: staying on page 4 while the
        // result shrank to five rows shows an empty table (paging.js clamps it,
        // but landing on the last page is not what the operator asked for).
        field.addEventListener('input', () => {
            if (pager) { pager.reset(); }
            apply();
        });
        apply();
    });
}
