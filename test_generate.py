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
            res = await session.call_tool("generate_background", {
                "prompt": "vast hive city cavern, towering machinery, catwalks, oppressive smog, detailed background art, no people",
                "sketch_path": r"C:\AI\sketch_input.png",
                "style_ref_path": r"C:\AI\cover_candidates\cand_17.jpg",
                "seed": 99,
                "ipa_weight": 0.6,
            })
            print("generate_background ->", res.content[0].text)

asyncio.run(main())
