#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Task Management Service                        #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                       #
# Licensed under the MIT License                                               #
# ============================================================================ #

"""
Task Management Service - Handles complex task management operations including
creation, validation, scheduling, status management, and lifecycle operations.
"""

import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AddTaskRequest:
    """Represents a task creation request."""
    container: str
    action: str
    cycle: str
    schedule_details: Dict[str, Any]
    timezone_str: Optional[str] = None
    status: str = 'pending'
    description: Optional[str] = None


@dataclass
class AddTaskResult:
    """Represents the result of task creation."""
    success: bool
    task_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class ListTasksRequest:
    """Represents a task listing request."""
    timezone_str: Optional[str] = None


@dataclass
class ListTasksResult:
    """Represents the result of task listing."""
    success: bool
    tasks: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None


@dataclass
class UpdateTaskStatusRequest:
    """Represents a task status update request."""
    task_id: str
    is_active: bool


@dataclass
class UpdateTaskStatusResult:
    """Represents the result of task status update."""
    success: bool
    task_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class DeleteTaskRequest:
    """Represents a task deletion request."""
    task_id: str


@dataclass
class DeleteTaskResult:
    """Represents the result of task deletion."""
    success: bool
    error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class EditTaskRequest:
    """Represents a task edit request."""
    task_id: str
    operation: str  # 'get' or 'update'
    data: Optional[Dict[str, Any]] = None
    timezone_str: Optional[str] = None


@dataclass
class EditTaskResult:
    """Represents the result of task edit operation."""
    success: bool
    task_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None


@dataclass
class TaskFormRequest:
    """Represents a task form data request."""
    pass


@dataclass
class TaskFormResult:
    """Represents the result of task form data preparation."""
    success: bool
    form_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class TaskManagementService:
    """Service for comprehensive task management with complex business logic."""

    def __init__(self):
        self.logger = logger

    def add_task(self, request: AddTaskRequest) -> AddTaskResult:
        """
        Add a new scheduled task with comprehensive validation and scheduling.

        Args:
            request: AddTaskRequest with task creation data

        Returns:
            AddTaskResult with task data or error information
        """
        try:
            # Step 1: Load configuration and determine timezone
            timezone_str = self._determine_timezone(request.timezone_str)

            # Step 2: Debug timezone and time handling
            self._debug_time_conversion(request.schedule_details, timezone_str)

            # Step 3: Create and validate ScheduledTask object
            scheduled_task = self._create_scheduled_task(request, timezone_str)
            if not scheduled_task:
                return AddTaskResult(
                    success=False,
                    error="Invalid task data provided. Could not create task object."
                )

            # Step 4: Validate and calculate next run time
            validation_result = self._validate_and_calculate_next_run(scheduled_task, timezone_str)
            if not validation_result:
                return AddTaskResult(
                    success=False,
                    error="Task validation failed or next run time could not be calculated."
                )

            # Step 5: Save task using scheduler service
            save_result = self._save_task_via_scheduler(scheduled_task)
            if not save_result['success']:
                return AddTaskResult(
                    success=False,
                    error=save_result['error']
                )

            # Step 6: Log user action
            self._log_task_creation(scheduled_task)

            return AddTaskResult(
                success=True,
                task_data=scheduled_task.to_dict(),
                message="Task added successfully"
            )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service, config service unavailable)
            self.logger.error(f"Service dependency error in add_task: {e}", exc_info=True)
            return AddTaskResult(
                success=False,
                error=f"Service error adding task: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data processing errors (task validation, timezone conversion, dict access)
            self.logger.error(f"Data processing error in add_task: {e}", exc_info=True)
            return AddTaskResult(
                success=False,
                error=f"Data error adding task: {str(e)}"
            )

    def list_tasks(self, request: ListTasksRequest) -> ListTasksResult:
        """
        List all tasks with status calculations and automatic cleanup.

        Args:
            request: ListTasksRequest with optional timezone

        Returns:
            ListTasksResult with tasks list or error information
        """
        try:
            # Step 1: Load tasks and configuration
            scheduled_tasks = self._load_tasks_from_scheduler()
            timezone_str = self._determine_timezone(request.timezone_str)

            # Step 2: Process each task for frontend display
            tasks_list = []
            tasks_to_update = []
            current_time = time.time()

            for task in scheduled_tasks:
                task_data = self._process_task_for_frontend(task, timezone_str, current_time)

                # Check if task needs updating (expired, etc.)
                if task_data.get('needs_update'):
                    tasks_to_update.append(task)
                    del task_data['needs_update']  # Remove internal flag

                tasks_list.append(task_data)

            # Step 3: Save changes for tasks that need updating
            self._save_updated_tasks(tasks_to_update)

            return ListTasksResult(
                success=True,
                tasks=tasks_list
            )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service unavailable)
            self.logger.error(f"Service dependency error in list_tasks: {e}", exc_info=True)
            return ListTasksResult(
                success=False,
                error=f"Service error listing tasks: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data processing errors (task data parsing, timezone conversion)
            self.logger.error(f"Data processing error in list_tasks: {e}", exc_info=True)
            return ListTasksResult(
                success=False,
                error=f"Data error listing tasks: {str(e)}"
            )

    def update_task_status(self, request: UpdateTaskStatusRequest) -> UpdateTaskStatusResult:
        """
        Update the active status of a task with validation.

        Args:
            request: UpdateTaskStatusRequest with task ID and new status

        Returns:
            UpdateTaskStatusResult with updated task data or error
        """
        try:
            # Step 1: Find task by ID
            task = self._find_task_by_id(request.task_id)
            if not task:
                return UpdateTaskStatusResult(
                    success=False,
                    error=f"Task with ID {request.task_id} not found"
                )

            # Step 2: Validate activation request for expired tasks
            if request.is_active:
                if self._is_task_expired(task):
                    return UpdateTaskStatusResult(
                        success=False,
                        error="Cannot activate expired task. This task's execution time is in the past or its cycle has completed."
                    )

            # Step 3: Update status
            task.is_active = bool(request.is_active)

            # Step 4: Save updated task
            if self._update_task_via_scheduler(task):
                self.logger.info(f"Task {request.task_id} active status updated to {request.is_active}")
                return UpdateTaskStatusResult(
                    success=True,
                    task_data=task.to_dict(),
                    message=f"Task {request.task_id} active status updated successfully"
                )
            else:
                return UpdateTaskStatusResult(
                    success=False,
                    error="Failed to update task status"
                )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service unavailable)
            self.logger.error(f"Service dependency error in update_task_status: {e}", exc_info=True)
            return UpdateTaskStatusResult(
                success=False,
                error=f"Service error updating task status: {str(e)}"
            )
        except (ValueError, TypeError) as e:
            # Data processing errors (task ID validation, status conversion)
            self.logger.error(f"Data processing error in update_task_status: {e}", exc_info=True)
            return UpdateTaskStatusResult(
                success=False,
                error=f"Data error updating task status: {str(e)}"
            )

    def delete_task(self, request: DeleteTaskRequest) -> DeleteTaskResult:
        """
        Delete a specific task by ID.

        Args:
            request: DeleteTaskRequest with task ID

        Returns:
            DeleteTaskResult with success status or error
        """
        try:
            # Step 1: Find task to verify it exists and get details for logging
            task = self._find_task_by_id(request.task_id)
            if not task:
                return DeleteTaskResult(
                    success=False,
                    error=f"Task with ID {request.task_id} not found"
                )

            # Step 2: Store details for logging before deletion
            task_details = {
                'container_name': task.container_name,
                'action': task.action,
                'cycle': task.cycle
            }

            # Step 3: Delete task via scheduler
            if self._delete_task_via_scheduler(request.task_id):
                self.logger.info(f"Task {request.task_id} successfully deleted via Web UI")

                # Step 4: Log user action
                self._log_task_deletion(request.task_id, task_details)

                return DeleteTaskResult(
                    success=True,
                    message=f"Task {request.task_id} deleted successfully"
                )
            else:
                return DeleteTaskResult(
                    success=False,
                    error="Failed to delete task"
                )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service, action log service unavailable)
            self.logger.error(f"Service dependency error in delete_task: {e}", exc_info=True)
            return DeleteTaskResult(
                success=False,
                error=f"Service error deleting task: {str(e)}"
            )
        except (ValueError, KeyError) as e:
            # Data processing errors (task details access)
            self.logger.error(f"Data processing error in delete_task: {e}", exc_info=True)
            return DeleteTaskResult(
                success=False,
                error=f"Data error deleting task: {str(e)}"
            )

    def edit_task(self, request: EditTaskRequest) -> EditTaskResult:
        """
        Get or update a specific task by ID.

        Args:
            request: EditTaskRequest with operation type and data

        Returns:
            EditTaskResult with task data or update result
        """
        try:
            # Step 1: Find task by ID
            task = self._find_task_by_id(request.task_id)
            if not task:
                return EditTaskResult(
                    success=False,
                    error=f"Task with ID {request.task_id} not found"
                )

            if request.operation == 'get':
                # Return task data for editing
                return self._get_task_for_editing(task, request.timezone_str)

            elif request.operation == 'update':
                # Update task with new data
                return self._update_task_with_data(task, request.data, request.timezone_str)

            else:
                return EditTaskResult(
                    success=False,
                    error=f"Invalid operation: {request.operation}"
                )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service unavailable)
            self.logger.error(f"Service dependency error in edit_task: {e}", exc_info=True)
            return EditTaskResult(
                success=False,
                error=f"Service error editing task: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data processing errors (task data validation, operation type)
            self.logger.error(f"Data processing error in edit_task: {e}", exc_info=True)
            return EditTaskResult(
                success=False,
                error=f"Data error editing task: {str(e)}"
            )

    def get_task_form_data(self, request: TaskFormRequest) -> TaskFormResult:
        """
        Get data needed for task creation form.

        Args:
            request: TaskFormRequest

        Returns:
            TaskFormResult with form data or error
        """
        try:
            # Step 1: Load active containers
            from app.utils.shared_data import load_active_containers_from_config, get_active_containers
            load_active_containers_from_config()
            active_containers = get_active_containers()

            # Step 2: Load timezone configuration
            from services.config.config_service import load_config
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')

            # Step 3: Get timezone abbreviation
            timezone_name = self._get_timezone_abbreviation(timezone_str)

            return TaskFormResult(
                success=True,
                form_data={
                    'active_containers': active_containers,
                    'timezone_str': timezone_str,
                    'timezone_name': timezone_name
                }
            )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (config service, shared_data unavailable)
            self.logger.error(f"Service dependency error in get_task_form_data: {e}", exc_info=True)
            return TaskFormResult(
                success=False,
                error=f"Service error loading form data: {str(e)}"
            )
        except (ValueError, KeyError) as e:
            # Data processing errors (config access, dict operations)
            self.logger.error(f"Data processing error in get_task_form_data: {e}", exc_info=True)
            return TaskFormResult(
                success=False,
                error=f"Data error loading form data: {str(e)}"
            )

    # ========================================================================
    # Private Helper Methods
    # ========================================================================

    def _determine_timezone(self, timezone_str: Optional[str]) -> str:
        """Determine timezone from request or config."""
        if timezone_str:
            return timezone_str

        from services.config.config_service import load_config
        config = load_config()
        return config.get('timezone', 'Europe/Berlin')

    def _debug_time_conversion(self, schedule_details: Dict[str, Any], timezone_str: str):
        """Debug time conversion for timezone handling."""
        if 'time' not in schedule_details:
            return

        try:
            import pytz
            tz = pytz.timezone(timezone_str)
            self.logger.debug(f"Entered time: {schedule_details['time']} in timezone {timezone_str}")

            time_parts = schedule_details['time'].split(':')
            if len(time_parts) == 2:
                hours, minutes = int(time_parts[0]), int(time_parts[1])
                now = datetime.now(tz)
                local_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                utc_time = local_time.astimezone(pytz.UTC)
                local_time_back = utc_time.astimezone(tz)

                self.logger.debug(f"Time test: Local={local_time.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
                                f"UTC={utc_time.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
                                f"Back to local={local_time_back.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        except (ImportError, AttributeError) as e:
            # Import errors (pytz unavailable)
            self.logger.error(f"Import error testing time conversion: {e}", exc_info=True)
        except (ValueError, IndexError) as e:
            # Data parsing errors (time format invalid)
            self.logger.error(f"Data error testing time conversion: {e}", exc_info=True)

    def _create_scheduled_task(self, request: AddTaskRequest, timezone_str: str):
        """Create ScheduledTask object from request data."""
        try:
            from services.scheduling.scheduler import ScheduledTask

            description = request.description or f"Task for {request.container} via Web UI"

            scheduled_task = ScheduledTask(
                container_name=request.container,
                action=request.action,
                cycle=request.cycle,
                schedule_details=request.schedule_details,
                status=request.status,
                description=description,
                created_by="Web UI",
                timezone_str=timezone_str,
                is_active=True
            )

            self.logger.debug(f"Created task object: container={scheduled_task.container_name}, "
                            f"action={scheduled_task.action}, cycle={scheduled_task.cycle}, "
                            f"time={scheduled_task.time_str}, day={scheduled_task.day_val}, "
                            f"month={scheduled_task.month_val}, year={scheduled_task.year_val}")

            return scheduled_task

        except (ImportError, AttributeError) as e:
            # Import errors (ScheduledTask class unavailable)
            self.logger.error(f"Import error creating ScheduledTask instance: {e}", exc_info=True)
            return None
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (task initialization failed)
            self.logger.error(f"Data error creating ScheduledTask instance: {e}", exc_info=True)
            return None

    def _validate_and_calculate_next_run(self, task, timezone_str: str) -> bool:
        """Validate task and calculate next run time."""
        try:
            if not task.is_valid():
                self.logger.error(f"Task validation failed for task with container={task.container_name}")
                return False

            self.logger.debug(f"Task is valid, calculating next execution time...")

            # Debug time parsing
            if task.time_str:
                self._debug_time_parsing(task.time_str, timezone_str)

            # Calculate next run
            task.calculate_next_run()
            self.logger.debug(f"Task validated and next_run calculated: {task.next_run_ts}")

            # Debug calculated time
            if task.next_run_ts:
                self._debug_calculated_time(task, timezone_str)

            # Check if task should be deactivated (one-time tasks in the past)
            from services.scheduling.scheduler import CYCLE_ONCE
            if task.next_run_ts is None or (task.cycle == CYCLE_ONCE and task.next_run_ts < time.time()):
                task.is_active = False
                self.logger.info(f"Task {task.task_id} was automatically deactivated because the execution time is in the past or could not be determined.")

            return True

        except (ImportError, AttributeError, RuntimeError) as e:
            # Import/service errors (CYCLE_ONCE constant, scheduler unavailable)
            self.logger.error(f"Service error validating and calculating next run: {e}", exc_info=True)
            return False
        except (ValueError, TypeError) as e:
            # Data errors (time calculation failed)
            self.logger.error(f"Data error validating and calculating next run: {e}", exc_info=True)
            return False

    def _debug_time_parsing(self, time_str: str, timezone_str: str):
        """Debug time parsing for troubleshooting."""
        try:
            import pytz
            self.logger.debug(f"Submitted time: {time_str} (in timezone {timezone_str})")

            time_parts = time_str.split(':')
            if len(time_parts) == 2:
                hours, minutes = int(time_parts[0]), int(time_parts[1])
                tz = pytz.timezone(timezone_str)
                now = datetime.now(tz)
                dt_with_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                self.logger.debug(f"Parsed time in {timezone_str}: {dt_with_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        except (ImportError, AttributeError) as e:
            # Import errors (pytz unavailable)
            self.logger.error(f"Import error parsing time: {e}", exc_info=True)
        except (ValueError, IndexError) as e:
            # Data parsing errors (time format invalid)
            self.logger.error(f"Data error parsing time: {e}", exc_info=True)

    def _debug_calculated_time(self, task, timezone_str: str):
        """Debug calculated execution time."""
        try:
            import pytz
            tz = pytz.timezone(timezone_str)
            utc_dt = datetime.utcfromtimestamp(task.next_run_ts).replace(tzinfo=pytz.UTC)
            local_dt = utc_dt.astimezone(tz)

            self.logger.debug(f"Calculated next_run: "
                            f"UTC={utc_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}, "
                            f"Local={local_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}")

            # Check if calculated time matches input time
            if task.time_str:
                time_parts = task.time_str.split(':')
                if len(time_parts) == 2:
                    input_hour, input_minute = int(time_parts[0]), int(time_parts[1])
                    if local_dt.hour != input_hour or local_dt.minute != input_minute:
                        self.logger.warning(f"TIME DIFFERENCE detected! Input: {input_hour}:{input_minute}, "
                                          f"Calculated: {local_dt.hour}:{local_dt.minute}")
        except (ImportError, AttributeError) as e:
            # Import errors (pytz unavailable)
            self.logger.error(f"Import error comparing input and calculated time: {e}", exc_info=True)
        except (ValueError, IndexError, TypeError) as e:
            # Data errors (timestamp conversion, time parsing)
            self.logger.error(f"Data error comparing input and calculated time: {e}", exc_info=True)

    def _save_task_via_scheduler(self, task) -> Dict[str, Any]:
        """Save task using scheduler service."""
        try:
            from services.scheduling.scheduler import add_task as scheduler_add_task

            if scheduler_add_task(task):
                self.logger.info(f"New task {task.task_id} added via Web UI.")
                return {'success': True}
            else:
                error_msg = f"Failed to add task {task.task_id} using scheduler.add_task. It might be a duplicate ID, invalid, or cause a time collision."
                self.logger.error(error_msg)
                return {'success': False, 'error': error_msg}

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service unavailable)
            self.logger.error(f"Service dependency error saving task via scheduler: {e}", exc_info=True)
            return {'success': False, 'error': f"Service error saving task: {str(e)}"}
        except (ValueError, TypeError) as e:
            # Data errors (task validation)
            self.logger.error(f"Data error saving task via scheduler: {e}", exc_info=True)
            return {'success': False, 'error': f"Data error saving task: {str(e)}"}

    def _log_task_creation(self, task):
        """Log task creation for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(
                action="SCHEDULE_CREATE",
                target=f"{task.container_name} ({task.action})",
                source="Web UI",
                details=f"Task ID: {task.task_id}, Cycle: {task.cycle}"
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (action logger unavailable)
            self.logger.error(f"Service dependency error logging task creation: {e}", exc_info=True)
        except (ValueError, TypeError) as e:
            # Data errors (task attribute access)
            self.logger.error(f"Data error logging task creation: {e}", exc_info=True)

    def _load_tasks_from_scheduler(self):
        """Load all tasks from scheduler."""
        from services.scheduling.scheduler import load_tasks
        return load_tasks()

    def _process_task_for_frontend(self, task, timezone_str: str, current_time: float) -> Dict[str, Any]:
        """Process task data for frontend display with status calculations."""
        task_dict = task.to_dict()

        # Mark special task types
        task_dict["is_system_task"] = task.is_system_task()
        task_dict["is_donation_task"] = task.is_donation_task()
        task_dict["is_active"] = task.is_active

        # Format created_at_local if needed
        if "created_at_local" not in task_dict and task.created_at_ts:
            task_dict["created_at_local"] = self._format_timestamp_local(task.created_at_ts, timezone_str)

        # Format next_run_local for display
        if task.next_run_ts:
            task_dict["next_run_local"] = self._format_timestamp_local(task.next_run_ts, timezone_str)

        # Calculate frontend status and handle expired tasks
        frontend_status, needs_update = self._calculate_frontend_status(task, current_time)
        task_dict["frontend_status"] = frontend_status
        task_dict["is_in_past"] = task.next_run_ts and task.next_run_ts < current_time

        if needs_update:
            task_dict["needs_update"] = True

        return task_dict

    def _calculate_frontend_status(self, task, current_time: float):
        """Calculate frontend status and determine if task needs updating."""
        from services.scheduling.scheduler import CYCLE_ONCE

        needs_update = False

        # Check various expiration conditions
        if task.next_run_ts is None and task.cycle == CYCLE_ONCE:
            frontend_status = "expired"
            if task.is_active:
                task.is_active = False
                needs_update = True
                self.logger.info(f"Task {task.task_id} is marked as expired (no next_run_ts) and deactivated")

        elif task.cycle == CYCLE_ONCE and task.status == "completed":
            frontend_status = "expired"
            if task.is_active:
                task.is_active = False
                needs_update = True
                self.logger.info(f"Task {task.task_id} is marked as expired (status completed) and deactivated")

        elif task.cycle == CYCLE_ONCE and task.next_run_ts and task.next_run_ts < current_time:
            frontend_status = "expired"
            if task.is_active:
                task.is_active = False
                needs_update = True
                self.logger.info(f"Task {task.task_id} is marked as expired (time in past) and deactivated")

        elif task.next_run_ts is None:
            frontend_status = "deactivated" if not task.is_active else "expired"
            self.logger.warning(f"Task {task.task_id} ({task.cycle}) has no next_run_ts")

        elif not task.is_active:
            frontend_status = "deactivated"

        else:
            frontend_status = "active"

        return frontend_status, needs_update

    def _format_timestamp_local(self, timestamp: float, timezone_str: str) -> str:
        """Format timestamp in local timezone."""
        try:
            import pytz
            tz = pytz.timezone(timezone_str)
            local_dt = datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.UTC).astimezone(tz)
            return local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        except (ImportError, AttributeError) as e:
            # Import errors (pytz unavailable)
            self.logger.error(f"Import error formatting timestamp: {e}", exc_info=True)
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError) as e:
            # Data/OS errors (invalid timestamp)
            self.logger.error(f"Error formatting timestamp: {e}", exc_info=True)
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    def _save_updated_tasks(self, tasks_to_update: List):
        """Save multiple updated tasks."""
        if not tasks_to_update:
            return

        try:
            from services.scheduling.scheduler import update_task
            for task in tasks_to_update:
                update_task(task)
                self.logger.info(f"Task {task.task_id} was marked as expired and deactivated. Changes saved.")
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler update_task unavailable)
            self.logger.error(f"Service dependency error saving updated tasks: {e}", exc_info=True)
        except (ValueError, TypeError) as e:
            # Data errors (task update failed)
            self.logger.error(f"Data error saving updated tasks: {e}", exc_info=True)

    def _find_task_by_id(self, task_id: str):
        """Find task by ID using scheduler."""
        try:
            from services.scheduling.scheduler import find_task_by_id
            return find_task_by_id(task_id)
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler find_task_by_id unavailable)
            self.logger.error(f"Service dependency error finding task by ID {task_id}: {e}", exc_info=True)
            return None
        except (ValueError, TypeError) as e:
            # Data errors (invalid task ID)
            self.logger.error(f"Data error finding task by ID {task_id}: {e}", exc_info=True)
            return None

    def _is_task_expired(self, task) -> bool:
        """Check if task is expired and cannot be activated."""
        from services.scheduling.scheduler import CYCLE_ONCE
        return task.next_run_ts is None or (task.cycle == CYCLE_ONCE and task.status == "completed")

    def _update_task_via_scheduler(self, task) -> bool:
        """Update task using scheduler service."""
        try:
            from services.scheduling.scheduler import update_task
            return update_task(task)
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler update_task unavailable)
            self.logger.error(f"Service dependency error updating task via scheduler: {e}", exc_info=True)
            return False
        except (ValueError, TypeError) as e:
            # Data errors (task validation failed)
            self.logger.error(f"Data error updating task via scheduler: {e}", exc_info=True)
            return False

    def _delete_task_via_scheduler(self, task_id: str) -> bool:
        """Delete task using scheduler service."""
        try:
            from services.scheduling.scheduler import delete_task
            return delete_task(task_id)
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler delete_task unavailable)
            self.logger.error(f"Service dependency error deleting task via scheduler: {e}", exc_info=True)
            return False
        except (ValueError, TypeError) as e:
            # Data errors (invalid task ID)
            self.logger.error(f"Data error deleting task via scheduler: {e}", exc_info=True)
            return False

    def _log_task_deletion(self, task_id: str, task_details: Dict[str, str]):
        """Log task deletion for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(
                action="SCHEDULE_DELETE",
                target=f"{task_details['container_name']} ({task_details['action']})",
                source="Web UI",
                details=f"Task ID: {task_id}, Cycle: {task_details['cycle']}"
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (action logger unavailable)
            self.logger.error(f"Service dependency error logging task deletion: {e}", exc_info=True)
        except (ValueError, KeyError) as e:
            # Data errors (task_details access)
            self.logger.error(f"Data error logging task deletion: {e}", exc_info=True)

    def _get_task_for_editing(self, task, timezone_str: Optional[str]) -> EditTaskResult:
        """Get task data formatted for editing."""
        try:
            if timezone_str is None:
                timezone_str = self._determine_timezone(None)

            task_dict = task.to_dict()

            # Format next_run_local for display
            if task.next_run_ts:
                task_dict["next_run_local"] = self._format_timestamp_local(task.next_run_ts, timezone_str)

            return EditTaskResult(
                success=True,
                task_data=task_dict
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (timezone service unavailable)
            self.logger.error(f"Service dependency error getting task for editing: {e}", exc_info=True)
            return EditTaskResult(
                success=False,
                error=f"Service error preparing task for editing: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (task data access, dict operations)
            self.logger.error(f"Data error getting task for editing: {e}", exc_info=True)
            return EditTaskResult(
                success=False,
                error=f"Data error preparing task for editing: {str(e)}"
            )

    def _update_task_with_data(self, task, data: Dict[str, Any], timezone_str: Optional[str]) -> EditTaskResult:
        """Update task with new data."""
        try:
            if not data:
                return EditTaskResult(
                    success=False,
                    error="No data provided"
                )

            self.logger.debug(f"Updating task {task.task_id} with data: {data}")

            # Store original values for logging
            original_values = {
                'container': task.container_name,
                'action': task.action,
                'cycle': task.cycle
            }

            # Update basic fields
            self._update_basic_task_fields(task, data)

            # Update schedule details
            if 'schedule_details' in data:
                self._update_task_schedule_details(task, data['schedule_details'])

            # Update timezone if provided
            if 'timezone_str' in data:
                task.timezone_str = data['timezone_str']

            # Validate updated task
            if not task.is_valid():
                return EditTaskResult(
                    success=False,
                    error="Updated task data is invalid"
                )

            # Recalculate next run time
            task.calculate_next_run()

            # Check if task should be deactivated (once tasks in the past)
            from services.scheduling.scheduler import CYCLE_ONCE
            if task.cycle == CYCLE_ONCE and task.next_run_ts and task.next_run_ts < time.time():
                task.is_active = False
                self.logger.info(f"Task {task.task_id} was automatically deactivated because the execution time is in the past.")

            # Save updated task
            if self._update_task_via_scheduler(task):
                self.logger.info(f"Task {task.task_id} successfully updated via Web UI")

                # Log user action
                self._log_task_update(task, original_values)

                return EditTaskResult(
                    success=True,
                    task_data=task.to_dict(),
                    message=f"Task {task.task_id} updated successfully"
                )
            else:
                return EditTaskResult(
                    success=False,
                    error="Failed to save updated task"
                )

        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (scheduler service unavailable)
            self.logger.error(f"Service dependency error updating task with data: {e}", exc_info=True)
            return EditTaskResult(
                success=False,
                error=f"Service error updating task: {str(e)}"
            )
        except (ValueError, TypeError, KeyError) as e:
            # Data errors (task data validation, dict access)
            self.logger.error(f"Data error updating task with data: {e}", exc_info=True)
            return EditTaskResult(
                success=False,
                error=f"Data error updating task: {str(e)}"
            )

    def _update_basic_task_fields(self, task, data: Dict[str, Any]):
        """Update basic task fields from data."""
        if 'container' in data:
            task.container_name = data['container']
        if 'action' in data:
            task.action = data['action']
        if 'cycle' in data:
            task.cycle = data['cycle']
        if 'is_active' in data:
            task.is_active = bool(data['is_active'])

    def _update_task_schedule_details(self, task, schedule_details: Dict[str, Any]):
        """Update task schedule details based on cycle type."""
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

    def _log_task_update(self, task, original_values: Dict[str, str]):
        """Log task update for audit trail."""
        try:
            from services.infrastructure.action_logger import log_user_action
            log_user_action(
                action="SCHEDULE_UPDATE",
                target=f"{task.container_name} ({task.action})",
                source="Web UI",
                details=f"Task ID: {task.task_id}, Cycle: {task.cycle}, Updated from: {original_values['container']} ({original_values['action']}, {original_values['cycle']})"
            )
        except (ImportError, AttributeError, RuntimeError) as e:
            # Service dependency errors (action logger unavailable)
            self.logger.error(f"Service dependency error logging task update: {e}", exc_info=True)
        except (ValueError, KeyError, TypeError) as e:
            # Data errors (task data access, dict operations)
            self.logger.error(f"Data error logging task update: {e}", exc_info=True)

    def _get_timezone_abbreviation(self, timezone_str: str) -> str:
        """Get timezone abbreviation for display."""
        try:
            import pytz
            tz = pytz.timezone(timezone_str)
            now = datetime.now(tz)
            return now.strftime("%Z")  # Returns abbreviation like CEST
        except (ImportError, AttributeError) as e:
            # Import errors (pytz unavailable)
            self.logger.error(f"Import error getting timezone abbreviation: {e}", exc_info=True)
            return timezone_str  # Fallback to timezone identifier
        except (ValueError, TypeError) as e:
            # Data errors (invalid timezone string)
            self.logger.error(f"Data error getting timezone abbreviation: {e}", exc_info=True)
            return timezone_str  # Fallback to timezone identifier


# Singleton instance
_task_management_service = None


def get_task_management_service() -> TaskManagementService:
    """Get the singleton TaskManagementService instance."""
    global _task_management_service
    if _task_management_service is None:
        _task_management_service = TaskManagementService()
    return _task_management_service
