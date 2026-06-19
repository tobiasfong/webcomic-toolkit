import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command=r"C:\AI\grimdark-background-mcp\.venv\Scripts\python.exe",
        args=[r"C:\AI\grimdark-background-mcp\server.py"],
        cwd=r"C:\AI\grimdark-background-mcp",
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS EXPOSED:", [t.name for t in tools.tools])
            res = await session.call_tool("check_status", {})
            print("check_status ->", res.content[0].text)

asyncio.run(main())
