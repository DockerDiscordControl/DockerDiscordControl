// The task creation form's script. Moved out of tasks/form.html on
// 2026-09-23: 326 lines inside a template the settings page includes, and
// _base.html sends that page Cache-Control: no-cache, so it crossed the wire
// again on every load.
//
// Its thirteen Jinja expressions were TRANSLATED STRINGS and one route, not
// code - the messages this form shows. They stay in the template, as the
// DDC_TASK_FORM object right above the tag that loads this file, the same way
// _container_groups.html already hands DDC_GROUP_TEXTS to container_groups.js.
// A translated string belongs to the catalogue; the code that shows it does not.

// Function to get the current date/time
function getCurrentDateTime() {
    const now = new Date();
    const year = now.getFullYear();
    // Make sure that month and day are always 2 digits
    const month = (now.getMonth() + 1).toString().padStart(2, '0'); // JavaScript months start at 0
    const day = now.getDate().toString().padStart(2, '0');
    const hours = now.getHours().toString().padStart(2, '0');
    const minutes = now.getMinutes().toString().padStart(2, '0');
    
    return {
        year: year,
        month: month, // Now always as string with padding
        day: day,     // Now always as string with padding
        time: `${hours}:${minutes}`
    };
}

// Function to pre-fill the time fields based on the selected cycle
function populateDateTimeFields() {
    const cycle = document.getElementById('taskCycle').value;
    const dateTime = getCurrentDateTime();
    
    // Access all relevant fields
    const timeField = document.getElementById('taskTime');
    const dayField = document.getElementById('taskDay');
    const monthField = document.getElementById('taskMonth');
    const yearField = document.getElementById('taskYear');
    const weekdayField = document.getElementById('taskWeekday');
    
    // By default, enable all fields and show normal day input
    timeField.disabled = false;
    dayField.disabled = false;
    monthField.disabled = false;
    yearField.disabled = false;
    
    // Toggle day/weekday display
    if (cycle === 'weekly') {
        dayField.style.display = 'none';
        weekdayField.style.display = 'block';
        // Pre-select current weekday
        const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const currentDayIndex = new Date().getDay(); // 0=Sunday, 1=Monday, ...
        const weekdayValue = weekdays[currentDayIndex];
        
        // Select weekday in dropdown
        for (let i = 0; i < weekdayField.options.length; i++) {
            if (weekdayField.options[i].value === weekdayValue) {
                weekdayField.selectedIndex = i;
                break;
            }
        }
    } else {
        dayField.style.display = 'block';
        weekdayField.style.display = 'none';
    }
    
    // Always set current time
    timeField.value = dateTime.time;
    
    // Set day, month and year according to cycle and disable corresponding fields
    if (cycle === 'once') {
        // For one-time tasks, fill in and enable all date fields
        dayField.value = dateTime.day;
        monthField.value = dateTime.month;
        yearField.value = dateTime.year;
    } 
    else if (cycle === 'yearly') {
        // For yearly tasks, enable day and month, disable year
        dayField.value = dateTime.day;
        monthField.value = dateTime.month;
        yearField.value = dateTime.year;
        yearField.disabled = true;
    } 
    else if (cycle === 'monthly') {
        // For monthly tasks, only day is needed
        dayField.value = dateTime.day;
        monthField.value = '';
        yearField.value = '';
        monthField.disabled = true;
        yearField.disabled = true;
    } 
    else if (cycle === 'weekly') {
        // For weekly: weekday is already set, disable month and year
        monthField.value = '';
        yearField.value = '';
        monthField.disabled = true;
        yearField.disabled = true;
    } 
    else if (cycle === 'daily') {
        // For daily tasks, disable all date fields
        dayField.value = '';
        monthField.value = '';
        yearField.value = '';
        dayField.disabled = true;
        monthField.disabled = true;
        yearField.disabled = true;
    }
    else if (cycle === 'cron') {
        // For cron tasks, disable all time and date fields
        timeField.disabled = true;
        dayField.disabled = true;
        monthField.disabled = true;
        yearField.disabled = true;
    }
}

// Event listener for changes in the cycle field
document.getElementById('taskCycle').addEventListener('change', function() {
    // Show/hide Cron field based on selection
    const cronRow = document.getElementById('taskCronStringRow');
    if (this.value === 'cron') {
        cronRow.style.display = 'block';
    } else {
        cronRow.style.display = 'none';
    }
    
    // Pre-fill date/time fields and enable/disable accordingly
    populateDateTimeFields();
});

// Form reset function
function resetTaskForm() {
    // Reset all input fields
    document.getElementById('taskContainer').selectedIndex = 0;
    document.getElementById('taskAction').selectedIndex = 0;
    document.getElementById('taskCycle').selectedIndex = 0;
    document.getElementById('taskTime').value = '';
    document.getElementById('taskDay').value = '';
    document.getElementById('taskMonth').value = '';
    document.getElementById('taskYear').value = '';
    document.getElementById('taskCronString').value = '';
    
    // Re-enable fields
    document.getElementById('taskTime').disabled = false;
    document.getElementById('taskDay').disabled = false;
    document.getElementById('taskMonth').disabled = false;
    document.getElementById('taskYear').disabled = false;
    
    // Hide cron field
    document.getElementById('taskCronStringRow').style.display = 'none';
    
    // Reset feedback message
    document.getElementById('responseMessage').textContent = '';
    document.getElementById('responseMessage').className = 'mt-3';
    
    // Reinitialize time
    const dateTime = getCurrentDateTime();
    document.getElementById('taskTime').value = dateTime.time;
}

// Form submit handling - triggered by button click
document.getElementById('createTaskButton').addEventListener('click', function() {
    // Collect all form fields
    const container = document.getElementById('taskContainer').value;
    const action = document.getElementById('taskAction').value;
    const cycle = document.getElementById('taskCycle').value;
    const time = document.getElementById('taskTime').value;
    const timezone = document.getElementById('serverTimezone').value;
    
    // Validation
    if (!container || container === '') {
        alert(DDC_TASK_FORM.errSelectContainer);
        return;
    }
    if (!action || action === '') {
        alert(DDC_TASK_FORM.errSelectAction);
        return;
    }
    if (!cycle || cycle === '') {
        alert(DDC_TASK_FORM.errSelectCycle);
        return;
    }
    if (cycle !== 'cron' && (!time || time === '')) {
        alert(DDC_TASK_FORM.errEnterTime);
        return;
    }
    
    // Additional validation based on cycle
    if (cycle === 'once') {
        const day = document.getElementById('taskDay').value;
        const month = document.getElementById('taskMonth').value;
        const year = document.getElementById('taskYear').value;

        if (!day || !month || !year) {
            alert(DDC_TASK_FORM.errOnceDate);
            return;
        }

        // Check if the date is in the future
        const taskDate = new Date(`${year}-${month}-${day}T${time}:00`);
        if (taskDate <= new Date()) {
            alert(DDC_TASK_FORM.errOnceFuture);
            return;
        }
    } else if (cycle === 'monthly') {
        const day = document.getElementById('taskDay').value;
        if (!day || day < 1 || day > 31) {
            alert(DDC_TASK_FORM.errMonthlyDay);
            return;
        }
    }
    
    // Prepare data for API request
    const data = {
        container: container,
        action: action,
        cycle: cycle,
        timezone_str: timezone,
        schedule_details: {}
    };
    
    // Add relevant fields to schedule_details object based on cycle
    if (cycle === 'cron') {
        const cronString = document.getElementById('taskCronString').value;
        if (!cronString) {
            alert(DDC_TASK_FORM.errEnterCron);
            return;
        }
        data.schedule_details.cron_string = cronString;
    } else {
        data.schedule_details.time = time;
        
        // Add relevant date values (if not disabled)
        if (cycle === 'weekly') {
            // For weekly tasks, use selected weekday
            const weekdayField = document.getElementById('taskWeekday');
            data.schedule_details.day = weekdayField.value; 
        } else {
            // For other tasks, use numerical day (if not disabled)
            const day = document.getElementById('taskDay').value;
            if (day && !document.getElementById('taskDay').disabled) {
                data.schedule_details.day = day;
            }
        }
        
        const month = document.getElementById('taskMonth').value;
        const year = document.getElementById('taskYear').value;
        
        if (month && !document.getElementById('taskMonth').disabled) {
            data.schedule_details.month = month;
        }
        
        if (year && !document.getElementById('taskYear').disabled) {
            data.schedule_details.year = year;
        }
    }

    const responseMessageDiv = document.getElementById('responseMessage');
    responseMessageDiv.textContent = '';
    responseMessageDiv.className = 'mt-3'; 
    
    // A group and a container are chosen from the same list; this is the bit
    // that says which one it was, and the scheduler needs it (a group task
    // would otherwise look for a container of that name).
    const chosen = document.getElementById('taskContainer').selectedOptions[0];
    data.target_is_group = chosen ? chosen.dataset.group === '1' : false;

    console.log('Sending data:', JSON.stringify(data)); // Debugging

    // Send API request
    fetch(DDC_TASK_FORM.addTaskUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
        body: JSON.stringify(data)
    })
    .then(response => {
        console.log('Response status:', response.status); // Additional debug output
        return response.json().then(body => ({ status: response.status, body: body }));
    })
    .then(data => {
        if (data.status === 201) {
            // Not always green: a one-time task whose time has passed is saved
            // and switched off in the same call, and the server says so.
            const notice = taskAddedNotice(data.body, DDC_TASK_FORM.taskAdded);
            responseMessageDiv.textContent = notice.text;
            responseMessageDiv.classList.add('alert', notice.level);
            resetTaskForm();
            // Reload task list
            if (window.taskManager && typeof window.taskManager.fetchTasks === 'function') {
                window.taskManager.fetchTasks();
            }
        } else {
            responseMessageDiv.textContent = DDC_TASK_FORM.errorLabel + ': ' + (data.body.error || DDC_TASK_FORM.unknownError);
            responseMessageDiv.classList.add('alert', 'alert-danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        responseMessageDiv.textContent = DDC_TASK_FORM.errSending;
        responseMessageDiv.classList.add('alert', 'alert-danger');
    });
});

// Cancel-Button Event-Listener
document.getElementById('cancelTaskButton').addEventListener('click', resetTaskForm);

// Pre-fill current date/time when form loads, and offer the operator's groups
document.addEventListener('DOMContentLoaded', function() {
    const timeField = document.getElementById('taskTime');
    const dateTime = getCurrentDateTime();
    timeField.value = dateTime.time;

    const groupOptions = document.getElementById('task-target-group');
    if (!groupOptions) return;
    fetch('/api/groups')
        .then(answer => answer.ok ? answer.json() : { groups: [] })
        .then(body => {
            const groups = body.groups || [];
            if (groups.length === 0) return;   // nothing to group: stays hidden
            for (const group of groups) {
                const option = document.createElement('option');
                option.value = group.name;
                option.textContent = group.name +
                    ' (' + (group.containers || []).length + ')';
                option.dataset.group = '1';
                groupOptions.appendChild(option);
            }
            groupOptions.hidden = false;
        })
        .catch(() => {});        // no groups offered is better than a broken form
});
