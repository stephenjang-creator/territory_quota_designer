"""
agents/ask_agent.py: a standalone agent that answers questions by driving the
Sales Plan Designer MCP server.

It spawns the project's own MCP server over stdio, discovers its read-only tools,
and hands them to Claude in a small tool-use loop. Claude decides which tools to
call and narrates the answer; the deterministic engine behind the MCP server owns
every number. This is the same human-in-the-loop split the dashboard uses, shown
against a real MCP transport rather than in-process calls.

Run it:

    pip install -r requirements.txt          # anthropic + mcp
    export ANTHROPIC_API_KEY=sk-ant-...
    python agents/ask_agent.py "which segment is most at risk?"
    python agents/ask_agent.py "how many reps should I hire, and in what priority?"

No key? The dashboard's Ask box still answers recognized questions offline via the
deterministic router (see core/ask.py); this script is the live, MCP-backed path.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

SYSTEM = (
    "You are a RevOps analyst answering questions about a deterministic territory & "
    "quota plan, using the provided MCP tools. The engine behind the tools owns every "
    "number; never invent or alter one. Call a tool or two, then answer in a short, "
    "concrete paragraph. Frame coverage as pipeline adequacy and risk, not a guarantee "
    "of attainment."
)

MODEL = os.environ.get("ASK_MODEL", "claude-opus-5")
MAX_TOKENS = 1024
MAX_TURNS = 6


def _server_params(server: str):
    from mcp.client.stdio import StdioServerParameters

    # Run the project's MCP server over stdio (its default transport).
    return StdioServerParameters(command=sys.executable, args=[server])


def _result_text(result) -> str:
    """Flatten an MCP tool result into text for the model."""
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
    return "\n".join(parts) if parts else "(no content)"


async def ask(question: str, server: str = "mcp_server.py") -> str:
    import anthropic
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    client = anthropic.AsyncAnthropic()  # reads ANTHROPIC_API_KEY

    async with stdio_client(_server_params(server)) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = [
                {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
                for t in listed.tools
            ]

            messages = [{"role": "user", "content": question}]
            for _ in range(MAX_TURNS):
                resp = await client.messages.create(
                    model=MODEL,
                    max_tokens=MAX_TOKENS,
                    system=SYSTEM,
                    tools=tools,
                    messages=messages,
                )
                if resp.stop_reason != "tool_use":
                    return "".join(
                        b.text for b in resp.content if getattr(b, "type", None) == "text"
                    ).strip()

                messages.append({"role": "assistant", "content": resp.content})
                results = []
                for b in resp.content:
                    if getattr(b, "type", None) == "tool_use":
                        print(f"  · calling {b.name}({json.dumps(b.input)})", file=sys.stderr)
                        out = await session.call_tool(b.name, b.input or {})
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": b.id,
                                "content": _result_text(out),
                            }
                        )
                messages.append({"role": "user", "content": results})

            return "I couldn't settle the answer within the tool-call budget."


def main() -> None:
    question = " ".join(sys.argv[1:]).strip() or "Which segment is most at risk?"
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY to run the live MCP agent (see the module docstring).")
    server = os.environ.get("MCP_SERVER", "mcp_server.py")
    print(asyncio.run(ask(question, server)))


if __name__ == "__main__":
    main()
