"""Connect to a running MCP server and print its advertised tools."""

import argparse
import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def inspect_server(url: str) -> list[str]:
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [tool.name for tool in result.tools]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    args = parser.parse_args()
    tools = asyncio.run(inspect_server(args.url))
    print("MCP tools:", ", ".join(tools))


if __name__ == "__main__":
    main()
