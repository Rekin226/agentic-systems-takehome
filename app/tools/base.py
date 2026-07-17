"""
tools/base.py: what a tool is in this system.

A tool is not a bare function. It is:
  - a stable `name` (how the planner/harness refers to it)
  - an `input_model` (its contract, the harness validates against this)
  - a `requires_approval` flag (its authorization level)
  - a `run()` implementation

The harness never calls run() directly. It routes every tool through a single
controlled method that:
  1. validates the raw input dict against input_model  (guardrail B)
  2. runs the tool
  3. returns a typed output

This is why a planner/LLM cannot inject invalid parameters into a tool: the
validation happens in the harness's hands, not the caller's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type

from pydantic import BaseModel


class Tool(ABC):
    #: Stable identifier used in the trace and by the planner.
    name: str
    #: Pydantic model the raw input must satisfy before run() is invoked.
    input_model: Type[BaseModel]
    #: High-risk tools may only run after an approval has been granted.
    requires_approval: bool = False

    def validate_input(self, raw: dict) -> BaseModel:
        """Guardrail B: never trust caller-supplied params. Raises on bad input."""
        return self.input_model.model_validate(raw)

    @abstractmethod
    def run(self, payload: BaseModel) -> BaseModel:
        """Execute with an ALREADY-VALIDATED payload. Returns a typed output."""
        raise NotImplementedError
