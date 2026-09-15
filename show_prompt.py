"""Retrieve the actual MCP Prompt for the local database, ready to paste into a client."""

import argparse
import asyncio
from pathlib import Path
import sys

# Client lifecycle adapted from the same cited SDK example as demo_checks.py:
# https://github.com/modelcontextprotocol/python-sdk/blob/8c2fa6eabacde869d75568e33b9d466b58c2f512/examples/snippets/clients/stdio_client.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(daily_hours: str):
    root = Path(__file__).resolve().parent
    params = StdioServerParameters(command=sys.executable,
        args=["-X", "utf8", str(root / "server.py"), "--env-file", str(root / ".env")])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.get_prompt("weekly_study_plan", {"daily_hours": daily_hours})
            for message in result.messages:
                print(message.content.text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-hours", default="2")
    args = parser.parse_args()
    asyncio.run(main(args.daily_hours))
