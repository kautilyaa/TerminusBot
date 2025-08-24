import os
from typing import Dict, Any

class Config:
    """Configuration for AWS MCP Server"""

    # Server configuration
    SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
    SERVER_PORT = int(os.getenv("SERVER_PORT", "8080"))

    # AWS configuration
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

    # Logging configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "mcp-server.log")

    # SSE configuration
    SSE_UPDATE_INTERVAL = int(os.getenv("SSE_UPDATE_INTERVAL", "30"))

    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        """Get configuration as dictionary"""
        return {
            "server_host": cls.SERVER_HOST,
            "server_port": cls.SERVER_PORT,
            "aws_region": cls.AWS_REGION,
            "log_level": cls.LOG_LEVEL,
            "log_file": cls.LOG_FILE,
            "sse_update_interval": cls.SSE_UPDATE_INTERVAL
        }
