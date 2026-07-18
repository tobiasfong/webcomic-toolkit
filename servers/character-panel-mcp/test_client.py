import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(HERE, ".venv", "Scripts", "python.exe")
SERVER = os.path.join(HERE, "server.py")


async def main():
    params = StdioServerParameters(
        command=VENV_PYTHON,
        args=[SERVER],
        cwd=HERE,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS EXPOSED:", [t.name for t in tools.tools])

            res = await session.call_tool("check_status", {})
            print("check_status ->", res.content[0].text)

            res = await session.call_tool("list_projects", {})
            print("list_projects ->", res.content[0].text)

asyncio.run(main())
