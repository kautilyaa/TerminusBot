# lambda_function.py
import json
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import logging
import uuid

# Initialize logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
instances_table = dynamodb.Table('oncall-instances')  # Table 1: Instance details
messages_table = dynamodb.Table('oncall-messages')    # Table 2: Chat history
bedrock_runtime = boto3.client('bedrock-runtime')

# Bedrock model configuration
BEDROCK_MODEL_ID = "us.anthropic.claude-opus-4-20250514-v1:0"

class DecimalEncoder(json.JSONEncoder):
    """Helper class to convert DynamoDB Decimal to JSON"""
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o)
        return super(DecimalEncoder, self).default(o)

def lambda_handler(event, context):
    """
    Main Lambda handler for chat interactions with Bedrock

    Expected event structure:
    {
        "action": "init" | "message" | "get" | "list_instances",
        "instance_id": "unique-instance-id",
        "system_prompt": "System prompt text (for init action)",
        "message": "User message (for message action)",
        "model_id": "Optional: specific Bedrock model to use"
    }
    """
    try:
        # Parse the event
        body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event
        action = body.get('action', 'message')
        instance_id = body.get('instance_id')

        if action == 'list_instances':
            return handle_list_instances()
        
        if not instance_id:
            return create_response(400, {'error': 'instance_id is required'})

        if action == 'init':
            return handle_init_instance(instance_id, body.get('system_prompt'))
        elif action == 'message':
            model_id = body.get('model_id', BEDROCK_MODEL_ID)
            return handle_message(instance_id, body.get('message'), model_id)
        elif action == 'get':
            return handle_get_instance(instance_id)
        else:
            return create_response(400, {'error': 'Invalid action'})

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return create_response(500, {'error': str(e)})

def handle_init_instance(instance_id: str, system_prompt: Optional[str]) -> Dict:
    """Initialize a new instance with system prompt"""
    try:
        # Check if instance already exists
        existing = get_instance(instance_id)
        if existing:
            return create_response(409, {'error': 'Instance already exists'})

        current_time = datetime.now(timezone.utc).isoformat()
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())

        # Create instance record
        instance = {
            'instance_id': instance_id,
            'system_prompt': system_prompt or '',
            'created_at': current_time,
            'updated_at': current_time,
            'message_count': 0,
            'status': 'active',
            'ttl': ttl_timestamp,
            'metadata': {
                'model_id': BEDROCK_MODEL_ID,
                'platform': 'terminal-mcp'
            }
        }

        # Save to instances table
        instances_table.put_item(Item=instance)

        return create_response(201, {
            'message': 'Instance initialized',
            'instance_id': instance_id,
            'system_prompt_set': bool(system_prompt)
        })

    except Exception as e:
        logger.error(f"Error in handle_init_instance: {str(e)}")
        return create_response(500, {'error': str(e)})

def handle_message(instance_id: str, user_message: str, model_id: str) -> Dict:
    """Handle a new message in the conversation"""
    try:
        if not user_message:
            return create_response(400, {'error': 'Message content is required'})

        # Get existing instance
        instance = get_instance(instance_id)
        if not instance:
            return create_response(404, {'error': 'Instance not found'})

        current_time = datetime.now(timezone.utc).isoformat()
        message_id = str(uuid.uuid4())

        # Add user message to messages table
        user_msg = {
            'instance_id': instance_id,
            'message_id': message_id,
            'role': 'user',
            'content': user_message,
            'timestamp': current_time,
            'message_order': instance['message_count'] + 1
        }

        messages_table.put_item(Item=user_msg)

        # Get conversation history for context
        conversation_history = get_conversation_history(instance_id)
        
        # Generate AI response using Bedrock
        ai_response = generate_bedrock_response(conversation_history + [user_msg], 
                                              instance.get('system_prompt'), model_id)

        # Add assistant message to messages table
        assistant_msg_id = str(uuid.uuid4())
        assistant_msg = {
            'instance_id': instance_id,
            'message_id': assistant_msg_id,
            'role': 'assistant',
            'content': ai_response,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'message_order': instance['message_count'] + 2,
            'model': model_id
        }

        messages_table.put_item(Item=assistant_msg)

        # Update instance record
        new_message_count = instance['message_count'] + 2
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())

        instances_table.update_item(
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

        return create_response(200, {
            'instance_id': instance_id,
            'user_message': user_msg,
            'assistant_message': assistant_msg,
            'total_messages': new_message_count
        })

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        return create_response(500, {'error': str(e)})

def handle_get_instance(instance_id: str) -> Dict:
    """Retrieve an existing instance with its messages"""
    try:
        instance = get_instance(instance_id)
        if not instance:
            return create_response(404, {'error': 'Instance not found'})

        # Get conversation history
        messages = get_conversation_history(instance_id)
        
        response_data = {
            'instance': instance,
            'messages': messages
        }

        return create_response(200, response_data)

    except Exception as e:
        logger.error(f"Error in handle_get_instance: {str(e)}")
        return create_response(500, {'error': str(e)})

def handle_list_instances() -> Dict:
    """List all active instances"""
    try:
        response = instances_table.scan(
            FilterExpression='#status = :status',
            ExpressionAttributeNames={
                '#status': 'status'
            },
            ExpressionAttributeValues={
                ':status': 'active'
            }
        )
        
        instances = response.get('Items', [])
        
        # Sort by updated_at descending
        instances.sort(key=lambda x: x.get('updated_at', ''), reverse=True)
        
        return create_response(200, {
            'instances': instances,
            'count': len(instances)
        })

    except Exception as e:
        logger.error(f"Error in handle_list_instances: {str(e)}")
        return create_response(500, {'error': str(e)})

def get_instance(instance_id: str) -> Optional[Dict]:
    """Retrieve instance from DynamoDB"""
    try:
        response = instances_table.get_item(Key={'instance_id': instance_id})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting instance: {str(e)}")
        return None

def get_conversation_history(instance_id: str) -> List[Dict]:
    """Retrieve conversation history from messages table"""
    try:
        response = messages_table.query(
            KeyConditionExpression='instance_id = :instance_id',
            ExpressionAttributeValues={
                ':instance_id': instance_id
            },
            ScanIndexForward=True  # Sort by message_order ascending
        )
        
        return response.get('Items', [])
    except Exception as e:
        logger.error(f"Error getting conversation history: {str(e)}")
        return []

def generate_bedrock_response(messages: List[Dict], system_prompt: Optional[str], model_id: str) -> str:
    """Generate AI response using AWS Bedrock"""
    try:
        # Prepare the prompt based on the model
        if model_id.startswith("anthropic.claude"):
            return generate_claude_response(messages, system_prompt, model_id)
        elif model_id.startswith("meta.llama"):
            return generate_llama_response(messages, system_prompt, model_id)
        elif model_id.startswith("amazon.nova"):
            return generate_titan_response(messages, system_prompt, model_id)
        else:
            # Default to Claude format
            return generate_claude_response(messages, system_prompt, model_id)

    except Exception as e:
        logger.error(f"Error generating Bedrock response: {str(e)}")
        return "I apologize, but I'm having trouble generating a response right now."

def generate_claude_response(messages: List[Dict], system_prompt: Optional[str], model_id: str) -> str:
    """Generate response using Claude models"""
    try:
        # Format messages for Claude
        formatted_messages = []

        # Claude expects alternating user/assistant messages
        for msg in messages:
            if msg['role'] in ['user', 'assistant']:
                formatted_messages.append({
                    'role': msg['role'],
                    'content': msg['content']
                })

        # Construct the request body for Claude
        request_body = {
            "messages": formatted_messages,
            "max_tokens": 1000,
            "temperature": 0.7,
            "anthropic_version": "bedrock-2023-05-31"
        }

        # Add system prompt if provided
        if system_prompt:
            request_body["system"] = system_prompt

        # Invoke the model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body)
        )

        # Parse the response
        response_body = json.loads(response['body'].read())
        return response_body.get('content', [{}])[0].get('text', 'No response generated')

    except Exception as e:
        logger.error(f"Error with Claude model: {str(e)}")
        raise

def generate_llama_response(messages: List[Dict], system_prompt: Optional[str], model_id: str) -> str:
    """Generate response using Llama models"""
    try:
        # Format the conversation for Llama
        prompt = ""

        if system_prompt:
            prompt = f"<s>[INST] <<SYS>>\\n{system_prompt}\\n<</SYS>>\\n\\n"
        else:
            prompt = "<s>[INST] "

        # Add conversation history
        for i, msg in enumerate(messages):
            if msg['role'] == 'user':
                if i > 0:  # Not the first message
                    prompt += f"[INST] {msg['content']} [/INST]"
                else:
                    prompt += f"{msg['content']} [/INST]"
            elif msg['role'] == 'assistant':
                prompt += f" {msg['content']} </s><s>"

        # Construct the request body for Llama
        request_body = {
            "prompt": prompt,
            "max_gen_len": 512,
            "temperature": 0.7,
            "top_p": 0.9
        }

        # Invoke the model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body)
        )

        # Parse the response
        response_body = json.loads(response['body'].read())
        return response_body.get('generation', 'No response generated')

    except Exception as e:
        logger.error(f"Error with Llama model: {str(e)}")
        raise

def generate_titan_response(messages: List[Dict], system_prompt: Optional[str], model_id: str) -> str:
    """Generate response using Amazon Titan models"""
    try:
        # Format the conversation for Titan
        conversation_text = ""

        if system_prompt:
            conversation_text = f"System: {system_prompt}\\n\\n"

        # Add conversation history
        for msg in messages:
            if msg['role'] == 'user':
                conversation_text += f"User: {msg['content']}\\n"
            elif msg['role'] == 'assistant':
                conversation_text += f"Assistant: {msg['content']}\\n"

        conversation_text += "Assistant: "

        # Construct the request body for Titan
        request_body = {
            "inputText": conversation_text,
            "textGenerationConfig": {
                "maxTokenCount": 512,
                "temperature": 0.7,
                "topP": 0.9,
                "stopSequences": ["User:"]
            }
        }

        # Invoke the model
        response = bedrock_runtime.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(request_body)
        )

        # Parse the response
        response_body = json.loads(response['body'].read())
        results = response_body.get('results', [])
        return results[0].get('outputText', 'No response generated') if results else 'No response generated'

    except Exception as e:
        logger.error(f"Error with Titan model: {str(e)}")
        raise

def create_response(status_code: int, body: Dict) -> Dict:
    """Create API Gateway response"""
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        },
        'body': json.dumps(body, cls=DecimalEncoder)
    }