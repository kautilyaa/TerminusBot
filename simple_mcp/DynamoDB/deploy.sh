#!/bin/bash

# DynamoDB Infrastructure Deployment Script
# This script deploys the DynamoDB tables and Lambda function for the Terminal MCP system

set -e  # Exit on any error

# Configuration
STACK_NAME="terminal-mcp-dynamodb"
REGION="us-east-1"
TEMPLATE_FILE="template.yaml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if AWS CLI is installed and configured
check_aws_cli() {
    print_status "Checking AWS CLI installation..."
    
    if ! command -v aws &> /dev/null; then
        print_error "AWS CLI is not installed. Please install it first."
        exit 1
    fi
    
    if ! aws sts get-caller-identity &> /dev/null; then
        print_error "AWS CLI is not configured. Please run 'aws configure' first."
        exit 1
    fi
    
    print_success "AWS CLI is installed and configured"
}

# Function to check if template file exists
check_template() {
    if [ ! -f "$TEMPLATE_FILE" ]; then
        print_error "Template file $TEMPLATE_FILE not found"
        exit 1
    fi
    print_success "Template file found"
}

# Function to validate CloudFormation template
validate_template() {
    print_status "Validating CloudFormation template..."
    
    if aws cloudformation validate-template --template-body file://$TEMPLATE_FILE --region $REGION &> /dev/null; then
        print_success "Template validation successful"
    else
        print_error "Template validation failed"
        exit 1
    fi
}

# Function to check if stack exists
stack_exists() {
    aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION &> /dev/null
}

# Function to deploy the stack
deploy_stack() {
    print_status "Deploying CloudFormation stack: $STACK_NAME"
    
    local deploy_command="aws cloudformation deploy \
        --template-file $TEMPLATE_FILE \
        --stack-name $STACK_NAME \
        --capabilities CAPABILITY_IAM \
        --region $REGION \
        --no-fail-on-empty-changeset"
    
    if eval $deploy_command; then
        print_success "Stack deployment completed successfully"
    else
        print_error "Stack deployment failed"
        exit 1
    fi
}

# Function to get stack outputs
get_stack_outputs() {
    print_status "Getting stack outputs..."
    
    local outputs=$(aws cloudformation describe-stacks \
        --stack-name $STACK_NAME \
        --region $REGION \
        --query 'Stacks[0].Outputs' \
        --output json)
    
    echo "$outputs" | jq -r '.[] | "\(.OutputKey): \(.OutputValue)"'
}

# Function to test DynamoDB tables
test_tables() {
    print_status "Testing DynamoDB tables..."
    
    # Test instances table
    if aws dynamodb describe-table --table-name oncall-instances --region $REGION &> /dev/null; then
        print_success "oncall-instances table exists"
    else
        print_error "oncall-instances table not found"
        return 1
    fi
    
    # Test messages table
    if aws dynamodb describe-table --table-name oncall-messages --region $REGION &> /dev/null; then
        print_success "oncall-messages table exists"
    else
        print_error "oncall-messages table not found"
        return 1
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -r, --region REGION AWS region (default: us-east-1)"
    echo "  -s, --stack-name    CloudFormation stack name (default: terminal-mcp-dynamodb)"
    echo "  --validate-only     Only validate the template, don't deploy"
    echo "  --test-only         Only test existing tables, don't deploy"
    echo ""
    echo "Examples:"
    echo "  $0                    # Deploy with default settings"
    echo "  $0 -r us-west-2       # Deploy to us-west-2 region"
    echo "  $0 --validate-only    # Only validate template"
    echo "  $0 --test-only        # Only test existing tables"
}

# Parse command line arguments
VALIDATE_ONLY=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_usage
            exit 0
            ;;
        -r|--region)
            REGION="$2"
            shift 2
            ;;
        -s|--stack-name)
            STACK_NAME="$2"
            shift 2
            ;;
        --validate-only)
            VALIDATE_ONLY=true
            shift
            ;;
        --test-only)
            TEST_ONLY=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            show_usage
            exit 1
            ;;
    esac
done

# Main execution
main() {
    echo "🚀 DynamoDB Infrastructure Deployment Script"
    echo "============================================="
    echo "Stack Name: $STACK_NAME"
    echo "Region: $REGION"
    echo "Template: $TEMPLATE_FILE"
    echo ""
    
    # Check prerequisites
    check_aws_cli
    check_template
    
    if [ "$VALIDATE_ONLY" = true ]; then
        validate_template
        print_success "Template validation completed"
        exit 0
    fi
    
    if [ "$TEST_ONLY" = true ]; then
        test_tables
        print_success "Table testing completed"
        exit 0
    fi
    
    # Validate template
    validate_template
    
    # Deploy stack
    if stack_exists; then
        print_warning "Stack $STACK_NAME already exists. Updating..."
    else
        print_status "Creating new stack: $STACK_NAME"
    fi
    
    deploy_stack
    
    # Test tables
    test_tables
    
    # Show outputs
    echo ""
    print_status "Stack outputs:"
    get_stack_outputs
    
    echo ""
    print_success "Deployment completed successfully!"
    echo ""
    echo "Next steps:"
    echo "1. Test the DynamoDB client: cd ../client && python test_dynamodb.py"
    echo "2. Use the CLI tool: cd ../client && python dynamodb_cli.py --help"
    echo "3. Deploy the Lambda function: cd ../lambda && ./deploy.sh"
}

# Run main function
main "$@" 