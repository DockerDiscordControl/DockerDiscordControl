# Task System Guide

DDC includes a flexible task system to automate container management through scheduled actions.

## Overview

The task system allows you to:
- **Schedule Actions**: Automatically start, stop, or restart containers
- **Multiple Schedules**: One-time, daily, weekly, monthly, and yearly tasks
- **Flexible Timing**: Precise time control and recurrence patterns
- **Management**: Create, view, edit, and delete tasks via Discord and Web UI
- **Monitoring**: Track task execution and troubleshoot issues

## Task Types

### 1. One-Time Tasks (`/task_once`)

Execute an action at a specific date and time.

**Command:**
```
/task_once container_name action date time
```

**Examples:**
```
/task_once minecraft restart 2024-06-15 03:00
/task_once backup start 2024-12-25 02:30  
/task_once maintenance stop 2024-07-01 01:00
```

**Use Cases:**
- Scheduled maintenance windows
- One-time server restarts
- Special event preparations

### 2. Daily Tasks (`/task_daily`)

Execute an action every day at a specified time.

**Command:**
```
/task_daily container_name action time
```

**Examples:**
```
/task_daily backup start 02:00
/task_daily gameserver restart 06:00
/task_daily database stop 23:30
```

**Use Cases:**
- Daily backups
- Regular restarts for stability
- Scheduled maintenance

### 3. Weekly Tasks (`/task_weekly`)

Execute an action on specific days of the week.

**Command:**
```
/task_weekly container_name action weekday time
```

**Examples:**
```
/task_weekly minecraft restart Monday 04:00
/task_weekly backup start Sunday 01:00
/task_weekly webserver restart Wednesday 03:30
```

**Use Cases:**
- Weekly maintenance schedules
- Regular server cleanups
- Coordinated restart schedules

### 4. Monthly Tasks (`/task_monthly`)

Execute an action on specific days of each month.

**Command:**
```
/task_monthly container_name action day time
```

**Examples:**
```
/task_monthly backup start 1 02:00    # 1st of each month
/task_monthly minecraft restart 15 04:00  # 15th of each month
/task_monthly cleanup stop 31 01:00   # Last day of month (when exists)
```

**Use Cases:**
- Monthly system maintenance
- Periodic full backups
- Monthly security updates

### 5. Yearly Tasks (`/task_yearly`)

Execute an action on specific dates each year.

**Command:**
```
/task_yearly container_name action month day time
```

**Examples:**
```
/task_yearly gameserver restart January 1 06:00   # New Year restart
/task_yearly backup start December 24 23:00       # Christmas Eve backup
/task_yearly maintenance stop July 4 02:00        # Independence Day maintenance
```

**Use Cases:**
- Annual maintenance schedules
- Holiday preparations
- Yearly system updates

## Task Management Commands

### View Tasks (`/task_info`)

Display scheduled tasks with filtering options.

**Command:**
```
/task_info [period]
```

**Periods:**
- `today` - Tasks for next 24 hours
- `tomorrow` - Tasks for tomorrow
- `next_week` - Tasks for next 7 days  
- `next_month` - Tasks for next 30 days
- `all` - All active tasks (default)

**Examples:**
```
/task_info today       # Today's scheduled tasks
/task_info next_week   # Upcoming week
/task_info all         # All active tasks
```

### Delete Tasks (`/task_delete`)

Remove scheduled tasks by ID.

**Command:**
```
/task_delete task_id
```

**Finding Task IDs:**
- Use `/task_info` to see task IDs
- IDs are displayed in task listings

**Example:**
```
/task_delete 12345
```

### Interactive Task Management (`/task_delete_panel`)

Open an interactive panel with delete buttons for all active tasks.

**Command:**
```
/task_delete_panel
```

**Features:**
- Visual task overview
- One-click deletion
- Confirmation prompts
- Real-time updates

## Advanced Scheduling

### Day Selection Notes

Due to Discord's 25-option autocomplete limit, day selection shows a strategic subset:
- **Shown**: 1-5, 7, 9, 10, 12-15, 17, 18, 20-22, 24-28, 30, 31
- **Manual Entry**: You can type any valid day number (1-31)

### Time Format

**Supported Formats:**
- `HH:MM` (24-hour format)
- `HH:MM:SS` (with seconds)

**Examples:**
- `02:30` - 2:30 AM
- `14:15` - 2:15 PM  
- `23:59:30` - 11:59:30 PM

### Container Permissions

Tasks respect container permissions:
- Only actions allowed in container configuration will work
- Verify container has required permissions (start/stop/restart)
- Check channel permissions for task commands

## Web UI Task Management

### Viewing Tasks

1. **Access Web UI**: `http://your-server:8374`
2. **Navigate**: Scroll to "Task Scheduler List" section
3. **Filter**: Use status filter (Active/Inactive/All)
4. **Sort**: Tasks are sorted by next execution time

### Task Information

**Task Details Include:**
- **ID**: Unique task identifier
- **Container**: Target container name
- **Action**: Scheduled action (start/stop/restart)
- **Schedule**: Recurrence pattern and timing
- **Next Run**: When task will next execute
- **Status**: Active/Inactive/Expired
- **Created**: Task creation timestamp

### Task Editing

**Via Web UI:**
- View complete task details
- Advanced editing capabilities
- Bulk operations
- Export/import functionality

**Via Discord:**
- Delete tasks with `/task_delete`
- Interactive management with `/task_delete_panel`
- Task creation with scheduling commands

## Task Examples

### Game Server Management

**Daily Restart Schedule:**
```
/task_daily minecraft restart 06:00
```

**Weekly Backup:**
```
/task_weekly minecraft-backup start Sunday 02:00
```

**Monthly Maintenance:**
```
/task_monthly minecraft stop 1 03:00
/task_once minecraft start 2024-07-01 06:00
```

### Media Server Automation

**Nightly Processing:**
```
/task_daily plex restart 03:00
/task_daily sonarr restart 03:30  
/task_daily radarr restart 04:00
```

**Weekly Cleanup:**
```
/task_weekly cleanup-container start Sunday 01:00
```

### Database Maintenance

**Daily Backup:**
```
/task_daily database-backup start 02:00
```

**Weekly Full Backup:**
```
/task_weekly database stop Saturday 23:00
/task_weekly backup-full start Sunday 00:00
/task_weekly database start Sunday 01:00
```

### Development Environment

**Workday Startup:**
```
/task_weekly dev-env start Monday 08:00
/task_weekly dev-env start Tuesday 08:00
/task_weekly dev-env start Wednesday 08:00
/task_weekly dev-env start Thursday 08:00
/task_weekly dev-env start Friday 08:00
```

**Workday Shutdown:**
```
/task_weekly dev-env stop Monday 18:00
/task_weekly dev-env stop Tuesday 18:00
/task_weekly dev-env stop Wednesday 18:00
/task_weekly dev-env stop Thursday 18:00
/task_weekly dev-env stop Friday 18:00
```

## Troubleshooting Tasks

### Task Not Executing

**Common Causes:**
1. **Container Permissions**: Action not allowed in container config
2. **Channel Permissions**: No task permission in current channel
3. **Container Status**: Container in wrong state for action
4. **Timing Issues**: System clock or timezone problems

**Solutions:**
1. **Check Permissions**: Verify container and channel permissions
2. **Review Logs**: Enable scheduler debug mode
3. **Test Manually**: Try action manually first
4. **Check Timing**: Verify system timezone settings

### Task Debugging

**Enable Debug Mode:**
1. Access Web UI
2. Enable "Scheduler Debug Mode"
3. Save configuration
4. Monitor logs for detailed task information

**Debug Information Includes:**
- Task loading and validation
- Execution attempts and results
- Error details and stack traces
- Performance metrics

### Task Status Issues

**Inactive Tasks:**
- Tasks may become inactive if container is removed
- Tasks with past dates become expired
- Check task list for status indicators

**Missing Tasks:**
- Verify task was created successfully
- Check task info with `/task_info all`
- Review action logs for creation/deletion events

## Best Practices

### Scheduling Strategy

1. **Avoid Conflicts**: Don't schedule conflicting actions
2. **Stagger Operations**: Space out resource-intensive tasks
3. **Consider Dependencies**: Order tasks logically
4. **Test First**: Verify tasks work before scheduling

### Maintenance

1. **Regular Review**: Periodically review active tasks
2. **Clean Up**: Remove obsolete or expired tasks  
3. **Monitor Execution**: Check logs for failed tasks
4. **Update Schedules**: Adjust timing as needed

### Security

1. **Channel Permissions**: Restrict task commands to admin channels
2. **Container Permissions**: Only allow necessary actions
3. **Monitor Changes**: Track task creation/deletion in action logs
4. **Audit Regularly**: Review task list for unauthorized entries

## Next Steps

- [⚙️ Configuration](Configuration) - Configure container permissions
- [Performance](Performance-and-Architecture) - Optimize task performance
- [Troubleshooting](Troubleshooting) - Resolve task issues 