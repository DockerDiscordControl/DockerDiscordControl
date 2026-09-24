// When a save really does need the container restarted.
//
// THE OPERATOR, 2026-09-24, on the two banners the settings page carried under
// every tab: "we have these annoying notices everywhere - is that really so,
// can it not be smoother, without a restart?"
//
// Measured, it is not so. Exactly TWO fields need the process restarted,
// because the bot's connection to Discord is built from them once at startup:
// the bot token and the guild id. Both already mark themselves in the markup
// with class="requires-restart" and carry their own badge. Everything else the
// page saves is re-read while the bot runs - the channel permissions through a
// hot-reload event, the container list on every status pass, language and
// timezone by invalidating their caches.
//
// THE CHECK THAT DECIDED IT WAS THE PROBLEM. After a save the page asked
// whether any `.requires-restart` field HAS A VALUE:
//
//     else if (element.value && element.value.trim() !== '') { changesDetected = true; }
//
// A bot token is never empty. So the notice appeared after every save that had
// touched anything at all, which is what taught the operator to restart for
// nothing - and a notice that is always there is one nobody reads on the day
// it matters.
//
// The field already remembers what it was loaded with, in data-initial-value,
// because the badge beside it needs exactly the same comparison.

// Whether any of these fields was actually changed by the operator.
//
// `elements` is what querySelectorAll gives: anything with .value and
// .getAttribute. A field with no remembered value has not been touched by the
// page's own bookkeeping, so it cannot have changed - guessing "yes" there
// would put the old always-on notice straight back.
function restartIsNeeded(elements) {
    for (const element of elements || []) {
        const initial = element.getAttribute
            ? element.getAttribute('data-initial-value') : null;
        if (initial === null || initial === undefined) { continue; }
        // A checkbox carries its answer in .checked; everything else in .value.
        const now = element.type === 'checkbox'
            ? (element.checked ? (element.value || '1') : '') : element.value;
        if (String(now) !== String(initial)) { return true; }
    }
    return false;
}

if (typeof window !== 'undefined') {
    window.restartIsNeeded = restartIsNeeded;
}
