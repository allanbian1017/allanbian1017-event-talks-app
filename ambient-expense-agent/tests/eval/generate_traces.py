import json
import os
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from expense_agent.agent import root_agent, detect_prompt_injection

def clean_part(part):
    res = {}
    if part.text is not None:
        res["text"] = part.text
    elif part.function_call is not None:
        res["function_call"] = {
            "name": part.function_call.name,
            "args": part.function_call.args
        }
        if part.function_call.id:
            res["function_call"]["id"] = part.function_call.id
    elif part.function_response is not None:
        res["function_response"] = {
            "name": part.function_response.name,
            "response": part.function_response.response
        }
        if part.function_response.id:
            res["function_response"]["id"] = part.function_response.id
    return res

def serialize_event(event, author=None):
    parts = []
    for part in event.content.parts:
        parts.append(clean_part(part))
    return {
        "author": author or event.author or "expense_agent",
        "content": {
            "role": event.content.role or "model",
            "parts": parts
        }
    }

def main():
    import time
    dataset_path = "tests/eval/datasets/basic-dataset.json"
    output_path = "artifacts/traces/generated_traces.json"
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(dataset_path, "r") as f:
        dataset = json.load(f)
        
    generated_cases = []
    
    for case_idx, case in enumerate(dataset["eval_cases"]):
        case_id = case["eval_case_id"]
        prompt_text = case["prompt"]["parts"][0]["text"]
        payload = json.loads(prompt_text)
        
        print(f"Running evaluation case: {case_id}...")
        
        session_service = InMemorySessionService()
        session = session_service.create_session_sync(user_id="eval_user", app_name="expense_agent")
        runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")
        
        message = types.Content(
            role="user", parts=[types.Part.from_text(text=json.dumps(payload))]
        )
        
        # Turn 0
        turn0_events = [
            {
                "author": "user",
                "content": {
                    "role": "user",
                    "parts": [{"text": json.dumps(payload)}]
                }
            }
        ]
        
        events1 = list(runner.run(
            new_message=message,
            user_id="eval_user",
            session_id=session.id,
        ))
        
        has_interrupt = False
        interrupt_id = None
        # Track the scrubbed description so we can inject it as the llm_reviewer input
        scrubbed_description = None
        llm_reviewer_injected = False
        
        for e in events1:
            # Detect security_checkpoint via node_info.path (author is always
            # 'ambient_expense_workflow', but path identifies the actual node).
            node_path = ""
            node_info = getattr(e, "node_info", None)
            if node_info and getattr(node_info, "path", None):
                node_path = node_info.path
            
            if "security_checkpoint" in node_path:
                # Capture the scrubbed description from the output object
                output = getattr(e, "output", None)
                if output is not None and hasattr(output, "description"):
                    scrubbed_description = output.description
                    sc_text = f"Security Checkpoint: Scrubbed description to: '{scrubbed_description}'"
                elif output is not None and isinstance(output, dict):
                    scrubbed_description = output.get("description", "")
                    sc_text = f"Security Checkpoint: Scrubbed description to: '{scrubbed_description}'"
                else:
                    sc_text = f"Security Checkpoint ran. output={output}"
                
                turn0_events.append({
                    "author": "security_checkpoint",
                    "content": {
                        "role": "model",
                        "parts": [{"text": sc_text}]
                    }
                })
                # Don't append again below — security_checkpoint events have no content
                continue
            
            # For the llm_reviewer, inject a synthetic input-context event first
            author_name = getattr(e, "author", "") or ""
            if "llm_reviewer" in author_name and not llm_reviewer_injected:
                llm_reviewer_injected = True
                # Determine what the scrubbed description was
                desc_for_llm = scrubbed_description if scrubbed_description is not None else payload.get("description", "")
                expense_ctx = dict(payload)
                expense_ctx["description"] = desc_for_llm
                turn0_events.append({
                    "author": "llm_reviewer_input",
                    "content": {
                        "role": "user",
                        "parts": [{
                            "text": (
                                f"[INPUT TO LLM REVIEWER - this is the exact expense the LLM sees, "
                                f"after security_checkpoint scrubbing]\n"
                                f"{json.dumps(expense_ctx, indent=2)}"
                            )
                        }]
                    }
                })

            if e.content is not None:
                turn0_events.append(serialize_event(e))
                # Check for human interrupt
                for part in e.content.parts:
                    if part.function_call and part.function_call.name == "adk_request_input":
                        has_interrupt = True
                        interrupt_id = part.function_call.id or "decision"
        
        turns = [
            {
                "turn_index": 0,
                "events": turn0_events
            }
        ]
        
        if has_interrupt:
            print(f"  -> Intercepted human approval step (interrupt_id={interrupt_id})")
            
            # Automate decision: Reject if it's prompt injection, approve if clean/redacted
            description = payload.get("description", "")
            is_injection = detect_prompt_injection(description)
            decision_result = "no" if is_injection else "yes"
            print(f"  -> Automating decision: {decision_result} (is_injection={is_injection})")
            
            # Resume message
            message_resume = types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=interrupt_id,
                            name="adk_request_input",
                            response={"result": decision_result},
                        )
                    )
                ],
            )
            
            # Turn 1
            turn1_events = [
                {
                    "author": "user",
                    "content": {
                        "role": "user",
                        "parts": [
                            {
                                "function_response": {
                                    "name": "adk_request_input",
                                    "response": {"result": decision_result}
                                }
                            }
                        ]
                    }
                }
            ]
            
            events2 = list(runner.run(
                new_message=message_resume,
                user_id="eval_user",
                session_id=session.id,
            ))
            
            for e in events2:
                if e.content is not None:
                    turn1_events.append(serialize_event(e))
                    
            turns.append({
                "turn_index": 1,
                "events": turn1_events
            })
            
        # Extract the final agent outcome text for the 'responses' field
        final_text = ""
        for turn in reversed(turns):
            for e in reversed(turn["events"]):
                if e["author"] != "user" and "content" in e and e["content"]:
                    for part in e["content"]["parts"]:
                        if "text" in part and part["text"]:
                            final_text = part["text"]
                            break
                    if final_text:
                        break
            if final_text:
                break
        
        if not final_text:
            final_text = "No final text response found."
            
        generated_cases.append({
            "eval_case_id": case_id,
            "prompt": case["prompt"],
            "responses": [
                {
                    "response": {
                        "role": "model",
                        "parts": [{"text": final_text}]
                    }
                }
            ],
            "agent_data": {
                "agents": {
                    "expense_agent": {
                        "agent_id": "expense_agent",
                        "instruction": "Orchestrates expense routing and approvals."
                    }
                },
                "turns": turns
            }
        })
        
    output_dataset = {
        "eval_cases": generated_cases
    }
    
    with open(output_path, "w") as f:
        json.dump(output_dataset, f, indent=2)
        
    print(f"Traces successfully generated and written to {output_path}!")

if __name__ == "__main__":
    main()
