import boto3
import json

def create_bedrock_client(access_key, secret_key, session_token, region="us-east-1"):
    """
    Create a boto3 session with temporary credentials
    
    Args:
        access_key (str): AWS access key ID
        secret_key (str): AWS secret access key
        session_token (str): AWS session token for temporary credentials
        region (str): AWS region name
    
    Returns:
        boto3.client: Configured Bedrock client
    """
    # Create a boto3 session with temporary credentials
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token,
        region_name=region
    )

    # Set up the Amazon Bedrock client using the session
    bedrock_client = session.client(
        service_name="bedrock-runtime",
        region_name=region
    )
    return bedrock_client

def invoke_model(bedrock_client, prompt, model_id="anthropic.claude-3-sonnet-20240229-v1:0"):
    """
    Invoke the Bedrock model with the given prompt
    
    Args:
        bedrock_client: The Bedrock client instance
        prompt (str): The input prompt
        model_id (str): The model ID to use
    
    Returns:
        str: The generated response
    """
    # Define the payload for the model invocation
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 3000,
        "temperature": 0.7,
        "system": "You are an intelligent AWS on-call agent. When a CloudWatch alarm is triggered, your job is to analyze the alarm details, summarize the failure, identify the root cause, and recommend concise remediation steps. Your responses must be structured, technically accurate, and easy for an engineer to act upon. If applicable, suggest AWS-native commands or actions to resolve the issue. Always prioritize clarity, brevity, and operational relevance. Do not invent metrics or data. Base your analysis strictly on the input event details.",

        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ]
    }

    # Invoke the Amazon Bedrock model
    response = bedrock_client.invoke_model(
        modelId=model_id,
        body=json.dumps(payload)
    )

    # Process the response
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]

# if __name__ == "__main__":
#     # Example usage with temporary credentials
#     ACCESS_KEY = "ASIAXMVFDUALOIHTFCDE"
#     SECRET_KEY = "bzd59enWtLjYLFfmBLqYy7prWfzOcspsfSS8yUxR"
#     SESSION_TOKEN = """IQoJb3JpZ2luX2VjEOr//////////wEaCXVzLWVhc3QtMSJGMEQCIGNCvRVIAVnJq/ZnmY8z35wSpFQt9fmFRPQ8zIlLw1ZOAiBTDwP9Fov5rnhaeN2i8EgRfC6fWMSX8VBWNG5SwOznVCqVAwjD//////////8BEAAaDDUwODIyNjE1MDQyMiIMV558pwuBqoZgpx/0KukCCAxcbvIY8slWdHDLd9ZI9SW+qI/gwsr8rRh4YJD8xpC+LOVm7K6kBHhJhEbYUndFzwtk71RmV9lw/gnCWd15r1JDHctkoajCx0ih1jMRSS6oMIQu7wbWgRt6tsKOX5DiGivMV/M1uAT/UsmrY6PZdIMPJ3HkCrs+s9ETK4qsY/zVqPhKW3TjCpU6HoJLQqvRSMdAzgG1TtQPz9EO9eyJWmbXvPH47IKnFw7fT4CIkbAEErl7O1k71RqMil4/Xm2Sk7oZYB9xHh4tjQc1QQ3Q7L0KlZMe5YkHk6Qc/GQ0ORa4t4YjKT9quRhq42/+7tBiTxwxjTN20lhx3bTZIoOT/pTfR3oWSGiUi0bBnd4ahJ8kqJRvwItlmCfpBf/p3Q4IULA5b6TeLBFbK5xh0yvla2VoCkGtZriTtmzvhtrUR0sMnh2rXfSVTkITCu/OTPIqUj6rV1+66BOKxjsOInGfgkohpHL10mQ+6TCs36HCBjqnAeTCjvfmXyEeqfi/KXAiNCvxirWl9FFrw512gh7x88Fz9ocbOJ8ZCiDD2U7Xw6Dv6QwT9oDJ9GhfeU6MrFd59/6/fHSZ7cb1UaoMQxXO3cwivZWWSoEpIkUN4Nwi9ttlSKj6y86iMKAY+OcHY5nxWaNxr9Brs9JrQVPleZ+2vjt4+II5O3m5yXDuajtWprpacoa8WUOHfTr7V74x9Eu3OOIx6Q6jxUGb"""
#     # Create client with temporary credentials
#     client = create_bedrock_client(
#         access_key=ACCESS_KEY,
#         secret_key=SECRET_KEY,
#         session_token=SESSION_TOKEN
#     )
    
#     # Test the client
#     response = invoke_model(client, "Hello, how are you? How to make agent for aws oncall?")
#     print(f"Response: {response}") 