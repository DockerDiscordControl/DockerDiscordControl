// What the task form says after a task was added.
//
// The form used to print its own green "Task added" for every 201, and the
// server's message was never shown. A one-time task whose time has passed IS
// saved - and switched off in the same call - so the operator saw a green
// line for a restart that will never run.
//
// Returns the css class and the text to show. `added` is the plain message
// the page already had; the server's own message wins whenever the task came
// back switched off.
//
// Warnings the server sends along (v3.0.2: "the player count cannot be read,
// so the server counts as empty") turn the line yellow and are shown in full.
function taskAddedNotice(body, added) {
    const task = body && body.task;
    if (task && task.is_active === false) {
        return { level: 'alert-warning', text: body.message || added };
    }
    const warnings = (body && Array.isArray(body.warnings)) ? body.warnings : [];
    if (warnings.length) {
        return { level: 'alert-warning', text: added + '. ' + warnings.join(' ') };
    }
    return { level: 'alert-success', text: added + ': ' + JSON.stringify(task) };
}
