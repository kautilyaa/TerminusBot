import json
import boto3
import logging
import os
from .bedrock_client import invoke_model
from .event_manager import EventManager
from .sns_alert import send_sns_alert

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
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
        
        # Send SNS alert
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if sns_topic_arn:
            alert_subject = "Lambda Function Execution Complete"
            alert_message = f"""
            Lambda function execution completed successfully.
            
            Event Details:
            {json.dumps(event, indent=2)}
            
            Result:
            {json.dumps(result, indent=2)}
            """
            send_sns_alert(alert_subject, alert_message, sns_topic_arn)
            logger.info("SNS alert sent successfully")
        
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
        logger.info(f"Returning response: {dict_json}")
        return dict_json
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}", exc_info=True)
        
        # Send error alert if SNS topic is configured
        sns_topic_arn = os.environ.get('SNS_TOPIC_ARN')
        if sns_topic_arn:
            error_subject = "Lambda Function Execution Failed"
            error_message = f"""
            Lambda function execution failed with an error.
            
            Event Details:
            {json.dumps(event, indent=2)}
            
            Error:
            {str(e)}
            """
            try:
                send_sns_alert(error_subject, error_message, sns_topic_arn)
                logger.info("Error SNS alert sent successfully")
            except Exception as sns_error:
                logger.error(f"Failed to send error SNS alert: {str(sns_error)}")
        
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