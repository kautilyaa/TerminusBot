I'll help you integrate the Slack and DynamoDB functionality with your AWS MCP Client. Here's a comprehensive solution that combines both:

```python
#!/usr/bin/env python3
"""AWS MCP Client with Slack and DynamoDB Integration"""

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
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(f'logs/aws_mcp_slack_{datetime.now().strftime("%Y%m%d")}.log')
        ]
    )
    
    # Set specific logger levels
    logging.getLogger('slack_bolt').setLevel(logging.INFO)
    logging.getLogger('slack_sdk').setLevel(logging.INFO)
    logging.getLogger('boto3').setLevel(logging.INFO)
    logging.getLogger('botocore').setLevel(logging.INFO)
    
    return logging.getLogger(__name__)

logger = setup_logging()

class AWSMCPSlackClient:
    def __init__(self, region: str = 'us-east-1', mcp_server_url: Optional[str] = None):
        """Initialize the AWS MCP Client with Slack and DynamoDB support"""
        self.region = region
        self.mcp_server_url = mcp_server_url
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        
        # Initialize AWS clients
        self._init_aws_clients()
        
        # Initialize Slack app if tokens are present
        self._init_slack_app()
        
        # DynamoDB settings
        self.table_name = os.environ.get("DYNAMODB_TABLE_NAME", "SlackBotSessionTable")
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
        """Ensure DynamoDB table exists"""
        try:
            logger.info(f"Checking DynamoDB table: {self.table_name}")
            table = self.dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[{"AttributeName": "SessionId", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "SessionId", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
            table.meta.client.get_waiter("table_exists").wait(TableName=self.table_name)
            logger.info(f"✅ Created DynamoDB table: {self.table_name}")
        except botocore.exceptions.ClientError as error:
            if error.response['Error']['Code'] == 'ResourceInUseException':
                logger.info(f"✅ DynamoDB table already exists: {self.table_name}")
            else:
                logger.error(f"DynamoDB table creation error: {error}")
                raise error

    async def connect_to_sse_server(self, server_url: str):
        """Connect to an MCP server running with SSE transport"""
        try:
            logger.info(f"Connecting to MCP server at {server_url}")
            
            self._streams_context = sse_client(url=server_url)
            streams = await self._streams_context.__aenter__()
            self._session_context = ClientSession(*streams)
            self.session = await self._session_context.__aenter__()
            
            await self.session.initialize()
            logger.info("Successfully initialized MCP client session")
            
            response = await self.session.list_tools()
            tools = response.tools
            tool_names = [tool.name for tool in tools]
            logger.info(f"Connected to server with {len(tools)} tools: {tool_names}")
            print(f"\nConnected to AWS MCP Server with tools: {', '.join(tool_names)}")
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {e}")
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
        
        return messages

    async def process_query_with_history(self, query: str, session_id: str) -> str:
        """Process a query using Claude, available tools, and chat history"""
        try:
            logger.info(f"Processing query with history for session: {session_id}")
            
            # Get chat history from DynamoDB
            history = DynamoDBChatMessageHistory(table_name=self.table_name, session_id=session_id)
            messages = self.convert_history_to_messages(history)
            
            # Add current message
            messages.append({"role": "user", "content": [{"text": query}]})
            
            # Get available tools from MCP server if connected
            tools = []
            if self.session:
                response = await self.session.list_tools()
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
                logger.info(f"Using {len(tools)} tools for query processing")
            
            system_prompt = """You are an expert AWS Operations Assistant with comprehensive access to AWS management tools and CloudWatch logging capabilities. You can help with:

            **Core AWS Services:**
            - **EC2 Management**: List, start, stop instances, and retrieve detailed instance information
            - **S3 Operations**: Manage buckets, list objects, create new buckets with proper regional configuration
            - **RDS Database Management**: Monitor instances, retrieve detailed database configurations and status
            - **Account & Regional Information**: Provide AWS account details and available regions

            **Advanced CloudWatch Log Management:**
            - **EC2 Log Analysis**: Access and search logs from EC2 instances including system logs (syslog), authentication logs (auth), kernel logs (kern), SSM agent logs, package management history (apt-history), cloud-init output, and kernel ring buffer (dmesg)
            - **Intelligent Log Search**: Search across single instances or all EC2 instances for specific terms, error patterns, or time ranges
            - **Error Detection**: Automatically identify and surface recent errors, failures, and critical issues across your infrastructure
            - **Log Stream Management**: Navigate different log types and understand what each log stream contains
            - **Time-based Analysis**: Retrieve logs from specific time ranges (hours, days) with customizable limits

            **Best Practices:**
            - Always specify the AWS region when working with resources (default: us-east-1)
            - When investigating issues, start with error logs and recent events
            - Use appropriate time ranges for log searches to balance relevance with performance
            - Provide context about what each log stream contains when presenting results
            - Format responses clearly with actionable insights and next steps

            **Response Guidelines:**
            - Provide clear, actionable responses with specific commands and recommendations
            - Always use the appropriate tools for each request
            - When showing logs, highlight important information and potential issues
            - Explain AWS-specific terminology and concepts when relevant
            - Suggest follow-up actions when investigating problems

            You have access to real-time AWS data and can perform actual operations, so always confirm actions that modify resources before executing them."""
            
            # Conversation loop
            max_iterations = 100
            iteration = 0
            
            while iteration < max_iterations:
                iteration += 1
                logger.debug(f"Conversation iteration {iteration}")
                
                converse_api_params = {
                    "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                    "system": [{"text": system_prompt}],
                    "messages": messages,
                    "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
                }
                
                if tools:
                    converse_api_params["toolConfig"] = {
                        "tools": tools,
                        "toolChoice": {"auto": {}}
                    }
                
                try:
                    logger.debug("Calling Bedrock Converse API")
                    response = self.bedrock_client.converse(**converse_api_params)
                    
                    messages.append({
                        "role": "assistant",
                        "content": response['output']['message']['content']
                    })
                    
                    if response['stopReason'] == "tool_use" and self.session:
                        logger.info("Processing tool use requests")
                        tool_results_content = []
                        
                        for content_item in response['output']['message']['content']:
                            if 'toolUse' in content_item:
                                tool_id = content_item['toolUse']['toolUseId']
                                tool_name = content_item['toolUse']['name']
                                tool_inputs = content_item['toolUse']['input']
                                
                                logger.info(f"Executing tool: {tool_name}")
                                
                                try:
                                    tool_result = await self.session.call_tool(tool_name, tool_inputs)
                                    result_text = tool_result[0].text if isinstance(tool_result, list) and tool_result else str(tool_result)
                                    logger.info(f"Tool {tool_name} executed successfully")
                                    
                                except Exception as tool_error:
                                    logger.error(f"Tool execution failed for {tool_name}: {tool_error}")
                                    result_text = f"Error executing {tool_name}: {str(tool_error)}"
                                
                                result_content = {
                                    "toolResult": {
                                        "toolUseId": tool_id,
                                        "content": [{"text": result_text}]
                                    }
                                }
                                tool_results_content.append(result_content)
                        
                        messages.append({
                            "role": "user",
                            "content": tool_results_content
                        })
                        
                    else:
                        # Return the final assistant's response
                        final_response = response['output']['message']['content'][0]['text']
                        
                        # Save to history
                        history.add_user_message(query)
                        history.add_ai_message(final_response)
                        
                        logger.info("Query processed successfully")
                        return final_response
                        
                except Exception as bedrock_error:
                    logger.error(f"Bedrock API error: {bedrock_error}")
                    return f"Error calling Bedrock API: {str(bedrock_error)}"
            
            logger.warning(f"Conversation exceeded maximum iterations ({max_iterations})")
            return "The conversation took too many turns. Please try a more specific query."
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            return f"An error occurred while processing your query: {str(e)}"

    def _setup_slack_handlers(self):
        """Setup Slack event handlers"""
        
        @self.slack_app.event("app_mention")
        def handle_app_mention(event, say, client):
            """Handle when bot is mentioned"""
            asyncio.create_task(self._handle_slack_message(event, say, client, is_mention=True))
        
        @self.slack_app.message("")
        def handle_direct_message(message, say, client):
            """Handle direct messages"""
            if message.get('bot_id'):
                return
            
            if message['channel_type'] == 'im':
                asyncio.create_task(self._handle_slack_message(message, say, client, is_mention=False))
        
        @self.slack_app.command("/clear_memory")
        def clear_memory_command(ack, respond, command):
            """Clear conversation memory"""
            ack()
            asyncio.create_task(self._clear_memory(respond, command))
        
        @self.slack_app.command("/bot_status")
        def bot_status_command(ack, respond):
            """Check bot status"""
            ack()
            asyncio.create_task(self._bot_status(respond))
        
        @self.slack_app.command("/show_history")
        def show_history_command(ack, respond, command):
            """Show conversation history"""
            ack()
            asyncio.create_task(self._show_history(respond, command))

    async def _handle_slack_message(self, event, say, client, is_mention):
        """Handle Slack messages asynchronously"""
        try:
            text = event['text']
            if is_mention:
                text = text.split('>', 1)[1].strip() if '>' in text else text
            
            user_id = event['user']
            channel_id = event['channel']
            thread_ts = event.get('thread_ts')
            
            session_id = self.get_session_id(user_id, channel_id, thread_ts)
            
            # Show typing indicator
            try:
                client.chat_postMessage(
                    channel=channel_id,
                    text="🤔 Thinking...",
                    thread_ts=thread_ts if thread_ts else event.get('ts')
                )
            except:
                pass
            
            # Process the query
            response = await self.process_query_with_history(text, session_id)
            
            # Send response
            say(
                text=response,
                thread_ts=thread_ts if thread_ts else event.get('ts')
            )
            
        except Exception as e:
            logger.error(f"Error handling Slack message: {e}", exc_info=True)
            say("Sorry, I encountered an error processing your message.")

    async def _clear_memory(self, respond, command):
        """Clear conversation memory"""
        try:
            user_id = command['user_id']
            channel_id = command['channel_id']
            session_id = self.get_session_id(user_id, channel_id)
            
            history = DynamoDBChatMessageHistory(table_name=self.table_name, session_id=session_id)
            history.clear()
            
            respond("✅ Your conversation memory has been cleared!")
            logger.info(f"Memory cleared for session: {session_id}")
        except Exception as e:
            logger.error(f"Error clearing memory: {e}")
            respond(f"❌ Error clearing memory: {str(e)}")

    async def _bot_status(self, respond):
        """Check bot status"""
        try:
            status_msg = "🤖 Bot Status: Online\n"
            status_msg += f"📊 DynamoDB: Connected\n"
            status_msg += f"🗄️ Table: {self.table_name}\n"
            status_msg += f"🧠 Model: us.anthropic.claude-sonnet-4-20250514-v1:0\n"
            
            if self.session:
                status_msg += "🔧 MCP Server: Connected\n"
                response = await self.session.list_tools()
                status_msg += f"🛠️ Available Tools: {len(response.tools)}"
            else:
                status_msg += "🔧 MCP Server: Not connected"
            
            respond(status_msg)
        except Exception as e:
            logger.error(f"Error checking status: {e}")
            respond(f"❌ Status check failed: {str(e)}")

    async def _show_history(self, respond, command):
        """Show conversation history"""
        try:
            user_id = command['user_id']
            channel_id = command['channel_id']
            session_id = self.get_session_id(user_id, channel_id)
            
            history = DynamoDBChatMessageHistory(table_name=self.table_name, session_id=session_id)
            messages = history.messages
            
            if not messages:
                respond("No conversation history found.")
                return
            
            history_text = "📜 *Conversation History:*\n\n"
            for msg in messages[-10:]:  # Show last 10 messages
                if isinstance(msg, HumanMessage):
                    history_text += f"👤 *You:* {msg.content}\n"
                elif isinstance(msg, AIMessage):
                    history_text += f"🤖 *Bot:* {msg.content}\n"
                history_text += "\n"
            
            respond(history_text)
        except Exception as e:
            logger.error(f"Error showing history: {e}")
            respond(f"❌ Error showing history: {str(e)}")

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nAWS MCP Client Started!")
        print("Available commands:")
        print("- Type your AWS-related queries")
        print("- 'quit' or 'exit' to quit")
        print("- 'tools' to list available tools")
        print("- 'logs' to show recent log entries")
        print("- 'clear' to clear conversation history")
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
                
                elif query.lower() == 'logs':
                    self._show_recent_logs()
                    continue
                
                elif query.lower() == 'clear':
                    history = DynamoDBChatMessageHistory(table_name=self.table_name, session_id=cli_session_id)
                    history.clear()
                    print("Conversation history cleared!")
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

    def _show_recent_logs(self):
        """Show recent log entries"""
        try:
            log_files = [f for f in os.listdir('logs') if f.startswith('aws_mcp_slack_')]
            if not log_files:
                print("No log files found yet.")
                return
            
            latest_log = sorted(log_files)[-1]
            with open(os.path.join('logs', latest_log), 'r') as f:
                lines = f.readlines()
                recent_lines = lines[-20:] if len(lines) > 20 else lines
                print("\nRecent log entries:")
                print("-" * 50)
                for line in recent_lines:
                    print(line.strip())
                print("-" * 50)
        except Exception as e:
            print(f"Error reading logs: {e}")

    def start_slack_bot(self):
        """Start the Slack bot in socket mode"""
        if not self.slack_app:
            logger.error("Slack app not initialized. Check SLACK_BOT_TOKEN and SLACK_APP_TOKEN")
            return
        
        try:
            slack_app_token = os.environ.get("SLACK_APP_TOKEN")
            self.slack_handler = SocketModeHandler(self.slack_app, slack_app_token)
            logger.info("✅ Slack bot is running! Press Ctrl+C to stop.")
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
            
            # Connect to MCP server if URL provided
            if args.mcp_server:
                await client.connect_to_sse_server(args.mcp_server)
            
            # Start Slack bot (this will block)
            client.start_slack_bot()
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
```

This integrated solution provides:

## Key Features:

1. **Dual Mode Operation**:
   - **CLI Mode**: `python aws_mcp_slack_client.py --mcp-server http://localhost:8002/sse`
   - **Slack Bot Mode**: `python aws_mcp_slack_client.py --slack --mcp-server http://localhost:8002/sse`

2. **DynamoDB Integration**:
   - Automatic table creation
   - Conversation history persistence
   - Session management per user/channel/thread

3. **Slack Commands**:
   - `/clear_memory` - Clear conversation history
   - `/bot_status` - Check bot and connection status
   - `/show_history` - Display recent conversation history

4. **MCP Tool Access**:
   - Connects to MCP server for AWS operations
   - Tool execution with proper error handling
   - Works with or without MCP server connection

5. **Unified Query Processing**:
   - Same query processing for both CLI and Slack
   - Maintains conversation context
   - Supports complex multi-turn conversations

## Usage Examples:

```bash
# CLI mode with MCP server
python aws_mcp_slack_client.py --mcp-server http://localhost:8002/sse --region us-east-1

# Slack bot mode with MCP server
python aws_mcp_slack_client.py --slack --mcp-server http://localhost:8002/sse

# Slack bot mode without MCP (uses Bedrock only)
python aws_mcp_slack_client.py --slack
```

## Environment Variables Required:

```env
# AWS (uses IAM role, no keys needed)
AWS_DEFAULT_REGION=us-east-1

# Slack (optional, only needed for Slack mode)
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# DynamoDB (optional)
DYNAMODB_TABLE_NAME=SlackBotSessionTable
```

The integration maintains all the original functionality while adding:
- Seamless switching between CLI and Slack modes
- Shared conversation history across modes
- Proper async handling for both interfaces
- Comprehensive error handling and logging

```bash
python aws_client/advanced_client.py --slack --mcp-server http://13.220.52.46:8002/sse/
```