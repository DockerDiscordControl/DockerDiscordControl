#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DockerDiscordControl (DDC) Heartbeat Monitor
============================================

Standalone application to monitor DDC bot heartbeats and send alerts.

Features:
- Cross-platform (Windows, macOS, Linux)
- JSON configuration file
- Automatic recovery detection
- Comprehensive logging
- Graceful shutdown handling

Requirements:
- Python 3.7+
- discord.py

Installation:
1. pip install discord.py
2. Configure config.json
3. Run: python ddc_heartbeat_monitor.py

Author: MAX
Website: https://ddc.bot
License: MIT
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

try:
    import discord
    from discord.ext import tasks
except ImportError:
    print("❌ Error: This application requires discord.py")
    print("📦 Install it with: pip install discord.py")
    sys.exit(1)

# Version info
VERSION = "1.0.0"
APP_NAME = "DDC Heartbeat Monitor"

class ConfigManager:
    """Manages configuration loading and validation"""
    
    DEFAULT_CONFIG = {
        "monitor": {
            "bot_token": "",
            "ddc_bot_user_id": 0,
            "heartbeat_channel_id": 0,
            "alert_channel_ids": [],
            "heartbeat_timeout_seconds": 300,
            "check_interval_seconds": 30
        },
        "logging": {
            "level": "INFO",
            "file_enabled": True,
            "file_name": "ddc_heartbeat_monitor.log",
            "console_enabled": True
        },
        "alerts": {
            "startup_notification": True,
            "recovery_notification": True,
            "include_timestamp": True,
            "mention_roles": []
        }
    }
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config = {}
        
    def load_config(self) -> Dict:
        """Load configuration from JSON file"""
        if not self.config_path.exists():
            print(f"⚠️  Configuration file '{self.config_path}' not found!")
            print("📝 Creating default configuration...")
            self.create_default_config()
            print(f"✅ Default config created at '{self.config_path}'")
            print("🔧 Please edit the configuration file and restart the application.")
            sys.exit(0)
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
            
            # Validate and merge with defaults
            self.config = self._merge_with_defaults(self.config)
            self._validate_config()
            
            return self.config
            
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing configuration file: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Error loading configuration: {e}")
            sys.exit(1)
    
    def create_default_config(self):
        """Create a default configuration file"""
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.DEFAULT_CONFIG, f, indent=2)
    
    def _merge_with_defaults(self, config: Dict) -> Dict:
        """Merge loaded config with defaults"""
        def merge_dict(default: Dict, loaded: Dict) -> Dict:
            result = default.copy()
            for key, value in loaded.items():
                if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                    result[key] = merge_dict(result[key], value)
                else:
                    result[key] = value
            return result
        
        return merge_dict(self.DEFAULT_CONFIG, config)
    
    def _validate_config(self):
        """Validate configuration values"""
        monitor = self.config['monitor']
        
        # Required fields
        if not monitor['bot_token']:
            raise ValueError("Bot token is required in monitor.bot_token")
        
        if not monitor['ddc_bot_user_id']:
            raise ValueError("DDC bot user ID is required in monitor.ddc_bot_user_id")
        
        if not monitor['heartbeat_channel_id']:
            raise ValueError("Heartbeat channel ID is required in monitor.heartbeat_channel_id")
        
        if not monitor['alert_channel_ids']:
            raise ValueError("At least one alert channel ID is required in monitor.alert_channel_ids")
        
        # Validate numeric values
        if monitor['heartbeat_timeout_seconds'] < 60:
            raise ValueError("Heartbeat timeout must be at least 60 seconds")
        
        if monitor['check_interval_seconds'] < 10:
            raise ValueError("Check interval must be at least 10 seconds")

class HeartbeatMonitor(discord.Client):
    """Main heartbeat monitoring client"""
    
    def __init__(self, config: Dict):
        # Setup intents
        # RAM-OPTIMIZED: Minimal intents for heartbeat monitor
        intents = discord.Intents.none()
        intents.guilds = True            # Required for guild access
        intents.message_content = True   # Required for message content
        super().__init__(intents=intents)
        
        # Store configuration
        self.config = config
        self.monitor_config = config['monitor']
        self.alert_config = config['alerts']
        
        # State tracking
        self.last_heartbeat_time: Optional[datetime] = None
        self.alert_sent = False
        self.start_time = datetime.now(timezone.utc)
        self.shutdown_requested = False
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Start monitoring task
        self.heartbeat_check.change_interval(seconds=self.monitor_config['check_interval_seconds'])
        self.heartbeat_check.start()
    
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        log_config = self.config['logging']
        
        # Create logger
        logger = logging.getLogger('ddc_monitor')
        logger.setLevel(getattr(logging, log_config['level'].upper()))
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Console handler
        if log_config['console_enabled']:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
        
        # File handler
        if log_config['file_enabled']:
            file_handler = logging.FileHandler(
                log_config['file_name'], 
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        
        return logger
    
    async def on_ready(self):
        """Called when the client is ready"""
        self.logger.info(f"🤖 {APP_NAME} v{VERSION} started")
        self.logger.info(f"👤 Logged in as {self.user} (ID: {self.user.id})")
        self.logger.info(f"🎯 Monitoring DDC bot ID: {self.monitor_config['ddc_bot_user_id']}")
        self.logger.info(f"📺 Watching channel: {self.monitor_config['heartbeat_channel_id']}")
        self.logger.info(f"🚨 Alert channels: {self.monitor_config['alert_channel_ids']}")
        self.logger.info(f"⏰ Heartbeat timeout: {self.monitor_config['heartbeat_timeout_seconds']}s")
        self.logger.info(f"🔄 Check interval: {self.monitor_config['check_interval_seconds']}s")
        
        # Send startup notification
        if self.alert_config['startup_notification']:
            await self._send_alert(
                title="🔄 DDC Heartbeat Monitor Started",
                description=(
                    f"Heartbeat monitoring is now active.\n\n"
                    f"**Configuration:**\n"
                    f"• Monitoring: <@{self.monitor_config['ddc_bot_user_id']}>\n"
                    f"• Timeout: {self.monitor_config['heartbeat_timeout_seconds']} seconds\n"
                    f"• Check interval: {self.monitor_config['check_interval_seconds']} seconds\n"
                    f"• Version: {VERSION}"
                ),
                color=discord.Color.blue(),
                is_startup=True
            )
    
    async def on_message(self, message):
        """Process incoming messages for heartbeat detection"""
        # Check if message is from DDC bot and in heartbeat channel
        if (message.author.id == self.monitor_config['ddc_bot_user_id'] and 
            message.channel.id == self.monitor_config['heartbeat_channel_id']):
            
            # Check for heartbeat indicators
            heartbeat_indicators = ["❤️", "💓", "heartbeat", "alive", "ping"]
            if any(indicator in message.content.lower() for indicator in heartbeat_indicators):
                
                # Update last heartbeat time
                self.last_heartbeat_time = datetime.now(timezone.utc)
                self.logger.debug(f"💓 Heartbeat detected at {self.last_heartbeat_time.isoformat()}")
                
                # Send recovery notification if we previously sent an alert
                if self.alert_sent:
                    self.alert_sent = False
                    self.logger.info("✅ Heartbeat recovered after alert")
                    
                    if self.alert_config['recovery_notification']:
                        await self._send_alert(
                            title="✅ DDC Heartbeat Recovered",
                            description=(
                                f"Heartbeat from DDC bot <@{self.monitor_config['ddc_bot_user_id']}> "
                                f"has been restored.\n\n"
                                f"Monitoring continues normally."
                            ),
                            color=discord.Color.green()
                        )
    
    @tasks.loop()
    async def heartbeat_check(self):
        """Periodic check for missing heartbeats"""
        if self.shutdown_requested:
            return
        
        now = datetime.now(timezone.utc)
        timeout_seconds = self.monitor_config['heartbeat_timeout_seconds']
        
        if not self.last_heartbeat_time:
            # No heartbeat received since startup
            startup_seconds = (now - self.start_time).total_seconds()
            if startup_seconds > timeout_seconds and not self.alert_sent:
                self.logger.warning(f"⚠️  No initial heartbeat after {startup_seconds:.1f}s")
                await self._send_missing_heartbeat_alert(startup_seconds, is_initial=True)
        else:
            # Check time since last heartbeat
            elapsed_seconds = (now - self.last_heartbeat_time).total_seconds()
            if elapsed_seconds > timeout_seconds and not self.alert_sent:
                self.logger.warning(f"⚠️  Heartbeat missing for {elapsed_seconds:.1f}s")
                await self._send_missing_heartbeat_alert(elapsed_seconds)
    
    async def _send_missing_heartbeat_alert(self, elapsed_seconds: float, is_initial: bool = False):
        """Send alert for missing heartbeat"""
        if self.alert_sent:
            return  # Prevent spam
        
        if is_initial:
            description = (
                f"❌ No initial heartbeat detected from DDC bot "
                f"<@{self.monitor_config['ddc_bot_user_id']}> "
                f"after {elapsed_seconds:.1f} seconds.\n\n"
                f"**Possible causes:**\n"
                f"• DDC container is not running\n"
                f"• Bot is not connected to Discord\n"
                f"• Heartbeat feature is disabled\n"
                f"• Wrong channel configuration"
            )
        else:
            last_heartbeat_str = self.last_heartbeat_time.strftime('%Y-%m-%d %H:%M:%S UTC')
            description = (
                f"❌ No heartbeat detected from DDC bot "
                f"<@{self.monitor_config['ddc_bot_user_id']}> "
                f"for {elapsed_seconds:.1f} seconds.\n\n"
                f"**Last heartbeat:** {last_heartbeat_str}\n\n"
                f"**Possible causes:**\n"
                f"• DDC container stopped or crashed\n"
                f"• Discord bot lost connection\n"
                f"• Discord API issues\n"
                f"• Network connectivity problems\n"
                f"• Missing permissions in heartbeat channel"
            )
        
        await self._send_alert(
            title="⚠️ DDC Heartbeat Missing",
            description=description,
            color=discord.Color.red()
        )
        
        self.alert_sent = True
    
    async def _send_alert(self, title: str, description: str, color: discord.Color, is_startup: bool = False):
        """Send alert to all configured channels"""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )
        
        if self.alert_config['include_timestamp']:
            embed.timestamp = datetime.now(timezone.utc)
        
        embed.set_footer(text=f"{APP_NAME} v{VERSION} | https://ddc.bot")
        
        # Add role mentions if configured
        content = ""
        if self.alert_config['mention_roles'] and not is_startup:
            mentions = [f"<@&{role_id}>" for role_id in self.alert_config['mention_roles']]
            content = " ".join(mentions)
        
        # Send to all alert channels
        for channel_id in self.monitor_config['alert_channel_ids']:
            try:
                channel = self.get_channel(channel_id)
                if not channel:
                    channel = await self.fetch_channel(channel_id)
                
                await channel.send(content=content, embed=embed)
                self.logger.info(f"📤 Alert sent to channel {channel_id}")
                
            except discord.NotFound:
                self.logger.error(f"❌ Channel {channel_id} not found")
            except discord.Forbidden:
                self.logger.error(f"❌ No permission to send to channel {channel_id}")
            except Exception as e:
                self.logger.error(f"❌ Error sending to channel {channel_id}: {e}")
    
    @heartbeat_check.before_loop
    async def before_heartbeat_check(self):
        """Wait until bot is ready before starting checks"""
        await self.wait_until_ready()
    
    async def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("🛑 Shutting down monitor...")
        self.shutdown_requested = True
        
        # Stop monitoring task
        if self.heartbeat_check.is_running():
            self.heartbeat_check.stop()
        
        # Send shutdown notification
        try:
            await self._send_alert(
                title="🛑 DDC Heartbeat Monitor Stopped",
                description="Heartbeat monitoring has been stopped.",
                color=discord.Color.orange(),
                is_startup=True
            )
        except (discord.HTTPException, discord.Forbidden, ConnectionError) as e:
            # Ignore specific Discord errors during shutdown
            pass
        
        # Close client
        if not self.is_closed():
            await self.close()
        
        self.logger.info("✅ Monitor shutdown complete")

class MonitorApp:
    """Main application class"""
    
    def __init__(self):
        self.config_manager = ConfigManager()
        self.monitor: Optional[HeartbeatMonitor] = None
        self.shutdown_event = asyncio.Event()
        
    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            print(f"\n🛑 Received signal {signum}, shutting down...")
            self.shutdown_event.set()
        
        # Handle common shutdown signals
        if hasattr(signal, 'SIGINT'):
            signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
    
    async def run(self):
        """Main application entry point"""
        print(f"🚀 Starting {APP_NAME} v{VERSION}")
        print("🌐 https://ddc.bot")
        print("=" * 50)
        
        try:
            # Load configuration
            print("📋 Loading configuration...")
            config = self.config_manager.load_config()
            print("✅ Configuration loaded successfully")
            
            # Create monitor instance
            self.monitor = HeartbeatMonitor(config)
            
            # Setup signal handlers
            self.setup_signal_handlers()
            
            # Start monitoring
            print("🔄 Starting heartbeat monitoring...")
            
            # Run monitor and wait for shutdown signal
            monitor_task = asyncio.create_task(
                self.monitor.start(config['monitor']['bot_token'])
            )
            shutdown_task = asyncio.create_task(self.shutdown_event.wait())
            
            # Wait for either monitor to finish or shutdown signal
            done, pending = await asyncio.wait(
                [monitor_task, shutdown_task],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Cancel pending tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            
            # Shutdown monitor if it's still running
            if self.monitor and not self.monitor.is_closed():
                await self.monitor.shutdown()
            
        except discord.LoginFailure:
            print("❌ Failed to login to Discord. Please check your bot token.")
            return 1
        except ValueError as e:
            print(f"❌ Configuration error: {e}")
            return 1
        except KeyboardInterrupt:
            print("\n🛑 Interrupted by user")
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return 1
        
        print(" Goodbye!")
        print("🌐 Visit https://ddc.bot for support and updates")
        return 0

def main():
    """Entry point"""
    app = MonitorApp()
    
    try:
        exit_code = asyncio.run(app.run())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n🛑 Interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 