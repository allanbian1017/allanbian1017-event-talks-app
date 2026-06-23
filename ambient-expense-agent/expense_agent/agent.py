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

import base64
import json
import os
import re

import google.auth
from dotenv import load_dotenv
from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.models import Gemini
from google.adk.workflow import START, Workflow, node
from google.genai import types
from pydantic import BaseModel, Field

from expense_agent import config

# ---------------------------------------------------------------------
# AUTHENTICATION & ENVIRONMENT SETUP
# ---------------------------------------------------------------------

# Load local environment variables from .env
load_dotenv()

# Determine authentication mode based on the environment variables
api_key = os.environ.get("GEMINI_API_KEY")

if api_key:
    # Use Google AI Studio (Gemini Developer API) backend
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
else:
    # Attempt to use Vertex AI / Google Cloud backend
    try:
        _, project_id = google.auth.default()
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    except Exception:
        # Fallback placeholders if credentials are not found yet
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "YOUR_PROJECT_ID")
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

# ---------------------------------------------------------------------
# DATA SCHEMAS
# ---------------------------------------------------------------------


class ExpenseDetails(BaseModel):
    amount: float = Field(description="The expense amount in dollars")
    submitter: str = Field(description="Name/ID of the submitter")
    category: str = Field(description="Category of the expense (e.g. Travel, Meals)")
    description: str = Field(description="Detailed description of the expense")
    date: str = Field(description="Date of the expense transaction")


class RiskAssessment(BaseModel):
    risk_notes: str = Field(
        description="Identified risk factors, anomalies, or policy violations"
    )
    risk_level: str = Field(description="Assessed risk level: Low, Medium, High")
    alert_raised: bool = Field(
        description="True if an alert should be raised for the reviewer"
    )


class ExpenseStatus(BaseModel):
    expense: ExpenseDetails = Field(description="The parsed expense details")
    approved: bool = Field(description="Whether the expense is approved")
    risk_assessed: bool = Field(description="Whether LLM risk assessment was performed")
    risk_notes: str = Field(description="Notes from the risk assessment")
    reason: str = Field(description="Reason for final decision")


# ---------------------------------------------------------------------
# WORKFLOW NODES
# ---------------------------------------------------------------------


# Node 1: Event Parsing & Routing Node
@node
def parse_event(ctx: Context, node_input: types.Content) -> Event:
    """Parses Pub/Sub (base64 encoded) or plain JSON event inputs and routes by amount."""
    text = ""
    if node_input and node_input.parts:
        text = node_input.parts[0].text or ""

    try:
        payload = json.loads(text)
    except Exception as e:
        raise ValueError(
            f"Input must be a valid JSON string representing the event. Error: {e}"
        ) from e

    # Extract raw data from Pub/Sub envelope or directly
    if isinstance(payload, dict) and "message" in payload:
        raw_data = payload["message"].get("data")
    elif isinstance(payload, dict):
        raw_data = payload.get("data")
    else:
        raw_data = payload

    if not raw_data:
        raw_data = payload

    expense_dict = None
    if isinstance(raw_data, str):
        # Try decoding base64 (Pub/Sub pattern)
        try:
            decoded_bytes = base64.b64decode(raw_data)
            decoded_str = decoded_bytes.decode("utf-8")
            expense_dict = json.loads(decoded_str)
        except Exception:
            # Fall back to parsing the raw string as JSON
            try:
                expense_dict = json.loads(raw_data)
            except Exception as e:
                raise ValueError(f"Failed to parse data field as JSON: {e}") from e
    elif isinstance(raw_data, dict):
        expense_dict = raw_data
    else:
        raise ValueError("Unsupported data field format")

    # Extract expense details
    expense = ExpenseDetails(
        amount=float(expense_dict.get("amount", 0.0)),
        submitter=str(expense_dict.get("submitter", "Unknown")),
        category=str(expense_dict.get("category", "Uncategorized")),
        description=str(expense_dict.get("description", "")),
        date=str(expense_dict.get("date", "")),
    )

    # Save original details to state for later nodes
    ctx.state["expense"] = expense.model_dump()

    # Route based on threshold rule
    if expense.amount < config.THRESHOLD:
        status = ExpenseStatus(
            expense=expense,
            approved=True,
            risk_assessed=False,
            risk_notes="Auto-approved (amount below threshold)",
            reason="Amount is under the manual review threshold.",
        )
        return Event(output=status, route="auto_approve")  # type: ignore
    else:
        return Event(output=expense, route="needs_review")  # type: ignore


# SSN matches: XXX-XX-XXXX, XXX XX XXXX, or XXXXXXXXX
SSN_PATTERN = re.compile(r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b')

# Credit Card matches: 13-19 digits, possibly separated by hyphens/spaces
CC_PATTERN = re.compile(
    r'\b(?:\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}|\d{4}[-\s]\d{6}[-\s]\d{5}|\d{13,19})\b'
)


def scrub_pii(text: str) -> tuple[str, list[str]]:
    redacted = []
    if SSN_PATTERN.search(text):
        text = SSN_PATTERN.sub("[SSN REDACTED]", text)
        redacted.append("SSN")
    if CC_PATTERN.search(text):
        text = CC_PATTERN.sub("[CREDIT CARD REDACTED]", text)
        redacted.append("Credit Card")
    return text, redacted


def detect_prompt_injection(description: str) -> bool:
    desc_lower = description.lower()
    injection_phrases = [
        "ignore previous instructions",
        "ignore the above",
        "ignore all previous",
        "ignore all instructions",
        "system prompt",
        "you must now",
        "new instruction",
        "auto-approve",
        "auto approve",
        "force approval",
        "bypass review",
        "bypass threshold",
        "bypass the rules",
        "admin override",
        "override threshold",
        "approve this",
        "automatically approve",
        "set approved to true",
        "set approved=true",
        "do not review",
        "skip review",
    ]
    return any(phrase in desc_lower for phrase in injection_phrases)


@node
def security_checkpoint(ctx: Context, node_input: ExpenseDetails) -> Event:
    """Scrubs PII and defends against prompt injection before the LLM reviewer."""
    description = node_input.description

    # 1. Scrub PII
    scrubbed_desc, redacted_categories = scrub_pii(description)
    ctx.state["redacted_categories"] = redacted_categories

    # Update state and node input with clean description
    ctx.state["expense"]["description"] = scrubbed_desc
    node_input.description = scrubbed_desc

    # 2. Defend against prompt injection (checking the original description)
    if detect_prompt_injection(description):
        # Flagged as security event: bypass LLM reviewer and go straight to human approval
        risk_assessment = RiskAssessment(
            risk_notes="SECURITY ALERT: Prompt injection attempt detected in description.",
            risk_level="High",
            alert_raised=True,
        )
        return Event(output=risk_assessment, route="flagged")

    # Clean: continue to LLM reviewer
    return Event(output=node_input, route="clean")


# Node 2: LLM Risk Assessment Node (LlmAgent)
llm_reviewer = LlmAgent(
    name="llm_reviewer",
    model=Gemini(model=config.MODEL_NAME),
    instruction="Review the following expense details for risk factors (e.g. suspicious activity, policy violations, anomalies). Provide risk notes and whether an alert should be raised.",
    output_schema=RiskAssessment,
)


# Node 3: Human-in-the-Loop Decision Node (FunctionNode)
@node(rerun_on_resume=True)
async def request_human_approval(ctx: Context, node_input: RiskAssessment):
    """Pauses graph for human decision if LLM risk review is needed."""
    expense = ExpenseDetails(**ctx.state["expense"])

    if not ctx.resume_inputs or "decision" not in ctx.resume_inputs:
        msg = (
            f"🚨 RISK REVIEW REQUIRED 🚨\n"
            f"Submitter: {expense.submitter}\n"
            f"Amount: ${expense.amount:.2f}\n"
            f"Category: {expense.category}\n"
            f"Description: {expense.description}\n"
            f"Date: {expense.date}\n\n"
            f"LLM Risk Assessment:\n"
            f"- Risk Level: {node_input.risk_level}\n"
            f"- Risk Notes: {node_input.risk_notes}\n"
            f"- Alert Raised: {node_input.alert_raised}\n\n"
            f"Please reply 'approve' or 'reject' to finalize this expense."
        )
        yield RequestInput(interrupt_id="decision", message=msg)
        return

    decision_val = ctx.resume_inputs["decision"]
    if isinstance(decision_val, dict):
        user_response = decision_val.get("result", "").strip().lower()
    else:
        user_response = str(decision_val).strip().lower()

    approved = user_response in ["yes", "y", "approve", "approved"]
    reason = (
        "Approved by human reviewer." if approved else "Rejected by human reviewer."
    )

    status = ExpenseStatus(
        expense=expense,
        approved=approved,
        risk_assessed=True,
        risk_notes=node_input.risk_notes,
        reason=reason,
    )
    yield Event(output=status)


# Node 4: Finalize Decision Node (FunctionNode)
@node
def finalize_expense(ctx: Context, node_input: ExpenseStatus):
    """Emits the final validation state and details."""
    outcome = "APPROVED" if node_input.approved else "REJECTED"
    msg = f"Final outcome for expense by {node_input.expense.submitter} for ${node_input.expense.amount:.2f}: {outcome}. Reason: {node_input.reason}"
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(output=node_input)


# ---------------------------------------------------------------------
# WORKFLOW ORCHESTRATION
# ---------------------------------------------------------------------

root_agent = Workflow(
    name="ambient_expense_workflow",
    edges=[
        (START, parse_event),
        (
            parse_event,
            {
                "auto_approve": finalize_expense,
                "needs_review": security_checkpoint,
            },
        ),
        (
            security_checkpoint,
            {
                "clean": llm_reviewer,
                "flagged": request_human_approval,
            },
        ),
        (llm_reviewer, request_human_approval),
        (request_human_approval, finalize_expense),
    ],
    rerun_on_resume=False,
    output_schema=ExpenseStatus,
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
