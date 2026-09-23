// The floating navigation: which dot is active, which dots make sense, and
// what a click does.
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

    // Which dots make sense right now.
    //
    // Ten of the thirteen sections live in a tab pane since the settings were
    // split, and three panes are hidden at any moment - so most of the dots
    // pointed at something not on screen. Clicking one still worked (a dot
    // opens its pane first), but the navigation was describing a page that no
    // longer exists: one long scroll of everything.
    //
    // It asks the DOM which pane each target is in rather than keeping a map of
    // section-to-tab. A map would be a second thing to keep in step with the
    // markup, and the list in updateActiveSection already has to be maintained
    // by hand. A section in NO pane - the mech panel above the tabs, the log
    // below them - always shows.
    function updateVisibleDots() {
        nav.querySelectorAll('.nav-dot').forEach(dot => {
            const href = dot.getAttribute('href');
            if (!href || href === '#top') { return; }
            const target = document.querySelector(href);
            const pane = target && target.closest ? target.closest('.tab-pane') : null;
            if (!pane) {
                dot.hidden = false;
                return;
            }
            dot.hidden = !pane.classList.contains('active');
        });
    }

    document.addEventListener('shown.bs.tab', updateVisibleDots);
    updateVisibleDots();

    // Update active section indicator
    function updateActiveSection() {
        const sections = [
            'donationSection', 'discord-settings', 'channel-settings',
            'permissions-table', 'server-selection', 'container-groups',
            'task-scheduler', 'task-list', 'aas-section',
            'language-settings', 'auth-settings',
            'heartbeat-section', 'log-section'
        ];

        const scrollPos = window.scrollY + 150;
        let activeId = null;

        sections.forEach(id => {
            const section = document.getElementById(id);
            // offsetTop was 0 for anything inside a hidden tab pane, so every
            // section in a closed tab looked like it was at the top of the page.
            // The rectangle is document-relative whatever is displayed, and a
            // hidden pane measures 0 height - which simply never matches.
            if (section) {
                const box = section.getBoundingClientRect();
                const top = box.top + window.scrollY;
                if (box.height > 0 && scrollPos >= top && scrollPos < top + box.height) {
                    activeId = id;
                }
            }
        });

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
