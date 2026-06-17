# ruff: noqa
import os
import google.auth
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.workflow import Workflow, START
from google.genai import types

# Authentication Setup
if not os.environ.get("GEMINI_API_KEY"):
    try:
        _, project_id = google.auth.default()
        os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
        os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
    except Exception:
        pass
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# Use the latest Gemini model
MODEL_NAME = "gemini-2.5-flash"

# Define structured output schemas
class Classification(BaseModel):
    is_shipping_related: bool = Field(
        description="True if the user query is about shipping rates, tracking, delivery, returns, or shipping FAQs. False if the query is unrelated to shipping."
    )

class ShippingResponse(BaseModel):
    response: str = Field(description="The response/answer to the user's shipping question.")

# 1. Node to extract and save original query in state
def save_query_and_classify(ctx: Context, node_input: types.Content) -> Event:
    user_query = ""
    if hasattr(node_input, "parts") and node_input.parts:
        user_query = node_input.parts[0].text or ""
    elif isinstance(node_input, str):
        user_query = node_input
    return Event(output=user_query, state={"user_query": user_query})

# 2. Classifier Agent (LlmAgent)
classifier_agent = LlmAgent(
    name="classifier_agent",
    model=MODEL_NAME,
    instruction=(
        "You are an AI classifier. Analyze the user's input query and classify whether it is related to "
        "shipping services (such as rates, tracking, delivery times, pickup, returns, shipping guidelines) "
        "or is completely unrelated to shipping."
    ),
    output_schema=Classification,
)

# 3. Routing Node
def route_classification(ctx: Context, node_input: dict) -> Event:
    is_shipping = node_input.get("is_shipping_related", False)
    user_query = ctx.state.get("user_query", "")
    route = "shipping" if is_shipping else "unrelated"
    return Event(output=user_query, route=route)

# 4. Shipping FAQ Agent (LlmAgent)
shipping_faq_agent = LlmAgent(
    name="shipping_faq_agent",
    model=MODEL_NAME,
    instruction=(
        "You are a helpful customer support representative for a shipping company. "
        "Answer the user's inquiry about shipping, rates, tracking, delivery, or returns "
        "politely and accurately. If they don't provide details (like a tracking number), "
        "you can ask them for it."
    ),
    output_schema=ShippingResponse,
)

# 5. Decline Node (FunctionNode)
def decline_node(ctx: Context, node_input: str):
    decline_message = (
        "I'm sorry, but I can only assist with shipping-related inquiries "
        "such as rates, tracking, delivery, or returns. Please let me know if you have "
        "any questions about our shipping services!"
    )
    # Yield content event so it displays correctly in UI/console
    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=decline_message)]
        )
    )
    yield Event(output=decline_message)

# Define the workflow graph
root_agent = Workflow(
    name="customer_support_workflow",
    description="Customer support router and responder for shipping inquiries.",
    edges=[
        ("START", save_query_and_classify),
        (save_query_and_classify, classifier_agent),
        (classifier_agent, route_classification),
        (route_classification, {"shipping": shipping_faq_agent, "unrelated": decline_node}),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
