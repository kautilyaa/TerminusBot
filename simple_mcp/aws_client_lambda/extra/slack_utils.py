import os
import json
import urllib.request
import logging
from common import SLACK_BOT_TOKEN
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def send_slack_message(channel, text):
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