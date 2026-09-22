// "Sort by stack" for the server order (roadmap Phase 4c).
//
// Containers of one Compose stack are moved together, to where the stack's
// first member stands; containers outside a stack keep their place among each
// other. Only the rows move - the operator still saves, and can still adjust
// by hand with + and -.

// entries: [{name, project}] in the current order -> names in the new order
function stackOrder(entries) {
    const members = new Map();
    for (const entry of entries) {
        if (!entry.project) continue;
        if (!members.has(entry.project)) members.set(entry.project, []);
        members.get(entry.project).push(entry.name);
    }
    const order = [];
    const placed = new Set();
    for (const entry of entries) {
        if (!entry.project) {
            order.push(entry.name);
        } else if (!placed.has(entry.project)) {
            placed.add(entry.project);
            order.push(...members.get(entry.project));
        }
    }
    return order;
}

// Reorders the rows of the server table; true when anything moved.
function sortServerRowsByStack() {
    const tbody = document.getElementById('docker-container-list');
    if (!tbody) return false;
    const rows = Array.from(tbody.querySelectorAll('tr[data-container-name]'));
    const byName = new Map(rows.map(row => [row.getAttribute('data-container-name'), row]));
    const order = stackOrder(rows.map(row => ({
        name: row.getAttribute('data-container-name'),
        project: row.getAttribute('data-compose-project') || null,
    })));
    if (order.every((name, index) => rows[index] === byName.get(name))) return false;
    order.forEach(name => tbody.appendChild(byName.get(name)));
    updateOrderNumbers();
    updateMoveButtons();
    markConfigurationChanged();
    return true;
}

document.addEventListener('DOMContentLoaded', function() {
    const button = document.getElementById('sort-by-stack-btn');
    if (button) button.addEventListener('click', sortServerRowsByStack);
});
