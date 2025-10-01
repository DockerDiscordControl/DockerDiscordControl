# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC)                                                  #
# https://ddc.bot                                                              #
# Copyright (c) 2025 MAX                                                  #
# Licensed under the MIT License                                               #
# ============================================================================ #

from flask import Blueprint, request, jsonify, current_app, render_template

tasks_bp = Blueprint('tasks_bp', __name__, url_prefix='/tasks')


@tasks_bp.route('/add', methods=['POST'])
def add_task():
    """Adds a new task using TaskManagementService."""
    try:
        # Get request JSON data
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Validate required fields
        if not data.get('cycle'):
            return jsonify({"error": "Cycle is required"}), 400
        if not data.get('container'):
            return jsonify({"error": "Container is required"}), 400
        if not data.get('action'):
            return jsonify({"error": "Action is required"}), 400

        # Use TaskManagementService for business logic
        from services.web.task_management_service import get_task_management_service, AddTaskRequest

        service = get_task_management_service()
        request_obj = AddTaskRequest(
            container=data.get('container'),
            action=data.get('action'),
            cycle=data.get('cycle'),
            schedule_details=data.get('schedule_details', {}),
            timezone_str=data.get('timezone_str'),
            status=data.get('status', 'pending'),
            description=data.get('description')
        )

        # Add task through service
        result = service.add_task(request_obj)

        if result.success:
            return jsonify({
                "message": result.message,
                "task": result.task_data
            }), 201
        else:
            return jsonify({"error": result.error}), 400

    except Exception as e:
        current_app.logger.error(f"Error in add_task route: {e}", exc_info=True)
        return jsonify({"error": "Internal error handling add_task request. Please check the logs for details."}), 500

@tasks_bp.route('/list', methods=['GET'])
def list_tasks():
    """Returns the list of saved tasks using TaskManagementService."""
    try:
        # Use TaskManagementService for business logic
        from services.web.task_management_service import get_task_management_service, ListTasksRequest

        service = get_task_management_service()
        request_obj = ListTasksRequest()

        # Get tasks through service
        result = service.list_tasks(request_obj)

        if result.success:
            return jsonify(result.tasks), 200
        else:
            current_app.logger.error(f"Failed to list tasks: {result.error}")
            return jsonify({"error": result.error}), 500

    except Exception as e:
        current_app.logger.error(f"Error in list_tasks route: {e}", exc_info=True)
        return jsonify({"error": "Internal error listing tasks. Please check the logs for details."}), 500

@tasks_bp.route('/form', methods=['GET'])
def show_task_form():
    """Shows the form for creating tasks using TaskManagementService."""
    try:
        # Use TaskManagementService for business logic
        from services.web.task_management_service import get_task_management_service, TaskFormRequest

        service = get_task_management_service()
        request_obj = TaskFormRequest()

        # Get form data through service
        result = service.get_task_form_data(request_obj)

        if result.success:
            return render_template('tasks/form.html', **result.form_data)
        else:
            current_app.logger.error(f"Failed to load task form data: {result.error}")
            return render_template('tasks/form.html',
                                 active_containers=[],
                                 timezone_str='Europe/Berlin',
                                 timezone_name='CEST',
                                 error_message=result.error)

    except Exception as e:
        current_app.logger.error(f"Error in show_task_form route: {e}", exc_info=True)
        return render_template('tasks/form.html',
                             active_containers=[],
                             timezone_str='Europe/Berlin',
                             timezone_name='CEST',
                             error_message="Error loading form data")


@tasks_bp.route('/update_status', methods=['POST'])
def update_task_status():
    """Updates the active status of a task using TaskManagementService."""
    try:
        if not request.is_json:
            return jsonify({"success": False, "error": "Request must be JSON"}), 400

        data = request.get_json()
        task_id = data.get('task_id')
        is_active = data.get('is_active')

        if not task_id:
            return jsonify({"success": False, "error": "Missing task_id"}), 400

        if is_active is None:  # Explicit check for None, since is_active can be a boolean
            return jsonify({"success": False, "error": "Missing is_active flag"}), 400

        # Use TaskManagementService for business logic
        from services.web.task_management_service import get_task_management_service, UpdateTaskStatusRequest

        service = get_task_management_service()
        request_obj = UpdateTaskStatusRequest(
            task_id=task_id,
            is_active=bool(is_active)
        )

        # Update task status through service
        result = service.update_task_status(request_obj)

        if result.success:
            return jsonify({
                "success": True,
                "message": result.message,
                "task": result.task_data
            })
        else:
            status_code = 404 if "not found" in result.error.lower() else 400
            return jsonify({"success": False, "error": result.error}), status_code

    except Exception as e:
        current_app.logger.error(f"Error in update_task_status route: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Internal error updating task status"}), 500 

@tasks_bp.route('/delete/<task_id>', methods=['DELETE'])
def delete_task_route(task_id):
    """Deletes a specific task by ID using TaskManagementService."""
    try:
        if not task_id:
            return jsonify({"success": False, "error": "Missing task_id"}), 400

        # Use TaskManagementService for business logic
        from services.web.task_management_service import get_task_management_service, DeleteTaskRequest

        service = get_task_management_service()
        request_obj = DeleteTaskRequest(task_id=task_id)

        # Delete task through service
        result = service.delete_task(request_obj)

        if result.success:
            return jsonify({
                "success": True,
                "message": result.message
            }), 200
        else:
            status_code = 404 if "not found" in result.error.lower() else 500
            return jsonify({"success": False, "error": result.error}), status_code

    except Exception as e:
        current_app.logger.error(f"Error in delete_task_route: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Internal error deleting task"}), 500

@tasks_bp.route('/edit/<task_id>', methods=['GET', 'PUT'])
def edit_task_route(task_id):
    """Gets or updates a specific task by ID using TaskManagementService."""
    try:
        if not task_id:
            return jsonify({"success": False, "error": "Missing task_id"}), 400

        # Use TaskManagementService for business logic
        from services.web.task_management_service import get_task_management_service, EditTaskRequest

        service = get_task_management_service()

        if request.method == 'GET':
            # Get task for editing
            request_obj = EditTaskRequest(
                task_id=task_id,
                operation='get'
            )

            result = service.edit_task(request_obj)

            if result.success:
                return jsonify({
                    "success": True,
                    "task": result.task_data
                }), 200
            else:
                status_code = 404 if "not found" in result.error.lower() else 500
                return jsonify({"success": False, "error": result.error}), status_code

        elif request.method == 'PUT':
            # Update task
            data = request.get_json()
            if not data:
                return jsonify({"success": False, "error": "No data provided"}), 400

            request_obj = EditTaskRequest(
                task_id=task_id,
                operation='update',
                data=data,
                timezone_str=data.get('timezone_str')
            )

            result = service.edit_task(request_obj)

            if result.success:
                return jsonify({
                    "success": True,
                    "message": result.message,
                    "task": result.task_data
                }), 200
            else:
                status_code = 404 if "not found" in result.error.lower() else 400
                return jsonify({"success": False, "error": result.error}), status_code

    except Exception as e:
        current_app.logger.error(f"Error in edit_task_route: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Internal error editing task"}), 500 