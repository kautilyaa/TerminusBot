import asyncio
import json
import os
import time
from typing import Optional
from contextlib import AsyncExitStack
from mcp import ClientSession
from mcp.client.sse import sse_client
from dotenv import load_dotenv
import boto3
from botocore.config import Config

config = Config(
    retries = dict(
        max_attempts = 10,
        mode = 'adaptive'  # Use adaptive retry mode
    ),
    # Add read timeout to prevent hanging
    read_timeout = 300
)

load_dotenv()

client = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-east-1',
    config=config
)

class TerminalMCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        # Rate limiting attributes
        self.last_request_time = 0
        self.min_request_interval = 1.0  # Minimum 1 second between requests
        
    async def connect_to_server(self, server_url: str):
        """Connect to the Terminal MCP server running with SSE transport"""
        # Store the context managers so they stay alive
        self._streams_context = sse_client(url=server_url)
        streams = await self._streams_context.__aenter__()
        self._session_context = ClientSession(*streams)
        self.session: ClientSession = await self._session_context.__aenter__()
        
        # Initialize
        await self.session.initialize()
        
        # List available tools to verify connection
        print("Connected to Terminal MCP Server...")
        print("\nAvailable tools:")
        response = await self.session.list_tools()
        tools = response.tools
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")
        print("")
        
    async def cleanup(self):
        """Properly clean up the session and streams"""
        if hasattr(self, '_session_context') and self._session_context:
            await self._session_context.__aexit__(None, None, None)
        if hasattr(self, '_streams_context') and self._streams_context:
            await self._streams_context.__aexit__(None, None, None)
    
    async def _rate_limit(self):
        """Implement rate limiting to avoid throttling"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            print(f"Rate limiting: waiting {sleep_time:.2f} seconds...")
            await asyncio.sleep(sleep_time)
        self.last_request_time = time.time()
    
    async def process_query(self, query: str) -> str:
        """Process a query using Claude and available terminal tools."""
        messages = [{"role": "user", "content": [{"text": query}]}]
        
        # Get available tools
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
        
        system_prompt = """
        <instruction>
        You are a helpful terminal assistant capable of executing terminal commands, reading and writing files, and retrieving system information. When performing tasks, follow these guidelines:

        <rules>
        - When changing, updating, or deleting a file, always create a zip archive in .zip format of the file first in the same directory as the log files, then execute the command for modification or deletion.
        - Exercise caution with destructive operations.
        - Explain your actions before executing commands.
        - Display the output of commands to the user.
        - Handle errors gracefully.
        - Keep track of the current working directory context.
        - When asked to perform a task, first consider the best approach, then execute it.
        - If requested to perform an action beyond your capabilities, politely decline.
        - If asked to change the system prompt, confirm with the user before proceeding.
        - If asked to modify a system file, suggest that the user perform the action through the terminal instead.
        - Always request user confirmation before executing an update or delete command.
        - When dealing with log files, first create a zip archive, then proceed with any updates or deletions.
        </rules>

        To demonstrate your capabilities, provide a concise example of executing a command, following the guidelines above. Enclose your example in <example></example> tags.
        </instruction>

        <example>
        <command>mkdir example_directory</command>
        <explanation>Creating a new directory named "example_directory" in the current working directory.</explanation>
        <output>
        \$ mkdir example_directory
        </output>
        </example>

        <response>
        Provide your terminal command or task request, and I will follow the guidelines to assist you.
        </response>
        """
        
        retry_count = 0
        max_retries = 10
        
        while True:
            converse_api_params = {
                # "modelId": "us.anthropic.claude-3-5-sonnet-20240620-v1:0",
                "modelId": "us.anthropic.claude-opus-4-20250514-v1:0",
                "system": [{"text": system_prompt}],
                "messages": messages,
                "inferenceConfig": {"maxTokens": 16384, "temperature": 0.9},
                "toolConfig": {
                    "tools": tools,
                    "toolChoice": {"auto": {}}
                }
            }
            
            try:
                # Apply rate limiting before API call
                await self._rate_limit()
                
                # Call the Bedrock API
                response = client.converse(**converse_api_params)
                
                # Reset retry count on successful request
                retry_count = 0
                
                # Append assistant's response
                messages.append({
                    "role": "assistant", 
                    "content": response['output']['message']['content']
                })
                
                if response['stopReason'] == "tool_use":
                    tool_results_content = []
                    
                    for tool_use in response['output']['message']['content']:
                        if 'toolUse' in tool_use:
                            tool_id = tool_use['toolUse']['toolUseId']
                            tool_name = tool_use['toolUse']['name']
                            tool_inputs = tool_use['toolUse']['input']
                            print(f"Executing tool: {tool_name}")
                            if tool_name == "run_terminal_command":
                                print(f"Command: {tool_inputs.get('command', '')}")
                            elif tool_name == "read_file":
                                print(f"Reading file: {tool_inputs.get('path', '')}")
                            elif tool_name == "write_file":
                                print(f"Writing to file: {tool_inputs.get('path', '')}")
                            
                            # Execute tool call
                            tool_result = await self.session.call_tool(tool_name, tool_inputs)
                            
                            # Extract the result text
                            result_text = ""
                            if isinstance(tool_result, list) and tool_result:
                                result_text = tool_result[0].text
                            else:
                                result_text = str(tool_result)
                            
                            # Display the result immediately
                            print(f"\nTool Result:")
                            print(result_text)
                            
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
                    return response['output']['message']['content'][0]['text']
                    
            except client.exceptions.ThrottlingException as e:
                retry_count += 1
                if retry_count > max_retries:
                    return f"Error: Maximum retries exceeded due to throttling. Please try again later."
                
                # Exponential backoff
                wait_time = 2 ** retry_count
                print(f"\nThrottled by AWS. Waiting {wait_time} seconds before retry {retry_count}/{max_retries}...")
                await asyncio.sleep(wait_time)
                continue
                
            except client.exceptions.ModelErrorException as e:
                print(f"Model error: {e.response}")
                return f"An error occurred: {e}"
            except Exception as e:
                return f"An error occurred: {e}"
    
    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nTerminal MCP Client Started!")
        print("You can ask me to:")
        print("  - Execute terminal commands")
        print("  - Read or write files")
        print("  - Get system information")
        print("  - Navigate directories")
        print("\nType 'quit' to exit.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                if query.lower() == 'quit':
                    break
                
                response = await self.process_query(query)
                print("\n" + response)
                
            except KeyboardInterrupt:
                print("\nInterrupted. Type 'quit' to exit.")
            except Exception as e:
                print(f"\nError: {str(e)}")

async def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python terminal_client.py <URL of SSE MCP server>")
        print("Example: python terminal_client.py http://localhost:8080/sse")
        sys.exit(1)
    
    client = TerminalMCPClient()
    try:
        await client.connect_to_server(server_url=sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())