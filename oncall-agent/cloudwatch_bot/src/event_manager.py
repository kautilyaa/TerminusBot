import json
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from bedrock_client import invoke_model

class AlarmState(BaseModel):
    value: str
    reason: str
    timestamp: str

class MetricConfig(BaseModel):
    namespace: str
    name: str
    dimensions: Dict[str, str]
    period: int
    stat: str

class AlarmEvent(BaseModel):
    instance_id: str
    alarm_name: str
    current_state: AlarmState
    previous_state: AlarmState
    metric_config: MetricConfig

class BedrockResponse(BaseModel):
    content: Optional[str] = None
    status: str
    error: Optional[str] = None

class EventManager:
    def __init__(self, bedrock_client):
        """Initialize EventManager with an existing Bedrock client."""
        self.bedrock_client = bedrock_client
        
    def _extract_instance_id(self, dimensions: Dict[str, str]) -> str:
        """Extract instance ID from metric dimensions."""
        return dimensions.get('InstanceId', '')
    
    def _parse_metric_config(self, metric_data: Dict) -> MetricConfig:
        """Parse metric configuration from the event."""
        metric = metric_data['metricStat']['metric']
        return MetricConfig(
            namespace=metric['namespace'],
            name=metric['name'],
            dimensions=metric['dimensions'],
            period=metric_data['metricStat']['period'],
            stat=metric_data['metricStat']['stat']
        )
    
    def _parse_alarm_state(self, state_data: Dict) -> AlarmState:
        """Parse alarm state information."""
        return AlarmState(
            value=state_data['value'],
            reason=state_data['reason'],
            timestamp=state_data['timestamp']
        )
    
    def parse_event(self, event: Dict) -> AlarmEvent:
        """Parse the CloudWatch alarm event into structured data."""
        detail = event['detail']
        
        # Extract metric configuration
        metric_config = self._parse_metric_config(detail['configuration']['metrics'][0])
        
        # Create alarm event object
        return AlarmEvent(
            instance_id=self._extract_instance_id(metric_config.dimensions),
            alarm_name=detail['alarmName'],
            current_state=self._parse_alarm_state(detail['state']),
            previous_state=self._parse_alarm_state(detail['previousState']),
            metric_config=metric_config
        )
    
    def generate_bedrock_prompt(self, alarm_event: AlarmEvent) -> str:
        """Generate a prompt for Bedrock to analyze the alarm event."""
        # return f"""
        # Analyze the following AWS CloudWatch alarm event and provide:
        # 1. Failure Summary
        # 2. Root Cause Analysis
        # 3. Recommended Remediation Steps

        # Instance ID: {alarm_event.instance_id}
        # Alarm Name: {alarm_event.alarm_name}
        # Current State: {alarm_event.current_state.value}
        # Previous State: {alarm_event.previous_state.value}
        # Metric: {alarm_event.metric_config.namespace}/{alarm_event.metric_config.name}
        # Failure Reason: {alarm_event.current_state.reason}
        # """
        return f"""
            Summarize the AWS CloudWatch alarm event below with:
            1. A brief Failure Summary  
            2. A concise Root Cause Analysis  
            3. Remediation Steps

            Details:
            - Instance ID: {alarm_event.instance_id}  
            - Alarm: {alarm_event.alarm_name}  
            - State: {alarm_event.previous_state.value} to {alarm_event.current_state.value}  
            - Metric: {alarm_event.metric_config.namespace}/{alarm_event.metric_config.name}  
            - Reason: {alarm_event.current_state.reason}



            """
                
    def get_bedrock_analysis(self, prompt: str) -> BedrockResponse:
        """Get analysis from Bedrock using the provided client."""
        try:
            response = invoke_model(
                bedrock_client=self.bedrock_client,
                prompt=prompt
            )
            return BedrockResponse(
                content=response,
                status="success"
            )
        except Exception as e:
            return BedrockResponse(
                error=str(e),
                status="error"
            )
    
    def process_event(self, event: Dict) -> Dict:
        """Main method to process the event and get Bedrock analysis."""
        # Parse the event
        alarm_event = self.parse_event(event)
        
        # Generate prompt
        prompt = self.generate_bedrock_prompt(alarm_event)
        
        # Get Bedrock analysis
        analysis = self.get_bedrock_analysis(prompt)
        
        # Create response using Pydantic model
        return {
            "instance_id": alarm_event.instance_id,
            "alarm_name": alarm_event.alarm_name,
            "failure_type": alarm_event.metric_config.name,
            "alarm_state": alarm_event.current_state.value,
            "metric_config": alarm_event.metric_config.model_dump(),
            "failure_reason": alarm_event.current_state.reason,
            "bedrock_analysis": analysis.model_dump()
        } 