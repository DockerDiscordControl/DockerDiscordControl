// Turning foreign text into text the page can hold.
//
// A message from the server or from the browser is not markup, and the panel
// used to write it into innerHTML as if it were: `Error: ${data.message}` in
// five places in panel.js, `+ error.message` twice in mech_panel.js, and four
// more besides. What such a message actually carries is a value the operator
// typed - a display name, a group name, the 250 characters of custom info text
// - or a URL out of a browser error.
//
// setup.html answered this for its own alerts (CodeQL #57) with textContent,
// and channel_translation.js escapes with a copy of this function. This is the
// one both of them describe, so there is one answer to find and one to change.
//
// THE FIVE CHARACTERS, and why not fewer: & first, or escaping it afterwards
// would double-escape everything the other four produced. < and > close and
// open a tag. The two quotes matter because the result is pasted into markup
// where it may land inside an attribute - `title="${…}"` - and one quote there
// ends the attribute early, which is the whole attack.

function ddcEscapeHtml(text) {
    if (text === null || text === undefined) { return ''; }
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

if (typeof window !== 'undefined') {
    window.ddcEscapeHtml = ddcEscapeHtml;
}
