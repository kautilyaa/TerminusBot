#!/usr/bin/env python3
"""AWS MCP Client with Slack and DynamoDB Integration - Enhanced with Context Management"""

import asyncio
import json
import os
import sys
import logging
import time
import re
from typing import Optional, Dict, Any, List
from contextlib import AsyncExitStack
from datetime import datetime
from mcp import ClientSession
from mcp.client.sse import sse_client
from dotenv import load_dotenv
import boto3
from botocore.config import Config
import botocore
from concurrent.futures import ThreadPoolExecutor

# Slack imports
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_community.chat_message_histories import DynamoDBChatMessageHistory

# Load environment variables
load_dotenv()

# Set up logging
def setup_logging():
    """Setup comprehensive logging configuration"""
    os.makedirs('logs', exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'logs/aws_mcp_slack_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
        ]
    )

    # Set specific logger levels
    logging.getLogger('slack_bolt').setLevel(logging.INFO)
    logging.getLogger('slack_sdk').setLevel(logging.INFO)
    logging.getLogger('boto3').setLevel(logging.INFO)
    logging.getLogger('botocore').setLevel(logging.INFO)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    return logging.getLogger(__name__)

logger = setup_logging()

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

**EXAMPLE FORMATTED RESPONSE:**
:white_check_mark: *Instance Status Check Complete*

• *Instance ID:* `i-1234567890abcdef0`
• *Type:* `t2.micro`
• *Status:* Running
• *CPU Utilization:* 85% :warning:

*Findings:*
The instance is experiencing high CPU usage. Here are the details:
Top Processes:

1. java - 75% CPU
2. mysql - 8% CPU
*Recommendations:*
1. Consider upgrading to a larger instance type
2. Investigate the Java application for optimization opportunities

**Core AWS Services:**
- **EC2 Management**: List, start, stop instances, and retrieve detailed instance information
- **CloudWatch Monitoring**: Check alarms, metrics, and dashboards
- **SSM Operations**: Run commands, check connectivity, and manage patches
- **S3 Operations**: Manage buckets and objects
- **RDS Database Management**: Monitor database instances

**Important**: You have access to real-time AWS data through MCP tools. Always use these tools to get accurate information rather than making assumptions."""

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
            r'instance[:\s]+([a-zA-Z0-9\-_]+)',  # Instance name
        ]
        
        # Instance type patterns
        type_patterns = [
            r'([tcmrpxgadni][0-9]\.[a-z0-9]+)',  # EC2 instance types
            r'instance type[:\s]+([a-zA-Z0-9\.]+)',
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

class AWSMCPSlackClient:
    def __init__(self, region: str = 'us-east-1', mcp_server_url: Optional[str] = None):
        """Initialize the AWS MCP Client with Slack and DynamoDB support"""
        self.region = region
        self.mcp_server_url = mcp_server_url
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.event_loop = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        
        # Initialize AWS clients
        self._init_aws_clients()
        
        # Initialize Slack app if tokens are present
        self._init_slack_app()
        
        # DynamoDB settings
        self.table_name = os.environ.get("DYNAMODB_TABLE_NAME", "oncalltable")
        self._ensure_dynamodb_table()
        
        # Initialize context manager
        self.context_manager = None
        if hasattr(self, 'dynamodb'):
            self.context_manager = ConversationContext(self.dynamodb, self.table_name)

    def _init_aws_clients(self):
        """Initialize AWS clients using IAM role"""
        try:
            # Create a session that will use IAM roles
            boto3_session = boto3.Session()
            
            # Configure retry settings
            config = Config(
                region_name=self.region,
                retries={'max_attempts': 3, 'mode': 'adaptive'},
                max_pool_connections=50
            )
            
            self.bedrock_client = boto3_session.client(
                service_name='bedrock-runtime',
                config=config
            )
            
            self.dynamodb = boto3.resource("dynamodb", config=config)
            self.dynamodb_client = boto3.client("dynamodb", config=config)
            
            # Test the connection
            sts_client = boto3_session.client('sts')
            identity = sts_client.get_caller_identity()
            logger.info(f"Successfully initialized AWS clients. Account: {identity.get('Account')}, ARN: {identity.get('Arn')}")
            
        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {e}")
            raise

    def _init_slack_app(self):
        """Initialize Slack app if tokens are available"""
        self.slack_app = None
        self.slack_handler = None
        
        slack_bot_token = os.environ.get("SLACK_BOT_TOKEN")
        slack_app_token = os.environ.get("SLACK_APP_TOKEN")
        
        if slack_bot_token and slack_app_token:
            try:
                self.slack_app = App(token=slack_bot_token)
                self._setup_slack_handlers()
                logger.info("Slack app initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Slack app: {e}")
                logger.info("Continuing without Slack integration")
        else:
            logger.info("Slack tokens not found, running without Slack integration")

    def _ensure_dynamodb_table(self):
        """Ensure DynamoDB table exists with correct schema"""
        try:
            logger.info(f"Checking DynamoDB table: {self.table_name}")
            
            # First, check if table exists
            try:
                table = self.dynamodb.Table(self.table_name)
                table.load()
                logger.info(f"✅ DynamoDB table already exists: {self.table_name}")
                
                # Verify the schema
                key_schema = table.key_schema
                if key_schema[0]['AttributeName'] != 'SessionId':
                    logger.warning("Table exists but with different schema. Consider creating a new table.")
                    
            except self.dynamodb.meta.client.exceptions.ResourceNotFoundException:
                # Table doesn't exist, create it
                logger.info(f"Creating DynamoDB table: {self.table_name}")
                table = self.dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[
                        {
                            'AttributeName': 'SessionId',
                            'KeyType': 'HASH'
                        }
                    ],
                    AttributeDefinitions=[
                        {
                            'AttributeName': 'SessionId',
                            'AttributeType': 'S'
                        }
                    ],
                    BillingMode='PAY_PER_REQUEST'
                )
                
                # Wait for table to be created
                table.wait_until_exists()
                logger.info(f"✅ Created DynamoDB table: {self.table_name}")
                
        except Exception as e:
            logger.error(f"DynamoDB table error: {e}")
            # Don't raise - allow bot to work without history
            logger.warning("Bot will continue without conversation history")

    async def connect_to_sse_server(self, server_url: str):
        """Connect to an MCP server running with SSE transport"""
        try:
            logger.info(f"🔌 Attempting to connect to MCP server at {server_url}")
            
            self._streams_context = sse_client(url=server_url)
            logger.debug("Created SSE client context")
            
            streams = await self._streams_context.__aenter__()
            logger.debug("Established SSE streams")
            
            self._session_context = ClientSession(*streams)
            logger.debug("Created MCP client session")
            
            self.session = await self._session_context.__aenter__()
            logger.debug("Entered MCP session context")
            
            await self.session.initialize()
            logger.info("✅ Successfully initialized MCP client session")
            
            response = await self.session.list_tools()
            tools = response.tools
            tool_names = [tool.name for tool in tools]
            logger.info(f"🛠️ Connected to server with {len(tools)} tools")
            logger.debug(f"Available tools: {tool_names}")
            print(f"\n✅ Connected to AWS MCP Server with {len(tools)} tools")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to MCP server: {e}", exc_info=True)
            raise

    async def cleanup(self):
        """Properly clean up the session and streams"""
        try:
            if hasattr(self, '_session_context') and self._session_context:
                await self._session_context.__aexit__(None, None, None)
                logger.info("Cleaned up MCP session")
            if hasattr(self, '_streams_context') and self._streams_context:
                await self._streams_context.__aexit__(None, None, None)
                logger.info("Cleaned up MCP streams")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def get_session_id(self, user_id: str, channel_id: str, thread_ts: Optional[str] = None) -> str:
        """Create unique session ID"""
        session_id = f"slack_{user_id}_{channel_id}_{thread_ts}" if thread_ts else f"slack_{user_id}_{channel_id}"
        logger.debug(f"Generated session ID: {session_id}")
        return session_id

    def convert_history_to_messages(self, history) -> list:
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
    
    def format_for_slack(self, text: str) -> str:
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
        text = re.sub(r'(i-[0-9a-f]{8,17})', r'`\1`', text)
        
        # Format instance types
        text = re.sub(r'([tcmrpxgadni][0-9]\.[a-z0-9]+)', r'`\1`', text)
        
        # Format IP addresses
        text = re.sub(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', r'`\1`', text)
        
        # Add line breaks for better readability (but not after every period)
        # Only add breaks after periods followed by capital letters
        text = re.sub(r'\. ([A-Z])', r'.\n\1', text)
        
        return text

    async def process_query_with_history(self, query: str, session_id: str) -> str:
        """Process a query using Claude, available tools, and chat history"""
        try:
            logger.info(f"🔄 Processing query with history for session: {session_id}")
            logger.info(f"📝 User Query: {query}")
            
            # Extract and update context
            context_info = ""
            if self.context_manager:
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
                    context_info = "\n\n**CURRENT CONTEXT:**\n"
                    if 'instance_id' in existing_context:
                        context_info += f"- Instance ID: {existing_context['instance_id']}\n"
                    if 'instance_type' in existing_context:
                        context_info += f"- Instance Type: {existing_context['instance_type']}\n"
                    if 'issue_types' in existing_context:
                        context_info += f"- Issues: {', '.join(existing_context['issue_types'])}\n"
                    
                    logger.info(f"Added context to query: {context_info}")
            
            # Initialize history - wrap in try/catch to handle DynamoDB errors
            history = None
            messages = []
            
            try:
                # Try to use DynamoDB history
                history = DynamoDBChatMessageHistory(
                    table_name=self.table_name,
                    session_id=session_id
                )
                messages = self.convert_history_to_messages(history)
                logger.info(f"📚 Loaded {len(messages)} messages from history")
            except Exception as db_error:
                logger.warning(f"Error accessing chat history: {db_error}. Starting fresh conversation.")
                messages = []
                history = None
            
            # Add current message with context
            query_with_context = query
            if context_info:
                query_with_context = f"{query}\n{context_info}"
            
            messages.append({"role": "user", "content": [{"text": query_with_context}]})
            logger.debug(f"💬 Total messages for Bedrock: {len(messages)}")
            
            # Get available tools from MCP server if connected
            tools = []
            tool_names = []
            if self.session:
                try:
                    logger.debug("🛠️ Fetching available tools from MCP server")
                    start_time = time.time()
                    
                    response = await asyncio.wait_for(
                        self.session.list_tools(), 
                        timeout=30
                    )
                    
                    tools_fetch_time = time.time() - start_time
                    logger.info(f"🔧 Fetched {len(response.tools)} tools in {tools_fetch_time:.2f}s")
                    
                    tools = [
                        {
                            "toolSpec": {
                                "name": tool.name,
                                "description": tool.description,
                                "inputSchema": {
                                    "json": tool.inputSchema
                                }
                            }
                        }
                        for tool in response.tools
                    ]
                    tool_names = [tool.name for tool in response.tools]
                    logger.info(f"🔧 Using {len(tools)} tools for query processing")
                    logger.debug(f"Available tools: {tool_names[:10]}{'...' if len(tool_names) > 10 else ''}")
                    
                except asyncio.TimeoutError:
                    logger.error("⏰ Timeout fetching tools from MCP server")
                    return "Sorry, there was a timeout connecting to the AWS tools. Please try again."
                except Exception as e:
                    logger.warning(f"Could not get tools: {e}")
            else:
                logger.warning("⚠️ No MCP session available - operating without tools")
            
            # Use context-aware system prompt
            system_prompt = CONTEXT_AWARE_SYSTEM_PROMPT
            logger.debug(f"Using context-aware system prompt")
            
            # Conversation loop
            max_iterations = 10
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"🔄 Conversation iteration {iteration}/{max_iterations}")
                
                # Try different model IDs
                model_ids = [
                    "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
                    "anthropic.claude-3-sonnet-20240229-v1:0",
                    "anthropic.claude-3-haiku-20240307-v1:0"
                ]
                
                response = None
                last_error = None
                
                for model_id in model_ids:
                    try:
                        converse_api_params = {
                            "modelId": model_id,
                            "system": [{"text": system_prompt}],
                            "messages": messages,
                            "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
                        }
                        
                        if tools:
                            converse_api_params["toolConfig"] = {
                                "tools": tools,
                                "toolChoice": {"auto": {}}
                            }
                        
                        logger.info(f"🧠 Calling Bedrock Converse API with model: {model_id}")
                        logger.debug(f"Request params: messages={len(messages)}, tools={len(tools)}")
                        
                        bedrock_start_time = time.time()
                        
                        # Create a sync wrapper for bedrock call
                        def call_bedrock():
                            return self.bedrock_client.converse(**converse_api_params)
                        
                        # Add timeout for Bedrock call
                        response = await asyncio.wait_for(
                            asyncio.to_thread(call_bedrock),
                            timeout=60
                        )
                        
                        bedrock_time = time.time() - bedrock_start_time
                        logger.info(f"✅ Successfully got response from model: {model_id} in {bedrock_time:.2f}s")
                        logger.debug(f"Response stop reason: {response.get('stopReason')}")
                        break
                        
                    except asyncio.TimeoutError:
                        logger.error(f"⏰ Timeout calling Bedrock model {model_id}")
                        last_error = f"Timeout calling model {model_id}"
                        continue
                    except Exception as e:
                        last_error = e
                        logger.warning(f"❌ Failed with model {model_id}: {str(e)}")
                        continue
                
                if not response:
                    error_msg = f"All AI models failed or timed out. Last error: {str(last_error)}"
                    logger.error(error_msg)
                    return f"I'm sorry, I couldn't process your request due to AI service issues. Please try again. Error: {str(last_error)}"
                
                # Add assistant's response to messages
                messages.append({
                    "role": "assistant",
                    "content": response['output']['message']['content']
                })
                
                if response['stopReason'] == "tool_use" and self.session:
                    logger.info("🔧 Processing tool use requests")
                    tool_results_content = []
                    
                    for content_item in response['output']['message']['content']:
                        if 'toolUse' in content_item:
                            tool_id = content_item['toolUse']['toolUseId']
                            tool_name = content_item['toolUse']['name']
                            tool_inputs = content_item['toolUse']['input']
                            
                            logger.info(f"🛠️ Bedrock chose tool: {tool_name}")
                            logger.info(f"📝 With parameters: {json.dumps(tool_inputs, indent=2)}")
                            logger.info(f"⏰ Starting tool execution at {datetime.now()}")
                            
                            try:
                                start_time = time.time()
                                
                                tool_result = await asyncio.wait_for(
                                    self.session.call_tool(tool_name, tool_inputs), 
                                    timeout=45
                                )
                                
                                execution_time = time.time() - start_time
                                result_text = tool_result[0].text if isinstance(tool_result, list) and tool_result else str(tool_result)
                                
                                logger.info(f"✅ Tool {tool_name} executed successfully in {execution_time:.2f}s")
                                logger.info(f"📊 Result length: {len(result_text)} characters")
                                logger.debug(f"Tool result preview: {result_text[:200]}...")
                                
                            except asyncio.TimeoutError:
                                logger.error(f"⏰ Tool {tool_name} timed out after 45 seconds")
                                result_text = f"Tool {tool_name} timed out. This might indicate a server issue. Please try again."
                                
                            except Exception as tool_error:
                                logger.error(f"❌ Tool execution failed for {tool_name}: {tool_error}", exc_info=True)
                                result_text = f"Error executing {tool_name}: {str(tool_error)}"
                            
                            result_content = {
                                "toolResult": {
                                    "toolUseId": tool_id,
                                    "content": [{"text": result_text}]
                                }
                            }
                            tool_results_content.append(result_content)
                    
                    # Send tool results back to Claude
                    messages.append({
                        "role": "user",
                        "content": tool_results_content
                    })
                    
                    logger.info(f"📤 Sent {len(tool_results_content)} tool results back to Claude")
                    
                else:
                    # Return the final assistant's response
                    final_response = response['output']['message']['content'][0]['text']
                    logger.info(f"✅ Got final response from Claude ({len(final_response)} chars)")
                    
                    # Format for Slack if this is a Slack session
                    if "slack_" in session_id:
                        final_response = self.format_for_slack(final_response)
                    
                    # Save to history if available
                    if history:
                        try:
                            history.add_user_message(query)
                            history.add_ai_message(final_response)
                            logger.info("💾 Saved conversation to history")
                        except Exception as e:
                            logger.warning(f"Could not save to history: {e}")
                    
                    logger.info("🎉 Query processed successfully")
                    return final_response
            
            logger.warning(f"⚠️ Conversation exceeded maximum iterations ({max_iterations})")
            return "The conversation took too many steps. Please try a more specific query."
            
        except Exception as e:
            logger.error(f"💥 Error processing query: {e}", exc_info=True)
            return f"An error occurred while processing your query: {str(e)}"

    def _run_async(self, coro):
        """Run async coroutine in the event loop"""
        try:
            if self.event_loop and self.event_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(coro, self.event_loop)
                return future.result(timeout=300)  # 5 minute timeout
            else:
                # Fallback to creating new event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()
        except Exception as e:
            logger.error(f"Error running async coroutine: {e}")
            raise

    def _setup_slack_handlers(self):
        """Setup Slack event handlers"""
        
        @self.slack_app.event("app_mention")
        def handle_app_mention(event, say, client, logger):
            """Handle when bot is mentioned"""
            try:
                logger.info(f"📢 App mention received from user {event['user']} in channel {event['channel']}")
                
                # Remove the bot mention from the text
                text = event['text']
                text = text.split('>', 1)[1].strip() if '>' in text else text
                logger.info(f"📝 Processed text: '{text}'")
                
                # Process message synchronously by running async code
                self._process_slack_message_sync(event, text, say, client, is_mention=True)
            except Exception as e:
                logger.error(f"Error in app_mention: {e}", exc_info=True)
                say("Sorry, I encountered an error processing your mention.")
        
        @self.slack_app.message("")
        def handle_direct_message(message, say, client, logger):
            """Handle direct messages"""
            try:
                # Skip bot messages
                if message.get('bot_id'):
                    logger.debug("Skipping bot message")
                    return
                
                # Skip message subtypes we don't want to process
                if message.get('subtype') in ['message_changed', 'message_deleted', 'message_replied']:
                    logger.debug(f"Skipping message subtype: {message.get('subtype')}")
                    return
                
                # Only respond to direct messages (not channel messages)
                if message.get('channel_type') == 'im':
                    text = message.get('text', '')
                    if not text:
                        logger.warning("Received message with no text")
                        return
                        
                    logger.info(f"💬 Direct message received from user {message['user']}: '{text}'")
                    self._process_slack_message_sync(message, text, say, client, is_mention=False)
                else:
                    logger.debug(f"Non-direct message ignored: channel_type={message.get('channel_type')}")
            except Exception as e:
                logger.error(f"Error in direct message: {e}", exc_info=True)
                try:
                    say("Sorry, I encountered an error processing your message.")
                except:
                    logger.error("Could not send error message")
        
        # Add handler for message_changed events to suppress warnings
        @self.slack_app.event("message")
        def handle_message_events(body, logger):
            """Handle all message events including subtypes"""
            event = body.get("event", {})
            subtype = event.get("subtype")
            
            if subtype == "message_changed":
                logger.debug("Received message_changed event")
            elif subtype:
                logger.debug(f"Received message event with subtype: {subtype}")
        
        @self.slack_app.command("/aws_help")
        def aws_help_command(ack, respond):
            """Show available commands and usage"""
            ack()
            help_text = """
*AWS Operations Assistant - Available Commands*

*Basic Commands:*
• `/aws_help` - Show this help message
• `/bot_status` - Check bot and service status
• `/test` - Quick test to verify bot is responding

*MCP Server Commands:*
• `/test_mcp` - Test MCP server connection and list tools
• `/list_tools` - List all available AWS tools

*Context Management:*
• `/show_context` - Display current conversation context
• `/set_context` - Manually set context (e.g., `/set_context instance_id=i-1234 instance_type=t2.micro`)
• `/clear_context` - Clear current context while keeping chat history

*Memory Management:*
• `/clear_memory` - Clear entire conversation history
• `/export_chat` - Export conversation history

*Usage Tips:*
• Mention me with @bot_name in channels or DM me directly
• I maintain context about instances and issues throughout our conversation
• Use specific instance IDs when asking about AWS resources

*Example Queries:*
• "Check the status of instance i-1234567890abcdef0"
• "Show me high CPU instances in us-east-1"
• "List all CloudWatch alarms in ALARM state"
• "Get the last 10 errors from application logs"
            """
            respond(help_text)
        
        @self.slack_app.command("/test_mcp")
        def test_mcp_command(ack, respond):
            """Test MCP server connection"""
            ack()
            try:
                logger.info("🧪 Testing MCP server connection")
                
                if not self.session:
                    respond("❌ No MCP session available")
                    return
                
                # Test 1: List available tools
                try:
                    tools_response = self._run_async(self.session.list_tools())
                    tool_count = len(tools_response.tools)
                    tool_names = [tool.name for tool in tools_response.tools[:10]]
                    
                    status_msg = f"✅ *MCP Server Connected!*\n\n"
                    status_msg += f"🛠️ *Found {tool_count} tools*\n\n"
                    status_msg += f"*Sample tools:*\n"
                    for tool_name in tool_names:
                        status_msg += f"• `{tool_name}`\n"
                    
                    if tool_count > 10:
                        status_msg += f"\n_...and {tool_count - 10} more tools_"
                        
                    respond(status_msg)
                    
                except Exception as e:
                    logger.error(f"Error listing tools: {e}")
                    respond(f"❌ Error listing tools: {str(e)}")
                    
            except Exception as e:
                logger.error(f"MCP test failed: {e}", exc_info=True)
                respond(f"❌ MCP test failed: {str(e)}")
        
        @self.slack_app.command("/list_tools")
        def list_tools_command(ack, respond):
            """List all available MCP tools"""
            ack()
            try:
                if not self.session:
                    respond("❌ No MCP session available")
                    return
                
                tools_response = self._run_async(self.session.list_tools())
                tools = tools_response.tools
                
                # Group tools by category
                tool_categories = {
                    'EC2': [],
                    'CloudWatch': [],
                    'S3': [],
                    'RDS': [],
                    'SSM': [],
                    'Other': []
                }
                
                for tool in tools:
                    name = tool.name.lower()
                    if 'ec2' in name or 'instance' in name:
                        tool_categories['EC2'].append(tool)
                    elif 'cloudwatch' in name or 'alarm' in name or 'metric' in name:
                        tool_categories['CloudWatch'].append(tool)
                    elif 's3' in name or 'bucket' in name:
                        tool_categories['S3'].append(tool)
                    elif 'rds' in name or 'database' in name:
                        tool_categories['RDS'].append(tool)
                    elif 'ssm' in name:
                        tool_categories['SSM'].append(tool)
                    else:
                        tool_categories['Other'].append(tool)
                
                response = f"*Available AWS Tools ({len(tools)} total)*\n\n"
                
                for category, category_tools in tool_categories.items():
                    if category_tools:
                        response += f"*{category} Tools ({len(category_tools)}):*\n"
                        for tool in category_tools[:5]:  # Show first 5 in each category
                            response += f"• `{tool.name}` - {tool.description[:50]}...\n"
                        if len(category_tools) > 5:
                            response += f"  _...and {len(category_tools) - 5} more_\n"
                        response += "\n"
                
                respond(response)
                
            except Exception as e:
                logger.error(f"Error listing tools: {e}", exc_info=True)
                respond(f"❌ Error listing tools: {str(e)}")
        
        @self.slack_app.command("/clear_memory")
        def clear_memory_command(ack, respond, command):
            """Clear conversation memory"""
            ack()
            try:
                user_id = command['user_id']
                channel_id = command['channel_id']
                session_id = self.get_session_id(user_id, channel_id)
                
                logger.info(f"🗑️ Clearing memory for session: {session_id}")
                
                # Clear the conversation history
                try:
                    history = DynamoDBChatMessageHistory(table_name=self.table_name, session_id=session_id)
                    history.clear()
                    respond("✅ Your conversation memory has been cleared!")
                    logger.info("Memory cleared successfully")
                except Exception as e:
                    logger.warning(f"Could not clear history: {e}")
                    respond("✅ Starting fresh conversation!")
                    
            except Exception as e:
                logger.error(f"Error clearing memory: {e}", exc_info=True)
                respond(f"❌ Error clearing memory: {str(e)}")
        
        @self.slack_app.command("/clear_context")
        def clear_context_command(ack, respond, command):
            """Clear just the context while keeping chat history"""
            ack()
            try:
                user_id = command['user_id']
                channel_id = command['channel_id']
                session_id = self.get_session_id(user_id, channel_id)
                
                if self.context_manager:
                    self.context_manager.update_context(session_id, {})
                    respond("✅ Context cleared! Chat history is preserved.")
                else:
                    respond("⚠️ Context management not available.")
                    
            except Exception as e:
                logger.error(f"Error clearing context: {e}", exc_info=True)
                respond(f"❌ Error clearing context: {str(e)}")
        
        @self.slack_app.command("/bot_status")
        def bot_status_command(ack, respond):
            """Check bot status"""
            ack()
            try:
                logger.info("📊 Bot status check requested")
                
                status_blocks = [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🤖 AWS Operations Bot Status"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": "*Status:* ✅ Online"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Region:* `{self.region}`"
                            },
                            {
                                "type": "mrkdwn",
                                "text": "*AI Model:* Claude 3 Sonnet"
                            }
                        ]
                    }
                ]
                
                # Test DynamoDB
                try:
                    table = self.dynamodb.Table(self.table_name)
                    table.load()
                    dynamodb_status = "✅ Connected"
                    table_status = f"`{self.table_name}`"
                except:
                    dynamodb_status = "⚠️ Error (bot works without history)"
                    table_status = "N/A"
                
                status_blocks.append({
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*DynamoDB:* {dynamodb_status}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Table:* {table_status}"
                        }
                    ]
                })
                
                # MCP Status
                if self.session:
                    try:
                        response = self._run_async(self.session.list_tools())
                        mcp_status = "✅ Connected"
                        tools_count = f"{len(response.tools)} tools"
                    except:
                        mcp_status = "⚠️ Error"
                        tools_count = "Unable to fetch"
                else:
                    mcp_status = "❌ Not connected"
                    tools_count = "N/A"
                
                status_blocks.append({
                    "type": "section",
                    "fields": [
                        {
                            "type": "mrkdwn",
                            "text": f"*MCP Server:* {mcp_status}"
                        },
                        {
                            "type": "mrkdwn",
                            "text": f"*Available Tools:* {tools_count}"
                        }
                    ]
                })
                
                # Context manager status
                if self.context_manager:
                    context_status = "✅ Enabled"
                else:
                    context_status = "❌ Disabled"
                
                status_blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Context Management:* {context_status}"
                    }
                })
                
                status_blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Last checked: <!date^{int(time.time())}^{{date_short_pretty}} at {{time}}|{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}>"
                        }
                    ]
                })
                
                respond(blocks=status_blocks)
                logger.info("Bot status check completed successfully")
                
            except Exception as e:
                logger.error(f"Bot status check failed: {e}", exc_info=True)
                respond(f"❌ Status check failed: {str(e)}")
        
        @self.slack_app.command("/test")
        def test_command(ack, respond):
            """Test command to verify bot is responding"""
            ack()
            respond("✅ Bot is working! I can respond to your messages.")
            logger.info("Test command executed successfully")
        
        @self.slack_app.command("/show_context")
        def show_context_command(ack, respond, command):
            """Show current conversation context"""
            ack()
            try:
                user_id = command['user_id']
                channel_id = command['channel_id']
                session_id = self.get_session_id(user_id, channel_id)
                
                if self.context_manager:
                    context = self.context_manager.get_context(session_id)
                    
                    if context:
                        response_blocks = [
                            {
                                "type": "header",
                                "text": {
                                    "type": "plain_text",
                                    "text": "📋 Current Conversation Context"
                                }
                            }
                        ]
                        
                        fields = []
                        if 'instance_id' in context:
                            fields.append({
                                "type": "mrkdwn",
                                "text": f"*Instance ID:* `{context['instance_id']}`"
                            })
                        if 'instance_type' in context:
                            fields.append({
                                "type": "mrkdwn",
                                "text": f"*Instance Type:* `{context['instance_type']}`"
                            })
                        
                        if fields:
                            response_blocks.append({
                                "type": "section",
                                "fields": fields
                            })
                        
                        if 'issue_types' in context:
                            response_blocks.append({
                                "type": "section",
                                "text": {
                                    "type": "mrkdwn",
                                    "text": f"*Issue Types:* {', '.join(context['issue_types'])}"
                                }
                            })
                        
                        if 'last_updated' in context:
                            response_blocks.append({
                                "type": "context",
                                "elements": [{
                                    "type": "mrkdwn",
                                    "text": f"Last updated: {context['last_updated']}"
                                }]
                            })
                        
                        respond(blocks=response_blocks)
                    else:
                        respond("No context found for this conversation. Start asking about specific instances or issues!")
                else:
                    respond("Context management not available.")
                
            except Exception as e:
                logger.error(f"Error showing context: {e}", exc_info=True)
                respond(f"❌ Error showing context: {str(e)}")

        @self.slack_app.command("/set_context")
        def set_context_command(ack, respond, command):
            """Manually set context"""
            ack()
            try:
                user_id = command['user_id']
                channel_id = command['channel_id']
                session_id = self.get_session_id(user_id, channel_id)
                
                text = command.get('text', '')
                
                if not text:
                    respond("*Usage:* `/set_context instance_id=i-1234567890abcdef0 instance_type=t2.micro issue_types=high_cpu,memory`")
                    return
                
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
                
                if context and self.context_manager:
                    self.context_manager.update_context(session_id, context)
                    
                    response = "✅ *Context updated successfully!*\n\n"
                    for key, value in context.items():
                        if isinstance(value, list):
                            response += f"• *{key}:* {', '.join(value)}\n"
                        else:
                            response += f"• *{key}:* `{value}`\n"
                    
                    respond(response)
                else:
                    respond("No valid key=value pairs found. Example: `/set_context instance_id=i-1234 instance_type=t2.micro`")
                    
            except Exception as e:
                logger.error(f"Error setting context: {e}", exc_info=True)
                respond(f"❌ Error setting context: {str(e)}")
        
        @self.slack_app.command("/export_chat")
        def export_chat_command(ack, respond, command, client):
            """Export conversation history"""
            ack()
            try:
                user_id = command['user_id']
                channel_id = command['channel_id']
                session_id = self.get_session_id(user_id, channel_id)
                
                # Get chat history
                history = DynamoDBChatMessageHistory(
                    table_name=self.table_name,
                    session_id=session_id
                )
                
                messages = history.messages
                if not messages:
                    respond("No conversation history found.")
                    return
                
                # Format messages
                export_text = f"# Conversation Export\n"
                export_text += f"Session: {session_id}\n"
                export_text += f"Exported: {datetime.now().isoformat()}\n"
                export_text += f"Total Messages: {len(messages)}\n"
                export_text += "-" * 50 + "\n\n"
                
                for i, msg in enumerate(messages):
                    if isinstance(msg, HumanMessage):
                        export_text += f"**User ({i+1}):**\n{msg.content}\n\n"
                    elif isinstance(msg, AIMessage):
                        export_text += f"**Assistant ({i+1}):**\n{msg.content}\n\n"
                    export_text += "-" * 30 + "\n\n"
                
                # Upload as file
                client.files_upload_v2(
                    channels=[channel_id],
                    content=export_text,
                    filename=f"chat_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
                    title="Conversation Export",
                    initial_comment="Here's your conversation history export:"
                )
                
                logger.info(f"Exported chat history for session: {session_id}")
                
            except Exception as e:
                logger.error(f"Error exporting chat: {e}", exc_info=True)
                respond(f"❌ Error exporting chat: {str(e)}")

    def _process_slack_message_sync(self, event, text, say, client, is_mention):
        """Process Slack message synchronously"""
        try:
            user_id = event['user']
            channel_id = event['channel']
            thread_ts = event.get('thread_ts')
            
            logger.info(f"🔄 Processing message from user {user_id} in channel {channel_id}")
            
            # Get session ID
            session_id = self.get_session_id(user_id, channel_id, thread_ts)
            
            # Show typing indicator with context awareness
            typing_msg = None
            try:
                # Get current context for the typing message
                context_info = ""
                if self.context_manager:
                    context = self.context_manager.get_context(session_id)
                    if context.get('instance_id'):
                        context_info = f" (Context: `{context.get('instance_id')}`)"
                
                typing_msg = client.chat_postMessage(
                    channel=channel_id,
                    text=f"🤔 Thinking{context_info}...",
                    thread_ts=thread_ts if thread_ts else event.get('ts')
                )
                logger.debug("Posted typing indicator")
            except Exception as e:
                logger.warning(f"Failed to post typing indicator: {e}")
            
            try:
                # Process the query using async function
                logger.info(f"🚀 Processing query: {text}")
                start_time = time.time()
                
                response = self._run_async(self.process_query_with_history(text, session_id))
                
                processing_time = time.time() - start_time
                logger.info(f"✅ Got response in {processing_time:.2f}s")
                
                # Delete typing indicator if it was posted
                if typing_msg:
                    try:
                        client.chat_delete(
                            channel=channel_id,
                            ts=typing_msg['ts']
                        )
                    except Exception as e:
                        logger.debug(f"Could not delete typing indicator: {e}")
                
                # Ensure response is properly formatted
                if not response or not isinstance(response, str):
                    response = "I couldn't generate a response. Please try again."
                    logger.error(f"Invalid response type: {type(response)}")
                
                # Create response blocks
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": response
                        }
                    }
                ]
                
                # Add context block if available
                if self.context_manager:
                    context = self.context_manager.get_context(session_id)
                    if context and any(k in context for k in ['instance_id', 'instance_type', 'issue_types']):
                        context_elements = []
                        
                        if 'instance_id' in context:
                            context_elements.append(f"Instance: `{context['instance_id']}`")
                        if 'instance_type' in context:
                            context_elements.append(f"Type: `{context['instance_type']}`")
                        if 'issue_types' in context:
                            context_elements.append(f"Issues: {', '.join(context['issue_types'])}")
                        
                        if context_elements:
                            blocks.append({
                                "type": "context",
                                "elements": [{
                                    "type": "mrkdwn",
                                    "text": " | ".join(context_elements)
                                }]
                            })
                
                # Send response with blocks
                result = client.chat_postMessage(
                    channel=channel_id,
                    blocks=blocks,
                    text=response,  # Fallback text
                    thread_ts=thread_ts if thread_ts else event.get('ts')
                )
                logger.info(f"📤 Response sent successfully")
                
            except Exception as e:
                logger.error(f"💥 Error getting response: {e}", exc_info=True)
                
                # Delete typing indicator on error
                if typing_msg:
                    try:
                        client.chat_delete(
                            channel=channel_id,
                            ts=typing_msg['ts']
                        )
                    except:
                        pass
                
                # Send error message
                error_msg = f"Sorry, I encountered an error: {str(e)}"
                say(
                    text=error_msg,
                    thread_ts=thread_ts if thread_ts else event.get('ts')
                )
                
        except Exception as e:
            logger.error(f"💥 Error processing message: {e}", exc_info=True)
            try:
                say("Sorry, I encountered an error processing your message.")
            except:
                logger.error("Could not send error message to Slack")

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nAWS MCP Client Started!")
        print("Available commands:")
        print("- Type your AWS-related queries")
        print("- 'quit' or 'exit' to quit")
        print("- 'tools' to list available tools")
        print("- 'clear' to clear conversation history")
        print("- 'context' to show current context")
        print("- 'test' to test MCP connection")
        print("-" * 50)
        
        # Create a session ID for CLI usage
        cli_session_id = "cli_user_default"
        
        while True:
            try:
                query = input("\nAWS Query: ").strip()
                
                if query.lower() in ['quit', 'exit']:
                    print("Goodbye!")
                    break
                
                elif query.lower() == 'tools':
                    if self.session:
                        try:
                            response = await self.session.list_tools()
                            tools = response.tools
                            print(f"\nAvailable tools ({len(tools)}):")
                            for tool in tools:
                                print(f"- {tool.name}: {tool.description}")
                        except Exception as e:
                            print(f"Error listing tools: {e}")
                    else:
                        print("No MCP server connected")
                    continue
                
                elif query.lower() == 'context':
                    if self.context_manager:
                        context = self.context_manager.get_context(cli_session_id)
                        if context:
                            print("\nCurrent Context:")
                            for key, value in context.items():
                                print(f"- {key}: {value}")
                        else:
                            print("No context set")
                    else:
                        print("Context management not available")
                    continue
                
                elif query.lower() == 'test':
                    if self.session:
                        try:
                            print("Testing MCP connection...")
                            tools_response = await self.session.list_tools()
                            print(f"✅ MCP Server connected with {len(tools_response.tools)} tools")
                            
                            # Try a simple tool if available
                            if tools_response.tools:
                                test_tool = tools_response.tools[0]
                                print(f"Testing tool: {test_tool.name}")
                                result = await self.session.call_tool(test_tool.name, {})
                                print(f"✅ Tool test successful!")
                        except Exception as e:
                            print(f"❌ MCP test failed: {e}")
                    else:
                        print("❌ No MCP server connected")
                    continue
                
                elif query.lower() == 'clear':
                    try:
                        history = DynamoDBChatMessageHistory(table_name=self.table_name, session_id=cli_session_id)
                        history.clear()
                        print("Conversation history cleared!")
                    except:
                        print("Starting fresh conversation!")
                    continue
                
                elif not query:
                    continue
                
                print("\nProcessing...")
                response = await self.process_query_with_history(query, cli_session_id)
                print(f"\nResponse:\n{response}")
                
            except KeyboardInterrupt:
                print("\nOperation cancelled by user")
                break
            except Exception as e:
                logger.error(f"Error in chat loop: {e}")
                print(f"\nError: {str(e)}")

    def start_slack_bot(self):
        """Start the Slack bot in socket mode"""
        if not self.slack_app:
            logger.error("Slack app not initialized. Check SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
            return
        
        try:
            slack_app_token = os.environ.get("SLACK_APP_TOKEN")
            self.slack_handler = SocketModeHandler(self.slack_app, slack_app_token)
            logger.info("✅ Slack bot is running! Press Ctrl+C to stop.")
            
            # Start the handler
            self.slack_handler.start()
                
        except Exception as e:
            logger.error(f"Failed to start Slack bot: {e}")
            raise

async def main():
    """Main function with multiple modes"""
    import argparse
    
    parser = argparse.ArgumentParser(description='AWS MCP Client with Slack Integration')
    parser.add_argument('--slack', action='store_true', help='Run in Slack bot mode')
    parser.add_argument('--mcp-server', type=str, help='MCP Server URL (e.g., http://localhost:8002/sse)')
    parser.add_argument('--region', type=str, default='us-east-1', help='AWS region')
    
    args = parser.parse_args()
    
    # Initialize client
    client = AWSMCPSlackClient(region=args.region, mcp_server_url=args.mcp_server)
    
    try:
        if args.slack:
            # Run in Slack bot mode
            if not client.slack_app:
                logger.error("Slack integration not available. Check SLACK_BOT_TOKEN and SLACK_APP_TOKEN environment variables.")
                sys.exit(1)
            
            # Create event loop for async operations
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            client.event_loop = loop
            
            # Connect to MCP server if URL provided
            if args.mcp_server:
                await client.connect_to_sse_server(args.mcp_server)
            
            # Start Slack bot in a separate thread
            import threading
            slack_thread = threading.Thread(target=client.start_slack_bot)
            slack_thread.start()
            
            # Keep the async loop running
            await asyncio.Event().wait()
            
        else:
            # Run in CLI mode
            if args.mcp_server:
                await client.connect_to_sse_server(args.mcp_server)
            else:
                print("Warning: No MCP server specified. Running without tool access.")
                print("Use --mcp-server <URL> to connect to an MCP server.")
            
            await client.chat_loop()
    
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
        print(f"Error: {e}")
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())