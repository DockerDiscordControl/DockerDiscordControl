// How wide a progress bar may claim to be.
//
// The services return null for a maximum they could not measure, on purpose -
// nothing is invented there. Dividing by it in the page turned that refusal
// into the opposite: in JavaScript 5 / null is Infinity, and
// Math.min(100, Infinity) is 100, so a mech nobody could read was drawn with a
// full power bar and a full evolution bar.
//
// Returns a percentage between 0 and 100, or null when the numbers do not
// allow one. The caller shows an empty bar for null and says why.
function barWidth(current, max) {
    const value = Number(current);
    const limit = Number(max);
    if (current === null || current === undefined || !Number.isFinite(value)) return null;
    if (max === null || max === undefined || !Number.isFinite(limit) || limit <= 0) return null;
    return Math.max(0, Math.min(100, (value / limit) * 100));
}
