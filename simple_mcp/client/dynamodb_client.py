import boto3
import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal
import logging

# Initialize logging
logger = logging.getLogger(__name__)

class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o)
        return super(DecimalEncoder, self).default(o)

class DynamoDBClient:
    """Client for interacting with DynamoDB tables for chat instances and messages"""
    
    def __init__(self, region_name: str = 'us-east-1'):
        """Initialize DynamoDB client with specified region"""
        self.dynamodb = boto3.resource('dynamodb', region_name=region_name)
        self.instances_table = self.dynamodb.Table('oncall-instances')
        self.messages_table = self.dynamodb.Table('oncall-messages')
        
    def create_instance(self, instance_id: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a new chat instance
        
        Args:
            instance_id: Unique identifier for the instance
            system_prompt: Optional system prompt for the conversation
            
        Returns:
            Dict containing the created instance data
        """
        try:
            # Check if instance already exists
            existing = self.get_instance(instance_id)
            if existing:
                raise ValueError(f"Instance {instance_id} already exists")
            
            current_time = datetime.now(timezone.utc).isoformat()
            ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
            
            instance = {
                'instance_id': instance_id,
                'system_prompt': system_prompt or '',
                'created_at': current_time,
                'updated_at': current_time,
                'message_count': 0,
                'status': 'active',
                'ttl': ttl_timestamp,
                'metadata': {
                    'model_id': 'us.anthropic.claude-opus-4-20250514-v1:0',
                    'platform': 'terminal-mcp'
                }
            }
            
            self.instances_table.put_item(Item=instance)
            logger.info(f"Created instance: {instance_id}")
            
            return {
                'success': True,
                'instance_id': instance_id,
                'system_prompt_set': bool(system_prompt),
                'data': instance
            }
            
        except Exception as e:
            logger.error(f"Error creating instance {instance_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_instance(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve an instance by ID
        
        Args:
            instance_id: Unique identifier for the instance
            
        Returns:
            Instance data or None if not found
        """
        try:
            response = self.instances_table.get_item(Key={'instance_id': instance_id})
            return response.get('Item')
        except Exception as e:
            logger.error(f"Error getting instance {instance_id}: {str(e)}")
            return None
    
    def list_instances(self, status: str = 'active') -> Dict[str, Any]:
        """
        List all instances with specified status
        
        Args:
            status: Status filter for instances (default: 'active')
            
        Returns:
            Dict containing list of instances
        """
        try:
            response = self.instances_table.query(
                IndexName='StatusIndex',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':status': status
                }
            )
            
            instances = response.get('Items', [])
            # Sort by updated_at descending
            instances.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
            
            return {
                'success': True,
                'instances': instances,
                'count': len(instances)
            }
            
        except Exception as e:
            logger.error(f"Error listing instances: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def add_message(self, instance_id: str, role: str, content: str, model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Add a message to an instance
        
        Args:
            instance_id: Instance ID to add message to
            role: Message role ('user' or 'assistant')
            content: Message content
            model_id: Optional model ID for assistant messages
            
        Returns:
            Dict containing the created message data
        """
        try:
            # Get instance to check if it exists and get message count
            instance = self.get_instance(instance_id)
            if not instance:
                raise ValueError(f"Instance {instance_id} not found")
            
            current_time = datetime.now(timezone.utc).isoformat()
            message_id = str(uuid.uuid4())
            
            message = {
                'instance_id': instance_id,
                'message_id': message_id,
                'role': role,
                'content': content,
                'timestamp': current_time,
                'message_order': instance['message_count'] + 1
            }
            
            # Add model info for assistant messages
            if role == 'assistant' and model_id:
                message['model'] = model_id
            
            self.messages_table.put_item(Item=message)
            
            # Update instance message count and timestamp
            new_message_count = instance['message_count'] + 1
            ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
            
            self.instances_table.update_item(
                Key={'instance_id': instance_id},
                UpdateExpression='SET message_count = :count, updated_at = :updated, #ttl_field = :ttl',
                ExpressionAttributeNames={
                    '#ttl_field': 'ttl'
                },
                ExpressionAttributeValues={
                    ':count': new_message_count,
                    ':updated': current_time,
                    ':ttl': ttl_timestamp
                }
            )
            
            logger.info(f"Added message to instance {instance_id}: {message_id}")
            
            return {
                'success': True,
                'message_id': message_id,
                'message_order': new_message_count,
                'data': message
            }
            
        except Exception as e:
            logger.error(f"Error adding message to instance {instance_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_conversation_history(self, instance_id: str) -> List[Dict[str, Any]]:
        """
        Get conversation history for an instance
        
        Args:
            instance_id: Instance ID to get history for
            
        Returns:
            List of messages in chronological order
        """
        try:
            response = self.messages_table.query(
                KeyConditionExpression='instance_id = :instance_id',
                ExpressionAttributeValues={
                    ':instance_id': instance_id
                },
                ScanIndexForward=True  # Sort by message_order ascending
            )
            
            return response.get('Items', [])
            
        except Exception as e:
            logger.error(f"Error getting conversation history for {instance_id}: {str(e)}")
            return []
    
    def delete_instance(self, instance_id: str) -> Dict[str, Any]:
        """
        Delete an instance and all its messages
        
        Args:
            instance_id: Instance ID to delete
            
        Returns:
            Dict containing deletion result
        """
        try:
            # First, delete all messages
            messages = self.get_conversation_history(instance_id)
            for message in messages:
                self.messages_table.delete_item(
                    Key={
                        'instance_id': instance_id,
                        'message_id': message['message_id']
                    }
                )
            
            # Then delete the instance
            self.instances_table.delete_item(Key={'instance_id': instance_id})
            
            logger.info(f"Deleted instance {instance_id} and {len(messages)} messages")
            
            return {
                'success': True,
                'deleted_messages': len(messages)
            }
            
        except Exception as e:
            logger.error(f"Error deleting instance {instance_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def update_instance_status(self, instance_id: str, status: str) -> Dict[str, Any]:
        """
        Update instance status
        
        Args:
            instance_id: Instance ID to update
            status: New status ('active', 'inactive', 'archived')
            
        Returns:
            Dict containing update result
        """
        try:
            current_time = datetime.now(timezone.utc).isoformat()
            
            self.instances_table.update_item(
                Key={'instance_id': instance_id},
                UpdateExpression='SET #status = :status, updated_at = :updated',
                ExpressionAttributeNames={
                    '#status': 'status'
                },
                ExpressionAttributeValues={
                    ':status': status,
                    ':updated': current_time
                }
            )
            
            logger.info(f"Updated instance {instance_id} status to {status}")
            
            return {
                'success': True,
                'status': status
            }
            
        except Exception as e:
            logger.error(f"Error updating instance {instance_id} status: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def get_instance_stats(self, instance_id: str) -> Dict[str, Any]:
        """
        Get statistics for an instance
        
        Args:
            instance_id: Instance ID to get stats for
            
        Returns:
            Dict containing instance statistics
        """
        try:
            instance = self.get_instance(instance_id)
            if not instance:
                return {
                    'success': False,
                    'error': 'Instance not found'
                }
            
            messages = self.get_conversation_history(instance_id)
            
            # Count messages by role
            user_messages = len([m for m in messages if m['role'] == 'user'])
            assistant_messages = len([m for m in messages if m['role'] == 'assistant'])
            
            # Calculate total tokens (rough estimate)
            total_tokens = sum(len(m['content'].split()) for m in messages)
            
            return {
                'success': True,
                'instance_id': instance_id,
                'total_messages': len(messages),
                'user_messages': user_messages,
                'assistant_messages': assistant_messages,
                'estimated_tokens': total_tokens,
                'created_at': instance['created_at'],
                'updated_at': instance['updated_at'],
                'status': instance['status']
            }
            
        except Exception as e:
            logger.error(f"Error getting stats for instance {instance_id}: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            } 