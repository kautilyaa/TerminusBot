import boto3
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def send_sns_alert_old(subject, message, topic_arn):
    """
    Send an email alert using SNS
    
    Args:
        subject (str): Email subject
        message (str): Email message body
        topic_arn (str): SNS topic ARN to publish to
    """
    try:
        sns_client = boto3.client('sns')
        
        # Publish message to SNS topic
        response = sns_client.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=message,
            MessageStructure='string'
        )
        
        logger.info(f"Successfully sent SNS alert. MessageId: {response['MessageId']}")
        return response
    except Exception as e:
        logger.error(f"Failed to send SNS alert: {str(e)}", exc_info=True)
        raise
import boto3

def send_sns_alert(subject, message, topic_arn):
    """Send SNS alert"""
    sns = boto3.client('sns')
    sns.publish(
        TopicArn=topic_arn,
        Subject=subject,
        Message=message
    )