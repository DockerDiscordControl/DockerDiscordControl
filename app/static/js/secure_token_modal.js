// Moved out of _secure_token_modal.html on 2026-09-23.
// It was 134 lines inside a template that every panel page includes, and _base.html sends those pages with Cache-Control: no-cache - so it crossed the wire again on every load.
// A static file is not covered by that meta tag.
// No Jinja in here; pinned by tests/spec/test_the_page_is_not_mostly_one_script.py

let tokenVisible = false;
let autoCloseInterval = null;
let timeRemaining = 300; // 5 minutes in seconds

function showSecureTokenModal(token) {
    // Set token in secure input
    document.getElementById('secureTokenInput').value = token;

    // Reset visibility state
    tokenVisible = false;
    updateTokenVisibility();

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('secureTokenModal'));
    modal.show();

    // Start auto-close timer
    startAutoCloseTimer();

    // Clear token when modal is hidden
    document.getElementById('secureTokenModal').addEventListener('hidden.bs.modal', function () {
        clearTokenData();
    });
}

function toggleTokenDisplay() {
    tokenVisible = !tokenVisible;
    updateTokenVisibility();
}

function updateTokenVisibility() {
    const input = document.getElementById('secureTokenInput');
    const icon = document.getElementById('tokenVisibilityIcon');

    if (tokenVisible) {
        input.type = 'text';
        icon.className = 'bi bi-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'bi bi-eye';
    }
}

async function copyTokenToClipboard() {
    const input = document.getElementById('secureTokenInput');
    const button = document.getElementById('copyTokenButton');

    try {
        await navigator.clipboard.writeText(input.value);

        // Visual feedback
        button.innerHTML = '<i class="bi bi-check"></i> ' + t('web.secure_token.copied');
        button.classList.remove('btn-success');
        button.classList.add('btn-success-alt');

        setTimeout(() => {
            button.innerHTML = '<i class="bi bi-clipboard"></i> ' + t('web.secure_token.copy');
            button.classList.remove('btn-success-alt');
            button.classList.add('btn-success');
        }, 2000);

    } catch (err) {
        console.error('Failed to copy token:', err);

        // Fallback: select text
        input.select();
        input.setSelectionRange(0, 99999); // For mobile devices

        button.innerHTML = '<i class="bi bi-exclamation-triangle"></i> ' + t('web.secure_token.select_all');
        setTimeout(() => {
            button.innerHTML = '<i class="bi bi-clipboard"></i> ' + t('web.secure_token.copy');
        }, 2000);
    }
}

function startAutoCloseTimer() {
    timeRemaining = 300; // Reset to 5 minutes
    updateTimerDisplay();

    autoCloseInterval = setInterval(() => {
        timeRemaining--;
        updateTimerDisplay();

        if (timeRemaining <= 0) {
            clearAndCloseSecureModal();
        }
    }, 1000);
}

function updateTimerDisplay() {
    const minutes = Math.floor(timeRemaining / 60);
    const seconds = timeRemaining % 60;
    const display = `${minutes}:${seconds.toString().padStart(2, '0')}`;

    const timerElement = document.getElementById('autoCloseTimer');
    if (timerElement) {
        timerElement.textContent = display;

        // Warning colors
        if (timeRemaining <= 60) {
            timerElement.className = 'text-danger fw-bold';
        } else if (timeRemaining <= 120) {
            timerElement.className = 'text-warning fw-bold';
        } else {
            timerElement.className = '';
        }
    }
}

function clearTokenData() {
    // Clear token input
    document.getElementById('secureTokenInput').value = '';

    // Reset visibility
    tokenVisible = false;
    updateTokenVisibility();

    // Clear timer
    if (autoCloseInterval) {
        clearInterval(autoCloseInterval);
        autoCloseInterval = null;
    }
}

function clearAndCloseSecureModal() {
    clearTokenData();

    // Close modal
    const modal = bootstrap.Modal.getInstance(document.getElementById('secureTokenModal'));
    if (modal) {
        modal.hide();
    }
}
