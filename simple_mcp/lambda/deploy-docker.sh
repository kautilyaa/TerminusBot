#!/bin/bash

# Set variables
FUNCTION_NAME="terminal-mcp-lambda"
AWS_ACCOUNT_ID=\$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="us-east-1"
IMAGE_NAME="terminal-mcp-lambda"
ECR_REPOSITORY="\$AWS_ACCOUNT_ID.dkr.ecr.\$AWS_REGION.amazonaws.com/\$IMAGE_NAME"
MCP_SERVER_URL="\${MCP_SERVER_URL:-http://localhost:8080/sse}"

# Create Lambda execution role if it doesn't exist
ROLE_NAME="\${FUNCTION_NAME}-role"
ROLE_ARN="arn:aws:iam::\$AWS_ACCOUNT_ID:role/\$ROLE_NAME"

# Check if role exists
aws iam get-role --role-name \$ROLE_NAME 2>/dev/null || {
    echo "Creating Lambda execution role..."
    aws iam create-role \
        --role-name \$ROLE_NAME \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "lambda.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole"
                }
            ]
        }'
    
    # Attach policies
    aws iam attach-role-policy \
        --role-name \$ROLE_NAME \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    
    # Attach Bedrock policy
    aws iam put-role-policy \
        --role-name \$ROLE_NAME \
        --policy-name BedrockAccess \
        --policy-document '{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream"
                    ],
                    "Resource": "*"
                }
            ]
        }'
    
    # Wait for role to be available
    sleep 10
}

# Check if Lambda function exists
aws lambda get-function --function-name \$FUNCTION_NAME 2>/dev/null && {
    echo "Updating existing Lambda function..."
    aws lambda update-function-code \
        --function-name \$FUNCTION_NAME \
        --image-uri \$ECR_REPOSITORY:latest
    
    aws lambda update-function-configuration \
        --function-name \$FUNCTION_NAME \
        --environment "Variables={MCP_SERVER_URL=\$MCP_SERVER_URL}" \
        --timeout 300 \
        --memory-size 512
} || {
    echo "Creating new Lambda function..."
    aws lambda create-function \
        --function-name \$FUNCTION_NAME \
        --package-type Image \
        --code ImageUri=\$ECR_REPOSITORY:latest \
        --role \$ROLE_ARN \
        --timeout 300 \
        --memory-size 512 \
        --environment "Variables={MCP_SERVER_URL=\$MCP_SERVER_URL}"
}

echo "Lambda function deployed successfully!"