# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import Blueprint, request, jsonify, current_app
import os # Keep for other os operations if present, otherwise remove.
from datetime import datetime
import time
# Import shared data class for active containers
from app.utils.shared_data import get_active_containers, load_active_containers_from_config
# Import log_user_action for User Action Logging
try:
    from services.infrastructure.action_logger import log_user_action
except ImportError:
    from app.utils.web_helpers import log_user_action

# Import the centralized task management functions
from services.scheduling.scheduler import load_tasks, save_tasks, ScheduledTask, CYCLE_CRON, CYCLE_ONCE # CYCLE_CRON for validation
from utils.config_cache import get_cached_config  # Import for configuration and timezone

tasks_bp = Blueprint('tasks_bp', __name__, url_prefix='/tasks')

# _get_tasks_file_path, the old load_tasks and save_tasks are removed, since they are now in utils.scheduler

@tasks_bp.route('/add', methods=['POST'])
def add_task():
    """Adds a new task based on form data, using centralized task management."""
    current_app.logger.debug("Handling add_task request...")
    
    try:
        # Get request JSON data
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        current_app.logger.debug(f"Request data: {data}")
        
        # Extract cycle and schedule_details
        cycle = data.get('cycle')
        if not cycle:
            return jsonify({"error": "Cycle is required"}), 400
            
        # Extract schedule_details from the request
        schedule_details = data.get('schedule_details', {})
        
        # Use timezone from the request if available, or from the configuration
        # This allows the frontend to provide the timezone that was displayed during time selection
        timezone_str = data.get('timezone_str')
        
        if not timezone_str:
            # Fallback: Load timezone from configuration
            config = get_cached_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
        
        current_app.logger.debug(f"Using timezone: {timezone_str}")

        # Debug output for time_str
        if 'time' in schedule_details:
            import pytz
            tz = pytz.timezone(timezone_str)
            current_app.logger.debug(f"Entered time: {schedule_details['time']} in timezone {timezone_str}")
            try:
                # Analyze the entered time and immediately test the conversion
                time_parts = schedule_details['time'].split(':')
                if len(time_parts) == 2:
                    hours, minutes = int(time_parts[0]), int(time_parts[1])
                    now = datetime.now(tz)
                    local_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                    utc_time = local_time.astimezone(pytz.UTC)
                    local_time_back = utc_time.astimezone(tz)
                    
                    current_app.logger.debug(f"Time test: Local={local_time.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
                                           f"UTC={utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
                                           f"Back to local={local_time_back.strftime('%Y-%m-%d %H:%M:%S %Z')}")
            except Exception as e:
                current_app.logger.error(f"Error testing time conversion: {e}")

        # Create a ScheduledTask object
        try:
            new_scheduled_task = ScheduledTask(
                # task_id is automatically generated if not provided
                container_name=data.get('container'),
                action=data.get('action'),
                cycle=data.get('cycle'),
                schedule_details=schedule_details,
                status=data.get('status', 'pending'),
                description=data.get('description', f"Task for {data.get('container')} via Web UI"), 
                created_by="Web UI",
                timezone_str=timezone_str,  # Here the loaded timezone is passed
                is_active=True  # Active by default
            )
            
            # Debugging log before validation
            current_app.logger.debug(f"Created task object: container={new_scheduled_task.container_name}, " + 
                                f"action={new_scheduled_task.action}, cycle={new_scheduled_task.cycle}, " +
                                f"time={new_scheduled_task.time_str}, day={new_scheduled_task.day_val}, " +
                                f"month={new_scheduled_task.month_val}, year={new_scheduled_task.year_val}")
            
            # Explicitly call calculate_next_run since next_run is not in the request
            if new_scheduled_task.is_valid():
                current_app.logger.debug(f"Task is valid, calculating next execution time...")
                
                # Debug info before calculation
                if new_scheduled_task.time_str:
                    current_app.logger.debug(f"Submitted time: {new_scheduled_task.time_str} (in timezone {timezone_str})")
                    try:
                        # Parse the entered time
                        time_parts = new_scheduled_task.time_str.split(':')
                        if len(time_parts) == 2:
                            hours, minutes = int(time_parts[0]), int(time_parts[1])
                            import pytz
                            tz = pytz.timezone(timezone_str)
                            now = datetime.now(tz)
                            dt_with_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                            current_app.logger.debug(f"Parsed time in {timezone_str}: {dt_with_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    except Exception as e:
                        current_app.logger.error(f"Error parsing time: {e}")
                
                # Calculate the next execution time
                new_scheduled_task.calculate_next_run() 
                current_app.logger.debug(f"Task validated and next_run calculated: {new_scheduled_task.next_run_ts}")
                
                # If next_run_ts was set, convert it to readable date/time for debugging
                if new_scheduled_task.next_run_ts:
                    import pytz
                    tz = pytz.timezone(timezone_str)
                    # Convert back to local time for display
                    utc_dt = datetime.utcfromtimestamp(new_scheduled_task.next_run_ts).replace(tzinfo=pytz.UTC)
                    local_dt = utc_dt.astimezone(tz)
                    current_app.logger.debug(f"Calculated next_run: " + 
                                           f"UTC={utc_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}, " + 
                                           f"Local={local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")
                    
                    # Check if the calculated local time matches the input time
                    if new_scheduled_task.time_str:
                        try:
                            time_parts = new_scheduled_task.time_str.split(':')
                            if len(time_parts) == 2:
                                input_hour, input_minute = int(time_parts[0]), int(time_parts[1])
                                if local_dt.hour != input_hour or local_dt.minute != input_minute:
                                    current_app.logger.warning(f"TIME DIFFERENCE detected! Input: {input_hour}:{input_minute}, " +
                                                            f"Calculated: {local_dt.hour}:{local_dt.minute}")
                        except Exception as e:
                            current_app.logger.error(f"Error comparing input and calculated time: {e}")
                
                # If the next execution time is in the past or cannot be set, deactivate the task
                if new_scheduled_task.next_run_ts is None or (new_scheduled_task.cycle == CYCLE_ONCE and new_scheduled_task.next_run_ts < time.time()):
                    # If the time is in the past or cannot be determined, deactivate the task
                    new_scheduled_task.is_active = False
                    current_app.logger.info(f"Task {new_scheduled_task.task_id} was automatically deactivated because the execution time is in the past or could not be determined.")
                
                # Check again if next_run was set (except for 'once' in the past or cron)
                if new_scheduled_task.next_run_ts is None and new_scheduled_task.cycle not in [CYCLE_ONCE, CYCLE_CRON]:
                    current_app.logger.warning(f"Task {new_scheduled_task.task_id} valid, but next_run_ts is None after calculation (cycle: {new_scheduled_task.cycle}).")
            else:
                current_app.logger.error(f"Failed to create a valid ScheduledTask from Web UI data: {data}")
                return jsonify({"error": "Invalid task data provided. Could not create task object."}), 400

        except Exception as e:
            current_app.logger.error(f"Error creating ScheduledTask instance: {e}", exc_info=True)
            return jsonify({"error": "Internal error creating task object. Please check the logs for details."}), 500

        # Import add_task from services.scheduling.scheduler to avoid name conflicts
        from services.scheduling.scheduler import add_task as scheduler_add_task
        
        # Use the add_task function from services.scheduling.scheduler
        if scheduler_add_task(new_scheduled_task):
            current_app.logger.info(f"New task {new_scheduled_task.task_id} added via Web UI.")
            
            # Entry in User Action Log
            log_user_action(
                action="SCHEDULE_CREATE", 
                target=f"{new_scheduled_task.container_name} ({new_scheduled_task.action})",
                source="Web UI",
                details=f"Task ID: {new_scheduled_task.task_id}, Cycle: {new_scheduled_task.cycle}"
            )
            
            # The returned task object should also be in the Web UI format
            return jsonify({"message": "Task added successfully", "task": new_scheduled_task.to_dict()}), 201
        else:
            # add_task returns False in case of collision or other error
            current_app.logger.error(f"Failed to add task {new_scheduled_task.task_id} using utils.scheduler.add_task. It might be a duplicate ID, invalid, or cause a time collision.")
            return jsonify({"error": "Failed to save task. It might be a duplicate, invalid, or conflict with an existing task (time collision)."}), 500

    except Exception as e:
        current_app.logger.error(f"Error handling add_task request: {e}", exc_info=True)
        return jsonify({"error": "Internal error handling add_task request. Please check the logs for details."}), 500

@tasks_bp.route('/list', methods=['GET'])
def list_tasks():
    """Returns the list of saved tasks using centralized task management."""
    # Load tasks from services.scheduling.scheduler returns a list of ScheduledTask objects
    scheduled_tasks_objects = load_tasks() 
    
    # Load the configuration for timezone and other settings
    config = get_cached_config()
    timezone_str = config.get('timezone', 'Europe/Berlin')
    
    # Calculate additional status information for each task
    current_time = time.time()
    tasks_to_update = []  # List for tasks that need to be updated
    
    # Convert each object to a dictionary for the JSON response (according to Web UI format)
    tasks_list_for_json = []
    for task in scheduled_tasks_objects:
        task_dict = task.to_dict()
        
        # Mark system tasks for UI handling
        task_dict["is_system_task"] = task.is_system_task()
        task_dict["is_donation_task"] = task.is_donation_task()
        
        # Ensure that is_active is taken directly
        # (if the dictionary doesn't contain it or sets it incorrectly)
        task_dict["is_active"] = task.is_active
        
        # If created_at_local is not in the dictionary, format it here
        if "created_at_local" not in task_dict and task.created_at_ts:
            try:
                import pytz
                tz = pytz.timezone(timezone_str)
                # Convert UTC timestamp to local time
                local_dt = datetime.utcfromtimestamp(task.created_at_ts).replace(tzinfo=pytz.UTC).astimezone(tz)
                task_dict["created_at_local"] = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception as e:
                current_app.logger.error(f"Error formatting created_at_local: {e}")
        
        # For debugging purposes
        is_active_orig = task.is_active
        is_in_past = False
        is_one_time = task.cycle == CYCLE_ONCE
        next_run_ts = task.next_run_ts
        
        # Format next_run_local for display in the UI
        if next_run_ts:
            try:
                import pytz
                tz = pytz.timezone(timezone_str)
                # Convert UTC timestamp to local time
                next_run_local = datetime.utcfromtimestamp(next_run_ts).replace(tzinfo=pytz.UTC).astimezone(tz)
                task_dict["next_run_local"] = next_run_local.strftime("%Y-%m-%d %H:%M:%S %Z")
                
                # Check if the execution time is in the past
                if next_run_ts < current_time:
                    is_in_past = True
                    current_app.logger.debug(f"Task {task.task_id} has next_run_ts in the past: {next_run_local} vs. now: {datetime.fromtimestamp(current_time)}")
            except Exception as e:
                current_app.logger.error(f"Error formatting next_run_local: {e}")
        
        # Calculate the frontend status for display
        # Frontend status can be "active", "deactivated" or "expired"
        # (independent from backend status, which is more like "pending", "executing", "completed" etc.)
        if task.next_run_ts is None and task.cycle == CYCLE_ONCE:
            # One-time task without next execution time: is expired
            frontend_status = "expired"
            is_in_past = True
            
            # If the task is still active, deactivate and mark for update
            if task.is_active:
                task.is_active = False
                task_dict["is_active"] = False
                tasks_to_update.append(task)
                current_app.logger.info(f"Task {task.task_id} is marked as expired (no next_run_ts) and deactivated")
        elif task.cycle == CYCLE_ONCE and task.status == "completed":
            # One-time task with status "completed": is already executed and thus expired
            frontend_status = "expired"
            is_in_past = True
            
            # If the task is still active, deactivate and mark for update
            if task.is_active:
                task.is_active = False
                task_dict["is_active"] = False
                tasks_to_update.append(task)
                current_app.logger.info(f"Task {task.task_id} is marked as expired (status completed) and deactivated")
        elif task.cycle == CYCLE_ONCE and is_in_past:
            # One-time task with execution time in the past: mark as expired
            frontend_status = "expired"
            
            # Also set is_active to False since the task has expired
            if task.is_active:
                task.is_active = False
                task_dict["is_active"] = False
                tasks_to_update.append(task)
                current_app.logger.info(f"Task {task.task_id} is marked as expired (time in past) and deactivated")
        elif task.next_run_ts is None:
            # Other task type without next execution time: could be a problem
            frontend_status = "deactivated" if not task.is_active else "expired"
            current_app.logger.warning(f"Task {task.task_id} ({task.cycle}) has no next_run_ts")
        elif not task.is_active:
            # Task is manually deactivated
            frontend_status = "deactivated"
        else:
            # Normal, active task
            frontend_status = "active"
        
        task_dict["frontend_status"] = frontend_status
        task_dict["is_in_past"] = is_in_past
        tasks_list_for_json.append(task_dict)
    
    # Save changes for deactivated tasks
    if tasks_to_update:
        from services.scheduling.scheduler import update_task
        for task in tasks_to_update:
            update_task(task)
            current_app.logger.info(f"Task {task.task_id} was marked as expired and deactivated. Changes saved.")
    
    return jsonify(tasks_list_for_json), 200

@tasks_bp.route('/form', methods=['GET'])
def show_task_form():
    """Shows the form for creating tasks."""
    # Load active containers to display in the form
    load_active_containers_from_config()
    active_containers = get_active_containers()
    
    # Load configuration for timezone
    config = get_cached_config()
    timezone_str = config.get('timezone', 'Europe/Berlin')
    
    # Get the local timezone with abbreviation (e.g. CEST)
    try:
        import pytz
        tz = pytz.timezone(timezone_str)
        now = datetime.now(tz)
        timezone_name = now.strftime("%Z")  # Returns the timezone abbreviation (e.g. CEST)
    except Exception as e:
        current_app.logger.error(f"Error getting timezone abbreviation: {e}")
        timezone_name = timezone_str  # Fallback to timezone identifier
    
    # Render the form template with active containers and timezone
    from flask import render_template
    return render_template('tasks/form.html', 
                          active_containers=active_containers,
                          timezone_str=timezone_str,
                          timezone_name=timezone_name)

# Route for displaying the form removed

# More routes could be added here (list, delete, update)

@tasks_bp.route('/update_status', methods=['POST'])
def update_task_status():
    """Updates the active status of a task."""
    if not request.is_json:
        return jsonify({"success": False, "error": "Request must be JSON"}), 400

    data = request.get_json()
    task_id = data.get('task_id')
    is_active = data.get('is_active')
    
    if not task_id:
        return jsonify({"success": False, "error": "Missing task_id"}), 400
    
    if is_active is None:  # Explicit check for None, since is_active can be a boolean
        return jsonify({"success": False, "error": "Missing is_active flag"}), 400
    
    # Import required functions
    from services.scheduling.scheduler import find_task_by_id, update_task
    
    # Find the task by ID
    task = find_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Task with ID {task_id} not found"}), 404
    
    # If the task is to be activated, check if it's in the past
    if is_active:
        # Check if the task is expired (next_run_ts is None or the task is a "once" task with status "completed")
        is_expired = task.next_run_ts is None or (task.cycle == CYCLE_ONCE and task.status == "completed")
        
        if is_expired:
            current_app.logger.warning(f"Attempt to activate expired task {task_id}")
            return jsonify({
                "success": False, 
                "error": "Cannot activate expired task. This task's execution time is in the past or its cycle has completed."
            }), 400
    
    # Update the active status
    task.is_active = bool(is_active)  # Ensure it's a boolean
    
    # Save the updated task
    if update_task(task):
        current_app.logger.info(f"Task {task_id} active status updated to {is_active}")
        return jsonify({
            "success": True, 
            "message": f"Task {task_id} active status updated successfully",
            "task": task.to_dict()
        })
    else:
        current_app.logger.error(f"Failed to update task {task_id} active status")
        return jsonify({"success": False, "error": "Failed to update task status"}), 500 

@tasks_bp.route('/delete/<task_id>', methods=['DELETE'])
def delete_task_route(task_id):
    """Deletes a specific task by ID."""
    if not task_id:
        return jsonify({"success": False, "error": "Missing task_id"}), 400
    
    # Import the delete_task function from services.scheduling.scheduler
    from services.scheduling.scheduler import delete_task, find_task_by_id
    
    # Check first if the task exists
    task = find_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Task with ID {task_id} not found"}), 404
    
    # Store details for the log before the task is deleted
    container_name = task.container_name
    action = task.action
    cycle = task.cycle
    
    # Delete the task
    if delete_task(task_id):
        current_app.logger.info(f"Task {task_id} successfully deleted via Web UI")
        
        # Entry in User Action Log
        log_user_action(
            action="SCHEDULE_DELETE", 
            target=f"{container_name} ({action})",
            source="Web UI",
            details=f"Task ID: {task_id}, Cycle: {cycle}"
        )
        
        return jsonify({"success": True, "message": f"Task {task_id} deleted successfully"}), 200
    else:
        current_app.logger.error(f"Failed to delete task {task_id}")
        return jsonify({"success": False, "error": "Failed to delete task"}), 500

@tasks_bp.route('/edit/<task_id>', methods=['GET', 'PUT'])
def edit_task_route(task_id):
    """Gets or updates a specific task by ID."""
    if not task_id:
        return jsonify({"success": False, "error": "Missing task_id"}), 400
    
    # Import required functions
    from services.scheduling.scheduler import find_task_by_id, update_task
    
    # Find the task by ID
    task = find_task_by_id(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Task with ID {task_id} not found"}), 404
    
    if request.method == 'GET':
        # Return task data for editing
        config = get_cached_config()
        timezone_str = config.get('timezone', 'Europe/Berlin')
        
        task_dict = task.to_dict()
        
        # Format next_run_local for display
        if task.next_run_ts:
            try:
                import pytz
                tz = pytz.timezone(timezone_str)
                next_run_local = datetime.utcfromtimestamp(task.next_run_ts).replace(tzinfo=pytz.UTC).astimezone(tz)
                task_dict["next_run_local"] = next_run_local.strftime("%Y-%m-%d %H:%M:%S %Z")
            except Exception as e:
                current_app.logger.error(f"Error formatting next_run_local: {e}")
        
        return jsonify({"success": True, "task": task_dict}), 200
    
    elif request.method == 'PUT':
        # Update task data
        try:
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400
            
            current_app.logger.debug(f"Updating task {task_id} with data: {data}")
            
            # Store original values for logging
            original_container = task.container_name
            original_action = task.action
            original_cycle = task.cycle
            
            # Update basic fields
            if 'container' in data:
                task.container_name = data['container']
            if 'action' in data:
                task.action = data['action']
            if 'cycle' in data:
                task.cycle = data['cycle']
            if 'is_active' in data:
                task.is_active = bool(data['is_active'])
            
            # Update schedule details
            if 'schedule_details' in data:
                schedule_details = data['schedule_details']
                
                # Clear existing schedule details
                task.time_str = None
                task.day_val = None
                task.month_val = None
                task.year_val = None
                task.weekday_val = None
                task.cron_string = None
                
                # Set new schedule details based on cycle
                if task.cycle == 'cron':
                    if 'cron_string' in schedule_details:
                        task.cron_string = schedule_details['cron_string']
                else:
                    if 'time' in schedule_details:
                        task.time_str = schedule_details['time']
                    
                    if 'day' in schedule_details:
                        if task.cycle == 'weekly':
                            # For weekly tasks, day is a weekday string
                            weekday_map = {'Mon': 0, 'Tue': 1, 'Wed': 2, 'Thu': 3, 'Fri': 4, 'Sat': 5, 'Sun': 6}
                            task.weekday_val = weekday_map.get(schedule_details['day'])
                        else:
                            # For other cycles, day is a number
                            try:
                                task.day_val = int(schedule_details['day'])
                            except (ValueError, TypeError):
                                pass
                    
                    if 'month' in schedule_details:
                        try:
                            task.month_val = int(schedule_details['month'])
                        except (ValueError, TypeError):
                            pass
                    
                    if 'year' in schedule_details:
                        try:
                            task.year_val = int(schedule_details['year'])
                        except (ValueError, TypeError):
                            pass
            
            # Update timezone if provided
            if 'timezone_str' in data:
                task.timezone_str = data['timezone_str']
            
            # Validate the updated task
            if not task.is_valid():
                return jsonify({"success": False, "error": "Updated task data is invalid"}), 400
            
            # Recalculate next run time
            task.calculate_next_run()
            
            # Check if the task should be deactivated (for once tasks in the past)
            if task.cycle == CYCLE_ONCE and task.next_run_ts and task.next_run_ts < time.time():
                task.is_active = False
                current_app.logger.info(f"Task {task_id} was automatically deactivated because the execution time is in the past.")
            
            # Save the updated task
            if update_task(task):
                current_app.logger.info(f"Task {task_id} successfully updated via Web UI")
                
                # Entry in User Action Log
                log_user_action(
                    action="SCHEDULE_UPDATE", 
                    target=f"{task.container_name} ({task.action})",
                    source="Web UI",
                    details=f"Task ID: {task_id}, Cycle: {task.cycle}, Updated from: {original_container} ({original_action}, {original_cycle})"
                )
                
                return jsonify({
                    "success": True, 
                    "message": f"Task {task_id} updated successfully",
                    "task": task.to_dict()
                }), 200
            else:
                current_app.logger.error(f"Failed to update task {task_id}")
                return jsonify({"success": False, "error": "Failed to save updated task"}), 500
                
        except Exception as e:
            current_app.logger.error(f"Error updating task {task_id}: {e}", exc_info=True)
            return jsonify({"success": False, "error": "Internal error updating task. Please check the logs for details."}), 500 