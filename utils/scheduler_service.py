# -*- coding: utf-8 -*-
import asyncio
import logging
import time
import sys
from datetime import datetime, timedelta
import threading
from typing import Dict, List, Optional, Any
import traceback
import os

from utils.scheduler import (
    load_tasks, 
    update_task, 
    execute_task, 
    ScheduledTask,
    find_task_by_id
)
from utils.logging_utils import setup_logger

# Logger for Scheduler Service
logger = setup_logger('ddc.scheduler_service', level=logging.DEBUG)

# CPU-OPTIMIZED: Increased check interval from 60 to 120 seconds (50% CPU reduction)
# Task scheduling doesn't need to be checked every minute for most use cases
CHECK_INTERVAL = int(os.environ.get('DDC_SCHEDULER_CHECK_INTERVAL', '120'))  # 2 minutes default

# CPU-OPTIMIZED: Batch processing settings
MAX_CONCURRENT_TASKS = int(os.environ.get('DDC_MAX_CONCURRENT_TASKS', '3'))  # Limit concurrent task execution
TASK_BATCH_SIZE = int(os.environ.get('DDC_TASK_BATCH_SIZE', '5'))  # Process tasks in batches

# Global bot reference for system tasks
_bot_instance = None

def set_bot_instance(bot):
    """Set the bot instance for use in system tasks."""
    global _bot_instance
    _bot_instance = bot

def get_bot_instance():
    """Get the bot instance for system tasks."""
    return _bot_instance

class SchedulerService:
    """Service for managing and executing scheduled tasks with CPU optimization."""
    
    def __init__(self):
        """Initializes the Scheduler Service with performance optimizations."""
        self.running = False
        self.thread = None
        self.event_loop = None
        self.last_check_time = None
        self.active_tasks = set()  # Track active tasks to prevent overload
        self.task_execution_stats = {
            'total_executed': 0,
            'total_skipped': 0,
            'last_batch_size': 0,
            'avg_execution_time': 0.0
        }

    def start(self):
        """Starts the Scheduler Service as a background process."""
        if self.running:
            logger.warning("Scheduler Service is already running.")
            return False
        
        self.running = True
        self.thread = threading.Thread(target=self._run_service)
        self.thread.daemon = True  # Daemon thread terminates when the main program ends
        self.thread.start()
        logger.info(f"CPU-optimized Scheduler Service started (check interval: {CHECK_INTERVAL}s, max concurrent: {MAX_CONCURRENT_TASKS})")
        return True
    
    def stop(self):
        """Stops the Scheduler Service."""
        if not self.running:
            logger.warning("Scheduler Service is not running.")
            return False
        
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)  # Wait maximum 2 seconds for thread termination
            self.thread = None
        
        # Log final statistics
        stats = self.task_execution_stats
        logger.info(f"Scheduler Service stopped. Stats: {stats['total_executed']} executed, {stats['total_skipped']} skipped")
        return True
    
    def _run_service(self):
        """Runs the service loop in the background."""
        try:
            # Check if we're already in an event loop
            try:
                loop = asyncio.get_running_loop()
                logger.error("Cannot start scheduler service in existing event loop!")
                return
            except RuntimeError:
                # No running loop - this is what we want
                pass
            
            # Create a new event loop for this thread
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            # Try to use uvloop for better performance
            if sys.platform != 'win32':
                try:
                    import uvloop
                    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
                    logger.info("Scheduler using uvloop for better performance")
                except ImportError:
                    pass
            
            try:
                # Start the loop
                self.event_loop.run_until_complete(self._service_loop())
            except Exception as e:
                logger.error(f"Error in Scheduler Service loop: {e}")
                logger.error(traceback.format_exc())
            finally:
                # Clean up tasks
                try:
                    pending = asyncio.all_tasks(self.event_loop)
                    if pending:
                        logger.info(f"Cancelling {len(pending)} pending scheduler tasks")
                        for task in pending:
                            task.cancel()
                        self.event_loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                except Exception as e:
                    logger.error(f"Error cleaning up scheduler tasks: {e}")
                
                # Close the loop
                try:
                    self.event_loop.close()
                except Exception as e:
                    logger.error(f"Error closing scheduler event loop: {e}")
                
                self.event_loop = None
                asyncio.set_event_loop(None)
                self.running = False
                logger.info("Scheduler Service loop ended cleanly.")
                
        except Exception as e:
            logger.error(f"Critical error in scheduler service: {e}", exc_info=True)
            self.running = False
    
    async def _service_loop(self):
        """Main loop of the service with CPU optimization."""
        logger.info(f"CPU-optimized Scheduler Service loop started (interval: {CHECK_INTERVAL}s)")
        
        while self.running:
            try:
                start_time = time.time()
                await self._check_and_execute_tasks()
                execution_time = time.time() - start_time
                
                # Update statistics
                self.task_execution_stats['avg_execution_time'] = (
                    (self.task_execution_stats['avg_execution_time'] * 0.9) + (execution_time * 0.1)
                )
                
                self.last_check_time = time.time()
                
                # CPU-OPTIMIZED: Dynamic sleep interval based on load
                sleep_interval = self._calculate_optimal_sleep_interval(execution_time)
                logger.debug(f"Scheduler check completed in {execution_time:.2f}s, sleeping for {sleep_interval}s")
                
                await asyncio.sleep(sleep_interval)
            except Exception as e:
                logger.error(f"Error checking or executing tasks: {e}")
                logger.error(traceback.format_exc())
                # CPU-OPTIMIZED: Longer sleep on error to prevent error loops
                await asyncio.sleep(min(CHECK_INTERVAL * 2, 300))  # Max 5 minutes
    
    def _calculate_optimal_sleep_interval(self, last_execution_time: float) -> int:
        """
        Calculates optimal sleep interval based on system load and execution time.
        
        Args:
            last_execution_time: Time taken for last task check cycle
            
        Returns:
            Optimal sleep interval in seconds
        """
        base_interval = CHECK_INTERVAL
        
        # If execution took a long time, increase sleep interval
        if last_execution_time > 5.0:  # If check took more than 5 seconds
            return min(base_interval * 2, 300)  # Double interval, max 5 minutes
        
        # If we have many active tasks, increase interval
        if len(self.active_tasks) >= MAX_CONCURRENT_TASKS:
            return min(base_interval + 30, 180)  # Add 30s, max 3 minutes
        
        return base_interval
    
    async def _check_system_tasks(self):
        """Check and execute system tasks like donation messages."""
        try:
            # Check for donation messages (every 2 minutes - more efficient than 1 minute)
            await self._check_donation_task()
        except Exception as e:
            logger.error(f"Error in system tasks check: {e}")
    
    async def _check_donation_task(self):
        """Check if donation message should be sent."""
        try:
            # Import here to avoid circular imports
            from utils.donation_manager import get_donation_manager
            
            donation_manager = get_donation_manager()
            if donation_manager.should_send_donation_message():
                bot = get_bot_instance()
                if bot:
                    logger.info("Scheduler: Sending donation message at configured time (13:37)")
                    result = await donation_manager.send_donation_message(bot)
                    if result["success"]:
                        logger.info(f"Scheduler: Donation message sent successfully: {result['message']}")
                    else:
                        logger.debug(f"Scheduler: No donation message sent: {result['message']}")
                else:
                    logger.warning("Scheduler: Bot instance not available for donation message")
        except ImportError:
            # Donation manager not available
            pass
        except Exception as e:
            logger.debug(f"Error checking donation task: {e}")
    
    async def _check_and_execute_tasks(self):
        """Checks all tasks and executes those that are due with CPU optimization."""
        try:
            # Check system tasks (like donations) first
            await self._check_system_tasks()
            
            tasks = load_tasks()
            if not tasks:
                return
            
            current_time = datetime.now()
            due_tasks = []
            
            # First pass: Find all due tasks
            for task in tasks:
                if not task.is_active:  # Fixed: was task.enabled
                    continue
                
                if task.next_run_ts:
                    task_time = datetime.fromtimestamp(task.next_run_ts)
                    
                    # Create a time window: task is "due" if it's within CHECK_INTERVAL/2 of its scheduled time
                    # This ensures we don't miss tasks between check intervals
                    time_window = timedelta(seconds=CHECK_INTERVAL / 2)  # 60 seconds for 2-minute checks
                    
                    # Task is due if it's scheduled before now but within the time window
                    # This prevents tasks from running too early or being missed
                    if task_time <= current_time < (task_time + time_window):
                        # Skip if task is already running
                        if task.task_id in self.active_tasks:
                            logger.debug(f"Task {task.container_name} (ID: {task.task_id}) is already running, skipping")
                            self.task_execution_stats['total_skipped'] += 1
                            continue
                        
                        due_tasks.append(task)
                        logger.debug(f"Task {task.task_id} is due (scheduled: {task_time}, window: ±{time_window})")
            
            if not due_tasks:
                logger.debug("No tasks due for execution")
                return
            
            # CPU-OPTIMIZED: Process tasks in batches to prevent system overload
            for i in range(0, len(due_tasks), TASK_BATCH_SIZE):
                batch = due_tasks[i:i + TASK_BATCH_SIZE]
                
                # Check if we have room for more concurrent tasks
                available_slots = MAX_CONCURRENT_TASKS - len(self.active_tasks)
                if available_slots <= 0:
                    logger.info(f"Maximum concurrent tasks ({MAX_CONCURRENT_TASKS}) reached, deferring {len(due_tasks) - i} tasks")
                    break
                
                # Execute batch with concurrency limit
                batch_to_execute = batch[:available_slots]
                self.task_execution_stats['last_batch_size'] = len(batch_to_execute)
                
                logger.info(f"Executing batch of {len(batch_to_execute)} tasks (active: {len(self.active_tasks)})")
                
                # Execute tasks concurrently within the batch
                await self._execute_task_batch(batch_to_execute)
                
                # Small delay between batches to prevent system overload
                if i + TASK_BATCH_SIZE < len(due_tasks):
                    await asyncio.sleep(1.0)
            
        except Exception as e:
            logger.error(f"Error in _check_and_execute_tasks: {e}")
            logger.error(traceback.format_exc())
    
    async def _execute_task_batch(self, tasks: List[ScheduledTask]):
        """
        Executes a batch of tasks concurrently with proper resource management.
        
        Args:
            tasks: List of tasks to execute
        """
        async def execute_single_task(task: ScheduledTask):
            """Execute a single task with proper error handling and tracking."""
            task_start_time = time.time()
            self.active_tasks.add(task.task_id)
            
            try:
                logger.info(f"Executing task: {task.container_name} (ID: {task.task_id})")
                await execute_task(task)
                
                # Update task's next run time after successful execution
                try:
                    update_task(task)  # Use the imported function instead of task.update_next_run()
                except Exception as update_error:
                    logger.warning(f"Failed to update next run time for task {task.task_id}: {update_error}")
                
                self.task_execution_stats['total_executed'] += 1
                execution_time = time.time() - task_start_time
                logger.info(f"Task {task.container_name} completed successfully in {execution_time:.2f}s")
                
            except Exception as e:
                logger.error(f"Error executing task {task.container_name} (ID: {task.task_id}): {e}")
                logger.error(traceback.format_exc())
            finally:
                self.active_tasks.discard(task.task_id)
        
        # Execute all tasks in the batch concurrently
        if tasks:
            await asyncio.gather(*[execute_single_task(task) for task in tasks], return_exceptions=True)
    
    def get_service_stats(self) -> Dict[str, Any]:
        """
        Gets current service statistics for monitoring.
        
        Returns:
            Dictionary with service statistics
        """
        return {
            'running': self.running,
            'active_tasks_count': len(self.active_tasks),
            'last_check_time': self.last_check_time,
            'check_interval': CHECK_INTERVAL,
            'max_concurrent_tasks': MAX_CONCURRENT_TASKS,
            'task_batch_size': TASK_BATCH_SIZE,
            **self.task_execution_stats
        }

# Global service instance
_scheduler_service = SchedulerService()

def start_scheduler_service() -> bool:
    """
    Starts the global scheduler service.
    
    Returns:
        True if started successfully, False otherwise
    """
    return _scheduler_service.start()

def stop_scheduler_service() -> bool:
    """
    Stops the global scheduler service.
    
    Returns:
        True if stopped successfully, False otherwise
    """
    return _scheduler_service.stop()

def get_scheduler_service() -> SchedulerService:
    """
    Gets the global scheduler service instance.
    
    Returns:
        The global SchedulerService instance
    """
    return _scheduler_service

def get_scheduler_stats() -> Dict[str, Any]:
    """
    Gets current scheduler service statistics.
    
    Returns:
        Dictionary with scheduler statistics
    """
    return _scheduler_service.get_service_stats() 