Here's a test script to check if your Slack bot is properly sending and receiving messages:

```python
#!/usr/bin/env python3
"""Slack Bot Connection Tester"""

import os
import logging
import time
from datetime import datetime
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG for detailed logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test configuration
TEST_CHANNEL = None  # Will be set to bot's DM channel
TEST_USER_ID = None

def test_slack_connection():
    """Test basic Slack connection and permissions"""
    print("\n" + "="*50)
    print("SLACK BOT CONNECTION TESTER")
    print("="*50 + "\n")
    
    # Check environment variables
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")
    
    if not bot_token:
        print("❌ SLACK_BOT_TOKEN not found in environment variables")
        return False
    else:
        print(f"✅ SLACK_BOT_TOKEN found: {bot_token[:20]}...")
    
    if not app_token:
        print("❌ SLACK_APP_TOKEN not found in environment variables")
        return False
    else:
        print(f"✅ SLACK_APP_TOKEN found: {app_token[:20]}...")
    
    return True

def test_bot_info(client):
    """Test bot authentication and get bot info"""
    print("\n📋 Testing Bot Authentication...")
    try:
        # Test auth
        auth_response = client.auth_test()
        bot_user_id = auth_response["user_id"]
        bot_name = auth_response["user"]
        team_name = auth_response["team"]
        
        print(f"✅ Bot authenticated successfully!")
        print(f"   - Bot Name: {bot_name}")
        print(f"   - Bot User ID: {bot_user_id}")
        print(f"   - Team: {team_name}")
        
        # Get bot user info
        bot_info = client.users_info(user=bot_user_id)
        print(f"   - Bot Display Name: {bot_info['user']['profile']['display_name']}")
        
        return bot_user_id
        
    except SlackApiError as e:
        print(f"❌ Bot authentication failed: {e.response['error']}")
        return None

def test_permissions(client):
    """Test bot permissions"""
    print("\n🔑 Testing Bot Permissions...")
    
    permissions_to_test = {
        "channels:read": "Read channel information",
        "chat:write": "Send messages",
        "im:read": "Read direct messages",
        "im:write": "Send direct messages",
        "im:history": "Read DM history",
        "app_mentions:read": "Read app mentions",
        "commands": "Use slash commands"
    }
    
    try:
        # Get bot permissions
        response = client.auth_test()
        print("✅ Bot has basic authentication")
        
        # Test sending a message to self
        try:
            # Open a DM with the bot itself (for testing)
            bot_user_id = response["user_id"]
            dm_response = client.conversations_open(users=bot_user_id)
            test_channel = dm_response["channel"]["id"]
            
            # Try to send a message
            client.chat_postMessage(
                channel=test_channel,
                text="🧪 Test message - Bot can send messages!"
            )
            print("✅ Bot can send messages (chat:write)")
            
            global TEST_CHANNEL
            TEST_CHANNEL = test_channel
            
        except SlackApiError as e:
            print(f"❌ Bot cannot send messages: {e.response['error']}")
            
    except SlackApiError as e:
        print(f"❌ Permission test failed: {e.response['error']}")

def setup_test_handlers(app):
    """Setup test event handlers"""
    global message_received_count
    message_received_count = 0
    
    @app.message("")
    def handle_message(message, say, logger):
        """Test message handler"""
        global message_received_count
        message_received_count += 1
        
        logger.info(f"📨 Message received #{message_received_count}")
        logger.info(f"   - User: {message.get('user', 'Unknown')}")
        logger.info(f"   - Channel: {message.get('channel', 'Unknown')}")
        logger.info(f"   - Text: {message.get('text', 'No text')}")
        logger.info(f"   - Type: {message.get('type', 'Unknown')}")
        
        # Skip bot's own messages
        if message.get('bot_id'):
            logger.info("   - Skipping bot message")
            return
            
        # Respond to test messages
        if 'test' in message.get('text', '').lower():
            response = f"🤖 Test response #{message_received_count}: I received your message!"
            say(response)
            logger.info(f"   - Sent response: {response}")
    
    @app.event("app_mention")
    def handle_app_mention(event, say, logger):
        """Test app mention handler"""
        logger.info("🔔 App mention received!")
        logger.info(f"   - User: {event.get('user', 'Unknown')}")
        logger.info(f"   - Text: {event.get('text', 'No text')}")
        
        say(f"👋 Hello <@{event['user']}>! I received your mention.", thread_ts=event.get('ts'))
    
    @app.command("/test_bot")
    def handle_test_command(ack, respond, command, logger):
        """Test slash command"""
        ack()
        logger.info("🔧 Slash command received: /test_bot")
        logger.info(f"   - User: {command.get('user_id', 'Unknown')}")
        logger.info(f"   - Text: {command.get('text', 'No text')}")
        
        respond(f"✅ Test command received! Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    @app.event("message")
    def handle_message_events(event, logger):
        """Catch all message events for debugging"""
        logger.debug(f"📩 Raw message event: {event}")

def run_interactive_test(app, client):
    """Run interactive tests"""
    print("\n🧪 Running Interactive Tests...")
    print("-" * 50)
    
    # Send a test message
    if TEST_CHANNEL:
        try:
            result = client.chat_postMessage(
                channel=TEST_CHANNEL,
                text="🤖 Bot Test Suite Started at " + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            print(f"✅ Sent test message to channel: {TEST_CHANNEL}")
            print(f"   Message timestamp: {result['ts']}")
        except SlackApiError as e:
            print(f"❌ Failed to send test message: {e.response['error']}")
    
    print("\n📝 Instructions for testing:")
    print("1. Send a direct message to the bot containing 'test'")
    print("2. Mention the bot in any channel with @botname test")
    print("3. Use the slash command: /test_bot")
    print("4. Watch the console for incoming events")
    print("\nPress Ctrl+C to stop the test\n")

def main():
    """Main test function"""
    # Test connection
    if not test_slack_connection():
        return
    
    try:
        # Initialize Slack app
        app = App(token=os.environ.get("SLACK_BOT_TOKEN"))
        client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))
        
        # Test bot info
        bot_user_id = test_bot_info(client)
        if not bot_user_id:
            return
            
        global TEST_USER_ID
        TEST_USER_ID = bot_user_id
        
        # Test permissions
        test_permissions(client)
        
        # Setup test handlers
        setup_test_handlers(app)
        
        # Initialize SocketModeHandler
        handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
        
        print("\n🚀 Starting Slack bot in test mode...")
        print("-" * 50)
        
        # Run interactive tests in a separate thread
        import threading
        test_thread = threading.Thread(target=lambda: run_interactive_test(app, client))
        test_thread.daemon = True
        test_thread.start()
        
        # Give the test thread time to run
        time.sleep(2)
        
        # Start the handler
        print("\n✅ Bot is now listening for events...")
        print("   Waiting for messages...\n")
        
        handler.start()
        
    except Exception as e:
        print(f"\n❌ Error starting bot: {e}")
        logger.error("Bot startup failed", exc_info=True)

if __name__ == "__main__":
    main()
```

Additionally, here's a simpler script to just test sending and receiving a single message:

```python
#!/usr/bin/env python3
"""Quick Slack Bot Send/Receive Test"""

import os
import time
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# Load environment variables
load_dotenv()

def quick_test():
    """Quick test to send and check for messages"""
    print("\n🚀 QUICK SLACK BOT TEST\n")
    
    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        print("❌ SLACK_BOT_TOKEN not found!")
        return
    
    client = WebClient(token=bot_token)
    
    try:
        # 1. Get bot info
        auth = client.auth_test()
        bot_id = auth["user_id"]
        print(f"✅ Bot authenticated: {auth['user']} (ID: {bot_id})")
        
        # 2. List recent conversations
        print("\n📋 Recent conversations:")
        convos = client.conversations_list(types="im", limit=10)
        for channel in convos["channels"]:
            print(f"   - {channel['id']}: {channel.get('name', 'DM')}")
        
        # 3. Send a test message to the bot's own DM
        dm = client.conversations_open(users=bot_id)
        channel_id = dm["channel"]["id"]
        
        test_msg = f"🧪 Test message sent at {time.strftime('%Y-%m-%d %H:%M:%S')}"
        result = client.chat_postMessage(channel=channel_id, text=test_msg)
        print(f"\n✅ Sent test message: {test_msg}")
        print(f"   Channel: {channel_id}")
        print(f"   Timestamp: {result['ts']}")
        
        # 4. Read recent messages
        print("\n📨 Recent messages in bot's DM:")
        history = client.conversations_history(channel=channel_id, limit=5)
        for msg in history["messages"]:
            sender = "Bot" if msg.get("bot_id") else f"User {msg.get('user', 'Unknown')}"
            print(f"   [{sender}] {msg.get('text', 'No text')}")
        
        # 5. Check for unread messages
        print("\n📬 Checking for unread messages...")
        try:
            im_list = client.conversations_list(types="im")
            for im in im_list["channels"]:
                if im.get("unread_count", 0) > 0:
                    print(f"   - {im['id']} has {im['unread_count']} unread messages")
        except:
            print("   - Could not check unread count")
        
    except SlackApiError as e:
        print(f"❌ Error: {e.response['error']}")
        if 'error' in e.response:
            print(f"   Details: {e.response}")

if __name__ == "__main__":
    quick_test()
```

## How to use these test scripts:

1. **Save the first script** as `test_slack_bot.py` - This is a comprehensive tester that:
   - Checks environment variables
   - Tests authentication
   - Tests permissions
   - Sets up event handlers
   - Listens for incoming messages

2. **Save the second script** as `quick_slack_test.py` - This is a quick tester that:
   - Sends a test message
   - Reads recent messages
   - Checks for unread messages

3. **Run the comprehensive test**:
```bash
python test_slack_bot.py
```

4. **Run the quick test**:
```bash
python quick_slack_test.py
```

## What to look for:

1. **Green checkmarks (✅)** indicate successful operations
2. **Red X marks (❌)** indicate failures
3. **Message counts** should increment when you send messages to the bot
4. **Event logs** will show detailed information about received messages

## Testing checklist:

1. Send a DM to your bot containing the word "test"
2. Mention your bot in a channel: `@YourBotName test`
3. Try the slash command: `/test_bot`
4. Check the console output for responses

This will help you identify exactly where the issue is - whether it's in receiving messages, sending messages, or both.






 python aws_client/final_client.py --slack --mcp-server http://13.220.52.46:8002/sse/