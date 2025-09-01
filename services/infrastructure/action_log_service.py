# -*- coding: utf-8 -*-
"""
Action Log Service - Clean service architecture for user action logging
"""

import os
import json
import pytz
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from utils.logging_utils import get_module_logger

logger = get_module_logger('action_log_service')

@dataclass(frozen=True)
class ActionLogEntry:
    """Immutable action log entry data structure."""
    timestamp: str  # ISO format
    timestamp_unix: int
    timezone: str
    action: str
    target: str
    user: str
    source: str
    details: str
    entry_id: str
    migrated: bool = False
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionLogEntry':
        """Create ActionLogEntry from dictionary data."""
        return cls(
            timestamp=str(data.get('timestamp', '')),
            timestamp_unix=int(data.get('timestamp_unix', 0)),
            timezone=str(data.get('timezone', 'UTC')),
            action=str(data.get('action', '')),
            target=str(data.get('target', '')),
            user=str(data.get('user', '')),
            source=str(data.get('source', '')),
            details=str(data.get('details', '')),
            entry_id=str(data.get('id', data.get('entry_id', ''))),
            migrated=bool(data.get('migrated', False))
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert ActionLogEntry to dictionary for storage."""
        return {
            'timestamp': self.timestamp,
            'timestamp_unix': self.timestamp_unix,
            'timezone': self.timezone,
            'action': self.action,
            'target': self.target,
            'user': self.user,
            'source': self.source,
            'details': self.details,
            'id': self.entry_id,
            'migrated': self.migrated
        }

@dataclass(frozen=True)
class ServiceResult:
    """Standard service result wrapper."""
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None

class ActionLogService:
    """Clean service for managing user action logs with proper separation of concerns."""
    
    def __init__(self, logs_dir: Optional[str] = None):
        """Initialize the action log service.
        
        Args:
            logs_dir: Directory to store log files. Defaults to logs/
        """
        if logs_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            logs_dir = os.path.join(base_dir, "logs")
        
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        self.json_log_file = self.logs_dir / 'user_actions.json'
        self.text_log_file = self.logs_dir / 'user_actions.log'
        
        logger.info(f"Action log service initialized: {self.logs_dir}")
    
    def log_action(self, action: str, target: str, user: str = "System", 
                   source: str = "Unknown", details: str = "-") -> ServiceResult:
        """Log a user action.
        
        Args:
            action: The action being performed (e.g., START, STOP, RESTART)
            target: The target of the action (e.g., container name)  
            user: The user who initiated the action
            source: Source of the action (e.g., Web UI, Discord Command)
            details: Additional details about the action
            
        Returns:
            ServiceResult indicating success or failure
        """
        try:
            # Get timezone
            timezone_str, tz = self._get_timezone()
            now = datetime.now(tz)
            
            # Create log entry
            entry_id = f"{int(now.timestamp())}-{hash(f'{action}{target}{user}{source}') % 10000:04d}"
            
            entry = ActionLogEntry(
                timestamp=now.isoformat(),
                timestamp_unix=int(now.timestamp()),
                timezone=timezone_str,
                action=action,
                target=target,
                user=user,
                source=source,
                details=details,
                entry_id=entry_id
            )
            
            # Save to JSON format
            json_result = self._save_to_json(entry)
            if not json_result.success:
                logger.warning(f"Failed to save to JSON: {json_result.error}")
            
            # Save to text format (for backward compatibility)
            text_result = self._save_to_text(entry)
            if not text_result.success:
                logger.warning(f"Failed to save to text: {text_result.error}")
            
            # Success if at least one format worked
            if json_result.success or text_result.success:
                return ServiceResult(success=True, data=entry)
            else:
                return ServiceResult(success=False, error="Failed to save to both JSON and text formats")
                
        except Exception as e:
            error_msg = f"Error logging action {action} for {target}: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def get_logs(self, limit: int = 500, format: str = "json") -> ServiceResult:
        """Get action logs.
        
        Args:
            limit: Maximum number of entries to return
            format: "json" or "text"
            
        Returns:
            ServiceResult with log data
        """
        try:
            if format == "json":
                return self._get_logs_json(limit)
            else:
                return self._get_logs_text(limit)
                
        except Exception as e:
            error_msg = f"Error retrieving logs: {e}"
            logger.error(error_msg)
            return ServiceResult(success=False, error=error_msg)
    
    def _save_to_json(self, entry: ActionLogEntry) -> ServiceResult:
        """Save log entry to JSON file."""
        try:
            # Read existing data
            actions = []
            if self.json_log_file.exists():
                try:
                    with open(self.json_log_file, 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            actions = json.loads(content)
                except (json.JSONDecodeError, IOError):
                    actions = []
            
            # Add new entry
            actions.append(entry.to_dict())
            
            # Keep only last 10000 entries
            if len(actions) > 10000:
                actions = actions[-10000:]
            
            # Atomic write
            temp_file = self.json_log_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(actions, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.json_log_file)
            
            return ServiceResult(success=True)
            
        except Exception as e:
            return ServiceResult(success=False, error=str(e))
    
    def _save_to_text(self, entry: ActionLogEntry) -> ServiceResult:
        """Save log entry to text file for backward compatibility."""
        try:
            # Format for text log
            text_line = f"{entry.action}|{entry.target}|{entry.user}|{entry.source}|{entry.details}\n"
            
            # Append to text file
            with open(self.text_log_file, 'a', encoding='utf-8') as f:
                f.write(text_line)
            
            return ServiceResult(success=True)
            
        except Exception as e:
            return ServiceResult(success=False, error=str(e))
    
    def _get_logs_json(self, limit: int) -> ServiceResult:
        """Get logs from JSON file."""
        try:
            if not self.json_log_file.exists():
                return ServiceResult(success=True, data=[])
            
            with open(self.json_log_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return ServiceResult(success=True, data=[])
                
                actions = json.loads(content)
                
                # Sort by timestamp (newest first) and limit results
                actions.sort(key=lambda x: x.get('timestamp_unix', 0), reverse=True)
                entries = [ActionLogEntry.from_dict(action) for action in actions[:limit]]
                
                return ServiceResult(success=True, data=entries)
                
        except Exception as e:
            return ServiceResult(success=False, error=str(e))
    
    def _get_logs_text(self, limit: int) -> ServiceResult:
        """Get logs as formatted text."""
        try:
            # First try JSON format
            json_result = self._get_logs_json(limit)
            if json_result.success and json_result.data:
                lines = []
                for entry in json_result.data:
                    # Convert ISO timestamp back to readable format
                    try:
                        dt = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
                        timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S %Z')
                    except:
                        timestamp_str = entry.timestamp
                    
                    line = f"{timestamp_str} - {entry.action}|{entry.target}|{entry.user}|{entry.source}|{entry.details}"
                    lines.append(line)
                
                return ServiceResult(success=True, data='\n'.join(lines))
            
            # Fallback to text file
            if self.text_log_file.exists():
                with open(self.text_log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    lines = lines[-limit:] if len(lines) > limit else lines
                    return ServiceResult(success=True, data=''.join(lines).strip())
            
            return ServiceResult(success=True, data="No action logs available")
            
        except Exception as e:
            return ServiceResult(success=False, error=str(e))
    
    def _get_timezone(self) -> tuple[str, pytz.BaseTzInfo]:
        """Get timezone configuration."""
        try:
            from utils.config_loader import load_config
            config = load_config()
            timezone_str = config.get('timezone', 'Europe/Berlin')
            tz = pytz.timezone(timezone_str)
            return timezone_str, tz
        except Exception:
            return 'UTC', pytz.UTC

# Singleton instance
_action_log_service = None

def get_action_log_service() -> ActionLogService:
    """Get the global action log service instance.
    
    Returns:
        ActionLogService instance
    """
    global _action_log_service
    if _action_log_service is None:
        _action_log_service = ActionLogService()
    return _action_log_service