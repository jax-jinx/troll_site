"""
Phone Automation Controller - Backend Server
===============================================
A Flask-based REST API that acts as a bridge between the web frontend
and Android phone automation webhooks.

Author: System Automation
Version: 1.0.0
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import logging
from datetime import datetime
from threading import Lock
import time

# ==================== APPLICATION SETUP ====================

# Initialize Flask application
app = Flask(__name__)

# Enable CORS (Cross-Origin Resource Sharing) to allow frontend to communicate
# This is essential for the HTML dashboard to make API calls
CORS(app)

# Configure logging for debugging and monitoring
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================

# Webhook URLs for MacroDroid or similar automation apps
# IMPORTANT: Replace these placeholder URLs with your actual webhook URLs
WEBHOOK_CONFIG = {
    'lock_screen': {
        'url': 'https://trigger.macrodroid.com/44152ed5-575d-4f82-97b1-8ce1f4e9bde5/lock',
        'description': 'Lock the phone screen immediately'
    },
    'block_touch': {
        'url': 'https://trigger.macrodroid.com/44152ed5-575d-4f82-97b1-8ce1f4e9bde5/block',
        'description': 'Block touch/UI interaction for 10 seconds'
    },
    'open_site1': {
        'url': 'https://trigger.macrodroid.com/44152ed5-575d-4f82-97b1-8ce1f4e9bde5/site1',
        'description': 'Open Site 1 (e.g., YouTube)'
    },
    'open_site2': {
        'url': 'https://trigger.macrodroid.com/44152ed5-575d-4f82-97b1-8ce1f4e9bde5/site2',
        'description': 'Open Site 2 (e.g., Twitter)'
    },
    'open_site3': {
        'url': 'https://trigger.macrodroid.com/44152ed5-575d-4f82-97b1-8ce1f4e9bde5/site3',
        'description': 'Open Site 3 (e.g., Gmail)'
    }
}

# Timeout for webhook HTTP requests (seconds)
WEBHOOK_TIMEOUT = 10

# ==================== STATE MANAGEMENT ====================

# Global state to track last action and system health
# Thread-safe using Lock to prevent race conditions
state_lock = Lock()
system_state = {
    'last_action': None,
    'last_action_time': None,
    'last_action_status': None,
    'total_requests': 0,
    'successful_requests': 0,
    'failed_requests': 0,
    'backend_start_time': datetime.now().isoformat()
}

def update_state(action_name, status, message=None):
    """
    Thread-safe state update function
    
    Args:
        action_name (str): Name of the action executed
        status (str): 'success' or 'error'
        message (str, optional): Additional message
    """
    with state_lock:
        system_state['last_action'] = action_name
        system_state['last_action_time'] = datetime.now().isoformat()
        system_state['last_action_status'] = status
        system_state['total_requests'] += 1
        
        if status == 'success':
            system_state['successful_requests'] += 1
        else:
            system_state['failed_requests'] += 1

# ==================== WEBHOOK FORWARDING ====================

def trigger_webhook(webhook_key, payload=None):
    """
    Forward request to phone webhook URL
    
    This is the core function that bridges the backend to the phone.
    It sends HTTP POST requests to MacroDroid webhook URLs.
    
    Args:
        webhook_key (str): Key from WEBHOOK_CONFIG (e.g., 'lock_screen')
        payload (dict, optional): Additional data to send with webhook
    
    Returns:
        dict: Response containing success status and metadata
    """
    # Validate webhook key exists in configuration
    if webhook_key not in WEBHOOK_CONFIG:
        logger.error(f"Invalid webhook key: {webhook_key}")
        return {
            'success': False,
            'action': webhook_key,
            'message': f'Unknown action: {webhook_key}',
            'timestamp': datetime.now().isoformat()
        }
    
    # Get webhook configuration
    webhook_info = WEBHOOK_CONFIG[webhook_key]
    webhook_url = webhook_info['url']
    
    logger.info(f"Triggering webhook: {webhook_key}")
    logger.info(f"URL: {webhook_url}")
    
    try:
        # Send POST request to webhook URL
        # MacroDroid webhooks accept both URL parameters and JSON body
        response = requests.post(
            webhook_url,
            json=payload if payload else {},
            timeout=WEBHOOK_TIMEOUT,
            headers={'Content-Type': 'application/json'}
        )
        
        # Log the response
        logger.info(f"Webhook response status: {response.status_code}")
        
        # Check if request was successful (200-299 status codes)
        if 200 <= response.status_code < 300:
            update_state(webhook_key, 'success')
            return {
                'success': True,
                'action': webhook_key,
                'message': f'{webhook_info["description"]} - Command sent successfully',
                'status_code': response.status_code,
                'timestamp': datetime.now().isoformat()
            }
        else:
            # Non-success HTTP status
            update_state(webhook_key, 'error', f'HTTP {response.status_code}')
            return {
                'success': False,
                'action': webhook_key,
                'message': f'Webhook returned HTTP {response.status_code}',
                'status_code': response.status_code,
                'timestamp': datetime.now().isoformat()
            }
    
    except requests.exceptions.Timeout:
        # Request timed out
        logger.error(f"Webhook timeout for {webhook_key}")
        update_state(webhook_key, 'error', 'Timeout')
        return {
            'success': False,
            'action': webhook_key,
            'message': 'Request timed out. Phone may be unreachable.',
            'timestamp': datetime.now().isoformat()
        }
    
    except requests.exceptions.ConnectionError:
        # Cannot connect to webhook
        logger.error(f"Connection error for {webhook_key}")
        update_state(webhook_key, 'error', 'Connection error')
        return {
            'success': False,
            'action': webhook_key,
            'message': 'Cannot connect to phone. Check internet connection.',
            'timestamp': datetime.now().isoformat()
        }
    
    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error for {webhook_key}: {str(e)}")
        update_state(webhook_key, 'error', str(e))
        return {
            'success': False,
            'action': webhook_key,
            'message': f'Unexpected error: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }

# ==================== REST API ENDPOINTS ====================

@app.route('/api/status', methods=['GET'])
def get_status():
    """
    Health check and status endpoint
    
    Returns current backend state and statistics.
    Frontend polls this endpoint to check if backend is online.
    
    Response:
        {
            "online": true,
            "last_action": "lock_screen",
            "last_action_time": "2024-01-31T10:30:45",
            "last_action_status": "success",
            "statistics": {...}
        }
    """
    with state_lock:
        return jsonify({
            'online': True,
            'last_action': system_state['last_action'],
            'last_action_time': system_state['last_action_time'],
            'last_action_status': system_state['last_action_status'],
            'statistics': {
                'total_requests': system_state['total_requests'],
                'successful_requests': system_state['successful_requests'],
                'failed_requests': system_state['failed_requests']
            },
            'backend_start_time': system_state['backend_start_time'],
            'current_time': datetime.now().isoformat()
        })

@app.route('/api/actions', methods=['GET'])
def get_actions():
    """
    List all available actions
    
    Returns metadata about all configured actions.
    Useful for dynamic UI generation or documentation.
    
    Response:
        {
            "actions": [
                {"key": "lock_screen", "description": "..."},
                ...
            ]
        }
    """
    actions = []
    for key, config in WEBHOOK_CONFIG.items():
        actions.append({
            'key': key,
            'description': config['description']
        })
    
    return jsonify({
        'actions': actions,
        'total_count': len(actions)
    })

@app.route('/api/lock', methods=['POST'])
def lock_screen():
    """
    ACTION 1: Lock the phone screen
    
    Triggers the lock_screen webhook to immediately lock the phone.
    Useful for security or privacy situations.
    """
    logger.info("Lock screen action requested")
    result = trigger_webhook('lock_screen')
    return jsonify(result)

@app.route('/api/block-touch', methods=['POST'])
def block_touch():
    """
    ACTION 2: Block touch/UI interaction for 10 seconds
    
    Prevents any touch input on the phone for a fixed duration.
    Useful to prevent accidental interactions or as a "phone timeout".
    
    Request body (optional):
        {
            "duration": 10  // Duration in seconds
        }
    """
    logger.info("Block touch action requested")
    
    # Get optional duration from request body
    data = request.get_json() or {}
    duration = data.get('duration', 10)  # Default 10 seconds
    
    # Send duration as payload to webhook
    result = trigger_webhook('block_touch', {'duration': duration})
    return jsonify(result)

@app.route('/api/open-site1', methods=['POST'])
def open_site1():
    """
    ACTION 3: Open Site 1
    
    Opens the first configured website/app on the phone.
    
    Request body (optional):
        {
            "url": "https://youtube.com"  // Override default URL
        }
    """
    logger.info("Open Site 1 action requested")
    
    # Get optional URL from request body
    data = request.get_json() or {}
    url = data.get('url', None)
    
    payload = {'url': url} if url else None
    result = trigger_webhook('open_site1', payload)
    return jsonify(result)

@app.route('/api/open-site2', methods=['POST'])
def open_site2():
    """
    ACTION 4: Open Site 2
    
    Opens the second configured website/app on the phone.
    
    Request body (optional):
        {
            "url": "https://twitter.com"  // Override default URL
        }
    """
    logger.info("Open Site 2 action requested")
    
    data = request.get_json() or {}
    url = data.get('url', None)
    
    payload = {'url': url} if url else None
    result = trigger_webhook('open_site2', payload)
    return jsonify(result)

@app.route('/api/open-site3', methods=['POST'])
def open_site3():
    """
    ACTION 5: Open Site 3
    
    Opens the third configured website/app on the phone.
    
    Request body (optional):
        {
            "url": "https://gmail.com"  // Override default URL
        }
    """
    logger.info("Open Site 3 action requested")
    
    data = request.get_json() or {}
    url = data.get('url', None)
    
    payload = {'url': url} if url else None
    result = trigger_webhook('open_site3', payload)
    return jsonify(result)

@app.route('/api/test-webhook/<webhook_key>', methods=['POST'])
def test_webhook(webhook_key):
    """
    Test endpoint for debugging individual webhooks
    
    Args:
        webhook_key (str): The webhook to test (e.g., 'lock_screen')
    
    Usage:
        POST /api/test-webhook/lock_screen
    """
    logger.info(f"Testing webhook: {webhook_key}")
    result = trigger_webhook(webhook_key)
    return jsonify(result)

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'success': False,
        'message': 'Endpoint not found',
        'timestamp': datetime.now().isoformat()
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {str(error)}")
    return jsonify({
        'success': False,
        'message': 'Internal server error',
        'timestamp': datetime.now().isoformat()
    }), 500

# ==================== SERVER STARTUP ====================

if __name__ == '__main__':
    # Print startup information
    print("=" * 70)
    print("Phone Automation Controller - Backend Server")
    print("=" * 70)
    print("\n📱 Configured Actions:")
    for key, config in WEBHOOK_CONFIG.items():
        print(f"  • {key}: {config['description']}")
    
    print("\n🔗 API Endpoints:")
    print("  • GET  /api/status          - Backend health check")
    print("  • GET  /api/actions         - List all actions")
    print("  • POST /api/lock            - Lock phone screen")
    print("  • POST /api/block-touch     - Block touch input")
    print("  • POST /api/open-site1      - Open Site 1")
    print("  • POST /api/open-site2      - Open Site 2")
    print("  • POST /api/open-site3      - Open Site 3")
    
    print("\n⚠️  IMPORTANT:")
    print("  Update WEBHOOK_CONFIG with your actual MacroDroid webhook URLs!")
    
    print("\n" + "=" * 70)
    print("🚀 Starting server on http://localhost:5000")
    print("   Press Ctrl+C to stop")
    print("=" * 70 + "\n")
    
    # Run Flask server
    # host='0.0.0.0' allows access from other devices on the network
    # port=5000 is the default Flask port
    # debug=False for production (set to True for development)
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=False  # Set to True during development
    )