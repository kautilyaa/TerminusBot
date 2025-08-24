
# # Use AWS Lambda Python runtime as base image
# FROM public.ecr.aws/lambda/python:3.11

# # Copy requirements file
# COPY requirements.txt \${LAMBDA_TASK_ROOT}/

# # Install Python dependencies
# RUN pip install --no-cache-dir -r \${LAMBDA_TASK_ROOT}/requirements.txt

# # Copy function code
# COPY lambda_function.py \${LAMBDA_TASK_ROOT}/

# # Set the CMD to your handler
# CMD ["lambda_function.lambda_handler"]



FROM public.ecr.aws/lambda/python:3.12

# Copy requirements.txt
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install the specified packages
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy function code
COPY sample_lambda_client.py ${LAMBDA_TASK_ROOT}
COPY common.py ${LAMBDA_TASK_ROOT}
COPY slack_utils.py ${LAMBDA_TASK_ROOT}

# Set the CMD to your handler
CMD [ "sample_lambda_client.lambda_handler" ]