// After a save that changed the panel timezone: take the existing tasks along?
//
// A task carries its own zone, so the save did not touch it - and whether it
// should is the operator's call, not ours: "10:00" can mean "10:00 wherever I
// am" or "10:00 in Berlin, because that is when the other end is awake"
// (operator decision 2026-09-23). The save answer carries the question; this
// puts it and, on yes, sends the answer.
//
// WHY A FILE OF ITS OWN (audit 2026-09-26): the question used to live in
// main.js, which no template loads, while the save handler the page actually
// runs (saveConfigAjax in panel.js) ignored it. The question was computed on
// every such save and never asked. It is here so node can run it
// (tests/js/timezone_question.test.js), and panel.js calls it.
//
// Returns how many tasks were moved: 0 for "no" or no question, -1 when the
// move was asked for and refused.
async function askAboutTaskTimezone(question, deps) {
    if (!question) { return 0; }
    const t = deps.t;
    const body = t('web.timezone.question_body')
        .replace('{count}', question.tasks)
        .replace('{old}', question.old)
        .replace('{new}', question.new);
    // Confirm: OK keeps the clock time, Cancel keeps the moment.
    const keepClock = deps.confirm(
        t('web.timezone.question_title') + '\n\n' + body + '\n\n' +
        'OK: ' + t('web.timezone.keep_clock') + '\n' +
        t('web.common.cancel') + ': ' + t('web.timezone.keep_moment'));
    if (!keepClock) { return 0; }
    try {
        const response = await deps.fetch('/tasks/retime', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({timezone: question.new})
        });
        const result = await response.json();
        return result && result.success ? (result.moved || 0) : -1;
    } catch (error) {
        console.error('Moving the tasks to the new timezone failed:', error);
        return -1;
    }
}

if (typeof window !== 'undefined') {
    window.askAboutTaskTimezone = askAboutTaskTimezone;
}
