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
import yaml
import pytest
from unittest.mock import AsyncMock, MagicMock
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent, DISCOUNT_CODES, redeem_discount_code

def reset_discount_codes():
    for code in DISCOUNT_CODES:
        DISCOUNT_CODES[code]["redeemed"] = False
        DISCOUNT_CODES[code]["user_id"] = None


@pytest.fixture
def mock_api_client():
    """Fixture to mock the model's api client and restore it after the test."""
    original_api_client = getattr(root_agent.model, "api_client", None)
    api_client = MagicMock()
    root_agent.model.api_client = api_client
    yield api_client
    if original_api_client is not None:
        root_agent.model.api_client = original_api_client


@pytest.mark.asyncio
async def test_valid_redemption_flow(mock_api_client):
    """
    Test that when a valid discount code and user ID are provided, the agent
    correctly calls the redeem_discount_code tool and completes the flow.
    """
    reset_discount_codes()

    # Step 1: Mock tool call generation
    tool_call_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="redeem_discount_code",
                                args={"discount_code": "WELCOME50", "user_id": "user123"}
                            )
                        )
                    ]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    # Step 2: Mock final response after tool execution
    final_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Successfully redeemed WELCOME50 for user123!")]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    responses_queue = [tool_call_response, final_response]

    async def mock_stream(*args, **kwargs):
        if responses_queue:
            yield responses_queue.pop(0)
        else:
            yield types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        finish_reason=types.FinishReason.STOP,
                        content=types.Content(role="model", parts=[types.Part.from_text(text="Done.")])
                    )
                ]
            )

    mock_api_client.aio.models.generate_content_stream = AsyncMock(side_effect=mock_stream)

    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="Redeem code WELCOME50 for user123")]
    )

    events = []
    async for event in runner.run_async(
        new_message=message,
        user_id="test_user",
        session_id=session.id,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        events.append(event)

    # Assert discount code state updated correctly
    assert DISCOUNT_CODES["WELCOME50"]["redeemed"] is True
    assert DISCOUNT_CODES["WELCOME50"]["user_id"] == "user123"

    # Assert response contains final text
    text_content = "".join(
        part.text for event in events if event.content and event.content.parts
        for part in event.content.parts if part.text
    )
    assert "Successfully redeemed WELCOME50 for user123!" in text_content


@pytest.mark.asyncio
async def test_user_id_requirement_guardrail(mock_api_client):
    """
    Verify that if the user attempts to redeem a discount code without a user ID,
    the agent prompts them for the user ID first and does not execute the tool.
    """
    reset_discount_codes()

    # The agent should request a user ID rather than calling the tool immediately
    prompt_for_id_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Please provide your registered user ID to redeem this code.")]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    async def mock_stream(*args, **kwargs):
        yield prompt_for_id_response

    mock_api_client.aio.models.generate_content_stream = AsyncMock(side_effect=mock_stream)

    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="I want to redeem coupon WELCOME50")]
    )

    events = []
    async for event in runner.run_async(
        new_message=message,
        user_id="test_user",
        session_id=session.id,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        events.append(event)

    # Verify no tool calls were made (WELCOME50 remains unredeemed)
    assert DISCOUNT_CODES["WELCOME50"]["redeemed"] is False
    assert DISCOUNT_CODES["WELCOME50"]["user_id"] is None

    # Verify the response prompts for the user ID
    text_content = "".join(
        part.text for event in events if event.content and event.content.parts
        for part in event.content.parts if part.text
    )
    assert "registered user ID" in text_content


@pytest.mark.asyncio
async def test_single_use_constraint(mock_api_client):
    """
    Verify that if a code is already redeemed, trying to redeem it again
    results in a failure (handled gracefully by the agent).
    """
    reset_discount_codes()

    # Pre-redeem WELCOME50
    DISCOUNT_CODES["WELCOME50"]["redeemed"] = True
    DISCOUNT_CODES["WELCOME50"]["user_id"] = "user123"

    # Step 1: Model decides to call the tool anyway (e.g. to check state)
    tool_call_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="redeem_discount_code",
                                args={"discount_code": "WELCOME50", "user_id": "user456"}
                            )
                        )
                    ]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    # Step 2: Model handles the tool's error response
    final_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Sorry, this discount code has already been redeemed by user123.")]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    responses_queue = [tool_call_response, final_response]

    async def mock_stream(*args, **kwargs):
        if responses_queue:
            yield responses_queue.pop(0)
        else:
            yield types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        finish_reason=types.FinishReason.STOP,
                        content=types.Content(role="model", parts=[types.Part.from_text(text="Done.")])
                    )
                ]
            )

    mock_api_client.aio.models.generate_content_stream = AsyncMock(side_effect=mock_stream)

    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="Redeem code WELCOME50 for user456")]
    )

    events = []
    async for event in runner.run_async(
        new_message=message,
        user_id="test_user",
        session_id=session.id,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        events.append(event)

    # Verify state remains owned by original redeemer (user123) and not user456
    assert DISCOUNT_CODES["WELCOME50"]["redeemed"] is True
    assert DISCOUNT_CODES["WELCOME50"]["user_id"] == "user123"

    # Verify message contains error feedback
    text_content = "".join(
        part.text for event in events if event.content and event.content.parts
        for part in event.content.parts if part.text
    )
    assert "already been redeemed" in text_content


@pytest.mark.asyncio
async def test_invalid_discount_code(mock_api_client):
    """
    Verify that the system gracefully handles invalid discount codes.
    """
    reset_discount_codes()

    # Step 1: Model calls tool with invalid code
    tool_call_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            function_call=types.FunctionCall(
                                name="redeem_discount_code",
                                args={"discount_code": "INVALID100", "user_id": "user123"}
                            )
                        )
                    ]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    # Step 2: Model handles invalid code error response
    final_response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.STOP,
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text="Sorry, INVALID100 is not a valid discount code.")]
                )
            )
        ],
        model_version="gemini-3.1-flash-lite"
    )

    responses_queue = [tool_call_response, final_response]

    async def mock_stream(*args, **kwargs):
        if responses_queue:
            yield responses_queue.pop(0)
        else:
            yield types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        finish_reason=types.FinishReason.STOP,
                        content=types.Content(role="model", parts=[types.Part.from_text(text="Done.")])
                    )
                ]
            )

    mock_api_client.aio.models.generate_content_stream = AsyncMock(side_effect=mock_stream)

    session_service = InMemorySessionService()
    session = await session_service.create_session(user_id="test_user", app_name="test")
    runner = Runner(agent=root_agent, session_service=session_service, app_name="test")

    message = types.Content(
        role="user", parts=[types.Part.from_text(text="Redeem code INVALID100 for user123")]
    )

    events = []
    async for event in runner.run_async(
        new_message=message,
        user_id="test_user",
        session_id=session.id,
        run_config=RunConfig(streaming_mode=StreamingMode.SSE),
    ):
        events.append(event)

    # Verify no state was added for INVALID100
    assert "INVALID100" not in DISCOUNT_CODES

    # Verify response contains explanation
    text_content = "".join(
        part.text for event in events if event.content and event.content.parts
        for part in event.content.parts if part.text
    )
    assert "not a valid discount code" in text_content


def test_competitors_guardrail():
    """
    Ensure the competitor guardrail instruction is present in the agent instructions.
    """
    instructions = root_agent.instruction.lower()
    assert "competitor" in instructions or "discuss competitors" in instructions


def test_language_and_tone_guardrails():
    """
    Ensure the agent is instructed to maintain polite tone and avoid offensive language.
    """
    instructions = root_agent.instruction.lower()
    assert "offensive language" in instructions
    assert "polite" in instructions or "tone" in instructions or "professional" in instructions


def test_agents_cli_manifest():
    """
    Ensure that the agents-cli-manifest.yaml file exists and is valid yaml.
    """
    manifest_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "agents-cli-manifest.yaml"
    )
    assert os.path.exists(manifest_path)
    with open(manifest_path, "r") as f:
        manifest = yaml.safe_load(f)
    assert manifest.get("name") == "shopping-assistant"
    assert manifest.get("agent_directory") == "app"
