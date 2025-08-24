import json
import boto3
import logging
# from .bedrock_client import invoke_model
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



def get_bedrock_slack_result(query: str):
    """Format query response for Slack using Bedrock"""
    start_time = time.time()
    
    # Ensure query is a string
    if not isinstance(query, str):
        query = str(query)
        logger.warning(f"Query was not a string, converted to: {query[:100]}...")
    
    system_prompt = """
        Disk Space Management Agent - Python Implementation Prompt

        You are implementing a disk space management agent that processes CloudWatch alerts 
        and manages large files. Your Python code must follow this exact workflow:

        WORKFLOW STEPS:

        Step 1: CloudWatch Alarm Analysis
        - Analyze the provided CloudWatch alarm summary
        - Extract key information: timestamp, affected instance, disk usage metrics, alert severity
        - Acknowledge the alarm and prepare for file investigation

        Step 2: File Identification
        - Based on the alarm summary, identify which specific file(s) are causing the disk space issue ignore the system files. And try to find files based on the alarm summary.
        - Determine file location, size, and type from the provided context
        - Report the problematic file details clearly

        Step 3: Log File Processing Decision
        - Evaluate if the identified file is a log file (check for .log, .out, .err extensions or log-related naming patterns)
        - If it IS a log file:
        * Automatically perform log rotation
        * Create compressed zip file in /tmp directory
        * Null the original log file using > filename
        * Report the action taken and space freed
        - If it is NOT a log file, proceed to Step 4

        Step 4: User Consultation for Non-Log Files
        - Present the file information to the user
        - Ask: "This file appears to be [file_type]. Based on its age ([age]) and size ([size]), is this file needed or can it be deleted/archived?"
        - Provide context about the file's age (old vs newer) and potential impact
        - Present clear options: Delete, Archive, or Keep

        Step 5: Process User Input
        - Wait for user response (Yes/No or Delete/Archive/Keep)
        - Execute the chosen action:
        * Yes/Delete: Remove the file and report space freed
        * Archive: Compress and move to archive location
        * No/Keep: Log the decision and provide recommendations for future monitoring
        - Confirm action completion and current disk status

        IMPLEMENTATION REQUIREMENTS:
        - Create a main class DiskSpaceManager with methods for each step
        - Include proper error handling and logging
        - Implement user input validation
        - Add safety checks before file operations
        - Return structured responses for each step
        - Maintain audit trail of all operations

        SAFETY REQUIREMENTS:
        - Always confirm file details before any deletion
        - Create backups for critical operations
        - Verify space recovery after each action
        - Maintain audit trail of all operations
        - Do not delete any system files or showcase them analyze. Ignore the system files.

        INPUT: CloudWatch alarm summary data
        OUTPUT: Step-by-step processing results and final status report here let it be a string as a prompt for the agent entry point.
        """
    
    messages = [{"role": "user", "content": [{"text": query}]}]
    api_params = {
        "modelId": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "system": [{"text": system_prompt}],
        "messages": messages,
        "inferenceConfig": {"maxTokens": 65535, "temperature": 0.9},
    }
    
    response = bedrock_client.converse(**api_params)
    response_time = time.time() - start_time
    logger.info(f"Bedrock API call completed in {response_time:.2f} seconds")
    return response['output']['message']['content'][0]['text']


def send_event_to_mcp_agent(event):
    logger.info(f"Entering send_event_to_mcp_agent with event: {event}")
    lambda_client = boto3.client('lambda')
    logger.info(f"Invoking Lambda function: {os.environ.get('AWS_LAMBDA_NAME')}")
    lambda_client.invoke(
        FunctionName=os.environ['AWS_LAMBDA_NAME'],
        InvocationType='Event',
        Payload=json.dumps(event)
    )
    logger.info(f"Sent event to Lambda function {os.environ['AWS_LAMBDA_NAME']}")

def lambda_handler(event, context):
    dict_json = {"statusCode": 200, "body": "Hello from Lambda!"}
    logger.info(f"Welcome: {dict_json}")
    logger.info(f"Received event: {json.dumps(event)}")
    try:
        logger.info(f"Received event: {json.dumps(event)}")
        
        # Create Bedrock client using Lambda's IAM role
        logger.info("Initializing Bedrock client...")
        bedrock_client = boto3.client(
            service_name="bedrock-runtime",
            region_name=event.get('region', 'us-east-1')
        )
        logger.info("Bedrock client initialized successfully")
        
        # Initialize EventManager with the Bedrock client
        event_manager = EventManager(bedrock_client)
        
        # Process the event using EventManager
        logger.info("Processing event with EventManager...")
        result = event_manager.process_event(event)
        logger.info("Successfully processed event")
        
        # Use Bedrock to format the result as the email body for the SNS alert
        email_subject = f"Lambda Function Execution Complete: {event.get('alarm_name', 'N/A')} : {event.get('id', 'N/A')}"

        # Minimal prompt: just ask Bedrock to format the given result for an on-call email
        bedrock_email_prompt = f"Format the following result as a professional on-call incident email body for sns alert, without changing the content:\n\n{json.dumps(result, indent=2)}"
        try:
            bedrock_email_response = bedrock_client.invoke_model(
                modelId="anthropic.claude-3-sonnet-20240229-v1:0",
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1000,
                    "temperature": 0.5,
                    "messages": [
                        {"role": "user", "content": bedrock_email_prompt}
                    ]
                })
            )
            bedrock_email_body = json.loads(bedrock_email_response["body"].read())["content"][0]["text"]
        except Exception as e:
            logger.error(f"Failed to generate email body with Bedrock: {str(e)}")
            bedrock_email_body = "Error generating formatted email body. Please see Lambda logs."

        email_body = f"""{bedrock_email_body}"""
        
        logger.info(f"Email body: {email_body}")

        # Send SNS alert if topic ARN is set
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        logger.info(f"SNS topic ARN: {sns_topic_arn}")
        if sns_topic_arn:
            send_sns_alert(email_subject, email_body, sns_topic_arn)


        mcp_agent_url = os.environ['MCP_AGENT_URL']
        logger.info(f"MCP_AGENT_URL: {mcp_agent_url}")
        # logger.info(f"Payload to send to MCP agent: {payload}")
        # send_event_to_mcp_agent(payload)
        response_url = ""
        command = "event-alert"
        text = get_bedrock_slack_result(result)
        user_id = ""
        channel_id = "C093YB9BJEA"
        
        
        payload = {
            'command': command,
            'text': text,
            'user_id': user_id,
            'channel_id': channel_id,
            'response_url': response_url,
            "body":{
                "query": text,
                "server_url": mcp_agent_url 
                }
        }
        send_event_to_mcp_agent(payload)

        dict_json = {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": "Success",
                "response": result,
                "event": event
            })
        }
        

        logger.info(f"Returning response: {json.dumps(result)}")
        return dict_json
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json"
            },
            "body": json.dumps({
                "message": "Error",
                "error": str(e),
                "event": event
            })
        }





