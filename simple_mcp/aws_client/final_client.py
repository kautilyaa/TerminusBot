#!/usr/bin/env python3
"""AWS MCP Client with Slack and DynamoDB Integration - Enhanced Debug Version"""

import asyncio
import json
import os
import sys
import logging
import time
from typing import Optional, Dict, Any
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
        level=logging.DEBUG,  # Changed to DEBUG for more detailed logging
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
    logging.getLogger('urllib3').setLevel(logging.WARNING)  # Reduce noise
    
    return logging.getLogger(__name__)

logger = setup_logging()

# Default system prompt
with open('aws_client/common_prompt.txt', 'r') as file:
    DEFAULT_SYSTEM_PROMPT = file.read()

"""You are an expert AWS Operations Assistant with comprehensive access to AWS management tools. You can help with:

**Core AWS Services:**
- **EC2 Management**: List, start, stop instances, and retrieve detailed instance information
- **CloudWatch Monitoring**: Check alarms, metrics, and dashboards
- **SSM Operations**: Run commands, check connectivity, and manage patches
- **S3 Operations**: Manage buckets and objects
- **RDS Database Management**: Monitor database instances

**CloudWatch Capabilities:**
- Monitor and analyze CloudWatch alarms and metrics
- Get instance health status and performance data
- Search CloudWatch logs for errors and issues
- Create comprehensive health reports

**Best Practices:**
- Always use the available tools to get real AWS data
- Provide specific, actionable information
- When asked about instance status, use health_check_ec2_instance, find_ec2_by_name, or get_ec2_instance_details
- Format responses clearly with relevant details

**Important**: You have access to real-time AWS data through MCP tools. Always use these tools to get accurate information rather than making assumptions. When a user asks about an EC2 instance, first find it by name if needed, then get its details and health status."""

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
    async def process_query_with_history(self, query: str, session_id: str) -> str:
        """Process a query using Claude, available tools, and chat history"""
        try:
            logger.info(f"🔄 Processing query with history for session: {session_id}")
            logger.info(f"📝 User Query: {query}")
            
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
            
            # Add current message
            messages.append({"role": "user", "content": [{"text": query}]})
            logger.debug(f"💬 Total messages for Bedrock: {len(messages)}")
            
            # Get available tools from MCP server if connected - ONLY ONCE!
            tools = []
            tool_names = []
            if self.session:
                try:
                    logger.debug("🛠️ Fetching available tools from MCP server")
                    start_time = time.time()
                    
                    response = await asyncio.wait_for(
                        self.session.list_tools(), 
                        timeout=30  # 30 second timeout for listing tools
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
            
            # Use default system prompt
            system_prompt = DEFAULT_SYSTEM_PROMPT
            logger.debug(f"Using system prompt: {system_prompt[:100]}...")
            
            # Conversation loop
            max_iterations = 10  # Reduced from 10 to prevent long waits
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                logger.info(f"🔄 Conversation iteration {iteration}/{max_iterations}")
                
                # Try different model IDs
                model_ids = [
                    "us.anthropic.claude-sonnet-4-20250514-v1:0",
                    "anthropic.claude-instant-v1",
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
                            "inferenceConfig": {"maxTokens": 65535, "temperature": 0.1},
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
                            timeout=60  # 1 minute timeout for Bedrock
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
                                    timeout=45  # 45 second timeout per tool
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
                    tool_names = [tool.name for tool in tools_response.tools[:5]]  # First 5 tools
                    
                    status_msg = f"✅ MCP Server connected!\n"
                    status_msg += f"🛠️ Found {tool_count} tools\n"
                    status_msg += f"📋 Sample tools: {', '.join(tool_names)}"
                    
                    if tool_count > 5:
                        status_msg += f" (and {tool_count - 5} more)"
                        
                    respond(status_msg)
                    
                except Exception as e:
                    logger.error(f"Error listing tools: {e}")
                    respond(f"❌ Error listing tools: {str(e)}")
                    return
                    
                # Test 2: Try a simple tool call if available
                try:
                    # Look for a simple test tool
                    tools = tools_response.tools
                    test_tools = [t for t in tools if 'test' in t.name.lower() or t.name in ['get_aws_account_info', 'get_aws_regions']]
                    
                    if test_tools:
                        test_tool = test_tools[0]
                        logger.info(f"Testing tool: {test_tool.name}")
                        
                        test_result = self._run_async(
                            self.session.call_tool(test_tool.name, {})
                        )
                        result_text = test_result[0].text if isinstance(test_result, list) and test_result else str(test_result)
                        
                        respond(f"✅ Tool test successful!\n🔧 Tested: {test_tool.name}\n📊 Result: {result_text[:200]}...")
                    else:
                        respond("✅ MCP connection verified, but no simple test tools available")
                        
                except Exception as e:
                    logger.error(f"Error testing tool call: {e}")
                    respond(f"⚠️ MCP connected but tool test failed: {str(e)}")
                    
            except Exception as e:
                logger.error(f"MCP test failed: {e}", exc_info=True)
                respond(f"❌ MCP test failed: {str(e)}")
        
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
        
        @self.slack_app.command("/bot_status")
        def bot_status_command(ack, respond):
            """Check bot status"""
            ack()
            try:
                logger.info("📊 Bot status check requested")
                
                # Test DynamoDB connection
                status_msg = "🤖 Bot Status: Online\n"
                
                try:
                    table = self.dynamodb.Table(self.table_name)
                    table.load()
                    status_msg += f"📊 DynamoDB: Connected\n"
                    status_msg += f"🗄️ Table: {self.table_name}\n"
                except:
                    status_msg += f"📊 DynamoDB: Error (bot will work without history)\n"
                
                status_msg += f"🧠 Model: Claude 3 Sonnet\n"
                status_msg += f"🌎 Region: {self.region}\n"
                
                if self.session:
                    status_msg += "🔧 MCP Server: Connected\n"
                    try:
                        response = self._run_async(self.session.list_tools())
                        status_msg += f"🛠️ Available Tools: {len(response.tools)}"
                    except:
                        status_msg += "🛠️ Available Tools: Error getting tools"
                else:
                    status_msg += "🔧 MCP Server: Not connected"
                
                respond(status_msg)
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

    def _process_slack_message_sync(self, event, text, say, client, is_mention):
        """Process Slack message synchronously"""
        try:
            user_id = event['user']
            channel_id = event['channel']
            thread_ts = event.get('thread_ts')
            
            logger.info(f"🔄 Processing message from user {user_id} in channel {channel_id}")
            
            # Get session ID
            session_id = self.get_session_id(user_id, channel_id, thread_ts)
            
            # Show typing indicator
            typing_msg = None
            try:
                typing_msg = client.chat_postMessage(
                    channel=channel_id,
                    text="🤔 Thinking...",
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
                logger.info(f"✅ Got response in {processing_time:.2f}s: {response[:100]}...")  # Log first 100 chars
                
                # Delete typing indicator if it was posted
                if typing_msg:
                    try:
                        client.chat_delete(
                            channel=channel_id,
                            ts=typing_msg['ts']
                        )
                    except Exception as e:
                        logger.debug(f"Could not delete typing indicator: {e}")
                
                # Ensure response is a string
                if not response or not isinstance(response, str):
                    response = "I couldn't generate a response. Please try again."
                    logger.error(f"Invalid response type: {type(response)}")
                
                # Send response
                result = say(
                    text=response,
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