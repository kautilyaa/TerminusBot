




# import asyncio
# import json
# import os
# from typing import Optional
# from contextlib import AsyncExitStack
# from mcp import ClientSession
# from mcp.client.sse import sse_client
# from dotenv import load_dotenv
# import boto3

# load_dotenv()

# client = boto3.client(
#     service_name='bedrock-runtime',
#     region_name='us-east-1'
# )

# class AWSMCPClient:
#     def __init__(self):
#         # Initialize session and client objects
#         self.session: Optional[ClientSession] = None
#         self.exit_stack = AsyncExitStack()

#     async def connect_to_server(self, server_url: str):
#         """Connect to the AWS MCP server running with SSE transport"""
#         # Store the context managers so they stay alive
#         self._streams_context = sse_client(url=server_url)
#         streams = await self._streams_context.__aenter__()
#         self._session_context = ClientSession(*streams)
#         self.session: ClientSession = await self._session_context.__aenter__()

#         # Initialize
#         await self.session.initialize()

#         # List available tools to verify connection
#         print("Connected to AWS MCP Server...")
#         print("\\nAvailable tools:")
#         response = await self.session.list_tools()
#         tools = response.tools
#         for tool in tools:
#             print(f"  - {tool.name}: {tool.description}")
#         print("")

#     async def cleanup(self):
#         """Properly clean up the session and streams"""
#         if hasattr(self, '_session_context') and self._session_context:
#             await self._session_context.__aexit__(None, None, None)
#         if hasattr(self, '_streams_context') and self._streams_context:
#             await self._streams_context.__aexit__(None, None, None)

#     async def process_query(self, query: str) -> str:
#         """Process a query using Claude and available AWS tools."""
#         messages = [{"role": "user", "content": [{"text": query}]}]

#         # Get available tools
#         response = await self.session.list_tools()
#         tools = [
#             {
#                 "toolSpec": {
#                     "name": tool.name,
#                     "description": tool.description,
#                     "inputSchema": {
#                         "json": tool.inputSchema
#                     }
#                 }
#             }
#             for tool in response.tools
#         ]

#         system_prompt = """You are a helpful AWS assistant. You can help with:
#         - EC2 instance management and monitoring
#         - CloudWatch logs viewing and analysis
#         - AWS resource queries and status checks

#         When working with AWS resources:
#         - Provide clear explanations of what you're doing
#         - Show AWS resource details in an organized way
#         - Help interpret CloudWatch logs and identify issues
#         - Suggest best practices for AWS resource management
#         - Use appropriate filters to narrow down results when needed
#         - Handle AWS API errors gracefully and explain them to the user"""

#         while True:
#             converse_api_params = {
#                 "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
#                 "system": [{"text": system_prompt}],
#                 "messages": messages,
#                 "inferenceConfig": {"maxTokens": 16384, "temperature": 0.1},
#                 "toolConfig": {
#                     "tools": tools,
#                     "toolChoice": {"auto": {}}
#                 },
#             }

#             try:
#                 # Call the Bedrock API
#                 response = client.converse(**converse_api_params)

#                 # Append assistant's response
#                 messages.append({
#                     "role": "assistant",
#                     "content": response['output']['message']['content']
#                 })

#                 if response['stopReason'] == "tool_use":
#                     tool_results_content = []

#                     for tool_use in response['output']['message']['content']:
#                         if 'toolUse' in tool_use:
#                             tool_id = tool_use['toolUse']['toolUseId']
#                             tool_name = tool_use['toolUse']['name']
#                             tool_inputs = tool_use['toolUse']['input']

#                             print(f"\\n🔧 Executing AWS tool: {tool_name}")
#                             if tool_name == "get_ec2_instances":
#                                 if tool_inputs.get('filters'):
#                                     print(f"   Filters: {json.dumps(tool_inputs['filters'], indent=2)}")
#                                 else:
#                                     print("   Getting all EC2 instances...")
#                             elif tool_name == "get_cloudwatch_logs":
#                                 print(f"   Log Group: {tool_inputs.get('log_group_name')}")
#                                 print(f"   Hours ago: {tool_inputs.get('start_time_hours_ago', 1)}")
#                                 if tool_inputs.get('filter_pattern'):
#                                     print(f"   Filter: {tool_inputs['filter_pattern']}")
#                             elif tool_name == "list_log_groups":
#                                 if tool_inputs.get('prefix'):
#                                     print(f"   Prefix filter: {tool_inputs['prefix']}")

#                             # Execute tool call
#                             tool_result = await self.session.call_tool(tool_name, tool_inputs)

#                             # Extract the result text
#                             result_text = ""
#                             if isinstance(tool_result, list) and tool_result:
#                                 result_text = tool_result[0].text
#                             else:
#                                 result_text = str(tool_result)

#                             result_content = {
#                                 "toolResult": {
#                                     "toolUseId": tool_id,
#                                     "content": [{"text": result_text}]
#                                 }
#                             }
#                             tool_results_content.append(result_content)

#                     # Append tool results to messages
#                     messages.append({
#                         "role": "user",
#                         "content": tool_results_content
#                     })
#                 else:
#                     # Return the final assistant's response
#                     return response['output']['message']['content'][0]['text']

#             except client.exceptions.ModelErrorException as e:
#                 print(f"Model error: {e.response}")
#                 return f"An error occurred: {e}"
#             except Exception as e:
#                 return f"An error occurred: {e}"

#     async def chat_loop(self):
#         """Run an interactive chat loop"""
#         print("\\n🚀 AWS MCP Client Started!")
#         print("You can ask me to:")
#         print("  - List and filter EC2 instances")
#         print("  - Get CloudWatch logs from log groups")
#         print("  - List available log groups")
#         print("  - Analyze AWS resource status")
#         print("  - Help with AWS troubleshooting")
#         print("\\nExample queries:")
#         print("  - 'Show me all running EC2 instances'")
#         print("  - 'Get logs from my-app log group from the last 2 hours'")
#         print("  - 'List all log groups starting with /aws/lambda'")
#         print("  - 'Find any errors in my application logs'")
#         print("\\nType 'quit' to exit.")

#         while True:
#             try:
#                 query = input("\\n💬 AWS Query: ").strip()
#                 if query.lower() == 'quit':
#                     break

#                 print("\\n🤔 Processing your request...")
#                 response = await self.process_query(query)
#                 print("\\n📋 Response:")
#                 print(response)

#             except KeyboardInterrupt:
#                 print("\\nInterrupted. Type 'quit' to exit.")
#             except Exception as e:
#                 print(f"\\n❌ Error: {str(e)}")

#     async def quick_status(self):
#         """Get a quick status overview of AWS resources"""
#         print("\\n📊 Getting AWS quick status...")

#         try:
#             # Get EC2 instances count
#             ec2_result = await self.session.call_tool("get_ec2_instances", {})
#             ec2_data = json.loads(ec2_result[0].text)

#             print(f"\\n🖥️  EC2 Instances: {len(ec2_data)} total")

#             # Count by state
#             states = {}
#             for instance in ec2_data:
#                 state = instance['State']
#                 states[state] = states.get(state, 0) + 1

#             for state, count in states.items():
#                 emoji = "🟢" if state == "running" else "🔴" if state == "stopped" else "🟡"
#                 print(f"   {emoji} {state}: {count}")

#             # Get log groups count
#             logs_result = await self.session.call_tool("list_log_groups", {})
#             logs_data = json.loads(logs_result[0].text)

#             print(f"\\n📝 CloudWatch Log Groups: {len(logs_data)} total")

#         except Exception as e:
#             print(f"❌ Error getting status: {e}")

# async def main():
#     import sys

#     if len(sys.argv) < 2:
#         print("Usage: python aws_client.py <URL of AWS MCP server>")
#         print("Example: python aws_client.py <http://localhost:8080/sse>")
#         print("\\nTo use the MCP endpoint instead of SSE:")
#         print("Example: python aws_client.py <http://localhost:8080/mcp>")
#         sys.exit(1)

#     aws_client = AWSMCPClient()
#     try:
#         await aws_client.connect_to_server(server_url=sys.argv[1])

#         # Show quick status first
#         await aws_client.quick_status()

#         # Start interactive chat
#         await aws_client.chat_loop()
#     finally:
#         await aws_client.cleanup()

# if __name__ == "__main__":
#     asyncio.run(main())















"""You are an expert AWS Operations Assistant with comprehensive access to AWS management tools and CloudWatch logging capabilities. You can help with:

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