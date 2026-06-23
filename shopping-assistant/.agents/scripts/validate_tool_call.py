#!/usr/bin/env python3
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
import re
import sys


def is_destructive_command(command_str: str) -> tuple[bool, str]:
    """Inspects a command string and determines if it is destructive.

    Returns:
        A tuple of (is_destructive, reason_message)
    """
    normalized_cmd = command_str.strip()

    # 1. Check for recursive and force rm targeting root or system roots
    # Matches word 'rm'
    if re.search(r'\brm\b', normalized_cmd):
        # Check for recursive flags: -r, -R, --recursive
        has_recursive = bool(re.search(r'-[a-zA-Z]*[rR]', normalized_cmd) or '--recursive' in normalized_cmd)
        # Check for force flag: -f, --force
        has_force = bool(re.search(r'-[a-zA-Z]*f', normalized_cmd) or '--force' in normalized_cmd)

        # Check if targets root '/' or '/*' or '/.*'
        # Looking for spaces followed by / or /* or /.* or quotes around them
        targets_root = bool(
            re.search(r'\s+[\'"]?/[\'"]?(?:\s+|$)', normalized_cmd) or
            re.search(r'\s+[\'"]?/\*[\'"]?(?:\s+|$)', normalized_cmd) or
            re.search(r'\s+[\'"]?/\.\*[\'"]?(?:\s+|$)', normalized_cmd)
        )

        if has_recursive and has_force and targets_root:
            return True, "Destructive 'rm' command targeting root '/' is prohibited."

    # 2. Check for Fork Bomb
    # e.g., :(){ :|:& };:
    if ":(){" in normalized_cmd.replace(" ", "") and ":|" in normalized_cmd.replace(" ", ""):
        return True, "Fork bomb execution is prohibited."

    # 3. Check for dd targeting critical block devices
    # e.g., dd of=/dev/sda
    if re.search(r'\bdd\b', normalized_cmd) and re.search(r'\bof=/dev/(?:sd[a-z]|hd[a-z]|disk|nvme|mem|kmem)', normalized_cmd):
        return True, "Destructive 'dd' command targeting block devices is prohibited."

    # 4. Check for recursive chmod/chown targeting root
    # e.g., chmod -R 777 /
    if re.search(r'\b(chmod|chown)\b', normalized_cmd):
        has_recursive_ch = bool(re.search(r'-[a-zA-Z]*[rR]', normalized_cmd) or '--recursive' in normalized_cmd)
        targets_root_ch = bool(
            re.search(r'\s+[\'"]?/[\'"]?(?:\s+|$)', normalized_cmd) or
            re.search(r'\s+[\'"]?/\*[\'"]?(?:\s+|$)', normalized_cmd)
        )
        if has_recursive_ch and targets_root_ch:
            cmd_name = re.search(r'\b(chmod|chown)\b', normalized_cmd).group(1)
            return True, f"Recursive changes to root directory permissions using '{cmd_name}' are prohibited."

    return False, ""

def main():
    try:
        # Read hook payload from stdin
        input_data = sys.stdin.read()
        if not input_data.strip():
            # If stdin is empty, allow for safety
            print(json.dumps({"decision": "allow"}))
            sys.exit(0)

        try:
            payload = json.loads(input_data)
        except json.JSONDecodeError as e:
            sys.stderr.write(f"Error parsing stdin as JSON: {e}\n")
            print(json.dumps({"decision": "deny", "reason": "Invalid JSON input"}))
            sys.exit(2)

        # Extract input parameters
        tool_input = payload.get("tool_input", {})

        # Extract command string from the tool input
        command_str = ""
        if isinstance(tool_input, dict):
            # Extract standard fields
            command_str = (
                tool_input.get("CommandLine") or
                tool_input.get("command") or
                tool_input.get("cmd") or
                ""
            )
            # Fallback: search values recursively for any string if keys don't match
            if not command_str:
                for val in tool_input.values():
                    if isinstance(val, str):
                        command_str = val
                        break
        elif isinstance(tool_input, str):
            command_str = tool_input

        # If no command is found to validate, allow
        if not command_str:
            print(json.dumps({"decision": "allow"}))
            sys.exit(0)

        # Perform security checks
        is_destructive, reason = is_destructive_command(command_str)
        if is_destructive:
            sys.stderr.write(f"Access Denied: {reason}\n")
            print(json.dumps({
                "decision": "deny",
                "reason": reason
            }))
            sys.exit(2)

        # Otherwise, allow the command execution
        print(json.dumps({
            "decision": "allow"
        }))
        sys.exit(0)

    except Exception as e:
        sys.stderr.write(f"Validation hook error: {e}\n")
        print(json.dumps({
            "decision": "deny",
            "reason": f"Internal hook validation error: {e}"
        }))
        sys.exit(2)

if __name__ == "__main__":
    main()
