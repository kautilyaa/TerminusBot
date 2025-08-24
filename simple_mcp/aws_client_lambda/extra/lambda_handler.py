# Here's the rewritten Lambda handler based on your AWS MCP Client structure:

# ```python
import json
import os
import time
import logging
from typing import Optional, Dict, List, Any
import boto3
from botocore.config import Config
from slack_utils import send_slack_message
import requests
import asyncio

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

class AWSMCPLambdaClient:
    def __init__(self, region: str = 'us-east-1'):
        """Initialize the AWS MCP Lambda Client"""
        self.region = region
        self.session = None
        self.last_request_time = 0
        self.min_request_interval = 1.0
        self.server_url = None
        
        # Initialize Bedrock client
        self._init_bedrock_client()
        logger.info("AWSMCPLambdaClient initialized")

    def _init_bedrock_client(self):
        """Initialize Bedrock client using IAM role"""
        try:
            # Create a session that will use IAM roles
            boto3_session = boto3.Session()

            # Configure retry settings
            bedrock_config = Config(
                region_name=self.region,
                retries={'max_attempts': 3, 'mode': 'adaptive'},
                max_pool_connections=50
            )

            self.bedrock_client = boto3_session.client(
                service_name='bedrock-runtime',
                config=bedrock_config
            )

            # Test the connection
            sts_client = boto3_session.client('sts')
            identity = sts_client.get_caller_identity()
            logger.info(f"AWS clients initialized. Account: {identity.get('Account')}")

        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {e}")
            raise

    def connect_to_server(self, server_url: str) -> bool:
        """Connect to the MCP server via HTTP/SSE"""
        try:
            logger.info(f"Attempting to connect to MCP server at: {server_url}")
            self.server_url = server_url
            
            # Test connectivity by trying to list tools
            tools = self._list_tools()
            if tools:
                logger.info(f"Successfully connected to MCP server with {len(tools)} tools")
                return True
            else:
                logger.error("Failed to retrieve tools from MCP server")
                return False
                
        except Exception as e:
            logger.error(f"Failed to connect to MCP server: {str(e)}", exc_info=True)
            return False

    def _list_tools(self) -> List[Dict]:
        """Get available tools from MCP server"""
        try:
            # Make HTTP request to get tools
            tools_url = f"{self.server_url.rstrip('/')}/tools"
            response = requests.get(tools_url, timeout=30)
            
            if response.status_code == 200:
                tools_data = response.json()
                return tools_data.get('tools', [])
            else:
                logger.error(f"Failed to get tools: HTTP {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"Error getting tools: {e}")
            # Return a default set of tools if we can't connect
            return self._get_default_tools()

    def _get_default_tools(self) -> List[Dict]:
        """Return default AWS MCP tools when server is unavailable"""
        return [
            {
                "name": "list_ec2_instances",
                "description": "List EC2 instances in the specified region",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "default": "us-east-1"}
                    }
                }
            },
            {
                "name": "start_ec2_instance",
                "description": "Start an EC2 instance",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"}
                    },
                    "required": ["instance_id"]
                }
            },
            {
                "name": "stop_ec2_instance",
                "description": "Stop an EC2 instance",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"}
                    },
                    "required": ["instance_id"]
                }
            },
            {
                "name": "list_s3_buckets",
                "description": "List S3 buckets",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string"}
                    }
                }
            },
            {
                "name": "list_cloudwatch_log_groups",
                "description": "List CloudWatch log groups in the specified region",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "default": "us-east-1"},
                        "max_groups": {"type": "integer", "default": 1000}
                    }
                }
            },
            {
                "name": "list_cloudwatch_log_streams",
                "description": "List log streams in a CloudWatch log group", 
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "log_group_name": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"},
                        "max_streams": {"type": "integer", "default": 50}
                    },
                    "required": ["log_group_name"]
                }
            },
            {
                "name": "get_cloudwatch_logs",
                "description": "Get CloudWatch logs from a log group",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "log_group_name": {"type": "string"},
                        "log_stream_name": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"},
                        "hours_back": {"type": "integer", "default": 1},
                        "max_events": {"type": "integer", "default": 100}
                    },
                    "required": ["log_group_name"]
                }
            },
            {
                "name": "search_cloudwatch_logs",
                "description": "Search CloudWatch logs for specific terms",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "log_group_name": {"type": "string"},
                        "search_term": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"},
                        "hours_back": {"type": "integer", "default": 24},
                        "max_events": {"type": "integer", "default": 1000}
                    },
                    "required": ["log_group_name", "search_term"]
                }
            },
            {
                "name": "search_ec2_logs",
                "description": "Search EC2 logs for a specific instance",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string"},
                        "search_term": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"},
                        "hours_back": {"type": "integer", "default": 24}
                    },
                    "required": ["instance_id"]
                }
            },
            {
                "name": "get_recent_ec2_errors",
                "description": "Get recent error messages from EC2 instance logs",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "instance_id": {"type": "string"},
                        "region": {"type": "string", "default": "us-east-1"},
                        "hours_back": {"type": "integer", "default": 24}
                    },
                    "required": ["instance_id"]
                }
            }
        ]

    def _call_tool(self, tool_name: str, tool_inputs: Dict) -> str:
        """Call a tool on the MCP server"""
        try:
            # Make HTTP request to call tool
            call_url = f"{self.server_url.rstrip('/')}/call"
            payload = {
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": tool_inputs
                }
            }
            
            response = requests.post(call_url, json=payload, timeout=120)
            
            if response.status_code == 200:
                result = response.json()
                return result.get('result', {}).get('content', [{}])[0].get('text', str(result))
            else:
                logger.error(f"Tool call failed: HTTP {response.status_code} - {response.text}")
                return f"Error calling tool {tool_name}: HTTP {response.status_code}"
                
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            return f"Error calling tool {tool_name}: {str(e)}"

    def cleanup(self):
        """Clean up connections"""
        logger.info("Cleaning up MCP client connections")
        self.session = None
        self.server_url = None

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
        """Process a query using Claude and available AWS MCP tools"""
        start_time = time.time()
        logger.info(f"Processing query: {query[:100]}...")
        
        try:
            messages = [{"role": "user", "content": [{"text": query}]}]

            # Get available tools
            available_tools = self._list_tools()
            
            # Format tools for Bedrock
            tools = [
                {
                    "toolSpec": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": {"json": tool["inputSchema"]}
                    }
                }
                for tool in available_tools
            ]

            logger.info(f"Using {len(tools)} AWS MCP tools for query processing")

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

            # Conversation loop with tool calling
            max_iterations = 10
            iteration = 0

            while iteration < max_iterations:
                iteration += 1
                logger.debug(f"Conversation iteration {iteration}")

                # Apply rate limiting
                self.rate_limit()

                api_params = {
                    "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
                    "system": [{"text": system_prompt}],
                    "messages": messages,
                    "inferenceConfig": {"maxTokens": 4096, "temperature": 0.1},
                    "toolConfig": {
                        "tools": tools,
                        "toolChoice": {"auto": {}}
                    },
                }

                logger.info("Calling Bedrock API with AWS MCP tools")
                response_start = time.time()
                response = self.bedrock_client.converse(**api_params)
                response_time = time.time() - response_start
                logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")

                # Log token usage if available
                if 'usage' in response:
                    logger.info(f"Token usage - Input: {response['usage'].get('inputTokens', 'N/A')}, " +
                               f"Output: {response['usage'].get('outputTokens', 'N/A')}")

                # Append assistant's response
                messages.append({
                    "role": "assistant", 
                    "content": response['output']['message']['content']
                })

                stop_reason = response.get('stopReason')
                logger.debug(f"Bedrock response stop reason: {stop_reason}")

                if stop_reason == "tool_use":
                    logger.info("Processing tool use requests")
                    tool_results_content = []
                    tool_calls = []

                    for content_item in response['output']['message']['content']:
                        if 'toolUse' in content_item:
                            tool_id = content_item['toolUse']['toolUseId']
                            tool_name = content_item['toolUse']['name']
                            tool_inputs = content_item['toolUse']['input']

                            logger.info(f"Executing AWS MCP tool: {tool_name} with inputs: {tool_inputs}")
                            tool_calls.append({"name": tool_name, "inputs": tool_inputs})

                            # Execute tool call via MCP server
                            try:
                                result_text = self._call_tool(tool_name, tool_inputs)
                                logger.info(f"AWS MCP tool {tool_name} executed successfully")
                                logger.debug(f"Tool result preview: {str(result_text)[:200]}...")

                            except Exception as tool_error:
                                logger.error(f"AWS MCP tool execution failed for {tool_name}: {tool_error}")
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
                    # Return the final response
                    final_response = response['output']['message']['content'][0]['text']
                    processing_time = time.time() - start_time
                    logger.info(f"Query processing completed successfully in {processing_time:.2f} seconds")
                    
                    return {
                        "response": final_response,
                        "tool_calls": getattr(self, '_last_tool_calls', []),
                        "processing_time_seconds": processing_time,
                        "iterations": iteration
                    }

            # Max iterations reached
            logger.warning(f"Conversation exceeded maximum iterations ({max_iterations})")
            processing_time = time.time() - start_time
            return {
                "response": "The conversation took too many turns. Please try a more specific query.",
                "tool_calls": [],
                "processing_time_seconds": processing_time,
                "error": "Max iterations exceeded"
            }

        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            return {
                "error": str(e),
                "tool_calls": [],
                "processing_time_seconds": processing_time
            }

def get_bedrock_slack_result(query: str) -> str:
    """Format response for Slack messaging"""
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
    
    try:
        response = bedrock_client.converse(**api_params)
        response_time = time.time() - start_time
        logger.info(f"Slack formatting completed in {response_time:.2f} seconds")
        return response['output']['message']['content'][0]['text']
    except Exception as e:
        logger.error(f"Error formatting for Slack: {e}")
        return f"Error formatting response: {str(e)}"

def lambda_handler(event, context):
    """Main Lambda handler for AWS MCP operations"""
    request_id = context.aws_request_id
    logger.info(f"Lambda invocation started - RequestID: {request_id}")
    
    # Log memory and time limits
    logger.info(f"Memory allocated: {context.memory_limit_in_mb}MB, " +
               f"Time remaining: {context.get_remaining_time_in_millis()/1000:.2f}s")
    
    # Log event data
    logger.info(f"Event type: {type(event)}")
    if isinstance(event, dict):
        # Be careful not to log sensitive data
        safe_keys = [k for k in event.keys() if not any(sensitive in k.lower() 
                    for sensitive in ['token', 'secret', 'password', 'key'])]
        logger.info(f"Event keys: {safe_keys}")

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
    server_url = body.get('server_url', os.environ.get('AWS_MCP_SERVER_URL', ''))
    region = body.get('region', os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'))
    
    # Get Slack-specific parameters
    channel_id = event.get('channel_id', body.get('channel_id', ''))
    user_id = event.get('user_id', body.get('user_id', ''))
    response_url = event.get('response_url', body.get('response_url', ''))
    
    logger.info(f"Query length: {len(query)}")
    logger.info(f"Server URL provided: {'Yes' if server_url else 'No'}")
    logger.info(f"Region: {region}")
    logger.info(f"Channel ID: {channel_id[:10]}..." if channel_id else "No channel ID")

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
            'body': json.dumps({'error': 'Missing required parameter: server_url (AWS MCP Server endpoint)'})
        }

    start_time = time.time()
    
    # Create AWS MCP client and process query
    try:
        logger.info("Creating AWSMCPLambdaClient instance")
        client = AWSMCPLambdaClient(region=region)

        # Connect to AWS MCP server
        logger.info("Connecting to AWS MCP server")
        connected = client.connect_to_server(server_url)
        if not connected:
            logger.error("Failed to connect to AWS MCP server")
            return {
                'statusCode': 503,
                'body': json.dumps({'error': 'Failed to connect to AWS MCP server'})
            }

        # Process the query with AWS MCP tools
        logger.info("Processing query with AWS MCP tools and Claude")
        result = client.process_query(query)
        
        # Check for errors in result
        if 'error' in result:
            logger.error(f"Error in AWS MCP query processing: {result['error']}")

        # Clean up
        logger.info("Cleaning up AWS MCP client resources")
        client.cleanup()
        
        execution_time = time.time() - start_time
        logger.info(f"Lambda execution completed in {execution_time:.2f} seconds")

        # Send to Slack if channel_id is provided
        if channel_id:
            try:
                # Extract just the response text for Slack formatting
                response_text = result.get('response', str(result))
                bedrock_slack_result = get_bedrock_slack_result(response_text)
                send_slack_message(channel_id, bedrock_slack_result)
                logger.info("Response sent to Slack successfully")
            except Exception as slack_error:
                logger.error(f"Failed to send Slack message: {slack_error}")

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
                'execution_time_seconds': execution_time,
                'region': region,
                'tools_used': len(result.get('tool_calls', [])),
                'iterations': result.get('iterations', 1)
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
                'execution_time_seconds': execution_time,
                'query': query if 'query' in locals() else 'Unknown'
            })
        }
# ```

# ## Key improvements in this rewrite:

# ### 1. **Proper AWS MCP Integration**
# - Based on your AWS MCP Client structure
# - Connects to your AWS MCP server via HTTP/SSE
# - Uses the actual AWS tools from your MCP server

# ### 2. **Tool Management**
# - Dynamically fetches available tools from MCP server
# - Falls back to default AWS tools if server unavailable
# - Includes all your AWS MCP tools (EC2, S3, CloudWatch, etc.)

# ### 3. **Enhanced Error Handling**
# - Better connection management
# - Proper tool call error handling
# - Comprehensive logging

# ### 4. **AWS-Specific System Prompt**
# - Tailored for AWS operations
# - Emphasizes CloudWatch log management
# - Provides AWS best practices

# ### 5. **Conversation Loop**
# - Implements proper tool calling workflow
# - Handles multiple iterations
# - Rate limiting for API calls

# ### 6. **Lambda Optimizations**
# - Proper resource cleanup
# - Enhanced logging with request tracking
# - Better parameter handling
# - Slack integration preserved

# ### 7. **Environment Variables**
# - `AWS_MCP_SERVER_URL`: Your MCP server endpoint
# - `AWS_DEFAULT_REGION`: Default AWS region
# - All existing Slack environment variables

# The handler now properly integrates with your AWS MCP server and can execute all the AWS operations you've defined in your MCP tools!