"""
app package init.

Exposes load_env(): read a local .env into os.environ. It is called explicitly
by the real entrypoints (the FastAPI server and scripts/demo.py) rather than on
import, so the test suite stays hermetic (pytest never accidentally flips to the
LLM planner because a developer's .env set AGENT_PLANNER=llm).

It is a no-op if python-dotenv is not installed or no .env exists, so the base
install still works with zero configuration.
"""

from __future__ import annotations


def load_env() -> None:
    """Load ./.env into os.environ (never overrides already-set real env vars)."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:  # pragma: no cover - dotenv is an optional convenience
        pass
