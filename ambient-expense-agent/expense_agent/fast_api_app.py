# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import json
import logging

import google.auth
from fastapi import FastAPI, Request
from google.adk.cli.fast_api import get_fast_api_app

from expense_agent.app_utils.telemetry import setup_telemetry
from expense_agent.app_utils.typing import Feedback

setup_telemetry()

# Configure standard Python logging using uvicorn's logger for visibility
logger = logging.getLogger("uvicorn.error")

_, project_id = google.auth.default()
allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# In-memory session configuration - no persistent storage
session_service_uri = None

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=False,
    trigger_sources=["pubsub"],
)
app.title = "ambient-expense-agent"
app.description = "API for interacting with the Agent ambient-expense-agent"


@app.middleware("http")
async def normalize_pubsub_subscription(request: Request, call_next):
    if request.url.path.endswith("/trigger/pubsub") and request.method == "POST":
        try:
            body = await request.body()
            if body:
                data = json.loads(body)
                if "subscription" in data and isinstance(data["subscription"], str):
                    sub_path = data["subscription"]
                    if "/" in sub_path:
                        short_name = sub_path.split("/")[-1]
                        data["subscription"] = short_name
                        print(f"Normalized subscription path: '{sub_path}' -> '{short_name}'", flush=True)
                        logger.info(f"Normalized subscription path: '{sub_path}' -> '{short_name}'")
                
                async def receive():
                    return {"type": "http.request", "body": json.dumps(data).encode("utf-8"), "more_body": False}
                request._receive = receive
        except Exception as e:
            print(f"Failed to normalize Pub/Sub subscription path: {e}", flush=True)
            logger.error(f"Failed to normalize Pub/Sub subscription path: {e}")
    return await call_next(request)


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.info(f"Feedback received: {feedback.model_dump()}")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
