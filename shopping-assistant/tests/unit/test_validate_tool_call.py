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

import json
import os
import subprocess
import sys

SCRIPT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".agents",
    "scripts",
    "validate_tool_call.py"
)

def run_validator(payload: dict) -> tuple[int, str, str]:
    """Runs the validation script with the given JSON payload.

    Returns:
        (returncode, stdout_str, stderr_str)
    """
    proc = subprocess.Popen(
        [sys.executable, SCRIPT_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, stderr = proc.communicate(input=json.dumps(payload))
    return proc.returncode, stdout.strip(), stderr.strip()

def test_allow_safe_commands():
    # Test typical safe dev commands
    safe_commands = [
        "ls -la",
        "git status",
        "echo 'hello world'",
        "python3 -m pytest tests/",
        "rm -rf .venv/lib",
        "rm -rf build/ dist/",
    ]
    for cmd in safe_commands:
        payload = {
            "tool_name": "run_command",
            "tool_input": {
                "CommandLine": cmd
            }
        }
        code, stdout, stderr = run_validator(payload)
        assert code == 0, f"Expected 0 for '{cmd}', got {code}. Stderr: {stderr}"
        data = json.loads(stdout)
        assert data.get("decision") == "allow"

def test_deny_destructive_rm():
    destructive_commands = [
        "rm -rf /",
        "rm -rf /*",
        "rm -fr /",
        "rm -r -f /",
        "rm -f -r /",
        "sudo rm -rf /",
        "rm -rf '/'",
        "rm -rf  / "
    ]
    for cmd in destructive_commands:
        payload = {
            "tool_name": "run_command",
            "tool_input": {
                "CommandLine": cmd
            }
        }
        code, stdout, stderr = run_validator(payload)
        assert code == 2, f"Expected 2 for '{cmd}', got {code}"
        data = json.loads(stdout)
        assert data.get("decision") == "deny"
        assert "Destructive 'rm' command targeting root" in data.get("reason", "")
        assert "Access Denied" in stderr

def test_deny_fork_bomb():
    bomb = ":(){ :|:& };:"
    payload = {
        "tool_name": "run_command",
        "tool_input": {
            "CommandLine": bomb
        }
    }
    code, stdout, _ = run_validator(payload)
    assert code == 2
    data = json.loads(stdout)
    assert data.get("decision") == "deny"
    assert "Fork bomb" in data.get("reason", "")

def test_deny_dd_destructive():
    payload = {
        "tool_name": "run_command",
        "tool_input": {
            "CommandLine": "dd if=/dev/zero of=/dev/sda bs=1M"
        }
    }
    code, stdout, _ = run_validator(payload)
    assert code == 2
    data = json.loads(stdout)
    assert data.get("decision") == "deny"
    assert "dd" in data.get("reason", "")

def test_deny_recursive_chmod_chown():
    commands = [
        "chmod -R 777 /",
        "chown -R root /",
        "chmod -R 755 /*"
    ]
    for cmd in commands:
        payload = {
            "tool_name": "run_command",
            "tool_input": {
                "CommandLine": cmd
            }
        }
        code, stdout, _ = run_validator(payload)
        assert code == 2, f"Expected 2 for '{cmd}', got {code}"
        data = json.loads(stdout)
        assert data.get("decision") == "deny"
        assert "permissions" in data.get("reason", "").lower() or "chown" in data.get("reason", "").lower()

def test_invalid_json_input():
    proc = subprocess.Popen(
        [sys.executable, SCRIPT_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    stdout, _ = proc.communicate(input="invalid-json")
    assert proc.returncode == 2
    data = json.loads(stdout.strip())
    assert data.get("decision") == "deny"
    assert "Invalid JSON" in data.get("reason")
