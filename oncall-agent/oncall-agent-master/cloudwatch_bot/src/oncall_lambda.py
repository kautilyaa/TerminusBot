import json
import boto3
import logging
from event_manager import EventManager
from sns_alert import send_sns_alert
import os
from botocore.config import Config
import time

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

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

def get_bedrock_slack_result(query: str, alarm_context: dict = None):
    """Format query response for Slack using Bedrock with enhanced disk space management"""
    start_time = time.time()
    
    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")
    
    # Enhanced system prompt with better structure and clarity
    system_prompt = """
        You are an advanced Disk Space Management Agent that processes CloudWatch alerts and manages large files efficiently. 

        CORE RESPONSIBILITIES:
        1. Analyze CloudWatch disk space alerts and extract critical information
        2. Identify problematic files causing disk space issues (excluding system files)
        3. Automatically process log files with rotation and compression
        4. Provide user consultation for non-log files with clear recommendations
        5. Execute approved actions and maintain comprehensive audit trails

        WORKFLOW EXECUTION:

        STEP 1: CloudWatch Alarm Analysis
        - Parse alarm data: timestamp, instance ID, disk usage %, alert severity
        - Validate if this is a disk space issue vs other system issues
        - If NOT disk-related: Generate investigation prompt for CloudWatch Analysis Agent
        - If disk-related: Proceed to file identification

        STEP 2: Intelligent File Discovery
        - Scan for large files based on alarm context and typical problem areas
        - Focus on: /var/log/, /tmp/, /home/, application directories
        - EXCLUDE system files: /bin/, /sbin/, /lib/, /etc/, /usr/bin/, /boot/
        - Prioritize by size and identify file types (log, data, temp, backup)
        - Report findings with size, age, location, and type classification

        STEP 3: Automated Log File Processing
        - Detect log files: .log, .out, .err extensions + naming patterns (access, error, debug)
        - Auto-execute for log files:
        * Create timestamped compressed archive in /tmp/ with .zip extension
        * Null original log file (> filename)
        * Calculate and report space recovery
        * Log action in audit trail
        - For non-log files: Proceed to user consultation

        STEP 4: Smart User Consultation
        - Present comprehensive file analysis:
        * File path, size, age, type, last modified
        * Risk assessment (critical data vs temp/cache)
        * Impact analysis of deletion/archival
        - Options with recommendations:
        * DELETE: For temp/cache files older than 30 days
        * ARCHIVE: For data files that might be needed later
        * KEEP: For recently modified or critical files
        - Provide context-aware suggestions based on file characteristics

        STEP 5: Safe Action Execution
        - Validate user choice and perform safety checks
        - Execute with confirmation:
        * DELETE: Permanent removal with space calculation
        * ARCHIVE: Compress to /tmp/archive/ with significant space savings
        * KEEP: Log decision and set monitoring recommendations
        - Verify action completion and update disk status

        OUTPUT REQUIREMENTS:
        - Provide concise, actionable Slack-formatted messages
        - Include metrics: files processed, space freed, actions taken
        - Add relevant emojis for visual clarity (🚨📁🗜️✅)
        - Format as professional incident response updates
        - Include next steps and monitoring recommendations

        SAFETY PROTOCOLS:
        - Never touch system files or critical OS components
        - Always create backups before destructive operations
        - Validate file paths and permissions before actions
        - Maintain detailed audit logs for compliance
        - Provide rollback information where applicable

        SPECIAL HANDLING:
        - For non-disk issues: Generate specific investigation prompts for CloudWatch agents
        - For database files: Recommend specialized database cleanup procedures  
        - For application logs: Suggest application-specific log management
        - For user data: Emphasize backup importance and provide archive options
        """

    # Add context if available
    context_info = ""
    if alarm_context:
        context_info = f"\nALARM CONTEXT:\n{json.dumps(alarm_context, indent=2)}\n"
    
    full_query = f"{context_info}\nEVENT DATA:\n{query}"
    
    messages = [{"role": "user", "content": [{"text": full_query}]}]
    api_params = {
        "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {
            "maxTokens": 65535, 
            "temperature": 0.7,  # Slightly lower for more consistent responses
            "topP": 0.9
        },
    }
    
    try:
        response = bedrock_client.converse(**api_params)
        response_time = time.time() - start_time
        logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")
        return response['output']['message']['content'][0]['text']
    except Exception as e:
        logger.error(f"Bedrock API call failed: {str(e)}")
        return f"🚨 **Disk Space Alert Processing Failed**\n\nError: {str(e)}\n\nRaw Event Data:\n```{query}```"

def generate_professional_email_body(result: dict, bedrock_client):
    """Generate professional email body using Bedrock"""
    
    email_prompt = """
You are tasked with creating a professional on-call incident email for a disk space management event.

REQUIREMENTS:
- Format as a clear, actionable incident report
- Include executive summary at the top
- Organize information hierarchically
- Use professional language suitable for technical stakeholders
- Include specific metrics and actions taken
- Provide clear next steps if any are required
- Maintain urgency appropriate to the situation

STRUCTURE:
1. Executive Summary (2-3 sentences)
2. Incident Details (timestamp, affected systems, severity)
3. Actions Taken (specific steps performed)
4. Results (space freed, files processed, status)
5.NextSteps (if any follow-up is required)
6. Contact Information (for escalation)

Format the following incident data into a professional email body:
"""
    
    try:
        response = bedrock_client.invoke_model(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1500,
                "temperature": 0.3,  # Lower temperature for professional consistency
                "messages": [
                    {"role": "user", "content": f"{email_prompt}\n\n{json.dumps(result, indent=2)}"}
                ]
            })
        )
        return json.loads(response["body"].read())["content"][0]["text"]
    except Exception as e:
        logger.error(f"Failed to generate professional email body: {str(e)}")
        return f"""
INCIDENT REPORT: Disk Space Management Event

Executive Summary:
Automated disk space management process completed. Please review the details below and Lambda logs for complete information.

Incident Details:
- Timestamp: {result.get('timestamp', 'N/A')}
- Status: {result.get('status', 'Unknown')}
- Processing Error: Failed to generate detailed report

Raw Data:
{json.dumps(result, indent=2)}

Next Steps:
Please review Lambda logs for detailed information and contact the on-call engineer if immediate action is required.
"""

def send_event_to_mcp_agent(event):
    """Send event to MCP agent with enhanced error handling"""
    try:
        logger.info(f"Sending event to MCP agent: {event.get('command', 'unknown')}")
        lambda_client = boto3.client('lambda')
        
        lambda_function_name = os.environ.get('AWS_LAMBDA_NAME')
        if not lambda_function_name:
            raise ValueError("AWS_LAMBDA_NAME environment variable not set")
            
        logger.info(f"Invoking Lambda function: {lambda_function_name}")
        
        response = lambda_client.invoke(
            FunctionName=lambda_function_name,
            InvocationType='Event',
            Payload=json.dumps(event)
        )
        
        logger.info(f"Successfully sent event to Lambda function {lambda_function_name}")
        return response
        
    except Exception as e:
        logger.error(f"Failed to send event to MCP agent: {str(e)}")
        raise

def extract_alarm_context(event):
    """Extract relevant alarm context for better processing"""
    return {
        'alarm_name': event.get('alarm_name', 'Unknown'),
        'instance_id': event.get('instance_id', 'Unknown'),
        'region': event.get('region', 'us-east-1'),
        'severity': event.get('severity', 'Unknown'),
        'timestamp': event.get('timestamp', 'Unknown'),
        'metric_name': event.get('metric_name', 'Unknown'),
        'threshold': event.get('threshold', 'Unknown')
    }

def lambda_handler(event, context):
    """Enhanced Lambda handler with better error handling and logging"""
    request_id = context.aws_request_id if context else 'unknown'
    logger.info(f"[{request_id}] Lambda function started")
    logger.info(f"[{request_id}] Received event: {json.dumps(event, default=str)}")
    
    try:
        # Validate required environment variables
        required_env_vars = ['AWS_LAMBDA_NAME', 'MCP_AGENT_URL']
        missing_vars = [var for var in required_env_vars if not os.environ.get(var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")
        
        # Create Bedrock client
        logger.info(f"[{request_id}] Initializing Bedrock client...")
        bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=event.get('region', 'us-east-1'),
            config=config
        )
        logger.info(f"[{request_id}] Bedrock client initialized successfully")
        
        # Initialize EventManager
        event_manager = EventManager(bedrock_client)
        
        # Process the event
        logger.info(f"[{request_id}] Processing event with EventManager...")
        result = event_manager.process_event(event)
        logger.info(f"[{request_id}] Successfully processed event")
        
        # Extract alarm context for better processing
        alarm_context = extract_alarm_context(event)
        
        # Generate email content
        email_subject = f"🚨 Disk Space Alert: {alarm_context['alarm_name']} - Instance {alarm_context['instance_id']}"
        email_body = generate_professional_email_body(result, bedrock_client)
        
        logger.info(f"[{request_id}] Generated email subject: {email_subject}")
        
        # Send SNS alert if configured
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if sns_topic_arn:
            logger.info(f"[{request_id}] Sending SNS alert to: {sns_topic_arn}")
            send_sns_alert(email_subject, email_body, sns_topic_arn)
        else:
            logger.warning(f"[{request_id}] SNS_TOPIC_ARN not configured, skipping email alert")
        
        # Prepare and send Slack notification via MCP agent
        mcp_agent_url = os.environ['MCP_AGENT_URL']
        logger.info(f"[{request_id}] MCP_AGENT_URL: {mcp_agent_url}")
        
        # Generate Slack-formatted message
        slack_text = get_bedrock_slack_result(json.dumps(result, indent=2), alarm_context)
        
        # Prepare MCP agent payload
        mcp_payload = {
            'command': 'event-alert',
            'text': slack_text,
            'user_id': '',
            'channel_id': 'C093YB9BJEA',  # Consider making this configurable
            'response_url': '',
            'body': {
                'query': slack_text,
                'server_url': mcp_agent_url,
                'context': alarm_context
            }
        }
        
        # Send to MCP agent
        send_event_to_mcp_agent(mcp_payload)
        
        # Prepare success response
        response_body = {
            "message": "Disk space management process completed successfully",
            "request_id": request_id,
            "alarm_context": alarm_context,
            "processing_result": result,
            "notifications_sent": {
                "sns_email": bool(sns_topic_arn),
                "slack_notification": True
            }
        }
        
        logger.info(f"[{request_id}] Process completed successfully")
        
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps(response_body, default=str)
        }
        
    except Exception as e:
        logger.error(f"[{request_id}] Critical error occurred: {str(e)}", exc_info=True)
        
        # Send error notification if possible
        try:
            error_subject = f"🔥 Lambda Error: Disk Space Management - {request_id}"
            error_body = f"""
CRITICAL ERROR in Disk Space Management Lambda

Request ID: {request_id}
Error: {str(e)}
Event: {json.dumps(event, indent=2, default=str)}

Please check CloudWatch logs for detailed stack trace.
"""
            sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
            if sns_topic_arn:
                send_sns_alert(error_subject, error_body, sns_topic_arn)
        except:
            logger.error(f"[{request_id}] Failed to send error notification")
        
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": "Internal server error",
                "request_id": request_id,
                "error": str(e),
                "event": event
            }, default=str)
        }