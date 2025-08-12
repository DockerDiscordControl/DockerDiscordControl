#!/usr/bin/env python3
"""
Supervisor Event Listener/Dispatcher for DockerDiscordControl
Handles process state changes and events from supervisord.
"""
import sys
import os
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('supervisor_dispatcher')


def handle_event(headers, payload):
    """Handle supervisor events."""
    try:
        processname = headers.get('processname', 'unknown')
        groupname = headers.get('groupname', 'unknown')
        from_state = headers.get('from_state', 'unknown')
        eventname = headers.get('eventname', 'unknown')
        
        logger.info(f"Process event: {eventname} - {processname} (group: {groupname}) from state: {from_state}")
        
        # Handle specific events if needed
        if eventname in ['PROCESS_STATE_FATAL', 'PROCESS_STATE_EXITED']:
            if processname in ['discordbot', 'webui']:
                logger.warning(f"Critical process {processname} has {eventname.lower()}")
        
    except Exception as e:
        logger.error(f"Error handling event: {e}")


def wait_for_event(stdin, stdout):
    """Wait for supervisor event - simplified version."""
    line = stdin.readline()
    if not line:
        return None, None
    
    headers = {}
    for kv in line.split():
        if ':' in kv:
            key, value = kv.split(':', 1)
            headers[key] = value
    
    # Read payload length and payload
    payload_length = int(headers.get('len', '0'))
    payload = stdin.read(payload_length) if payload_length > 0 else ''
    
    return headers, payload


def send_ok(stdout):
    """Send OK response to supervisor."""
    stdout.write('RESULT 2\nOK')
    stdout.flush()


def send_fail(stdout):
    """Send FAIL response to supervisor."""
    stdout.write('RESULT 4\nFAIL')
    stdout.flush()


def main():
    """Main event loop for supervisor dispatcher."""
    logger.info("Supervisor dispatcher started")
    
    # Send ready signal to supervisor
    sys.stdout.write('READY\n')
    sys.stdout.flush()
    
    while True:
        try:
            # Wait for supervisor events
            headers, payload = wait_for_event(sys.stdin, sys.stdout)
            if headers is None:
                break
                
            handle_event(headers, payload)
            send_ok(sys.stdout)
            
        except KeyboardInterrupt:
            logger.info("Supervisor dispatcher shutting down")
            break
        except Exception as e:
            logger.error(f"Dispatcher error: {e}")
            send_fail(sys.stdout)


if __name__ == '__main__':
    main()