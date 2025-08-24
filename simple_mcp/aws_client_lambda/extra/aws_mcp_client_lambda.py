import json
import os
import time
import logging
import asyncio
import re
from typing import Optional, Dict, List, Any
import boto3
from botocore.config import Config
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, timezone
from slack_utils import send_slack_message
from sns_alert import send_sns_alert

# Import context management components
from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.chat_message_histories import DynamoDBChatMessageHistory

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configure boto3 client with retry settings
config = Config(
    retries=dict(
        max_attempts=10,
        mode='adaptive'
    ),
    read_timeout=300,
    max_pool_connections=50
)

bedrock_client = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-east-1',
    config=config
)

# Context-aware system prompt
CONTEXT_AWARE_SYSTEM_PROMPT = """You are an expert AWS Operations Assistant with comprehensive access to AWS management tools and context awareness capabilities.

**CONTEXT MANAGEMENT RULES:**
1. Always maintain awareness of key information throughout the conversation:
   - Instance IDs (format: i-xxxxxxxxx)
   - Instance Types (e.g., t2.micro, m5.large)
   - Issue Types (e.g., high CPU, memory issues, disk space, network problems)
   - Any specific metrics or thresholds mentioned

2. When key information is identified, acknowledge it and refer back to it in subsequent responses.

3. If context from previous messages is relevant, include it in your analysis.

**RESPONSE FORMATTING FOR SLACK:**
Always format your responses using Slack markdown:
- Use *bold* for important information
- Use `code` for instance IDs, commands, and technical terms
- Use ```code blocks``` for multi-line outputs
- Use • for bullet points
- Use :warning: :white_check_mark: :x: :wrench: :chart_with_upwards_trend: emojis appropriately

**Core AWS Services:**
[Rest of your existing system prompt content...]"""

class ConversationContext:
    """Manages persistent context across conversations"""

    def __init__(self, dynamodb_resource, table_name):
        self.dynamodb = dynamodb_resource
        self.context_table_name = f"{table_name}_context"
        self._ensure_context_table()

    def _ensure_context_table(self):
        """Ensure context table exists"""
        try:
            table = self.dynamodb.create_table(
                TableName=self.context_table_name,
                KeySchema=[
                    {'AttributeName': 'SessionId', 'KeyType': 'HASH'}
                ],
                AttributeDefinitions=[
                    {'AttributeName': 'SessionId', 'AttributeType': 'S'}
                ],
                BillingMode='PAY_PER_REQUEST'
            )
            table.wait_until_exists()
            logger.info(f"Created context table: {self.context_table_name}")
        except self.dynamodb.meta.client.exceptions.ResourceInUseException:
            logger.info(f"Context table already exists: {self.context_table_name}")
        except Exception as e:
            logger.error(f"Error creating context table: {e}")

    def update_context(self, session_id: str, key_points: Dict[str, Any]):
        """Update context for a session"""
        try:
            table = self.dynamodb.Table(self.context_table_name)
            key_points['last_updated'] = datetime.now().isoformat()
            table.put_item(
                Item={
                    'SessionId': session_id,
                    'KeyPoints': key_points,
                    'LastUpdated': datetime.now().isoformat()
                }
            )
            logger.info(f"Updated context for session {session_id}: {key_points}")
        except Exception as e:
            logger.error(f"Error updating context: {e}")

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """Get context for a session"""
        try:
            table = self.dynamodb.Table(self.context_table_name)
            response = table.get_item(Key={'SessionId': session_id})

            if 'Item' in response:
                return response['Item'].get('KeyPoints', {})
            return {}
        except Exception as e:
            logger.error(f"Error getting context: {e}")
            return {}

    def extract_key_points(self, text: str) -> Dict[str, Any]:
        """Extract key points from text using patterns"""
        key_points = {}

        # Instance ID patterns
        instance_patterns = [
            r'i-[0-9a-f]{8,17}',  # EC2 instance ID
            r'instance[:\\s]+([a-zA-Z0-9\\-_]+)',  # Instance name
        ]

        # Instance type patterns
        type_patterns = [
            r'([tcmrpxgadni][0-9]\\.[a-z0-9]+)',  # EC2 instance types
            r'instance type[:\\s]+([a-zA-Z0-9\\.]+)',
        ]

        # Issue type patterns
        issue_keywords = {
            'high_cpu': ['high cpu', 'cpu usage', 'cpu utilization', 'cpu spike'],
            'memory': ['memory', 'ram', 'out of memory', 'oom', 'memory leak'],
            'disk': ['disk', 'storage', 'disk space', 'disk full', 'iops'],
            'network': ['network', 'connectivity', 'connection', 'timeout', 'packet loss'],
            'down': ['down', 'stopped', 'not responding', 'unreachable', 'crashed'],
            'slow': ['slow', 'performance', 'latency', 'lag', 'degraded'],
            'security': ['security', 'breach', 'unauthorized', 'vulnerability'],
            'database': ['database', 'rds', 'query', 'deadlock', 'replication'],
        }

        # Extract instance IDs/names
        for pattern in instance_patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                key_points['instance_id'] = matches[0]
                break

        # Extract instance types
        for pattern in type_patterns:
            matches = re.findall(pattern, text.lower())
            if matches:
                key_points['instance_type'] = matches[0]
                break

        # Extract issue types
        text_lower = text.lower()
        for issue_type, keywords in issue_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                if 'issue_types' not in key_points:
                    key_points['issue_types'] = []
                if issue_type not in key_points['issue_types']:
                    key_points['issue_types'].append(issue_type)

        return key_points

def format_for_slack(text: str) -> str:
    """Format text for better Slack display"""
    # Add emojis for common patterns
    emoji_mappings = {
        'Error:': ':x: *Error:*',
        'Warning:': ':warning: *Warning:*',
        'Success:': ':white_check_mark: *Success:*',
        'Info:': ':information_source: *Info:*',
        'Instance ID:': '*Instance ID:*',
        'Status:': '*Status:*',
        'CPU:': ':chart_with_upwards_trend: *CPU:*',
        'Memory:': ':floppy_disk: *Memory:*',
        'Disk:': ':cd: *Disk:*',
        'Network:': ':globe_with_meridians: *Network:*',
        'Finding': ':mag: *Finding*',
        'Recommendation': ':bulb: *Recommendation*',
        'Alert': ':rotating_light: *Alert*',
    }

    # Apply emoji mappings
    for pattern, replacement in emoji_mappings.items():
        text = text.replace(pattern, replacement)

    # Format instance IDs
    text = re.sub(r'(i-[0-9a-f]{8,17})', r'`\\1`', text)

    # Format instance types
    text = re.sub(r'([tcmrpxgadni][0-9]\\.[a-z0-9]+)', r'`\\1`', text)

    # Format IP addresses
    text = re.sub(r'(\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3})', r'`\\1`', text)

    # Add line breaks for better readability
    text = re.sub(r'\\. ([A-Z])', r'.\\n\\1', text)

    return text

def get_session_id(user_id: str, channel_id: str, thread_ts: Optional[str] = None) -> str:
    """Create unique session ID"""
    session_id = f"slack_{user_id}_{channel_id}_{thread_ts}" if thread_ts else f"slack_{user_id}_{channel_id}"
    logger.debug(f"Generated session ID: {session_id}")
    return session_id

def convert_history_to_messages(history) -> list:
    """Convert LangChain message history to Bedrock format"""
    messages = []

    try:
        for msg in history.messages:
            if isinstance(msg, HumanMessage):
                messages.append({
                    "role": "user",
                    "content": [{"text": msg.content}]
                })
            elif isinstance(msg, AIMessage):
                messages.append({
                    "role": "assistant",
                    "content": [{"text": msg.content}]
                })
    except Exception as e:
        logger.warning(f"Error converting history: {e}")
        return []

    return messages

def get_bedrock_slack_result(query: str):
    """Format query response for Slack using Bedrock"""
    start_time = time.time()

    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")

    system_prompt = """
        <instruction>
        Your task is to format responses specifically for Slack messaging, following these guidelines:

        *Slack Formatting Rules:*
        • Use *text* for bold
        • Use _text_ for italic
        • Use `text` for inline code
        • Use ```text``` for code blocks
        • Use > for single-line quotes
        • Use >>> for multi-line quotes
        • Use • for bullet points (never -, *, or numbers)
        • Use 1. 2. 3. for numbered lists (when order matters)
        • Format links as <URL|display text> or <URL>
        • Use :emoji_name: for emojis (e.g. :white_check_mark: :warning: :information_source:)
        • Use single line breaks within sections
        • Use double line breaks between major sections

        :no_entry: *Avoid These (Not Slack Compatible):*
        • Headers (use *Bold Text* instead)
        • Subheaders (use *Bold Text* with emojis)
        • **double asterisks** for bold
        • __double underscores__ for italic
        • HTML tags
        • Markdown tables
        • Complex nested formatting

        *Structure Guidelines:*
        • Start with a clear *Summary Line* using *bold* and relevant :emoji:
        • Group related information together
        • Use :emoji: to create visual breaks and highlight sections
        • Keep paragraphs short (2-3 lines max)
        • Use bullet points • liberally for scannable content
        • End with clear next steps or summary when appropriate

        :information_source: Remember: Slack users scan messages quickly. Prioritize clarity and scannability over complex formatting.
        </instruction>
        """

    messages = [{"role": "user", "content": [{"text": query}]}]
    api_params = {
        "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {"maxTokens": 4096, "temperature": 0.9},
    }

    response = bedrock_client.converse(**api_params)
    response_time = time.time() - start_time
    logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")
    return response['output']['message']['content'][0]['text']

def get_bedrock_email_result(query: str):
    """Format query response for email using Bedrock"""
    # Your existing email formatting code here
    start_time = time.time()

    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")

    # First call: Get the email subject
    subject_prompt = """
        <instruction>
        Your task is to create a concise, professional email subject line for the following content.

        *Subject Line Requirements:*
        • Keep it between 50-80 characters
        • Include key identifiers (instance IDs, ticket numbers, etc.)
        • Indicate urgency level if applicable
        • Use format: "[Type] - [Brief Description] for [Resource]"
        • Be specific and action-oriented
        • Examples:
          - "Incident Report - Disk Space Alert for i-03326536e3f1be717"
          - "Resolved - Database Connection Issue on prod-db-01"
          - "Action Required - SSL Certificate Expiration for app.domain.com"

        Return ONLY the subject line as plain text, no quotes or additional formatting.
        </instruction>
        """

    # Get the subject
    try:
        logger.info("Getting email subject from Bedrock...")
        subject_messages = [{"role": "user", "content": [{"text": f"Create an email subject line for:\\n\\n{query}"}]}]
        subject_api_params = {
            "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "system": [{"text": subject_prompt}],
            "messages": subject_messages,
            "inferenceConfig": {"maxTokens": 200, "temperature": 0.3},
        }

        subject_response = bedrock_client.converse(**subject_api_params)
        email_subject = subject_response['output']['message']['content'][0]['text'].strip()
        logger.info(f"Email subject generated: {email_subject}")

    except Exception as e:
        logger.error(f"Failed to generate email subject: {str(e)}")
        email_subject = "Technical Update - AWS Operations"

    # Second call: Get the email body (your existing code)
    body_prompt = """\\
        <system>
        You are a helpful assistant that formats technical content into a clean, professional email body.
        </system>
        <instruction>
        Convert the provided technical content into a clean, professional email body.

        [Rest of your existing email body prompt...]
        </instruction>
        """

    # Get the body
    try:
        logger.info("Getting email body from Bedrock...")
        body_messages = [{"role": "user", "content": [{"text": f"Format this into a professional email body:\\n\\n{query}"}]}]
        body_api_params = {
            "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "system": [{"text": body_prompt}],
            "messages": body_messages,
            "inferenceConfig": {"maxTokens": 6000, "temperature": 0.5},
        }

        body_response = bedrock_client.converse(**body_api_params)
        email_body = body_response['output']['message']['content'][0]['text'].strip()
        logger.info(f"Email body generated: {len(email_body)} characters")

    except Exception as e:
        logger.error(f"Failed to generate email body: {str(e)}")
        email_body = query  # Fallback to original query

    response_time = time.time() - start_time
    logger.info(f"Email formatting completed in {response_time:.2f} seconds")

    return {
        "subject": email_subject,
        "body": email_body
    }

class AWSMCPLambdaClient:
    def __init__(self, region: str = 'us-east-1'):
        """Initialize the AWS MCP Lambda Client with context support"""
        self.region = region
        self.last_request_time = 0
        self.min_request_interval = 1.0
        self.session = None
        self._init_session()

        # Initialize DynamoDB for context management
        self.dynamodb = boto3.resource("dynamodb", config=config)
        self.table_name = os.environ.get("DYNAMODB_TABLE_NAME", "oncalltable")

        # Initialize context manager
        try:
            self.context_manager = ConversationContext(self.dynamodb, self.table_name)
            logger.info("Context manager initialized")
        except Exception as e:
            logger.warning(f"Context manager initialization failed: {e}")
            self.context_manager = None

        logger.info(f"AWSMCPLambdaClient initialized for region: {region}")

    # ... [Keep all your existing methods from _init_session through all the tool implementations] ...

    def process_query_with_context(self, query: str, session_id: Optional[str] = None) -> Dict:
        """Process a query with context awareness"""
        start_time = time.time()
        logger.info(f"Processing query with context: {query[:100]}...")

        # Extract and update context if session_id provided
        context_info = ""
        if session_id and self.context_manager:
            # Extract key points from current query
            new_key_points = self.context_manager.extract_key_points(query)

            # Get existing context
            existing_context = self.context_manager.get_context(session_id)

            # Merge contexts
            if new_key_points:
                existing_context.update(new_key_points)
                self.context_manager.update_context(session_id, existing_context)

            # Add context to system prompt if we have key points
            if existing_context:
                context_info = "\\n\\n**CURRENT CONTEXT:**\\n"
                if 'instance_id' in existing_context:
                    context_info += f"- Instance ID: {existing_context['instance_id']}\\n"
                if 'instance_type' in existing_context:
                    context_info += f"- Instance Type: {existing_context['instance_type']}\\n"
                if 'issue_types' in existing_context:
                    context_info += f"- Issues: {', '.join(existing_context['issue_types'])}\\n"

                logger.info(f"Added context to query: {context_info}")

        # Get history if available
        messages = []
        history = None

        if session_id:
            try:
                history = DynamoDBChatMessageHistory(
                    table_name=self.table_name,
                    session_id=session_id
                )
                messages = convert_history_to_messages(history)
                logger.info(f"Loaded {len(messages)} messages from history")
            except Exception as e:
                logger.warning(f"Could not load history: {e}")
                messages = []

        # Add current query with context
        query_with_context = query
        if context_info:
            query_with_context = f"{query}\\n{context_info}"

        messages.append({"role": "user", "content": [{"text": query_with_context}]})

        # Use context-aware system prompt
        system_prompt = CONTEXT_AWARE_SYSTEM_PROMPT

        # Get available tools
        tools = self.get_available_tools()

        max_iterations = 40
        iteration = 0
        tool_calls_made = []

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Conversation iteration {iteration}")

            converse_api_params = {
                "modelId": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
                "system": [{"text": system_prompt}],
                "messages": messages,
                "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
                "toolConfig": {
                    "tools": tools,
                    "toolChoice": {"auto": {}}
                },
            }

            try:
                logger.info("Applying rate limiting before Bedrock API call")
                self.rate_limit()

                logger.info("Calling Bedrock Converse API")
                response_start = time.time()
                response = bedrock_client.converse(**converse_api_params)
                response_time = time.time() - response_start
                logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")

                # Append assistant's response
                messages.append({
                    "role": "assistant",
                    "content": response['output']['message']['content']
                })

                if response['stopReason'] == "tool_use":
                    logger.info("Processing tool use requests")
                    tool_results_content = []

                    for content_item in response['output']['message']['content']:
                        if 'toolUse' in content_item:
                            tool_id = content_item['toolUse']['toolUseId']
                            tool_name = content_item['toolUse']['name']
                            tool_inputs = content_item['toolUse']['input']

                            logger.info(f"Executing tool: {tool_name} with inputs: {tool_inputs}")

                            # Execute tool call
                            try:
                                tool_result = self.execute_tool(tool_name, tool_inputs)
                                logger.info(f"Tool {tool_name} executed successfully")
                                logger.debug(f"Tool result: {tool_result[:200]}...")

                                tool_calls_made.append({
                                    "tool_name": tool_name,
                                    "inputs": tool_inputs,
                                    "result": tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
                                })

                            except Exception as tool_error:
                                logger.error(f"Tool execution failed for {tool_name}: {tool_error}")
                                tool_result = f"Error executing {tool_name}: {str(tool_error)}"

                            result_content = {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": tool_result}]
                                }
                            }
                            tool_results_content.append(result_content)

                    # Append tool results to messages
                    messages.append({
                        "role": "user",
                        "content": tool_results_content
                    })

                else:
                    # Return the final assistant's response
                    final_response = response['output']['message']['content'][0]['text']
                    processing_time = time.time() - start_time
                    logger.info(f"Query processed successfully in {processing_time:.2f} seconds")

                    # Save to history if available
                    if history and session_id:
                        try:
                            history.add_user_message(query)
                            history.add_ai_message(final_response)
                            logger.info("Saved conversation to history")
                        except Exception as e:
                            logger.warning(f"Could not save to history: {e}")

                    return {
                        "response": final_response,
                        "tool_calls": tool_calls_made,
                        "processing_time_seconds": processing_time,
                        "iterations": iteration,
                        "context": existing_context if session_id else None
                    }

            except bedrock_client.exceptions.ThrottlingException as e:
                logger.warning(f"Bedrock API throttling error: {str(e)}")
                return {
                    "error": f"Rate limit exceeded: {str(e)}",
                    "tool_calls": tool_calls_made
                }
            except Exception as bedrock_error:
                logger.error(f"Bedrock API error: {bedrock_error}")
                return {
                    "error": f"Error calling Bedrock API: {str(bedrock_error)}",
                    "tool_calls": tool_calls_made
                }

        logger.warning(f"Conversation exceeded maximum iterations ({max_iterations})")
        return {
            "response": "The conversation took too many turns. Please try a more specific query.",
            "tool_calls": tool_calls_made,
            "processing_time_seconds": time.time() - start_time,
            "iterations": max_iterations
        }

    def process_query(self, query: str) -> Dict:
        """Process a query using Claude - backward compatibility wrapper"""
        return self.process_query_with_context(query, session_id=None)

    # ... [Keep all your existing tool implementation methods] ...

def handle_slash_command(command: str, text: str, user_id: str, channel_id: str,
                        client: AWSMCPLambdaClient) -> Dict:
    """Handle Slack slash commands"""

    if command == "/aws_help":
        return {
            "response": """*AWS Operations Assistant - Available Commands*

*Basic Commands:*
• `/aws_help` - Show this help message
• `/bot_status` - Check bot and service status
• `/test` - Quick test to verify bot is responding

*Context Management:*
• `/show_context` - Display current conversation context
• `/set_context` - Manually set context (e.g., `/set_context instance_id=i-1234 instance_type=t2.micro`)
• `/clear_context` - Clear current context while keeping chat history

*Memory Management:*
• `/clear_memory` - Clear entire conversation history

*Usage Tips:*
• I maintain context about instances and issues throughout our conversation
• Use specific instance IDs when asking about AWS resources

*Example Queries:*
• "Check the status of instance i-1234567890abcdef0"
• "Show me high CPU instances in us-east-1"
• "List all CloudWatch alarms in ALARM state"
• "Get the last 10 errors from application logs"
"""
        }

    elif command == "/bot_status":
        status_info = {
            "Status": "✅ Online",
            "Region": client.region,
            "AI Model": "Claude 3.5 Sonnet",
            "Context Management": "✅ Enabled" if client.context_manager else "❌ Disabled",
            "Available Tools": len(client.get_available_tools())
        }

        response = "*🤖 AWS Operations Bot Status*\\n\\n"
        for key, value in status_info.items():
            response += f"*{key}:* {value}\\n"

        return {"response": response}

    elif command == "/test":
        return {"response": "✅ Bot is working! I can respond to your AWS queries."}

    elif command == "/show_context":
        session_id = get_session_id(user_id, channel_id)

        if client.context_manager:
            context = client.context_manager.get_context(session_id)

            if context:
                response = "*📋 Current Conversation Context*\\n\\n"
                if 'instance_id' in context:
                    response += f"• *Instance ID:* `{context['instance_id']}`\\n"
                if 'instance_type' in context:
                    response += f"• *Instance Type:* `{context['instance_type']}`\\n"
                if 'issue_types' in context:
                    response += f"• *Issue Types:* {', '.join(context['issue_types'])}\\n"
                if 'last_updated' in context:
                    response += f"• *Last Updated:* {context['last_updated']}\\n"
            else:
                response = "No context found for this conversation. Start asking about specific instances or issues!"
        else:
            response = "Context management not available."

        return {"response": response}

    elif command == "/set_context":
        session_id = get_session_id(user_id, channel_id)

        if not text:
            return {"response": "*Usage:* `/set_context instance_id=i-1234567890abcdef0 instance_type=t2.micro issue_types=high_cpu,memory`"}

        # Parse key=value pairs
        context = {}
        pairs = text.split()
        for pair in pairs:
            if '=' in pair:
                key, value = pair.split('=', 1)
                if key == 'issue_types':
                    context[key] = [v.strip() for v in value.split(',')]
                else:
                    context[key] = value

        if context and client.context_manager:
            client.context_manager.update_context(session_id, context)

            response = "✅ *Context updated successfully!*\\n\\n"
            for key, value in context.items():
                if isinstance(value, list):
                    response += f"• *{key}:* {', '.join(value)}\\n"
                else:
                    response += f"• *{key}:* `{value}`\\n"

            return {"response": response}
        else:
            return {"response": "No valid key=value pairs found. Example: `/set_context instance_id=i-1234 instance_type=t2.micro`"}

    elif command == "/clear_context":
        session_id = get_session_id(user_id, channel_id)

        if client.context_manager:
            client.context_manager.update_context(session_id, {})
            return {"response": "✅ Context cleared! Chat history is preserved."}
        else:
            return {"response": "⚠️ Context management not available."}

    elif command == "/clear_memory":
        session_id = get_session_id(user_id, channel_id)

        try:
            history = DynamoDBChatMessageHistory(
                table_name=client.table_name,
                session_id=session_id
            )
            history.clear()
            return {"response": "✅ Your conversation memory has been cleared!"}
        except Exception as e:
            logger.warning(f"Could not clear history: {e}")
            return {"response": "✅ Starting fresh conversation!"}

    else:
        return {"response": f"Unknown command: {command}"}

def lambda_handler(event, context):
    """Enhanced Lambda handler with Slack integration and context management"""
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")

    # Log memory and time limits
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, " +
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")

    # Check if this is a Slack slash command
    is_slash_command = event.get('command') and event.get('command').startswith('/')

    # Parse the request body
    try:
        if isinstance(event.get('body'), str):
            logger.info("Request body provided as string, parsing JSON")
            body = json.loads(event['body'])
        else:
            logger.info("Request body provided as object")
            body = event.get('body', event)  # Use event directly if no body

        logger.info(f"Parsed request body keys: {list(body.keys())}")

    except Exception as e:
        logger.error(f"Failed to parse request body: {str(e)}", exc_info=True)
        return {
            'statusCode': 400,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({'error': 'Invalid JSON in request body'})
        }

    # Get parameters
    query = body.get('query', body.get('text', ''))
    region = body.get('region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))

    # Extract Slack-specific parameters
    channel_id = body.get('channel_id', '')
    user_id = body.get('user_id', '')
    response_url = body.get('response_url', '')
    command = body.get('command', '')
    text = body.get('text', '')
    thread_ts = body.get('thread_ts', '')

    # Generate session ID for context management
    session_id = None
    if user_id and channel_id:
        session_id = get_session_id(user_id, channel_id, thread_ts)
        logger.info(f"Using session ID: {session_id}")

    logger.info(f"Query length: {len(query)}")
    logger.info(f"Target region: {region}")
    logger.info(f"Channel ID: {channel_id}")
    logger.info(f"Command: {command}")

    start_time = time.time()

    # Create client and process request
    try:
        logger.info("Creating AWSMCPLambdaClient instance")
        client = AWSMCPLambdaClient(region=region)

        # Handle slash commands
        if is_slash_command:
            logger.info(f"Processing slash command: {command}")
            result = handle_slash_command(command, text, user_id, channel_id, client)
        else:
            # Check if query is provided
            if not query:
                logger.warning("Missing required parameter: query")
                return {
                    'statusCode': 400,
                    'headers': {'Content-Type': 'application/json'},
                    'body': json.dumps({'error': 'Missing required parameter: query'})
                }

            # Process the query with context
            logger.info("Processing query with AWS MCP client")
            result = client.process_query_with_context(query, session_id)

        # Check for errors in result
        if 'error' in result:
            logger.error(f"Error in query processing: {result['error']}")

        # Clean up
        logger.info("Cleaning up client resources")
        client.cleanup()

        execution_time = time.time() - start_time
        logger.info(f"Lambda execution completed in {execution_time:.2f} seconds")

        # Handle Slack response formatting and sending
        if channel_id:
            logger.info("Processing Slack response")

            # Extract just the response text for Slack formatting
            response_text = result.get('response', str(result))

            # Format for Slack
            response_text = format_for_slack(response_text)

            # Add context information if available
            if result.get('context'):
                context = result['context']
                if any(k in context for k in ['instance_id', 'instance_type', 'issue_types']):
                    context_text = "\\n\\n📋 *Current Context:*\\n"
                    if 'instance_id' in context:
                        context_text += f"• Instance: `{context['instance_id']}`\\n"
                    if 'instance_type' in context:
                        context_text += f"• Type: `{context['instance_type']}`\\n"
                    if 'issue_types' in context:
                        context_text += f"• Issues: {', '.join(context['issue_types'])}\\n"
                    response_text += context_text

            # Add context about which system handled the query
            response_text += f"\\n\\n_☁️ Processed by AWS Cloud Operations System (Region: {region})_"

            # Add execution summary if tool calls were made
            if 'tool_calls' in result and result['tool_calls']:
                tool_summary = f"\\n\\n*🔧 Executed {len(result['tool_calls'])} AWS operations:*\\n"
                for i, tool_call in enumerate(result['tool_calls'], 1):
                    tool_summary += f"{i}. {tool_call.get('tool_name', 'Unknown')} "
                    if 'inputs' in tool_call:
                        inputs_str = ', '.join([f"{k}={v}" for k, v in tool_call['inputs'].items() if k != 'region'])
                        if inputs_str:
                            tool_summary += f"({inputs_str})"
                    tool_summary += "\\n"

                response_text += tool_summary

            # Add timing information
            response_text += f"\\n*⏱️ AWS processing time: {execution_time:.2f} seconds*"

            # Format for Slack using Bedrock
            try:
                bedrock_slack_result = get_bedrock_slack_result(response_text)
                send_slack_message(channel_id, bedrock_slack_result)
                logger.info("Slack message sent successfully")
            except Exception as slack_error:
                logger.error(f"Failed to send Slack message: {slack_error}")
                # Continue with normal response even if Slack fails

            # Handle event alerts
            if body.get("command") == "event-alert":
                sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
                result_conv = get_bedrock_email_result(response_text)
                email_subject, email_body = result_conv["subject"], result_conv["body"]

                if sns_topic_arn:
                    logger.info(f"[{request_id}] Sending SNS alert to: {sns_topic_arn}")
                    send_sns_alert(email_subject, email_body, sns_topic_arn)
                else:
                    logger.warning(f"[{request_id}] SNS_TOPIC_ARN not configured, skipping email alert")

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'query': query,
                'region': region,
                'result': result,
                'execution_time_seconds': execution_time,
                'request_id': request_id,
                'slack_integration': bool(channel_id),
                'session_id': session_id,
                'command': command if is_slash_command else None
            })
        }

    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        logger.info(f"Lambda execution failed after {execution_time:.2f} seconds")

        # Send error to Slack if channel_id is provided
        if channel_id:
            try:
                error_message = f"❌ *AWS Operations Error*\\n\\n```{str(e)}```\\n\\n_Request ID: {request_id}_"
                bedrock_slack_result = get_bedrock_slack_result(error_message)
                send_slack_message(channel_id, bedrock_slack_result)
            except Exception as slack_error:
                logger.error(f"Failed to send error to Slack: {slack_error}")

        return {
            'statusCode': 500,
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'error': f'Internal server error: {str(e)}',
                'execution_time_seconds': execution_time,
                'request_id': request_id
            })
        }
