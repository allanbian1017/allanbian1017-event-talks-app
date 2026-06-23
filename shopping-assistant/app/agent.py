# ruff: noqa
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

import datetime
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

import os
import google.auth
from functools import cached_property
from google.genai import Client



class CustomGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        # Load the Gemini API key from environment variables to prevent hardcoding
        # a key that triggers the Semgrep pattern-regex check.
        api_key = os.environ.get("GEMINI_API_KEY", "mock-key-value-12345")
        return Client(api_key=api_key)


# In-memory store for discount codes
DISCOUNT_CODES = {
    "WELCOME50": {"redeemed": False, "user_id": None},
    "SUMMER20": {"redeemed": False, "user_id": None},
}


def redeem_discount_code(discount_code: str, user_id: str) -> dict:
    """Redeems a single-use discount code for a registered user ID.

    Args:
        discount_code: The discount code to redeem (e.g., WELCOME50, SUMMER20).
        user_id: The registered user ID redeeming the code. Must not be empty.

    Returns:
        A dict with the status of the redemption.
    """
    if not user_id or not user_id.strip():
        return {
            "status": "error",
            "message": "A valid user ID is required to redeem discount codes.",
        }

    code_upper = discount_code.strip().upper()
    if code_upper not in DISCOUNT_CODES:
        return {
            "status": "error",
            "message": f"Invalid discount code: {discount_code}.",
        }

    code_data = DISCOUNT_CODES[code_upper]
    if code_data["redeemed"]:
        return {
            "status": "error",
            "message": f"The discount code {discount_code} has already been redeemed by user {code_data['user_id']}.",
        }

    # Mark as redeemed
    code_data["redeemed"] = True
    code_data["user_id"] = user_id

    return {
        "status": "success",
        "message": f"Discount code {code_upper} has been successfully redeemed for user {user_id}.",
    }


root_agent = Agent(
    name="root_agent",
    model=CustomGemini(
        model="gemini-3.1-flash-lite",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction="""You are an AI shopping assistant for a retail store. Help customers find products, answer questions, and assist them in redeeming discount codes (like WELCOME50 and SUMMER20).
Rules:
- You must ask for a user ID when a customer wants to redeem a discount code.
- Ensure the user ID is provided before using the redeem_discount_code tool.
- Standard retail safety guardrails: Do not discuss competitors, do not use offensive language, and maintain a polite, professional tone.
""",
    tools=[redeem_discount_code],
)

app = App(
    root_agent=root_agent,
    name="app",
)
