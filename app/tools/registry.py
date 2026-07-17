"""
tools/registry.py: the Tool Registry.

A name -> Tool map. Why a registry instead of importing tools directly in the
harness?

  1. The harness dispatches tools *by name* (the same way a planner/LLM would
     name a tool). This is the seam a real LLM tool-call would plug into.
  2. It is the one place that knows the full set of tools and their
     authorization levels, the natural home for "is this tool allowed?".
  3. Adding a tool = register it here. The harness never changes.
"""

from __future__ import annotations

from app.tools.base import Tool
from app.tools.check_policy import CheckPolicyTool
from app.tools.create_draft_po import CreateDraftPOTool
from app.tools.lookup_catalog import LookupCatalogTool
from app.tools.submit_to_erp import SubmitToErpTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def requires_approval(self, name: str) -> bool:
        return self.get(name).requires_approval

    def names(self) -> list[str]:
        return list(self._tools)


def default_registry() -> ToolRegistry:
    """Wire up the standard toolset."""
    registry = ToolRegistry()
    registry.register(LookupCatalogTool())
    registry.register(CheckPolicyTool())
    registry.register(CreateDraftPOTool())
    registry.register(SubmitToErpTool())
    return registry
