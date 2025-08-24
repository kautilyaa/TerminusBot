# Set variables
AWS_ACCOUNT_ID=\$(aws sts get-caller-identity --query Account --output text)
AWS_REGION="us-east-1"
IMAGE_NAME="terminal-mcp-lambda"
ECR_REPOSITORY="\$AWS_ACCOUNT_ID.dkr.ecr.\$AWS_REGION.amazonaws.com/\$IMAGE_NAME"

# Create ECR repository if it doesn't exist
aws ecr describe-repositories --repository-names \$IMAGE_NAME --region \$AWS_REGION 2>/dev/null || \
    aws ecr create-repository --repository-name \$IMAGE_NAME --region \$AWS_REGION

# Get login token and log in to ECR
aws ecr get-login-password --region \$AWS_REGION | docker login --username AWS --password-stdin \$ECR_REPOSITORY

# Build the Docker image
echo "Building Docker image..."
docker build -t \$IMAGE_NAME:latest .

# Tag the image
docker tag \$IMAGE_NAME:latest \$ECR_REPOSITORY:latest

# Push the image to ECR
echo "Pushing image to ECR..."
docker push \$ECR_REPOSITORY:latest

echo "Docker image pushed successfully!"
echo "Image URI: \$ECR_REPOSITORY:latest"