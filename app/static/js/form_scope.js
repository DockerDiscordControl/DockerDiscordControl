// What belongs to the settings form's one save, and what does not.
//
// THE OPERATOR, 2026-09-24, on flipping the debug level: "the message still
// comes up." It had just been given its own save, and the warning still
// appeared - because the log view had moved INSIDE #config-form that morning,
// and the form's own change listener reports everything inside it.
//
// That listener already had exceptions, as a hard-coded list of three ids:
//
//     if (e.target.id === 'taskFilterStatus' || e.target.closest('#taskListBody')
//         || e.target.closest('.task-filters')) { return; }
//
// A list, not a rule - so the next control that did not belong to the save had
// to be remembered, and this one was not. The rule underneath all four is the
// same: THE FORM'S SAVE IS ONE ACT. A token, a channel list and a language are
// changed together and written together, and the Save button is what makes
// that one act. A control that stores itself the moment it is touched, and a
// filter that changes only what is shown, are not part of it.
//
// So a control says so in the markup - data-saves-itself="true" - and this
// answers the question in one place.

// The task list is built at runtime and carries no marker of its own, so its
// controls are named here. They edit TASKS, which have their own routes and
// their own saves - pressing one has never had anything to do with the
// settings form. Nine ids and classes were spread across three listeners in
// panel.js, in two different lists that had drifted apart: the change listener
// knew three of them, the click listener six, and neither knew the other's.
const TASK_CONTROLS = ['#taskListBody', '.task-filters', '.editTaskBtn',
                       '.deleteTaskBtn', '.toggle-active'];
const TASK_CONTROL_IDS = ['taskFilterStatus', 'refreshTasksBtn'];

// Whether changing this element means the form has unsaved changes.
function belongsToTheFormSave(element) {
    if (!element || typeof element.closest !== 'function') { return false; }
    // Declared in the markup by anything that persists on its own.
    if (element.closest('[data-saves-itself="true"]')) { return false; }
    if (TASK_CONTROL_IDS.includes(element.id)) { return false; }
    if (TASK_CONTROLS.some(selector => element.closest(selector))) { return false; }
    return true;
}

if (typeof window !== 'undefined') {
    window.belongsToTheFormSave = belongsToTheFormSave;
}
