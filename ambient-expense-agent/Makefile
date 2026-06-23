# Makefile for Ambient Expense Agent

.PHONY: install playground test generate-traces grade grade-ci update-golden start

install:
	uv sync

playground:
	agents-cli playground

test:
	uv run pytest

generate-traces:
	PYTHONPATH=. uv run python tests/eval/generate_traces.py

grade:
	agents-cli eval grade --traces artifacts/traces/generated_traces.json --config tests/eval/eval_config.yaml

## CI target: grades against the committed golden fixture (no agent execution needed)
grade-ci:
	agents-cli eval grade --traces tests/eval/fixtures/golden_traces.json --config tests/eval/eval_config.yaml

## Promote the latest generated traces to the golden fixture (run after verifying grade scores)
update-golden:
	cp artifacts/traces/generated_traces.json tests/eval/fixtures/golden_traces.json
	@echo "Golden fixture updated. Review the diff and commit tests/eval/fixtures/golden_traces.json."

start:
	uv run python -m expense_agent.fast_api_app
