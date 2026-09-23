// Which target checkboxes the rule editor shows, and what a save may do.
//
// Two mistakes are possible here and both are silent, which is why this is a
// function of its own with a node test beside it:
//
// * a rule watching "group:Gameserver" is opened after that group was deleted
//   (or after /api/groups failed once). The checkbox does not exist, the tick
//   is lost, and saving writes an EMPTY trigger list - which DDC reads as
//   "every container". A rule written for three containers then acts on all of
//   them. So a stored value with no checkbox gets one, ticked and marked.
// * a container-state rule saved with nothing ticked means the same thing on
//   purpose. That is allowed, but it must be a decision, not an accident.

function targetCheckboxes(groups, containers, ticked) {
    const boxes = [];
    const seen = new Set();
    for (const group of groups || []) {
        const value = 'group:' + group.name;
        seen.add(value);
        boxes.push({
            value: value, label: group.name, kind: 'group',
            count: (group.containers || []).length,
            checked: (ticked || []).includes(value), missing: false,
        });
    }
    for (const container of containers || []) {
        seen.add(container);
        boxes.push({
            value: container, label: container, kind: 'container',
            checked: (ticked || []).includes(container), missing: false,
        });
    }
    // Anything the rule holds that has no checkbox: kept, ticked, and marked -
    // losing it would widen the rule instead of narrowing it.
    for (const value of ticked || []) {
        if (seen.has(value)) continue;
        const isGroup = value.startsWith('group:');
        boxes.push({
            value: value, label: isGroup ? value.slice('group:'.length) : value,
            kind: isGroup ? 'group' : 'container', checked: true, missing: true,
        });
    }
    return boxes;
}

function saveWidensToEveryContainer(isContainerStateRule, chosen, wasWatching) {
    // True when this save turns a rule that watched something into one that
    // watches everything. The caller asks before it happens.
    return Boolean(isContainerStateRule) && (chosen || []).length === 0 &&
           (wasWatching || []).length > 0;
}

if (typeof window !== 'undefined') {
    window.targetCheckboxes = targetCheckboxes;
    window.saveWidensToEveryContainer = saveWidensToEveryContainer;
}
