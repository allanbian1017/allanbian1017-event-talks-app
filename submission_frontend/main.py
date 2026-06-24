import os
import re
import logging
import asyncio
import base64
import json
from typing import Any, Dict, List, Optional
import google.auth
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import vertexai
from google.adk.sessions import VertexAiSessionService
from google.adk.events.event import Event

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("manager-dashboard")

# Environment configurations
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
AGENT_RUNTIME_ID = os.getenv("AGENT_RUNTIME_ID")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

def parse_runtime_id(runtime_id: str) -> tuple[str, Optional[str], Optional[str]]:
    if not runtime_id:
        return "", None, None
    match = re.search(r"projects/([^/]+)/locations/([^/]+)/reasoningEngines/(\d+)", runtime_id)
    if match:
        return match.group(3), match.group(1), match.group(2)
    if "/" in runtime_id:
        return runtime_id.split("/")[-1], None, None
    return runtime_id, None, None

SHORT_ENGINE_ID, parsed_project, parsed_location = parse_runtime_id(AGENT_RUNTIME_ID)
if parsed_location:
    LOCATION = parsed_location

# If PROJECT_ID is not set in environment, try to auto-detect using google.auth
if not PROJECT_ID:
    try:
        _, project = google.auth.default()
        if project:
            PROJECT_ID = project
            logger.info(f"Auto-detected Google Cloud Project: {PROJECT_ID}")
    except Exception as e:
        logger.warning(f"Could not auto-detect project ID: {e}")

# Initialize Vertex AI
if PROJECT_ID:
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    logger.info(f"Vertex AI initialized with project={PROJECT_ID}, location={LOCATION}")
else:
    logger.error("GOOGLE_CLOUD_PROJECT is not set and could not be auto-detected.")

# Instantiate the VertexAiSessionService
session_service = None
if PROJECT_ID and SHORT_ENGINE_ID:
    session_service = VertexAiSessionService(
        project=PROJECT_ID,
        location=LOCATION,
        agent_engine_id=SHORT_ENGINE_ID
    )
    logger.info(f"VertexAiSessionService initialized for engine={SHORT_ENGINE_ID} (location={LOCATION})")
else:
    logger.error("Session service not initialized: GOOGLE_CLOUD_PROJECT or AGENT_RUNTIME_ID missing.")

app = FastAPI(title="Manager Dashboard Service")

# CORS middleware to allow cross-origin requests (e.g. from developer servers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_headers=["*"],
    allow_methods=["*"],
)

class ActionRequest(BaseModel):
    approved: bool
    interrupt_id: str
    user_id: Optional[str] = None

def parse_expense_from_message(message: str) -> dict:
    """Parses expense details and risk notes from human warning message text."""
    details = {}
    
    # Extract standard expense fields
    submitter_match = re.search(r"Submitter:\s*(.*)", message)
    amount_match = re.search(r"Amount:\s*\$?([\d,.]+)", message)
    category_match = re.search(r"Category:\s*(.*)", message)
    desc_match = re.search(r"Description:\s*(.*)", message)
    date_match = re.search(r"Date:\s*(.*)", message)
    
    # Extract risk assessment fields
    risk_level_match = re.search(r"Risk Level:\s*(.*)", message)
    risk_notes_match = re.search(r"Risk Notes:\s*(.*)", message)
    alert_raised_match = re.search(r"Alert Raised:\s*(.*)", message)
    
    if submitter_match:
        details["submitter"] = submitter_match.group(1).strip()
    if amount_match:
        try:
            details["amount"] = float(amount_match.group(1).replace(",", "").strip())
        except ValueError:
            pass
    if category_match:
        details["category"] = category_match.group(1).strip()
    if desc_match:
        details["description"] = desc_match.group(1).strip()
    if date_match:
        details["date"] = date_match.group(1).strip()
        
    if risk_level_match:
        details["risk_level"] = risk_level_match.group(1).strip()
    if risk_notes_match:
        details["risk_notes"] = risk_notes_match.group(1).strip()
    if alert_raised_match:
        details["alert_raised"] = alert_raised_match.group(1).strip()
        
    return details

def extract_expense_details(call_args: dict, session_state: dict, events: List[Event]) -> dict:
    """Combines information from state, events, and message parsing to construct full details."""
    details = {
        "submitter": "Unknown",
        "amount": 0.0,
        "category": "Expense",
        "description": "",
        "date": "",
        "risk_level": "Low",
        "risk_notes": "No suspicious factors flagged.",
        "alert_raised": "False"
    }
    
    # 1. Populate from session state if available
    if session_state and "expense" in session_state:
        exp = session_state["expense"]
        if isinstance(exp, dict):
            for k in ["submitter", "amount", "category", "description", "date"]:
                if k in exp:
                    details[k] = exp[k]
                    
    # 2. Look for RiskAssessment output in event history
    for ev in events:
        if ev.output:
            output = ev.output
            if hasattr(output, "risk_level") or (isinstance(output, dict) and "risk_level" in output):
                if isinstance(output, dict):
                    details["risk_level"] = output.get("risk_level", details["risk_level"])
                    details["risk_notes"] = output.get("risk_notes", details["risk_notes"])
                    details["alert_raised"] = str(output.get("alert_raised", details["alert_raised"]))
                else:
                    details["risk_level"] = getattr(output, "risk_level", details["risk_level"])
                    details["risk_notes"] = getattr(output, "risk_notes", details["risk_notes"])
                    details["alert_raised"] = str(getattr(output, "alert_raised", details["alert_raised"]))
                    
    # 3. Overlay values parsed from the message string (highest source of truth for the human review block)
    message = call_args.get("message")
    if message and isinstance(message, str):
        parsed = parse_expense_from_message(message)
        for k, v in parsed.items():
            if v: # Only override if we parsed a non-empty value
                details[k] = v
                
    return details

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serves the manager dashboard HTML page."""
    index_path = os.path.join(os.path.dirname(__file__), "index.html")
    if not os.path.exists(index_path):
        index_path = "index.html"
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading index.html: {e}")

@app.get("/api/pending")
async def get_pending_approvals():
    """Lists sessions and returns all pending human-in-the-loop approvals."""
    if not session_service:
        raise HTTPException(
            status_code=500,
            detail="Session service not initialized. Verify GCP project and AGENT_RUNTIME_ID environment variables."
        )

    try:
        # List all sessions under the deployed reasoning engine
        list_response = await session_service.list_sessions(app_name=SHORT_ENGINE_ID)
        sessions = list_response.sessions
        
        pending_items = []
        
        # Fetch detailed history for each session to find pending interruptions
        for session in sessions:
            full_session = await session_service.get_session(
                app_name=SHORT_ENGINE_ID,
                user_id=session.user_id,
                session_id=session.id
            )
            
            if not full_session or not full_session.events:
                continue

            calls = {}
            responses = set()

            for event in full_session.events:
                # Find adk_request_input calls
                for call in event.get_function_calls():
                    if call.name == "adk_request_input":
                        calls[call.id] = call.args
                        
                # Find corresponding responses
                for resp in event.get_function_responses():
                    if resp.name == "adk_request_input":
                        responses.add(resp.id)

            # Identify calls that have no matching response
            for interrupt_id, args in calls.items():
                if interrupt_id not in responses:
                    expense_details = extract_expense_details(args, full_session.state, full_session.events)
                    
                    pending_items.append({
                        "session_id": session.id,
                        "interrupt_id": interrupt_id,
                        "expense": expense_details
                    })

        return pending_items

    except Exception as e:
        logger.error(f"Error querying pending approvals: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/action/{session_id}")
async def resume_session(session_id: str, request: ActionRequest):
    """Resumes the paused session on Agent Runtime with the approved state."""
    if not PROJECT_ID or not AGENT_RUNTIME_ID:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLOUD_PROJECT and AGENT_RUNTIME_ID environment variables must be set."
        )

    try:
        from vertexai.agent_engines import AgentEngine
        
        # Resolve engine resource name
        if "projects/" in AGENT_RUNTIME_ID:
            resource_name = AGENT_RUNTIME_ID
        else:
            resource_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{AGENT_RUNTIME_ID}"
            
        agent_engine = AgentEngine(resource_name=resource_name)
        
        # Determine string representation of decision for agent workflow compatibility ("yes"/"no")
        decision_str = "yes" if request.approved else "no"
        
        # Build the exact resume payload. Set response keys to satisfy both:
        # 1. The user request requirement: {approved: True/False}
        # 2. The agent's implementation: {"result": "yes"/"no"}
        resume_payload = {
            "role": "user",
            "parts": [
                {
                    "function_response": {
                        "id": request.interrupt_id,
                        "name": "adk_request_input",
                        "response": {
                            "approved": request.approved,
                            "result": decision_str
                        }
                    }
                }
            ]
        }
        
        # Determine the user ID to use. Default to request.user_id or "default-user".
        # If user_id is "default-user", lookup the session owner dynamically from GCP to avoid mismatch.
        user_id = request.user_id or "default-user"
        if user_id == "default-user" and session_service:
            try:
                list_response = await session_service.list_sessions(app_name=SHORT_ENGINE_ID)
                for s in list_response.sessions:
                    if s.id == session_id:
                        user_id = s.user_id
                        logger.info(f"Resolved owner user_id '{user_id}' dynamically for session {session_id}")
                        break
            except Exception as e:
                logger.warning(f"Dynamic owner lookup failed for session {session_id}: {e}")

        # Run stream_query in threadpool to prevent blocking FastAPI's event loop
        def run_sdk_stream():
            logger.info(f"Resuming session {session_id} on reasoning engine {resource_name} for user {user_id}")
            return list(agent_engine.stream_query(
                message=resume_payload,
                user_id=user_id,
                session_id=session_id
            ))
            
        events = await run_in_threadpool(run_sdk_stream)
        
        # Parse final compliance/validation result message
        compliance_review = ""
        for chunk in events:
            if isinstance(chunk, dict):
                content = chunk.get("content")
                if content and isinstance(content, dict):
                    parts = content.get("parts")
                    if parts:
                        for part in parts:
                            if isinstance(part, dict) and "text" in part:
                                compliance_review += part["text"]

        if not compliance_review:
            compliance_review = f"Expense successfully {'approved' if request.approved else 'rejected'}. Session resumed."

        return {"status": "success", "compliance_review": compliance_review}

    except Exception as e:
        logger.error(f"Error resuming session: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trigger")
async def trigger_pipeline(request_data: Dict[str, Any]):
    """Receives incoming Pub/Sub messages, normalizes them, and triggers the Reasoning Engine."""
    logger.info(f"Received trigger request: {request_data}")
    
    # 1. Parse payload. Handle both Pub/Sub wrapped envelope and direct raw payload
    expense_data = None
    if "message" in request_data and isinstance(request_data["message"], dict):
        raw_data = request_data["message"].get("data")
        if raw_data:
            try:
                decoded = base64.b64decode(raw_data).decode("utf-8")
                expense_data = json.loads(decoded)
            except Exception as e:
                logger.error(f"Failed to decode base64 data: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid base64 payload: {e}")
    else:
        # Direct raw payload (e.g. --push-no-wrapper or manual trigger)
        expense_data = request_data

    if not expense_data:
        raise HTTPException(status_code=400, detail="No expense data found in payload.")

    # 2. Trigger the Reasoning Engine
    if not PROJECT_ID or not AGENT_RUNTIME_ID:
        raise HTTPException(
            status_code=500,
            detail="GOOGLE_CLOUD_PROJECT and AGENT_RUNTIME_ID environment variables must be set."
        )

    try:
        from vertexai.agent_engines import AgentEngine
        
        # Resolve engine resource name
        if "projects/" in AGENT_RUNTIME_ID:
            resource_name = AGENT_RUNTIME_ID
        else:
            resource_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{AGENT_RUNTIME_ID}"
            
        agent_engine = AgentEngine(resource_name=resource_name)
        
        # Serialize the expense data to a JSON string
        message_payload = json.dumps(expense_data)
        
        # Use user_id="vais-query-reasoning-engine" to match pipeline owner
        user_id = "vais-query-reasoning-engine"
        
        logger.info(f"Triggering reasoning engine {resource_name} for user {user_id}")
        
        def run_trigger_stream():
            return list(agent_engine.stream_query(
                message=message_payload,
                user_id=user_id
            ))
            
        events = await run_in_threadpool(run_trigger_stream)
        logger.info(f"Successfully triggered session. Stream yielded {len(events)} events.")
        
        return {"status": "success", "events_count": len(events)}

    except Exception as e:
        logger.error(f"Error triggering reasoning engine: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Respect Cloud Run's PORT env variable, defaulting to 8081 for local use
    port = int(os.getenv("PORT", 8081))
    uvicorn.run(app, host="0.0.0.0", port=port)
