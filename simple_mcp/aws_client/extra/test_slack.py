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
    print(f"Bot token: {bot_token}")
    client = WebClient(token=bot_token)
    try:
        response = client.auth_test()
        print("Auth test response:", response)
        print("Team:", response['team'])
        print("User:", response['user'])
        print("Bot ID:", response.get('bot_id'))
        # print("App home scopes:", response['info']['app_home']['scopes'])
        # print("Team scopes:", response['info']['team']['scopes'])
        # print("User scopes:", response['info']['user']['scopes'])
    except SlackApiError as e:
        print(f"Error: {e.response['error']}")

    
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
        print(f"   Error: {e}")

if __name__ == "__main__":
    quick_test()