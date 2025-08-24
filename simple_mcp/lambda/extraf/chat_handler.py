# lambda_function.py
import json
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import logging

# Initialize logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('oncalltable')
bedrock_runtime = boto3.client('bedrock-runtime')

# Bedrock model configuration
BEDROCK_MODEL_ID = "us.anthropic.claude-opus-4-20250514-v1:0"  # You can change this to your preferred model
# Other options: "anthropic.claude-instant-v1", "anthropic.claude-3-sonnet-20240229-v1:0",
# "meta.llama2-13b-chat-v1", "amazon.titan-text-express-v1"

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
        "action": "init" | "message" | "get",
        "session_id": "unique-session-id",
        "system_prompt": "System prompt text (for init action)",
        "message": "User message (for message action)",
        "model_id": "Optional: specific Bedrock model to use"
    }
    """
    try:
        # Parse the event
        body = json.loads(event.get('body', '{}')) if isinstance(event.get('body'), str) else event
        action = body.get('action', 'message')
        session_id = body.get('session_id')

        if not session_id:
            return create_response(400, {'error': 'session_id is required'})

        if action == 'init':
            return handle_init_conversation(session_id, body.get('system_prompt'))
        elif action == 'message':
            model_id = body.get('model_id', BEDROCK_MODEL_ID)
            return handle_message(session_id, body.get('message'), model_id)
        elif action == 'get':
            return handle_get_conversation(session_id)
        else:
            return create_response(400, {'error': 'Invalid action'})

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return create_response(500, {'error': str(e)})

def handle_init_conversation(session_id: str, system_prompt: Optional[str]) -> Dict:
    """Initialize a new conversation with system prompt"""
    try:
        # Check if conversation already exists
        existing = get_conversation(session_id)
        if existing:
            return create_response(409, {'error': 'Conversation already exists'})

        current_time = datetime.now(timezone.utc).isoformat()
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())

        # Create initial conversation with system prompt
        messages = []
        conversation_metadata = {}

        if system_prompt:
            # Store system prompt in metadata (some models handle it differently)
            conversation_metadata['system_prompt'] = system_prompt
            # For models that support system messages, add it to messages
            messages.append({
                'role': 'system',
                'content': system_prompt,
                'timestamp': current_time
            })

        conversation = {
            'session_id': session_id,
            'messages': messages,
            'created_at': current_time,
            'last_updated': current_time,
            'message_count': len(messages),
            'ttl': ttl_timestamp,
            'metadata': conversation_metadata
        }

        # Save to DynamoDB
        table.put_item(Item=conversation)

        return create_response(201, {
            'message': 'Conversation initialized',
            'session_id': session_id,
            'system_prompt_set': bool(system_prompt)
        })

    except Exception as e:
        logger.error(f"Error in handle_init_conversation: {str(e)}")
        return create_response(500, {'error': str(e)})

def handle_message(session_id: str, user_message: str, model_id: str) -> Dict:
    """Handle a new message in the conversation"""
    try:
        if not user_message:
            return create_response(400, {'error': 'Message content is required'})

        # Get existing conversation
        conversation = get_conversation(session_id)
        if not conversation:
            return create_response(404, {'error': 'Conversation not found'})

        current_time = datetime.now(timezone.utc).isoformat()

        # Add user message
        user_msg = {
            'role': 'user',
            'content': user_message,
            'timestamp': current_time
        }

        # Get system prompt from metadata if exists
        system_prompt = conversation.get('metadata', {}).get('system_prompt')

        # Generate AI response using Bedrock
        messages = conversation['messages']
        ai_response = generate_bedrock_response(messages + [user_msg], system_prompt, model_id)

        assistant_msg = {
            'role': 'assistant',
            'content': ai_response,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'model': model_id
        }

        # Update conversation
        messages.extend([user_msg, assistant_msg])

        # Update TTL (extend by 7 days from now)
        ttl_timestamp = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp())

        # Update in DynamoDB
        update_response = table.update_item(
            Key={'session_id': session_id},
            UpdateExpression='SET messages = :messages, last_updated = :last_updated, message_count = :count, #ttl_field = :ttl',
            ExpressionAttributeNames={
                '#ttl_field': 'ttl'
            },
            ExpressionAttributeValues={
                ':messages': messages,
                ':last_updated': current_time,
                ':count': len(messages),
                ':ttl': ttl_timestamp
            },
            ReturnValues='ALL_NEW'
        )
        logger.info(f"Update response: {update_response}")
        return create_response(200, {
            'session_id': session_id,
            'user_message': user_msg,
            'assistant_message': assistant_msg,
            'total_messages': len(messages)
        })

    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        return create_response(500, {'error': str(e)})

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

def handle_get_conversation(session_id: str) -> Dict:
    """Retrieve an existing conversation"""
    try:
        conversation = get_conversation(session_id)
        if not conversation:
            return create_response(404, {'error': 'Conversation not found'})

        return create_response(200, conversation)

    except Exception as e:
        logger.error(f"Error in handle_get_conversation: {str(e)}")
        return create_response(500, {'error': str(e)})

def get_conversation(session_id: str) -> Optional[Dict]:
    """Retrieve conversation from DynamoDB"""
    try:
        response = table.get_item(Key={'session_id': session_id})
        return response.get('Item')
    except Exception as e:
        logger.error(f"Error getting conversation: {str(e)}")
        return None

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
