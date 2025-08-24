#!/bin/bash

# Build and deploy the Lambda function
echo "Building Lambda function..."
sam build

echo "Deploying Lambda function..."
sam deploy \
  --stack-name terminal-mcp-lambda \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides MCPServerURL=\$MCP_SERVER_URL \
  --resolve-s3

# Get the API endpoint and key
echo "Getting API details..."
API_ENDPOINT=\$(aws cloudformation describe-stacks \
  --stack-name terminal-mcp-lambda \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiEndpoint`].OutputValue' \
  --output text)

API_KEY_ID=\$(aws cloudformation describe-stacks \
  --stack-name terminal-mcp-lambda \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiKeyId`].OutputValue' \
  --output text)

API_KEY=\$(aws apigateway get-api-key \
  --api-key \$API_KEY_ID \
  --include-value \
  --query 'value' \
  --output text)

echo "API Endpoint: \$API_ENDPOINT"
echo "API Key: \$API_KEY"