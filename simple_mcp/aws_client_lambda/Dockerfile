FROM public.ecr.aws/lambda/python:3.12

# Copy requirements.txt
COPY requirements.txt ${LAMBDA_TASK_ROOT}

# Install the specified packages
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy function code
# COPY aws_mcp_client_lambda.py ${LAMBDA_TASK_ROOT}
COPY lambda_config.json ${LAMBDA_TASK_ROOT}
COPY common.py ${LAMBDA_TASK_ROOT}
COPY slack_utils.py ${LAMBDA_TASK_ROOT}
# COPY merged_lambda_client.py ${LAMBDA_TASK_ROOT}
# COPY merged_adv_slack.py ${LAMBDA_TASK_ROOT}
COPY tool ${LAMBDA_TASK_ROOT}/tool
# COPY changed_adv_slack.py ${LAMBDA_TASK_ROOT}
COPY common_prompt.txt ${LAMBDA_TASK_ROOT}
COPY sns_alert.py ${LAMBDA_TASK_ROOT}
COPY changed_adv_slack.py ${LAMBDA_TASK_ROOT}
COPY adv_slack.py ${LAMBDA_TASK_ROOT}
# Set the CMD to your handler
# CMD [ "aws_mcp_client_lambda.lambda_handler" ]
# CMD [ "merged_lambda_client.lambda_handler" ]
# CMD [ "changed_adv_slack.lambda_handler" ]
CMD [ "adv_slack.lambda_handler" ]