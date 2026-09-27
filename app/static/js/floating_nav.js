// The floating navigation: which dot is active, and what a click does.
//
// EVERY dot stays visible, whichever tab is open. An earlier version this
// evening hid the dots of closed panes - the navigation was "describing a page
// that no longer exists" - and the operator asked for the opposite. He is
// right: a dot click already opens its pane before scrolling, so hiding the
// dot removed the one thing the bar is for, which is reaching anything on the
// page in one click without first working out which tab it lives behind.
//
// Moved out of base.html on 2026-09-23 - it grew past the inline budget when
// the dots learned to follow the open tab, and the rule that caught it is the
// same one that cleared 4,691 lines out of the templates that evening. No
// Jinja in here; pinned by
// tests/spec/test_the_page_is_not_mostly_one_script.py

(function() {
    const nav = document.getElementById('floatingNav');
    if (!nav) return;

    // Throttled scroll handler for active section tracking
    let ticking = false;
    window.addEventListener('scroll', function() {
        if (!ticking) {
            window.requestAnimationFrame(function() {
                updateActiveSection();
                ticking = false;
            });
            ticking = true;
        }
    });

    function scrollToTarget(target) {
        const offset = 20;
        window.scrollTo({
            top: target.getBoundingClientRect().top + window.scrollY - offset,
            behavior: 'smooth'
        });
    }

    // Shows the tab pane a target sits in, if it is not the open one.
    // Answers true when it had to switch, so the caller can wait for the layout.
    function showPaneOf(target) {
        const pane = target.closest ? target.closest('.tab-pane') : null;
        if (!pane || pane.classList.contains('active')) { return false; }
        const trigger = document.querySelector('[data-bs-target="#' + pane.id + '"]');
        if (!trigger || !window.bootstrap || !window.bootstrap.Tab) { return false; }
        window.bootstrap.Tab.getOrCreateInstance(trigger).show();
        return true;
    }

    // Smooth scroll to sections
    nav.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href');

            if (targetId === '#top') {
                window.scrollTo({ top: 0, behavior: 'smooth' });
            } else {
                const target = document.querySelector(targetId);
                if (target) {
                    // The settings live in tab panes now. A hidden pane has no
                    // position to scroll to, so the pane is shown FIRST and the
                    // scroll happens after Bootstrap has laid it out - otherwise
                    // half the dots do nothing at all.
                    if (showPaneOf(target)) {
                        setTimeout(() => scrollToTarget(target), 200);
                    } else {
                        scrollToTarget(target);
                    }
                }
            }
        });
    });

    // Update active section indicator
    function updateActiveSection() {
        // THE BAR'S OWN DOTS, not a second list. This was a list of twelve ids
        // typed out here, and the channel-translation dot added on 2026-09-27
        // was not in it: it never lit up (operator: "it is not highlighted
        // like the others"). A dot now lights up because it is in the bar.
        const sections = Array.from(nav.querySelectorAll('.nav-dot'))
            .map(dot => (dot.getAttribute('href') || '').replace(/^#/, ''))
            .filter(id => id && id !== 'top');

        const scrollPos = window.scrollY + 150;
        // Every section that is laid out, top to bottom. offsetTop was 0 for
        // anything inside a hidden tab pane, so every section in a closed tab
        // looked like it was at the top of the page; the rectangle is
        // document-relative whatever is displayed, and a hidden pane measures
        // 0 height - which is left out here.
        const laidOut = sections
            .map(id => {
                const section = document.getElementById(id);
                if (!section) { return null; }
                const box = section.getBoundingClientRect();
                return box.height > 0 ? { id, top: box.top + window.scrollY } : null;
            })
            .filter(Boolean)
            .sort((a, b) => a.top - b.top);

        // The last section that begins above the line. "The section the line
        // is inside" left every dot dark in the gap between two cards (operator,
        // 2026-09-27) - there the section above is still the one being read.
        let activeId = null;
        laidOut.forEach(entry => {
            if (entry.top <= scrollPos) { activeId = entry.id; }
        });

        // AT THE END OF THE PAGE the line cannot reach a short last section:
        // the channel translation and the Auto-Action System, each the last
        // card of its tab, never lit up and the section above stayed lit. Once
        // the page is scrolled as far as it goes, the lowest section in view is
        // the one being read.
        const doc = document.documentElement;
        const pageEnd = Math.max(doc.scrollHeight || 0, (document.body && document.body.scrollHeight) || 0);
        if (window.innerHeight + window.scrollY >= pageEnd - 2) {
            const bottom = window.scrollY + window.innerHeight;
            laidOut.forEach(entry => {
                if (entry.top < bottom) { activeId = entry.id; }
            });
        }

        // Update active class
        nav.querySelectorAll('.nav-dot').forEach(dot => {
            const href = dot.getAttribute('href');
            if (activeId && href === '#' + activeId) {
                dot.classList.add('active');
            } else {
                dot.classList.remove('active');
            }
        });
    }

    // Initial check
    updateActiveSection();
})();
