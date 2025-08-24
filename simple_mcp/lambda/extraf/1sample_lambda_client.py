import json
import os
import time
import logging
from typing import Optional, Dict
import boto3
from botocore.config import Config
from slack_utils import send_slack_message

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Configure boto3 client
config = Config(
    retries=dict(
        max_attempts=10,
        mode='adaptive'
    ),
    read_timeout=300
)

bedrock_client = boto3.client(
    service_name='bedrock-runtime',
    region_name='us-east-1',
    config=config
)

class TerminalMCPLambdaClient:
    def __init__(self):
        self.session = None
        self.last_request_time = 0
        self.min_request_interval = 1.0
        logger.info("TerminalMCPLambdaClient initialized")

    def connect_to_server(self, server_url: str):
        """Connect to the Terminal MCP server"""
        try:
            logger.info(f"Attempting to connect to MCP server at: {server_url}")
            # Simplified connection logic without using the problematic async code
            # This will need to be customized based on how your MCP server expects connections
            # This is just a placeholder
            logger.info("Successfully connected to MCP server")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {str(e)}", exc_info=True)
            return False

    def cleanup(self):
        """Clean up connections"""
        logger.info("Cleaning up MCP client connections")
        # Simplified cleanup logic
        pass

    def rate_limit(self):
        """Implement rate limiting"""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last_request
            logger.info(f"Rate limiting applied: waiting {sleep_time:.2f} seconds")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def process_query(self, query: str) -> Dict:
        """Process a query and return results"""
        start_time = time.time()
        logger.info(f"Processing query: {query[:100]}...")
        
        messages = [{"role": "user", "content": [{"text": query}]}]

        # Fixed list of tools since we can't call MCP's list_tools()
        tools = [
            {
                "toolSpec": {
                    "name": "run_terminal_command",
                    "description": "Run a command in the terminal",
                    "inputSchema": {"json": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}
                }
            },
            {
                "toolSpec": {
                    "name": "read_file",
                    "description": "Read a file from the filesystem",
                    "inputSchema": {"json": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}
                }
            },
            {
                "toolSpec": {
                    "name": "write_file",
                    "description": "Write content to a file",
                    "inputSchema": {"json": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}
                }
            }
        ]

        system_prompt = """
        <instruction>
        You are a helpful terminal assistant capable of executing terminal commands, reading and writing files, and retrieving system information. When performing tasks, follow these guidelines:

        <rules>
        - When changing, updating, or deleting a file, always create a zip archive of the file first in the same directory as the log files, then execute the command for modification or deletion.
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
        - When given multiple tasks, execute them in the order specified and clearly separate the results.
        </rules>
        </instruction>
        """

        # Use Bedrock's Claude to generate a response
        api_params = {
            "modelId": "us.anthropic.claude-opus-4-20250514-v1:0",
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": 4096, "temperature": 0.7},
        }

        try:
            logger.info("Applying rate limiting before Bedrock API call")
            self.rate_limit()
            
            logger.info("Calling Bedrock API with Claude Opus model")
            response_start = time.time()
            response = bedrock_client.converse(**api_params)
            response_time = time.time() - response_start
            logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")
            
            # Log token usage if available in response
            if 'usage' in response:
                logger.info(f"Token usage - Input: {response['usage'].get('inputTokens', 'N/A')}, " +
                           f"Output: {response['usage'].get('outputTokens', 'N/A')}")

            result_text = response['output']['message']['content'][0]['text']
            logger.info(f"Response generated successfully, length: {len(result_text)} chars")
            
            processing_time = time.time() - start_time
            logger.info(f"Query processing completed in {processing_time:.2f} seconds")
            
            return {
                "response": result_text,
                "tool_calls": [],  # No tool calls in this simplified version
                "processing_time_seconds": processing_time
            }

        except bedrock_client.exceptions.ThrottlingException as e:
            logger.warning(f"Bedrock API throttling error: {str(e)}")
            return {
                "error": f"Rate limit exceeded: {str(e)}",
                "tool_calls": []
            }
        except bedrock_client.exceptions.ValidationException as e:
            logger.error(f"Bedrock API validation error: {str(e)}")
            return {
                "error": f"Invalid request to Bedrock: {str(e)}",
                "tool_calls": []
            }
        except bedrock_client.exceptions.ModelTimeoutException as e:
            logger.error(f"Bedrock model timeout: {str(e)}")
            return {
                "error": f"Model timeout: {str(e)}",
                "tool_calls": []
            }
        except bedrock_client.exceptions.ModelStreamErrorException as e:
            logger.error(f"Bedrock model stream error: {str(e)}")
            return {
                "error": f"Model stream error: {str(e)}",
                "tool_calls": []
            }
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "error": str(e),
                "tool_calls": []
            }
def get_bedrock_slack_result(query: str):
    start_time = time.time()
    
    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")
    system_prompt = """
    <instruction>
    You are an AI assistant that formats all responses for Slack messaging. Follow these Slack formatting rules:

    1. Use *asterisks* for bold text (not ** double asterisks)
    2. Use _underscores_ for italic text
    3. Use `backticks` for inline code
    4. Use ```triple backticks``` for code blocks
    5. Use > for blockquotes
    6. Use • for bullet points (not - or *)
    7. Format links as <URL|display text> or just <URL>
    8. Use :emoji_name: for emojis when appropriate
    9. Keep line breaks clean and use double line breaks for paragraphs
    10. Avoid HTML tags or Markdown that Slack doesn't support
    11. Use numbered lists with actual numbers (1. 2. 3.)
    12. Keep messages concise and scannable
    13. Use >>> for multi-line quotes

    Structure your responses to be easily readable in Slack's interface. Break up long text into shorter paragraphs and use formatting to highlight key information.
    </instruction>
    """
    messages = [{"role": "user", "content": [{"text": query}]}]
    api_params = {
            "modelId": "us.anthropic.claude-opus-4-20250514-v1:0",
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": 4096, "temperature": 0.7},
        }
    response = bedrock_client.converse(**api_params)
    response_time = time.time() - start_time
    logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")
    return response['output']['message']['content'][0]['text']

# Lambda handler without async/await
def lambda_handler(event, context):
    """Main Lambda handler"""
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")
    
    # Log memory and time limits
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, " +
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")
    
    # Log event data (be careful with sensitive data)
    logger.info(f"Event type: {type(event)}")
    if isinstance(event, dict):
        logger.info(f"Event keys: {list(event.keys())}")
        logger.info(f"Event: {event}")
    # Parse the request body
    try:
        if isinstance(event.get('body'), str):
            logger.info("Request body provided as string, parsing JSON")
            body = json.loads(event['body'])
        else:
            logger.info("Request body provided as object")
            body = event.get('body', {})
            
        logger.info(f"Parsed request body keys: {list(body.keys())}")
    except Exception as e:
        logger.error(f"Failed to parse request body: {str(e)}", exc_info=True)
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid JSON in request body'})
        }

    # Get parameters
    query = body.get('query', '')
    server_url = body.get('server_url', os.environ.get('MCP_SERVER_URL', ''))
    
    logger.info(f"Query length: {len(query)}")
    logger.info(f"Server URL provided: {'Yes' if server_url else 'No'}")

    if not query:
        logger.warning("Missing required parameter: query")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing required parameter: query'})
        }

    if not server_url:
        logger.warning("Missing required parameter: server_url")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing required parameter: server_url'})
        }

    start_time = time.time()
    
    # Create client and process query
    try:
        logger.info("Creating TerminalMCPLambdaClient instance")
        client = TerminalMCPLambdaClient()

        # Connect to server (simplified)
        logger.info("Connecting to MCP server")
        connected = client.connect_to_server(server_url)
        if not connected:
            logger.error("Failed to connect to MCP server")
            return {
                'statusCode': 503,
                'body': json.dumps({'error': 'Failed to connect to MCP server'})
            }

        # Process the query (Claude only, no tool calls)
        logger.info("Processing query with Claude")
        result = client.process_query(query)
        
        # Check for errors in result
        if 'error' in result:
            logger.error(f"Error in query processing: {result['error']}")

        # Clean up
        logger.info("Cleaning up client resources")
        client.cleanup()
        
        execution_time = time.time() - start_time
        logger.info(f"Lambda execution completed in {execution_time:.2f} seconds")
        logger.info(f"Result: {result}")

        # send_slack_message(SLACK_CHANNEL, f"Query: {query}\nResult: {result}")
        # payload = {
        #     'command': command,
        #     'text': text,
        #     'user_id': user_id,
        #     'channel_id': channel_id,
        #     'response_url': response_url,
        #     "body":{
        #         "query": text,
        #         "server_url": mcp_agent_url }
        # }

        channel_id = event.get('channel_id', '')
        user_id = event.get('user_id', '')
        response_url = event.get('response_url', '')
        text = event.get('text', '')
        
        # Extract just the response text for Slack formatting
        response_text = result.get('response', str(result))
        bedrock_slack_result = get_bedrock_slack_result(response_text)
        send_slack_message(channel_id, bedrock_slack_result)
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps({
                'success': True,
                'query': query,
                'result': result,
                'execution_time_seconds': execution_time
            })
        }
        

        
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Internal server error: {str(e)}", exc_info=True)
        logger.info(f"Lambda execution failed after {execution_time:.2f} seconds")
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': f'Internal server error: {str(e)}',
                'execution_time_seconds': execution_time
            })
        }