// Cutting a long list into pages, for the container table and the group picker.
//
// Both used to scroll inside a box of their own. The operator asked for seven
// rows and a page switcher instead (2026-09-24), which also retires the sticky
// header the container table had: that existed only because the box scrolled,
// and with seven rows the column names never leave the screen.
//
// A ROW OFF THE PAGE IS HIDDEN, NEVER REMOVED. Every container row carries
// eighteen form fields, thirteen of them hidden round-trip values, and
// saveConfigAjax collects what is inside #config-form. A removed row would be
// absent from the next save, and the handler reads an absent checkbox as OFF -
// the container's permissions would go quiet without anyone touching them.

function pageCount(total, perPage) {
    // Zero pages would mean a pager with nothing in it and "page 0 of 0" under
    // an empty table. One empty page is what is actually on screen.
    return Math.max(1, Math.ceil(total / perPage));
}

function clampPage(page, total, perPage) {
    // THE CASE THAT BITES: on page 4, three letters typed into the search, five
    // matches left. Page 4 of 1 shows nothing and says nothing about why.
    return Math.min(Math.max(1, page), pageCount(total, perPage));
}

function pageSlice(items, page, perPage) {
    const wanted = clampPage(page, items.length, perPage);
    return items.slice((wanted - 1) * perPage, wanted * perPage);
}

if (typeof window !== 'undefined') {
    window.pageCount = pageCount;
    window.clampPage = clampPage;
    window.pageSlice = pageSlice;
}

// --- the page itself -------------------------------------------------------

if (typeof document !== 'undefined' && document.addEventListener) {
    // One pager, driven by whoever owns the list. `visible` is the rows that
    // pass whatever filter is in force - the search box, usually - so the pages
    // are pages of the MATCHES, not of everything with the misses left as gaps.
    window.ddcPager = function ddcPager(pagerId, perPage) {
        let page = 1;

        function render(visible) {
            const pager = document.getElementById(pagerId);
            const pages = pageCount(visible.length, perPage);
            page = clampPage(page, visible.length, perPage);
            const shown = new Set(pageSlice(visible, page, perPage));

            for (const item of visible) {
                item.hidden = !shown.has(item);
            }
            if (!pager) { return; }

            pager.innerHTML = '';
            pager.hidden = pages < 2;   // one page needs no switcher
            for (let number = 1; number <= pages; number += 1) {
                const button = document.createElement('button');
                // Not an <a href>: a link would add a history entry per page,
                // and on this page the back button means "leave the settings".
                button.type = 'button';
                button.className = 'btn btn-sm ' +
                    (number === page ? 'btn-primary' : 'btn-outline-secondary');
                button.textContent = String(number);
                button.addEventListener('click', () => {
                    page = number;
                    render(visible);
                });
                pager.appendChild(button);
            }
        }

        return {
            show(visible) { render(visible); },
            reset() { page = 1; },
        };
    };
}
