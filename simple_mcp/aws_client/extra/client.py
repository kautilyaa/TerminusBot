#!/usr/bin/env python3
"""AWS MCP Client - A client for connecting to AWS MCP Server using FastMCP"""

import asyncio
import json
import os
import sys
import logging
from typing import Optional
from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.sse import sse_client
from dotenv import load_dotenv
import boto3
from botocore.config import Config

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('aws_mcp_client.log')
    ]
)
logger = logging.getLogger(__name__)

class AWSMCPClient:
    def __init__(self, region: str = 'us-east-1'):
        """Initialize the AWS MCP Client with IAM role support"""
        self.region = region
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()

        # Initialize Bedrock client with IAM role
        self._init_bedrock_client()

    def _init_bedrock_client(self):
        """Initialize Bedrock client using IAM role"""
        try:
            # Create a session that will use IAM roles (from EC2 instance profile, ECS task role, etc.)
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

            # Test the connection by getting caller identity
            sts_client = boto3_session.client('sts')
            identity = sts_client.get_caller_identity()
            logger.info(f"Successfully initialized AWS clients using IAM role. Account: {identity.get('Account')}, ARN: {identity.get('Arn')}")

        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {e}")
            raise

    async def connect_to_sse_server(self, server_url: str):
        """Connect to an MCP server running with SSE transport"""
        try:
            logger.info(f"Connecting to MCP server at {server_url}")

            # Store the context managers so they stay alive
            self._streams_context = sse_client(url=server_url)
            streams = await self._streams_context.__aenter__()
            self._session_context = ClientSession(*streams)
            self.session: ClientSession = await self._session_context.__aenter__()

            # Initialize
            await self.session.initialize()
            logger.info("Successfully initialized MCP client session")

            # List available tools to verify connection
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

    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available tools."""
        try:
            logger.info(f"Processing query: {query[:100]}...")

            messages = []
            messages.append({"role": "user", "content": [{"text": query}]})

            # Get available tools from MCP server
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

                if messages[-1].get("role") == "assistant":
                    messages.append({"role": "user", "content": [{"text": query}]})

                converse_api_params = {
                    "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                    "system": [{"text": system_prompt}],
                    "messages": messages,
                    "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
                    "toolConfig": {
                        "tools": tools,
                        "toolChoice": {"auto": {}}
                    },
                }

                try:
                    # Call the Bedrock API
                    logger.debug("Calling Bedrock Converse API")
                    response = self.bedrock_client.converse(**converse_api_params)

                    # Log the response details
                    logger.debug(f"Bedrock response stop reason: {response.get('stopReason')}")

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

                                # Execute tool call via MCP
                                try:
                                    tool_result = await self.session.call_tool(tool_name, tool_inputs)
                                    result_text = tool_result[0].text if isinstance(tool_result, list) and tool_result else str(tool_result)
                                    logger.info(f"Tool {tool_name} executed successfully")
                                    logger.debug(f"Tool result: {result_text[:200]}...")

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

                        # Append tool results to messages
                        messages.append({
                            "role": "user",
                            "content": tool_results_content
                        })

                    else:
                        # Return the final assistant's response
                        final_response = response['output']['message']['content'][0]['text']
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

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nAWS MCP Client Started!")
        print("Available commands:")
        print("- Type your AWS-related queries")
        print("- 'quit' or 'exit' to quit")
        print("- 'tools' to list available tools")
        print("- 'logs' to show recent log entries")
        print("-" * 50)

        while True:
            try:
                query = input("\nAWS Query: ").strip()

                if query.lower() in ['quit', 'exit']:
                    print("Goodbye!")
                    break

                elif query.lower() == 'tools':
                    try:
                        response = await self.session.list_tools()
                        tools = response.tools
                        print(f"\nAvailable tools ({len(tools)}):")
                        for tool in tools:
                            print(f"- {tool.name}: {tool.description}")
                    except Exception as e:
                        print(f"Error listing tools: {e}")
                    continue

                elif query.lower() == 'logs':
                    self._show_recent_logs()
                    continue

                elif not query:
                    continue

                print("\nProcessing...")
                response = await self.process_query(query)
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
            with open('aws_mcp_client.log', 'r') as f:
                lines = f.readlines()
                recent_lines = lines[-20:] if len(lines) > 20 else lines
                print("\nRecent log entries:")
                print("-" * 50)
                for line in recent_lines:
                    print(line.strip())
                print("-" * 50)
        except FileNotFoundError:
            print("No log file found yet.")
        except Exception as e:
            print(f"Error reading logs: {e}")

async def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python aws_mcp_client.py <MCP_SERVER_URL>")
        print("Example: python aws_mcp_client.py <http://localhost:8002/sse>")
        sys.exit(1)

    server_url = sys.argv[1]
    region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')

    client = AWSMCPClient(region=region)

    try:
        await client.connect_to_sse_server(server_url=server_url)
        await client.chat_loop()
    except Exception as e:
        logger.error(f"Client error: {e}")
        print(f"Error: {e}")
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
