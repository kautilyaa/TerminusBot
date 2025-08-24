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

# Initialize Lambda client for invoking AWS MCP Lambda
lambda_client = boto3.client('lambda', region_name='us-east-1', config=config)

def is_cloud_query_bedrock(query: str) -> bool:
    """Use Bedrock to intelligently determine if a query is cloud/AWS related"""
    try:
        logger.info("Using Bedrock to classify query type")
        
        classification_prompt = f"""
        <instruction>
        You are a query classifier. Analyze the following user query and determine if it's related to cloud computing, AWS services, or infrastructure management versus terminal/system administration tasks.

        Cloud/AWS queries include:
        - AWS service operations (EC2, S3, RDS, Lambda, CloudWatch, etc.)
        - Cloud infrastructure management
        - AWS account information
        - Cloud monitoring and logging
        - Resource provisioning and management
        - AWS regions and availability zones

        Terminal/System queries include:
        - Local file operations
        - System commands (ls, cat, grep, etc.)
        - Local server administration
        - Package management
        - Process management
        - Local log file analysis
        - Script execution

        Query: "{query}"

        Respond with ONLY a JSON object in this exact format:
        {{"is_cloud": true/false, "confidence": 0.0-1.0, "reasoning": "brief explanation"}}
        </instruction>
        """

        messages = [{"role": "user", "content": [{"text": classification_prompt}]}]
        
        api_params = {
            "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "messages": messages,
            "inferenceConfig": {"maxTokens": 200, "temperature": 0.9},
        }

        response = bedrock_client.converse(**api_params)
        result_text = response['output']['message']['content'][0]['text'].strip()
        
        # Parse the JSON response
        try:
            classification = json.loads(result_text)
            is_cloud = classification.get('is_cloud', False)
            confidence = classification.get('confidence', 0.0)
            reasoning = classification.get('reasoning', 'No reasoning provided')
            
            logger.info(f"Bedrock classification - Cloud: {is_cloud}, Confidence: {confidence:.2f}, Reasoning: {reasoning}")
            
            # Use confidence threshold
            if confidence >= 0.7:
                return is_cloud
            else:
                logger.warning(f"Low confidence ({confidence:.2f}), falling back to keyword matching")
                return is_cloud_query_fallback(query)
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Bedrock classification response: {e}")
            logger.warning(f"Raw response: {result_text}")
            return is_cloud_query_fallback(query)
            
    except Exception as e:
        logger.error(f"Error using Bedrock for query classification: {str(e)}")
        logger.info("Falling back to keyword-based classification")
        return is_cloud_query_fallback(query)

def is_cloud_query_fallback(query: str) -> bool:
    """Fallback keyword-based cloud query detection"""
    cloud_keywords = [
        # AWS Services
        'aws', 'ec2', 's3', 'rds', 'lambda', 'cloudwatch', 'iam', 'vpc', 'elb', 'route53',
        'dynamodb', 'sqs', 'sns', 'cloudformation', 'eks', 'ecs', 'fargate', 'beanstalk',
        
        # AWS Operations
        'instance', 'bucket', 'database', 'cloud', 'region', 'availability zone',
        'security group', 'load balancer', 'auto scaling', 'elastic', 'cloudfront',
        
        # AWS Resources
        'ami', 'snapshot', 'volume', 'subnet', 'internet gateway', 'nat gateway',
        'elastic ip', 'key pair', 'certificate', 'parameter store',
        
        # AWS Monitoring
        'cloudwatch logs', 'metrics', 'alarms', 'billing', 'cost', 'usage',
        
        # General cloud terms
        'start instance', 'stop instance', 'create bucket', 'list buckets',
        'aws account', 'caller identity', 'describe instances'
    ]
    
    query_lower = query.lower()
    
    # Check for direct AWS service mentions
    for keyword in cloud_keywords:
        if keyword in query_lower:
            logger.info(f"Fallback: Cloud query detected with keyword '{keyword}'")
            return True
    
    # Check for patterns that suggest cloud operations
    cloud_patterns = [
        'list all', 'show me all', 'get all',
        'create', 'delete', 'modify', 'update',
        'monitor', 'check status', 'health check',
        'logs from', 'search logs', 'error logs',
    ]
    
    for pattern in cloud_patterns:
        if pattern in query_lower:
            # Check if it's combined with infrastructure terms
            infra_terms = ['server', 'service', 'resource', 'infrastructure', 'deployment']
            for term in infra_terms:
                if term in query_lower:
                    logger.info(f"Fallback: Cloud query detected with pattern '{pattern}' and term '{term}'")
                    return True
    
    logger.info("Fallback: Query determined to be non-cloud related")
    return False

def extract_region_from_query_bedrock(query: str) -> str:
    """Use Bedrock to intelligently extract AWS region from query"""
    try:
        logger.info("Using Bedrock to extract AWS region")
        
        region_prompt = f"""
        <instruction>
        Extract the AWS region from this query if mentioned. Consider both technical region names and common location names.

        AWS Regions:
        - us-east-1: N. Virginia, Virginia, US East
        - us-east-2: Ohio, US East 2
        - us-west-1: N. California, California, US West 1
        - us-west-2: Oregon, US West 2
        - eu-west-1: Ireland, Europe West
        - eu-central-1: Frankfurt, Germany, Europe Central
        - ap-southeast-1: Singapore, Asia Pacific Southeast
        - ap-northeast-1: Tokyo, Japan, Asia Pacific Northeast

        Query: "{query}"

        Respond with ONLY a JSON object:
        {{"region": "region-code-or-us-east-1", "found": true/false}}
        </instruction>
        """

        messages = [{"role": "user", "content": [{"text": region_prompt}]}]
        
        api_params = {
            "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "messages": messages,
            "inferenceConfig": {"maxTokens": 100, "temperature": 0.1},
        }

        response = bedrock_client.converse(**api_params)
        result_text = response['output']['message']['content'][0]['text'].strip()
        
        try:
            region_data = json.loads(result_text)
            region = region_data.get('region', 'us-east-1')
            found = region_data.get('found', False)
            
            if found and region != 'us-east-1':
                logger.info(f"Bedrock extracted region: {region}")
            else:
                logger.info("Bedrock: No specific region found, using default us-east-1")
                region = 'us-east-1'
            
            return region
                
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Bedrock region response: {e}")
            return extract_region_fallback(query)
        
    except Exception as e:
        logger.error(f"Error using Bedrock for region extraction: {str(e)}")
        return extract_region_fallback(query)

def extract_region_fallback(query: str) -> str:
    """Fallback keyword-based region extraction"""
    region_keywords = {
        'us-east-1': ['us-east-1', 'virginia', 'n. virginia'],
        'us-east-2': ['us-east-2', 'ohio'],
        'us-west-1': ['us-west-1', 'california', 'n. california'],
        'us-west-2': ['us-west-2', 'oregon'],
        'eu-west-1': ['eu-west-1', 'ireland'],
        'eu-central-1': ['eu-central-1', 'frankfurt'],
        'ap-southeast-1': ['ap-southeast-1', 'singapore'],
        'ap-northeast-1': ['ap-northeast-1', 'tokyo']
    }
    
    query_lower = query.lower()
    for aws_region, keywords in region_keywords.items():
        for keyword in keywords:
            if keyword in query_lower:
                logger.info(f"Fallback: Detected region: {aws_region}")
                return aws_region
    
    return 'us-east-1'  # default

def invoke_aws_mcp_lambda(query: str, region: str = 'us-east-1') -> Dict:
    """Invoke the AWS MCP Lambda function"""
    try:
        aws_lambda_function_name = os.environ.get('AWS_MCP_LAMBDA_FUNCTION_NAME', 'oncall-lambda-4')
        logger.info(f"Invoking AWS MCP Lambda: {aws_lambda_function_name}")
        
        payload = {
            'body': json.dumps({
                'query': query,
                'region': region,
                'server_url': 'http://13.222.180.210:8002/sse/'
            })
        }
        
        response = lambda_client.invoke(
            FunctionName=aws_lambda_function_name,
            InvocationType='RequestResponse',  # Synchronous invocation
            Payload=json.dumps(payload)
        )
        
        # Parse the response
        response_payload = json.loads(response['Payload'].read())
        
        if response['StatusCode'] == 200:
            # Parse the body if it's a string
            if isinstance(response_payload.get('body'), str):
                body = json.loads(response_payload['body'])
            else:
                body = response_payload.get('body', {})
            
            logger.info("AWS Lambda invocation successful")
            
            # Format the response for consistency
            aws_result = body.get('result', {})
            formatted_response = format_aws_response(aws_result)
            
            return {
                "response": formatted_response,
                "tool_calls": aws_result.get('tool_calls', []),
                "processing_time_seconds": body.get('execution_time_seconds', 0),
                "aws_lambda_used": True,
                "region": region
            }
        else:
            logger.error(f"AWS Lambda invocation failed with status: {response['StatusCode']}")
            return {
                "error": f"AWS Lambda invocation failed: {response_payload}",
                "aws_lambda_used": True
            }
            
    except Exception as e:
        logger.error(f"Error invoking AWS Lambda: {str(e)}", exc_info=True)
        return {
            "error": f"Failed to invoke AWS Lambda: {str(e)}",
            "aws_lambda_used": True
        }

def format_aws_response(aws_result: Dict) -> str:
    """Format the AWS Lambda response for better readability"""
    if isinstance(aws_result, dict):
        if 'response' in aws_result:
            response_text = aws_result['response']
            
            # Add execution summary if tool calls were made
            if 'tool_calls' in aws_result and aws_result['tool_calls']:
                tool_summary = f"\n\n**🔧 Executed {len(aws_result['tool_calls'])} AWS operations:**\n"
                for i, tool_call in enumerate(aws_result['tool_calls'], 1):
                    tool_summary += f"{i}. {tool_call.get('tool_name', 'Unknown')} "
                    if 'inputs' in tool_call:
                        inputs_str = ', '.join([f"{k}={v}" for k, v in tool_call['inputs'].items() if k != 'region'])
                        if inputs_str:
                            tool_summary += f"({inputs_str})"
                    tool_summary += "\n"
                
                response_text += tool_summary
            
            # Add timing information
            if 'processing_time_seconds' in aws_result:
                response_text += f"\n*⏱️ AWS processing time: {aws_result['processing_time_seconds']:.2f} seconds*"
            
            return response_text
        else:
            return str(aws_result)
    else:
        return str(aws_result)

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
        - For cloud/AWS related queries, inform the user that these should be handled by the AWS specialist system.
        </rules>
        </instruction>
        """

        # Use Bedrock's Claude to generate a response
        api_params = {
            "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": 16384, "temperature": 0.9},
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
            "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": 16384, "temperature": 0.9},
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

    start_time = time.time()
    
    # Use Bedrock to intelligently determine if this is a cloud-related query
    if is_cloud_query_bedrock(query):
        logger.info("🤖 Bedrock determined: Cloud query detected - routing to AWS MCP Lambda")
        
        # Use Bedrock to extract region from query if mentioned
        region = extract_region_from_query_bedrock(query)
        
        # Route to AWS Lambda
        result = invoke_aws_mcp_lambda(query, region)
        
        # Add processing time
        execution_time = time.time() - start_time
        result['total_execution_time_seconds'] = execution_time
        
        # Handle Slack response for cloud queries
        channel_id = event.get('channel_id', '')
        user_id = event.get('user_id', '')
        response_url = event.get('response_url', '')
        text = event.get('text', '')
        
        # Extract just the response text for Slack formatting
        response_text = result.get('response', str(result))
        
        # Add context about which system handled the query
        response_text += f"\n\n_☁️ Processed by AWS Cloud Operations System (Region: {region})_"
        
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
                'execution_time_seconds': execution_time,
                'routed_to_aws_lambda': True,
                'region': region,
                'classification_method': 'bedrock'
            })
        }
    
    # Continue with original terminal processing logic
    logger.info("🤖 Bedrock determined: Terminal query - processing locally")
    
    if not server_url:
        logger.warning("Missing required parameter: server_url")
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing required parameter: server_url'})
        }
    
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

        channel_id = event.get('channel_id', '')
        user_id = event.get('user_id', '')
        response_url = event.get('response_url', '')
        text = event.get('text', '')
        
        # Extract just the response text for Slack formatting
        response_text = result.get('response', str(result))
        
        # Add context about which system handled the query
        response_text += f"\n\n_💻 Processed by Terminal System_"
        
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
                'execution_time_seconds': execution_time,
                'routed_to_aws_lambda': False,
                'classification_method': 'bedrock'
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