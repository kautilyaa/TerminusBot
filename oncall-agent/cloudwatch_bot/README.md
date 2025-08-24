# AWS Lambda with Bedrock Integration

This project implements an AWS Lambda function that integrates with Amazon Bedrock for AI/ML capabilities. The function is monitored using CloudWatch for logging and alerting.

## Architecture

- AWS Lambda function that processes requests and interacts with Amazon Bedrock
- CloudWatch for logging and monitoring
- SNS for error notifications
- IAM role-based authentication

## Prerequisites

1. **AWS CLI** - Install and configure with your AWS credentials
   ```bash
   aws configure
   ```

2. **AWS SAM CLI** - Install the SAM CLI
   ```bash
   # On macOS
   brew install aws-sam-cli
   
   # Or using pip
   pip install aws-sam-cli
   ```

3. **Docker** - Install Docker for containerization
   ```bash
   # On macOS
   brew install docker
   ```

4. **Additional Requirements**
   - AWS Account with appropriate permissions
   - Python 3.10 or later
   - Amazon Bedrock access enabled in your AWS account
   - Amazon ECR repository for storing Docker images

## Deployment Options

### Option 1: Using Docker

1. **Build the Docker image**
   ```bash
   # Build the image
   docker build -t oncall-lambda .
   ```

2. **Test the Docker image locally**
   ```bash
   # Run the container locally
   docker run -p 9000:8080 oncall-lambda
   
   # In another terminal, test the function
   curl -XPOST "http://localhost:9000/2015-03-31/functions/function/invocations" -d '{"prompt": "test"}'
   ```

3. **Push to Amazon ECR**
   ```bash
   # Create an ECR repository (if not exists)
   aws ecr create-repository --repository-name oncall-lambda --image-scanning-configuration scanOnPush=true
   
   # Get the ECR login command
   aws ecr get-login-password --region your-region | docker login --username AWS --password-stdin your-account-id.dkr.ecr.your-region.amazonaws.com
   
   # Tag the image
   docker tag oncall-lambda:latest your-account-id.dkr.ecr.your-region.amazonaws.com/oncall-lambda:latest
   
   # Push the image
   docker push your-account-id.dkr.ecr.your-region.amazonaws.com/oncall-lambda:latest
   ```

4. **Update Lambda function to use the container image**
   ```bash
   aws lambda update-function-code \
       --function-name your-function-name \
       --image-uri your-account-id.dkr.ecr.your-region.amazonaws.com/oncall-lambda:latest
   ```

### Option 2: Using AWS SAM

1. **Build the SAM application**
   ```bash
   sam build
   ```

2. **Deploy the application**
   For first time deployment:
   ```bash
   sam deploy --guided
   ```

   This will prompt you for:
   - Stack Name (e.g., `lambda-sample-stack`)
   - AWS Region (e.g., `us-east-1`)
   - Confirm changes before deploy: Y
   - Allow SAM to create IAM roles: Y
   - Save parameters to samconfig.toml: Y

   For subsequent deployments:
   ```bash
   sam deploy
   ```

3. **Test the API**
   After deployment, SAM will output the API Gateway URL. You can test it using:
   ```bash
   curl https://YOUR-API-ID.execute-api.REGION.amazonaws.com/Prod/hello/
   ```

### Option 2: Using CloudFormation

1. **Deploy the Lambda Function**
   ```bash
   # Package the Lambda function
   zip -r function.zip src/
   
   # Create the Lambda function
   aws lambda create-function \
       --function-name your-function-name \
       --runtime python3.13 \
       --handler src/oncall-lambda.lambda_handler \
       --role arn:aws:iam::your-account-id:role/your-lambda-role \
       --zip-file fileb://function.zip
   ```

   ```bash
   aws lambda update-function-code \  --function-name oncall-lambda \            --zip-file fileb://oncall-lambda.zip
   ```a

2. **Deploy CloudWatch Resources**
   ```bash
   aws cloudformation deploy \
       --template-file cloudwatch-resources.yaml \
       --stack-name lambda-monitoring-stack \
       --parameter-overrides \
           LambdaFunctionName=your-function-name \
           ErrorThreshold=1 \
           LatencyThreshold=1000
   ```

3. **Subscribe to SNS Notifications**
   ```bash
   # Get the SNS Topic ARN from CloudFormation outputs
   aws cloudformation describe-stacks \
       --stack-name lambda-monitoring-stack \
       --query 'Stacks[0].Outputs[?OutputKey==`NotificationTopicARN`].OutputValue' \
       --output text
   
   # Subscribe to the topic (replace with your email)
   aws sns subscribe \
       --topic-arn your-sns-topic-arn \
       --protocol email \
       --notification-endpoint your-email@example.com
   ```

## Local Testing

You can test the function locally before deploying:

```bash
# Start the local API
sam local start-api

# Test the endpoint
curl http://localhost:3000/hello
```

## Monitoring

The function is monitored using CloudWatch with the following features:

1. **Log Groups**
   - All Lambda function logs are stored in CloudWatch Logs
   - 30-day retention period
   - Access via AWS Console or CLI

2. **Alarms**
   - Error monitoring: Triggers when function errors exceed threshold
   - Latency monitoring: Triggers when function duration exceeds threshold
   - Notifications sent via SNS

3. **Viewing Logs**
   ```bash
   aws logs get-log-events \
       --log-group-name /aws/lambda/your-function-name \
       --log-stream-name latest
   ```

## IAM Permissions

The Lambda function requires the following IAM permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "bedrock:InvokeModel"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents"
            ],
            "Resource": "arn:aws:logs:*:*:*"
        }
    ]
}
```

## Error Handling

The function includes comprehensive error handling and logging:
- All errors are logged to CloudWatch
- Error details are returned in the response
- Alarms are triggered for error conditions
- Stack traces are included in error logs

## Project Structure

- `src/oncall-lambda.py` - The Lambda function code
- `src/bedrock_client.py` - Bedrock client implementation
- `cloudwatch-resources.yaml` - CloudFormation template for monitoring
- `template.yaml` - SAM template defining the infrastructure
- `requirements.txt` - Python dependencies


