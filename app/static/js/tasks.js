/**
 * Task Management JavaScript Module
 * Handles all task-related functionality in the Web UI
 */

class TaskManager {
    constructor() {
        this.cachedTasks = [];
        this.editModal = null;
        this.init();
    }

    // Security: HTML escape function to prevent XSS attacks
    escapeHtml(unsafe) {
        if (unsafe === null || unsafe === undefined) return '';
        return String(unsafe)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    init() {
        this.bindEventListeners();
        this.initializeModal();
        this.fetchTasks();
    }

    bindEventListeners() {
        // Refresh button
        document.getElementById('refreshTasksBtn')?.addEventListener('click', () => this.fetchTasks());
        
        // Status filter
        document.getElementById('taskFilterStatus')?.addEventListener('change', () => this.handleFilterChange());
        
        // Task list event delegation
        document.getElementById('taskListBody')?.addEventListener('click', (e) => this.handleTaskListClick(e));
        
        // Edit modal events
        document.getElementById('editTaskCycle')?.addEventListener('change', (e) => this.handleCycleChange(e));
        document.getElementById('saveTaskChanges')?.addEventListener('click', () => this.saveTaskChanges());
        
        // Modal reset on close
        document.getElementById('editTaskModal')?.addEventListener('hidden.bs.modal', () => this.resetEditModal());
    }

    initializeModal() {
        const modalElement = document.getElementById('editTaskModal');
        if (modalElement) {
            this.editModal = new bootstrap.Modal(modalElement);
        }
    }

    async fetchTasks() {
        const tbody = document.getElementById('taskListBody');
        const errorDiv = document.getElementById('taskListError');
        
        if (!tbody) return;

        // Show loading state
        tbody.innerHTML = '<tr><td colspan="11" class="text-center task-loading"><div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>Loading tasks...</td></tr>';
        errorDiv.style.display = 'none';

        try {
            const response = await fetch(window.DDC_CONFIG?.urls?.list || '/tasks/list');
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            
            const data = await response.json();
            this.cachedTasks = data;
            this.renderTaskList(data);
        } catch (error) {
            console.error('Failed to fetch tasks:', error);
            
            const tbody = document.getElementById('taskListBody');
            if (tbody) {
                tbody.innerHTML = '<tr><td colspan="11" class="text-center task-empty"><div class="empty-icon">⚠️</div><div class="empty-title">Error Loading Tasks</div><div class="empty-description">' + this.escapeHtml(error.message) + '</div></td></tr>';
            }
        }
    }

    renderTaskList(tasks) {
        const tbody = document.getElementById('taskListBody');
        const statusFilter = document.getElementById('taskFilterStatus')?.value || 'all';
        
        if (!tbody) return;

        tbody.innerHTML = '';

        if (!tasks || tasks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="11" class="text-center task-empty"><div class="empty-icon">📋</div><div class="empty-title">No Tasks Found</div><div class="empty-description">No scheduled tasks have been created yet.</div></td></tr>';
            return;
        }

        // Filter tasks
        const filteredTasks = this.filterTasks(tasks, statusFilter);
        
        if (filteredTasks.length === 0) {
            tbody.innerHTML = '<tr><td colspan="11" class="text-center task-empty"><div class="empty-icon">🔍</div><div class="empty-title">No Matching Tasks</div><div class="empty-description">No tasks match the selected filter "' + this.escapeHtml(statusFilter) + '".</div></td></tr>';
            return;
        }

        // Render tasks
        filteredTasks.forEach(task => {
            const row = this.createTaskRow(task);
            row.classList.add('task-row', 'fade-in');
            tbody.appendChild(row);
        });
    }

    filterTasks(tasks, statusFilter) {
        if (statusFilter === 'all') return tasks;
        
        return tasks.filter(task => {
            switch (statusFilter) {
                case 'active':
                    return task.frontend_status === 'active' || (!task.frontend_status && task.is_active);
                case 'deactivated':
                    return task.frontend_status === 'deactivated' || (!task.frontend_status && !task.is_active);
                case 'expired':
                    return task.frontend_status === 'expired';
                default:
                    return true;
            }
        });
    }

    createTaskRow(task) {
        const row = document.createElement('tr');
        
        // Determine status styling
        const statusInfo = this.getTaskStatusInfo(task);
        
        // Check if this is a system task
        const isSystemTask = task.is_system_task || false;
        const isDonationTask = task.is_donation_task || false;
        
        // Escape all dynamic content
        const escapedData = {
            id: this.escapeHtml(task.id),
            container: this.escapeHtml(task.container || 'N/A'),
            action: this.escapeHtml(task.action || 'N/A'),
            cycle: this.escapeHtml(task.cycle || 'N/A'),
            nextRunLocal: this.escapeHtml(task.next_run_local || 'N/A'),
            statusText: this.escapeHtml(statusInfo.text),
            createdAtLocal: this.escapeHtml(task.created_at_local)
        };
        
        // Add system task styling
        if (isSystemTask) {
            row.classList.add('system-task-row');
        }
        
        // Build container display - for system tasks, show only blue SYSTEM without extra badge
        let containerDisplay;
        if (isSystemTask) {
            containerDisplay = `<code class="text-info container-name">SYSTEM</code>`;
        } else {
            containerDisplay = `<code class="text-info container-name">${escapedData.container}</code>`;
        }
        
        // Build action buttons based on task type
        let actionButtons;
        if (isSystemTask) {
            actionButtons = `
                <span class="text-muted" title="System tasks cannot be modified">
                    n/a
                </span>`;
        } else {
            actionButtons = `
                <div class="btn-group btn-group-sm" role="group">
                    <button class="btn btn-primary editTaskBtn" data-task-id="${escapedData.id}" title="Edit Task" data-bs-toggle="tooltip">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <button class="btn btn-danger deleteTaskBtn" data-task-id="${escapedData.id}" title="Delete Task" data-bs-toggle="tooltip">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>`;
        }
        
        row.innerHTML = `
            <td class="task-id">${escapedData.id}</td>
            <td>${containerDisplay}</td>
            <td><span class="badge bg-secondary">${escapedData.action}</span></td>
            <td><span class="badge bg-info">${escapedData.cycle}</span></td>
            <td><div class="schedule-details">${this.formatScheduleDetails(task.schedule_details)}</div></td>
            <td><small class="text-muted">${escapedData.nextRunLocal}</small></td>
            <td><span class="badge status-badge status-${statusInfo.class}">${escapedData.statusText}</span></td>
            <td>
                <div class="form-check">
                    <input class="form-check-input toggle-active task-checkbox" type="checkbox" 
                           id="active-${escapedData.id}" data-task-id="${escapedData.id}" 
                           ${task.is_active ? 'checked' : ''} 
                           ${!statusInfo.canBeActivated || isSystemTask ? 'disabled' : ''}>
                    <label class="form-check-label visually-hidden" for="active-${escapedData.id}">Active</label>
                </div>
            </td>
            <td>${this.formatLastRunResult(task)}</td>
            <td><small class="text-muted">${this.formatDate(task.created_at, escapedData.createdAtLocal)}</small></td>
            <td class="text-center task-actions">
                ${actionButtons}
            </td>
        `;
        
        return row;
    }

    getTaskStatusInfo(task) {
        const taskStatus = task.frontend_status || '';
        
        switch (taskStatus) {
            case 'expired':
                return { class: 'expired', text: 'Expired', canBeActivated: false };
            case 'deactivated':
                return { class: 'deactivated', text: 'Inactive', canBeActivated: true };
            default:
                return { class: 'active', text: 'Active', canBeActivated: true };
        }
    }

    formatScheduleDetails(details) {
        if (!details) return 'N/A';
        
        if (details.cron_string) {
            return `Cron: <code>${this.escapeHtml(details.cron_string)}</code>`;
        }
        
        const parts = [];
        if (details.time) parts.push(`Time: ${this.escapeHtml(details.time)}`);
        if (details.day) parts.push(`Day: ${this.escapeHtml(details.day)}`);
        if (details.month) parts.push(`Month: ${this.escapeHtml(details.month)}`);
        if (details.year) parts.push(`Year: ${this.escapeHtml(details.year)}`);
        
        return parts.join(', ') || 'No details';
    }

    formatLastRunResult(task) {
        if (task.last_run_success === true) {
            return '<span class="badge bg-success" title="Task was executed successfully">Success</span>';
        } else if (task.last_run_success === false) {
            const escapedError = this.escapeHtml(task.last_run_error || 'Task execution failed');
            return `<span class="badge bg-danger" title="${escapedError}">Failed</span>`;
        }
        return '<span class="text-muted">Not run yet</span>';
    }

    formatDate(dateString, localDateString) {
        if (localDateString) return localDateString;
        if (!dateString) return 'N/A';
        
        try {
            const date = new Date(dateString);
            return isNaN(date.getTime()) ? 'Invalid Date' : date.toLocaleString();
        } catch (e) {
            return 'Error';
        }
    }

    handleFilterChange() {
        this.renderTaskList(this.cachedTasks);
    }

    handleTaskListClick(event) {
        const target = event.target.closest('button, input');
        if (!target) return;

        const taskId = target.getAttribute('data-task-id');
        
        // Check if this is a system task by looking at the row
        const row = target.closest('tr');
        const isSystemTask = row && row.classList.contains('system-task-row');
        
        if (target.classList.contains('editTaskBtn')) {
            if (isSystemTask) {
                this.showError('System tasks cannot be edited');
                return;
            }
            this.openEditModal(taskId);
        } else if (target.classList.contains('deleteTaskBtn')) {
            if (isSystemTask) {
                this.showError('System tasks cannot be deleted');
                return;
            }
            this.deleteTask(taskId);
        } else if (target.classList.contains('toggle-active')) {
            if (isSystemTask) {
                // Prevent the checkbox change
                target.checked = !target.checked;
                this.showError('System task activation cannot be changed');
                return;
            }
            this.toggleTaskActive(taskId, target.checked);
        }
    }

    async openEditModal(taskId) {
        try {
            const url = (window.DDC_CONFIG?.urls?.edit || '/tasks/edit/PLACEHOLDER').replace('PLACEHOLDER', taskId);
            const response = await fetch(url);
            const data = await response.json();
            
            if (data.success) {
                this.populateEditForm(data.task);
                this.editModal?.show();
            } else {
                this.showError(`Error loading task: ${data.error}`);
            }
        } catch (error) {
            this.showError(`Error: ${error.message || 'Failed to load task'}`);
        }
    }

    populateEditForm(task) {
        // Set basic fields
        this.setFormValue('editTaskId', task.id);
        this.setFormValue('editTaskContainer', task.container);
        this.setFormValue('editTaskAction', task.action);
        this.setFormValue('editTaskCycle', task.cycle);
        this.setFormValue('editTaskActive', task.is_active, 'checkbox');
        
        // Handle schedule details
        const scheduleDetails = task.schedule_details || {};
        
        if (task.cycle === 'cron') {
            this.setFormValue('editTaskCronString', scheduleDetails.cron_string);
            this.showElement('editTaskCronStringRow');
            this.disableTimeFields(true);
        } else {
            this.hideElement('editTaskCronStringRow');
            this.disableTimeFields(false);
            this.setFormValue('editTaskTime', scheduleDetails.time);
            
            // Handle day/weekday
            if (task.cycle === 'weekly') {
                this.hideElement('editTaskDay');
                this.showElement('editTaskWeekday');
                this.setFormValue('editTaskWeekday', scheduleDetails.day);
            } else {
                this.showElement('editTaskDay');
                this.hideElement('editTaskWeekday');
                this.setFormValue('editTaskDay', scheduleDetails.day);
            }
            
            this.setFormValue('editTaskMonth', scheduleDetails.month);
            this.setFormValue('editTaskYear', scheduleDetails.year);
            this.updateFormFieldStates(task.cycle);
        }
        
        this.clearMessage();
    }

    setFormValue(elementId, value, type = 'text') {
        const element = document.getElementById(elementId);
        if (!element) return;
        
        if (type === 'checkbox') {
            element.checked = Boolean(value);
        } else {
            element.value = value || '';
        }
    }

    showElement(elementId) {
        const element = document.getElementById(elementId);
        if (element) element.style.display = 'block';
    }

    hideElement(elementId) {
        const element = document.getElementById(elementId);
        if (element) element.style.display = 'none';
    }

    disableTimeFields(disabled) {
        ['editTaskTime', 'editTaskDay', 'editTaskMonth', 'editTaskYear'].forEach(id => {
            const element = document.getElementById(id);
            if (element) element.disabled = disabled;
        });
    }

    updateFormFieldStates(cycle) {
        const fields = {
            time: document.getElementById('editTaskTime'),
            day: document.getElementById('editTaskDay'),
            month: document.getElementById('editTaskMonth'),
            year: document.getElementById('editTaskYear')
        };

        // Reset all to enabled
        Object.values(fields).forEach(field => {
            if (field) field.disabled = false;
        });

        // Disable based on cycle
        switch (cycle) {
            case 'daily':
                [fields.day, fields.month, fields.year].forEach(f => f && (f.disabled = true));
                break;
            case 'weekly':
                [fields.month, fields.year].forEach(f => f && (f.disabled = true));
                break;
            case 'monthly':
                [fields.month, fields.year].forEach(f => f && (f.disabled = true));
                break;
            case 'yearly':
                if (fields.year) fields.year.disabled = true;
                break;
            case 'cron':
                Object.values(fields).forEach(f => f && (f.disabled = true));
                break;
        }
    }

    handleCycleChange(event) {
        const cycle = event.target.value;
        
        if (cycle === 'cron') {
            this.showElement('editTaskCronStringRow');
        } else {
            this.hideElement('editTaskCronStringRow');
        }
        
        if (cycle === 'weekly') {
            this.hideElement('editTaskDay');
            this.showElement('editTaskWeekday');
        } else {
            this.showElement('editTaskDay');
            this.hideElement('editTaskWeekday');
        }
        
        this.updateFormFieldStates(cycle);
    }

    async saveTaskChanges() {
        const taskData = this.collectFormData();
        
        if (!this.validateTaskData(taskData)) {
            return;
        }

        // Show loading state
        const saveButton = document.getElementById('saveTaskChanges');
        const originalText = saveButton.innerHTML;
        saveButton.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Saving...';
        saveButton.disabled = true;

        try {
            const url = (window.DDC_CONFIG?.urls?.edit || '/tasks/edit/PLACEHOLDER').replace('PLACEHOLDER', taskData.taskId);
            const response = await fetch(url, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify(taskData.data)
            });

            const result = await response.json();
            
            if (result.success) {
                this.showSuccess('Task updated successfully!');
                setTimeout(() => {
                    this.editModal?.hide();
                    this.fetchTasks();
                }, 1500);
            } else {
                this.showError(`Error: ${result.error}`);
            }
        } catch (error) {
            this.showError(`Error: ${error.message || 'Failed to update task'}`);
        } finally {
            // Reset button state
            saveButton.innerHTML = originalText;
            saveButton.disabled = false;
        }
    }

    collectFormData() {
        const taskId = document.getElementById('editTaskId')?.value;
        const container = document.getElementById('editTaskContainer')?.value;
        const action = document.getElementById('editTaskAction')?.value;
        const cycle = document.getElementById('editTaskCycle')?.value;
        const isActive = document.getElementById('editTaskActive')?.checked;

        const scheduleDetails = {};
        
        if (cycle === 'cron') {
            scheduleDetails.cron_string = document.getElementById('editTaskCronString')?.value;
        } else {
            scheduleDetails.time = document.getElementById('editTaskTime')?.value;
            
            if (cycle === 'weekly') {
                const weekday = document.getElementById('editTaskWeekday')?.value;
                if (weekday) scheduleDetails.day = weekday;
            } else {
                const day = document.getElementById('editTaskDay')?.value;
                const dayField = document.getElementById('editTaskDay');
                if (day && dayField && !dayField.disabled) {
                    scheduleDetails.day = day;
                }
            }
            
            const month = document.getElementById('editTaskMonth')?.value;
            const year = document.getElementById('editTaskYear')?.value;
            const monthField = document.getElementById('editTaskMonth');
            const yearField = document.getElementById('editTaskYear');
            
            if (month && monthField && !monthField.disabled) {
                scheduleDetails.month = month;
            }
            if (year && yearField && !yearField.disabled) {
                scheduleDetails.year = year;
            }
        }

        return {
            taskId,
            data: {
                container,
                action,
                cycle,
                is_active: isActive,
                schedule_details: scheduleDetails,
                timezone_str: window.DDC_CONFIG?.timezone || 'Europe/Berlin'
            }
        };
    }

    validateTaskData(taskData) {
        const { data } = taskData;
        
        if (!data.container || !data.action || !data.cycle) {
            this.showError('Please fill in all required fields');
            return false;
        }
        
        if (data.cycle === 'cron' && !data.schedule_details.cron_string) {
            this.showError('Please enter a cron string');
            return false;
        }
        
        if (data.cycle !== 'cron' && !data.schedule_details.time) {
            this.showError('Please enter a time');
            return false;
        }
        
        return true;
    }

    async deleteTask(taskId) {
        const escapedTaskId = this.escapeHtml(taskId);
        
        if (!confirm(`Are you sure you want to delete task #${escapedTaskId}?\n\nThis action cannot be undone.`)) {
            return;
        }

        try {
            const url = (window.DDC_CONFIG?.urls?.delete || '/tasks/delete/PLACEHOLDER').replace('PLACEHOLDER', taskId);
            const response = await fetch(url, {
                method: 'DELETE',
                headers: { 'Accept': 'application/json' }
            });

            const data = await response.json();
            
            if (data.success) {
                // Show success message briefly
                const tbody = document.getElementById('taskListBody');
                const successRow = document.createElement('tr');
                successRow.innerHTML = '<td colspan="11" class="text-center text-success"><i class="bi bi-check-circle me-2"></i>Task deleted successfully!</td>';
                tbody.insertBefore(successRow, tbody.firstChild);
                
                setTimeout(() => {
                    this.fetchTasks();
                }, 1000);
            } else {
                this.showError(`Error: ${data.error || 'Unknown error during deletion'}`);
            }
        } catch (error) {
            this.showError(`Error: ${error.message || 'Failed to delete task'}`);
        }
    }

    async toggleTaskActive(taskId, isActive) {
        try {
            const url = window.DDC_CONFIG?.urls?.updateStatus || '/tasks/update_status';
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ task_id: taskId, is_active: isActive })
            });

            const data = await response.json();
            
            if (!data.success) {
                // Revert checkbox state
                const checkbox = document.getElementById(`active-${taskId}`);
                if (checkbox) checkbox.checked = !isActive;
                this.showError(`Failed to update task status: ${data.error}`);
            } else {
                // Show brief success feedback
                const checkbox = document.getElementById(`active-${taskId}`);
                if (checkbox) {
                    const originalTitle = checkbox.title;
                    checkbox.title = isActive ? 'Task activated!' : 'Task deactivated!';
                    setTimeout(() => {
                        checkbox.title = originalTitle;
                    }, 2000);
                }
            }
        } catch (error) {
            // Revert checkbox state
            const checkbox = document.getElementById(`active-${taskId}`);
            if (checkbox) checkbox.checked = !isActive;
            this.showError(`Error updating task status: ${error.message}`);
        }
    }

    resetEditModal() {
        document.getElementById('editTaskForm')?.reset();
        this.clearMessage();
        this.hideElement('editTaskCronStringRow');
        this.showElement('editTaskDay');
        this.hideElement('editTaskWeekday');
        this.disableTimeFields(false);
    }

    showSuccess(message) {
        this.showMessage(message, 'alert-success');
    }

    showError(message) {
        // Try to show in modal first, then fallback to page-level error
        const modalMessageDiv = document.getElementById('editTaskMessage');
        const pageErrorDiv = document.getElementById('taskListError');
        
        if (modalMessageDiv && modalMessageDiv.style.display !== 'none') {
            // Modal is visible, show error there
            this.showMessage(message, 'alert-danger');
        } else if (pageErrorDiv) {
            // Show error on the main page
            pageErrorDiv.textContent = message;
            pageErrorDiv.style.display = 'block';
            // Hide after 5 seconds
            setTimeout(() => {
                pageErrorDiv.style.display = 'none';
            }, 5000);
        } else {
            // Fallback to browser alert
            alert(message);
        }
        
        console.error(message);
    }

    showMessage(message, className) {
        const messageDiv = document.getElementById('editTaskMessage');
        if (messageDiv) {
            messageDiv.textContent = message;
            messageDiv.className = `task-message ${className}`;
            messageDiv.style.display = 'block';
        } else {
            // Fallback to browser alert
            alert(message);
        }
    }

    clearMessage() {
        const messageDiv = document.getElementById('editTaskMessage');
        if (messageDiv) {
            messageDiv.textContent = '';
            messageDiv.className = 'task-message';
            messageDiv.style.display = 'none';
        }
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    if (document.getElementById('taskListBody')) {
        window.taskManager = new TaskManager();
    }
});

// Export for potential external use
window.TaskManager = TaskManager; 