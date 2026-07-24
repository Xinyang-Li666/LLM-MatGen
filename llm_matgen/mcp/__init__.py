"""Minimal, dependency-light MCP integration for LLM-MatGen."""

from .server import MCPServer, MCPProtocolError, serve_stdio

__all__ = ["MCPServer", "MCPProtocolError", "serve_stdio"]
