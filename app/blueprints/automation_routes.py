# -*- coding: utf-8 -*-
# ============================================================================ #
# DockerDiscordControl (DDC) - Automation Web Routes                          #
# ============================================================================ #
"""
Web Blueprint for Auto-Action System (AAS).
Provides API endpoints for rule management, testing, and history.
"""

import logging
import discord
from flask import Blueprint, jsonify, request
from app.auth import auth
from services.automation import (
    get_auto_action_config_service,
    get_auto_action_state_service,
    get_automation_service
)
# Import Context for Test execution
from services.automation.automation_service import TriggerContext

logger = logging.getLogger('ddc.web.automation_routes')

automation_bp = Blueprint('automation_bp', __name__)

# --- Rule Management ---

@automation_bp.route('/api/automation/rules', methods=['GET'])
@auth.login_required
def get_rules():
    """Get all configured auto-action rules."""
    config_service = get_auto_action_config_service()
    rules = config_service.get_rules()
    return jsonify({'rules': [r.to_dict() for r in rules]})

@automation_bp.route('/api/automation/rules', methods=['POST'])
@auth.login_required
def create_rule():
    """Create a new auto-action rule."""
    config_service = get_auto_action_config_service()
    data = request.json
    
    result = config_service.add_rule(data)
    if result.success:
        return jsonify({'success': True, 'rule': result.data.to_dict()})
    return jsonify({'success': False, 'error': result.error}), 400

@automation_bp.route('/api/automation/rules/<rule_id>', methods=['PUT'])
@auth.login_required
def update_rule(rule_id):
    """Update an existing auto-action rule."""
    config_service = get_auto_action_config_service()
    data = request.json
    
    result = config_service.update_rule(rule_id, data)
    if result.success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': result.error}), 400

@automation_bp.route('/api/automation/rules/<rule_id>', methods=['DELETE'])
@auth.login_required
def delete_rule(rule_id):
    """Delete an auto-action rule."""
    config_service = get_auto_action_config_service()
    result = config_service.delete_rule(rule_id)
    
    if result.success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': result.error}), 400

# --- Global Settings ---

@automation_bp.route('/api/automation/settings', methods=['GET'])
@auth.login_required
def get_settings():
    """Get global automation settings."""
    config_service = get_auto_action_config_service()
    return jsonify(config_service.get_global_settings())

@automation_bp.route('/api/automation/settings', methods=['POST'])
@auth.login_required
def update_settings():
    """Update global automation settings."""
    config_service = get_auto_action_config_service()
    data = request.json
    
    result = config_service.update_global_settings(data)
    if result.success:
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': result.error}), 400

# --- History & State ---

@automation_bp.route('/api/automation/history', methods=['GET'])
@auth.login_required
def get_history():
    """Get automation execution history."""
    state_service = get_auto_action_state_service()
    container = request.args.get('container')

    # Edge Case: Handle non-integer limit parameter
    try:
        limit = int(request.args.get('limit', 50))
        limit = max(1, min(limit, 500))  # Clamp between 1 and 500
    except (ValueError, TypeError):
        limit = 50

    history = state_service.get_history(container, limit)
    return jsonify({'history': history})

# --- Testing (Dry Run) ---

@automation_bp.route('/api/automation/test', methods=['POST'])
@auth.login_required
def test_rule():
    """
    Test a message against configured rules (Dry Run).
    Does NOT execute actions, just checks matching logic.

    Note: This is a synchronous handler that uses asyncio.run() internally
    to properly handle the async _check_match method without blocking Flask.
    """
    import asyncio

    # Edge Case: Handle missing or invalid JSON body
    data = request.json
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    message_content = data.get('content', '')

    # Construct a mock context
    ctx = TriggerContext(
        message_id="test-msg-id",
        channel_id=str(data.get('channel_id', '0')),
        guild_id=str(data.get('guild_id', '0')),
        user_id=str(data.get('user_id', '0')),
        username=data.get('username', 'Test User'),
        is_webhook=data.get('is_webhook', False),
        content=message_content,
        embeds_text=data.get('embeds_text', '')
    )

    automation_service = get_automation_service()
    config_service = get_auto_action_config_service()

    rules = config_service.get_rules()
    candidates = automation_service._pre_filter_rules(rules, ctx)

    results = []

    async def check_all_rules():
        """Async helper to check all rules."""
        matches = []
        for rule in candidates:
            is_match, reason = await automation_service._check_match(rule, ctx)

            match_result = {
                'rule_name': rule.name,
                'rule_id': rule.id,
                'matched': is_match,
                'reason': reason if is_match else "Keywords/Regex did not match",
                'would_execute': rule.action.type,
                'containers': rule.action.containers
            }
            matches.append(match_result)
        return matches

    # Run async code in sync context
    try:
        # Try to get existing event loop (if running in async context)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Create a new loop for this thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, check_all_rules())
                results = future.result(timeout=30)  # 30s timeout for safety
        else:
            results = loop.run_until_complete(check_all_rules())
    except RuntimeError:
        # No event loop, create one
        results = asyncio.run(check_all_rules())
    except Exception as e:
        logger.error(f"Error in test_rule: {e}")
        return jsonify({'error': str(e)}), 500

    return jsonify({
        'input_summary': {
            'full_text_preview': ctx.full_text[:100] + "..."
        },
        'matches': results
    })

# --- Channel Selection ---

@automation_bp.route('/api/automation/channels', methods=['GET'])
@auth.login_required
def get_channels():
    """Get a list of Discord channels the bot can see, for selection in UI."""
    try:
        # Access bot instance globally
        from services.scheduling.donation_message_service import get_bot_instance
        bot = get_bot_instance()

        # Edge Case: Bot not ready - return empty list instead of error
        if not bot:
            logger.warning("Bot instance not available to fetch channels - returning empty list")
            return jsonify({'channels': [], 'warning': 'Bot not ready'})

        # Edge Case: Bot has no guilds yet (still connecting)
        if not bot.guilds:
            logger.warning("Bot has no guilds yet - returning empty list")
            return jsonify({'channels': [], 'warning': 'Bot not connected to any servers'})

        channels_data = []
        for guild in bot.guilds:
            # Edge Case: guild.me can be None if bot is not fully ready
            if not guild.me:
                continue

            for channel in guild.channels:
                if isinstance(channel, discord.TextChannel):
                    # Check bot's permissions to read messages in this channel
                    perms = channel.permissions_for(guild.me)
                    if perms.read_messages:
                        channels_data.append({
                            'id': str(channel.id),
                            'name': f"#{channel.name} ({guild.name})",
                            'guild_id': str(guild.id),
                            'guild_name': guild.name
                        })

        # Sort channels by guild name, then channel name
        channels_data.sort(key=lambda c: (c['guild_name'].lower(), c['name'].lower()))

        return jsonify({'channels': channels_data})

    except Exception as e:
        logger.error(f"Error fetching channels: {e}", exc_info=True)
        # Edge Case: Return empty list on error to prevent UI crash
        return jsonify({'channels': [], 'error': str(e)})