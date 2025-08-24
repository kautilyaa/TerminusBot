import os
import json
import urllib.request
import logging
from common import SLACK_BOT_TOKEN
logger = logging.getLogger()
logger.setLevel(logging.INFO)
import requests
import time


def send_slack_message_with_thread(channel, text, thread_ts=None):
    """Send Slack message directly without any formatting"""
    try:
        slack_token = os.environ.get('SLACK_BOT_TOKEN')

        if slack_token:
            url = "https://slack.com/api/chat.postMessage"
            headers = {
                "Authorization": f"Bearer {slack_token}",
                "Content-Type": "application/json"
            }

            data = {
                "channel": channel,
                "text": text,  # Send exactly what Claude gave us
                "unfurl_links": False,
                "unfurl_media": False
            }

            if thread_ts:
                data["thread_ts"] = thread_ts

            # Send with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    response = requests.post(url, headers=headers, json=data, timeout=10)
                    response_data = response.json()

                    if response_data.get('ok'):
                        logger.info("Message sent successfully via Slack API")
                        return True
                    else:
                        logger.error(f"Slack API error: {response_data.get('error')}")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                        
                except requests.exceptions.Timeout:
                    logger.warning(f"Slack API timeout on attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
                except Exception as e:
                    logger.error(f"Error sending to Slack on attempt {attempt + 1}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(1)
        else:
            # Fallback
            send_slack_message(channel, text)

    except Exception as e:
        logger.error(f"Failed to send Slack message: {e}")
        return False

def send_slack_message_old(channel, text):
    token = SLACK_BOT_TOKEN
    url = 'https://slack.com/api/chat.postMessage'
    data = {
        'channel': channel,
        'text': text
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}'
        },
        method='POST'
    )
    with urllib.request.urlopen(req) as resp:
        resp_data = resp.read()
        logger.info(f"Slack API response: {resp_data}")
        return json.loads(resp_data)
    
def send_slack_message(channel, text):
    """Send message to Slack channel"""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if webhook_url:
        requests.post(webhook_url, json={"channel": channel, "text": text})



def update_slack_message(channel, message_ts, text):
    """Update an existing Slack message"""
    try:
        slack_token = os.environ.get('SLACK_BOT_TOKEN')
        
        if slack_token:
            url = "https://slack.com/api/chat.update"
            headers = {
                "Authorization": f"Bearer {slack_token}",
                "Content-Type": "application/json"
            }
            
            data = {
                "channel": channel,
                "ts": message_ts,
                "text": text,
                "unfurl_links": False,
                "unfurl_media": False
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=5)
            response_data = response.json()
            
            if response_data.get('ok'):
                return response_data
            else:
                logger.error(f"Slack update error: {response_data.get('error')}")
                return None
                
    except Exception as e:
        logger.error(f"Failed to update Slack message: {e}")
        return None
def stream_response_to_slack(channel, thread_ts, session_id):
    """Stream responses to Slack as they're generated"""
    message_ts = None
    accumulated_text = ""
    
    def update_callback(chunk):
        nonlocal message_ts, accumulated_text
        accumulated_text += chunk
        
        if len(accumulated_text) > 100:  # Update every 100 chars
            if not message_ts:
                # Send initial message
                resp = send_slack_message_with_thread(channel, accumulated_text, thread_ts)
                message_ts = resp.get('ts')
            else:
                # Update existing message
                update_slack_message(channel, message_ts, accumulated_text)
    
    return update_callback


class SlackStreamingHandler:
    """Handle streaming responses to Slack with rate limiting and buffering"""
    
    def __init__(self, channel, thread_ts, min_update_interval=0.5, min_chars_per_update=50):
        self.channel = channel
        self.thread_ts = thread_ts
        self.message_ts = None
        self.accumulated_text = ""
        self.last_update_time = 0
        self.min_update_interval = min_update_interval  # Reduced from 2.0 to 0.5
        self.min_chars_per_update = min_chars_per_update  # Reduced from 100 to 50
        self.update_scheduled = False
        self.is_complete = False
        self.last_sent_text = ""
        
        # Reuse session for connection pooling
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {os.environ.get('SLACK_BOT_TOKEN')}",
            "Content-Type": "application/json"
        })
        
    def send_initial_message(self, text):
        """Send the initial message and store its timestamp"""
        try:
            data = {
                "channel": self.channel,
                "text": text,
                "unfurl_links": False,
                "unfurl_media": False
            }
            
            if self.thread_ts:
                data["thread_ts"] = self.thread_ts
            
            # Use session for faster connection
            response = self.session.post(
                "https://slack.com/api/chat.postMessage", 
                json=data, 
                timeout=3  # Reduced from 5
            )
            response_data = response.json()
            
            if response_data.get('ok'):
                self.message_ts = response_data.get('ts')
                self.accumulated_text = text
                self.last_sent_text = text
                return self.message_ts
            else:
                logger.error(f"Failed to send initial message: {response_data.get('error')}")
                return None
                
        except Exception as e:
            logger.error(f"Error sending initial message: {e}")
            return None
    
    def add_chunk(self, chunk):
        """Add a chunk of text to the buffer"""
        self.accumulated_text += chunk
        
        # Immediately update for better UX
        self.perform_update()
    
    def replace_message(self, new_text):
        """Replace the entire message content with new text - optimized for speed"""
        self.accumulated_text = new_text
        
        if self.message_ts:
            # Direct update without buffering for tool status
            try:
                data = {
                    "channel": self.channel,
                    "ts": self.message_ts,
                    "text": new_text if new_text else " "
                }
                
                # Fire and forget for speed (don't wait for response)
                self.session.post(
                    "https://slack.com/api/chat.update",
                    json=data,
                    timeout=2
                )
                self.last_sent_text = new_text
                
            except Exception as e:
                logger.error(f"Error replacing Slack message: {e}")
        else:
            self.send_initial_message(new_text if new_text else "Processing...")
    
    def get_last_sent_text(self):
        """Get the text that was last sent to Slack"""
        return self.last_sent_text
    
    def perform_update(self):
        """Actually perform the Slack message update - optimized"""
        try:
            current_time = time.time()
            
            # Skip if too soon since last update
            if current_time - self.last_update_time < self.min_update_interval:
                return
                
            if not self.message_ts:
                # Send initial message
                self.send_initial_message(self.accumulated_text + "\n\n_...thinking..._")
            else:
                # Update existing message
                update_text = self.accumulated_text
                if not self.is_complete:
                    update_text += "\n\n_...thinking..._"
                
                # Use session for faster update
                data = {
                    "channel": self.channel,
                    "ts": self.message_ts,
                    "text": update_text
                }
                
                self.session.post(
                    "https://slack.com/api/chat.update",
                    json=data,
                    timeout=2
                )
                self.last_sent_text = update_text
            
            self.last_update_time = current_time
            
        except Exception as e:
            logger.error(f"Error updating Slack message: {e}")
    
    def finalize(self, final_text=None):
        """Send the final update"""
        self.is_complete = True
        if final_text:
            self.accumulated_text = final_text
        
        # Final update without "thinking" indicator
        if self.message_ts:
            try:
                data = {
                    "channel": self.channel,
                    "ts": self.message_ts,
                    "text": self.accumulated_text
                }
                self.session.post(
                    "https://slack.com/api/chat.update",
                    json=data,
                    timeout=3
                )
            except Exception as e:
                logger.error(f"Error finalizing message: {e}")
        else:
            self.send_initial_message(self.accumulated_text)
        
        # Close session
        self.session.close()



# class SlackStreamingHandler:
#     """Handle streaming responses to Slack with rate limiting and buffering"""
    
#     def __init__(self, channel, thread_ts, min_update_interval=2.0, min_chars_per_update=100):
#         self.channel = channel
#         self.thread_ts = thread_ts
#         self.message_ts = None
#         self.accumulated_text = ""
#         self.last_update_time = 0
#         self.min_update_interval = min_update_interval  # Minimum seconds between updates
#         self.min_chars_per_update = min_chars_per_update
#         self.update_scheduled = False
#         self.is_complete = False
#         self.last_sent_text = ""  # Track what was last sent
        
#     def send_initial_message(self, text):
#         """Send the initial message and store its timestamp"""
#         try:
#             slack_token = os.environ.get('SLACK_BOT_TOKEN')
            
#             if slack_token:
#                 url = "https://slack.com/api/chat.postMessage"
#                 headers = {
#                     "Authorization": f"Bearer {slack_token}",
#                     "Content-Type": "application/json"
#                 }
                
#                 data = {
#                     "channel": self.channel,
#                     "text": text,
#                     "unfurl_links": False,
#                     "unfurl_media": False
#                 }
                
#                 if self.thread_ts:
#                     data["thread_ts"] = self.thread_ts
                
#                 response = requests.post(url, headers=headers, json=data, timeout=5)
#                 response_data = response.json()
                
#                 if response_data.get('ok'):
#                     self.message_ts = response_data.get('ts')
#                     self.accumulated_text = text
#                     self.last_sent_text = text
#                     return self.message_ts
#                 else:
#                     logger.error(f"Failed to send initial message: {response_data.get('error')}")
#                     return None
                    
#         except Exception as e:
#             logger.error(f"Error sending initial message: {e}")
#             return None
    
#     def add_chunk(self, chunk):
#         """Add a chunk of text to the buffer"""
#         self.accumulated_text += chunk
        
#         # Check if we should update
#         current_time = time.time()
#         time_since_last = current_time - self.last_update_time
#         chars_since_last = len(self.accumulated_text) - len(self.last_sent_text)
        
#         should_update = (
#             not self.update_scheduled and
#             self.message_ts and  # Have sent initial message
#             time_since_last >= self.min_update_interval and
#             chars_since_last >= self.min_chars_per_update
#         )
        
#         if should_update:
#             self.schedule_update()
    
#     def replace_message(self, new_text):
#         """Replace the entire message content with new text"""
#         self.accumulated_text = new_text
        
#         # For tool status updates, we want to update immediately
#         if self.message_ts:
#             # Update existing message
#             update_text = new_text if new_text else " "  # Slack doesn't allow empty messages
            
#             try:
#                 update_slack_message(self.channel, self.message_ts, update_text)
#                 self.last_sent_text = update_text
#                 self.last_update_time = time.time()
#             except Exception as e:
#                 logger.error(f"Error replacing Slack message: {e}")
#         else:
#             # No initial message yet, send one
#             self.send_initial_message(new_text if new_text else "Processing...")
    
#     def get_last_sent_text(self):
#         """Get the text that was last sent to Slack"""
#         return self.last_sent_text
    
#     def schedule_update(self):
#         """Schedule an update to avoid rate limiting"""
#         if not self.update_scheduled:
#             self.update_scheduled = True
#             # In Lambda, we can't use threading, so update immediately
#             self.perform_update()
#             self.update_scheduled = False
    
#     def perform_update(self):
#         """Actually perform the Slack message update"""
#         try:
#             if not self.message_ts:
#                 # Send initial message
#                 self.send_initial_message(self.accumulated_text + "\n\n_...thinking..._")
#             else:
#                 # Update existing message
#                 update_text = self.accumulated_text
#                 if not self.is_complete:
#                     update_text += "\n\n_...thinking..._"
                
#                 update_slack_message(self.channel, self.message_ts, update_text)
#                 self.last_sent_text = update_text
            
#             self.last_update_time = time.time()
            
#         except Exception as e:
#             logger.error(f"Error updating Slack message: {e}")
    
#     def finalize(self, final_text=None):
#         """Send the final update"""
#         self.is_complete = True
#         if final_text:
#             self.accumulated_text = final_text
        
#         # Remove the "thinking" indicator
#         if self.message_ts:
#             update_slack_message(self.channel, self.message_ts, self.accumulated_text)
#         else:
#             self.send_initial_message(self.accumulated_text)







# class SlackStreamingHandler:
#     """Handle streaming responses to Slack with rate limiting and buffering"""
    
#     def __init__(self, channel, thread_ts, min_update_interval=2.0, min_chars_per_update=100):
#         self.channel = channel
#         self.thread_ts = thread_ts
#         self.message_ts = None
#         self.accumulated_text = ""
#         self.last_update_time = 0
#         self.min_update_interval = min_update_interval  # Minimum seconds between updates
#         self.min_chars_per_update = min_chars_per_update
#         self.update_scheduled = False
#         self.is_complete = False
        
#     def send_initial_message(self, text):
#         """Send the initial message and store its timestamp"""
#         try:
#             slack_token = os.environ.get('SLACK_BOT_TOKEN')
            
#             if slack_token:
#                 url = "https://slack.com/api/chat.postMessage"
#                 headers = {
#                     "Authorization": f"Bearer {slack_token}",
#                     "Content-Type": "application/json"
#                 }
                
#                 data = {
#                     "channel": self.channel,
#                     "text": text,
#                     "unfurl_links": False,
#                     "unfurl_media": False
#                 }
                
#                 if self.thread_ts:
#                     data["thread_ts"] = self.thread_ts
                
#                 response = requests.post(url, headers=headers, json=data, timeout=5)
#                 response_data = response.json()
                
#                 if response_data.get('ok'):
#                     self.message_ts = response_data.get('ts')
#                     return self.message_ts
#                 else:
#                     logger.error(f"Failed to send initial message: {response_data.get('error')}")
#                     return None
                    
#         except Exception as e:
#             logger.error(f"Error sending initial message: {e}")
#             return None
    
#     def add_chunk(self, chunk):
#         """Add a chunk of text to the buffer"""
#         self.accumulated_text += chunk
        
#         # Check if we should update
#         current_time = time.time()
#         time_since_last = current_time - self.last_update_time
#         chars_since_last = len(self.accumulated_text) - len(self.get_last_sent_text())
        
#         should_update = (
#             not self.update_scheduled and
#             self.message_ts and  # Have sent initial message
#             time_since_last >= self.min_update_interval and
#             chars_since_last >= self.min_chars_per_update
#         )
        
#         if should_update:
#             self.schedule_update()
    
#     def get_last_sent_text(self):
#         """Get the text that was last sent to Slack"""
#         # This would need to be tracked
#         return ""
    
#     def schedule_update(self):
#         """Schedule an update to avoid rate limiting"""
#         if not self.update_scheduled:
#             self.update_scheduled = True
#             # In Lambda, we can't use threading, so update immediately
#             self.perform_update()
#             self.update_scheduled = False
    
#     def perform_update(self):
#         """Actually perform the Slack message update"""
#         try:
#             if not self.message_ts:
#                 # Send initial message
#                 self.send_initial_message(self.accumulated_text + "\n\n_...thinking..._")
#             else:
#                 # Update existing message
#                 update_text = self.accumulated_text
#                 if not self.is_complete:
#                     update_text += "\n\n_...thinking..._"
                
#                 update_slack_message(self.channel, self.message_ts, update_text)
            
#             self.last_update_time = time.time()
            
#         except Exception as e:
#             logger.error(f"Error updating Slack message: {e}")
    
#     def finalize(self, final_text=None):
#         """Send the final update"""
#         self.is_complete = True
#         if final_text:
#             self.accumulated_text = final_text
        
#         # Remove the "thinking" indicator
#         if self.message_ts:
#             update_slack_message(self.channel, self.message_ts, self.accumulated_text)
#         else:
#             self.send_initial_message(self.accumulated_text)