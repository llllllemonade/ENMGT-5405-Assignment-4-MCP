"""Real MCP protocol demo: functionality, input exploits, rate limiting and .env use."""

import asyncio
from contextlib import closing
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from cryptography.fernet import Fernet
# Adapted client lifecycle and request patterns from the official MCP SDK (MIT):
# https://github.com/modelcontextprotocol/python-sdk/blob/8c2fa6eabacde869d75568e33b9d466b58c2f512/examples/snippets/clients/stdio_client.py
# Changes: temporary .env/database, assertions, three tools and a planning prompt.
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parent


# Decode a successful MCP text response into a Python dictionary.
def unpack(result):
    if result.isError:
        raise AssertionError(f"Unexpected MCP error: {result}")
    return json.loads(next(item.text for item in result.content if item.type == "text"))


# Run an isolated MCP subprocess and pass its initialized session to a check.
async def with_server(db: Path, limit: int, window: float, operation):
    env_file = db.with_suffix(".env")
    if not env_file.exists():
        key = Fernet.generate_key().decode("ascii")
        env_file.write_text(
            f"TASK_DATA_KEY={key}\nTASK_DB_PATH={db.name}\n"
            f"TASK_RATE_LIMIT={limit}\nTASK_RATE_WINDOW_SECONDS={window}\n", encoding="utf-8"
        )
    parameters = StdioServerParameters(command=sys.executable,
        args=["-X", "utf8", str(ROOT / "server.py"), "--env-file", str(env_file)])
    log_path = db.with_suffix(".log")
    try:
        with log_path.open("w", encoding="utf-8") as server_log:
            async with stdio_client(parameters, errlog=server_log) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    await operation(session)
    except Exception:
        print(log_path.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
        raise


# Verify endpoint discovery, valid requests, input exploits and prompt content.
async def functionality(session):
    tools, prompts = await session.list_tools(), await session.list_prompts()
    assert {tool.name for tool in tools.tools} == {"add_assignment", "upcoming_assignments", "delete_assignment"}
    assert {prompt.name for prompt in prompts.prompts} == {"weekly_study_plan"}
    print("[PASS] Real stdio MCP server: discovered 3 tools + 1 prompt", flush=True)
    args = dict(course="ENMGT 5405", title="MCP MVP demo", due_date=date.today().isoformat(), estimated_hours=3)
    assert unpack(await session.call_tool("add_assignment", args))["ok"]
    print("[PASS] Added a valid assignment")
    for attack in ({"due_date": "2026-02-30"}, {"estimated_hours": -3},
                   {"due_date": "2026-09-15'; DROP TABLE assignments;--"}):
        blocked = unpack(await session.call_tool("add_assignment", {**args, **attack}))
        assert not blocked["ok"] and blocked["error"]["code"] == "INVALID_INPUT"
        print(f"[PASS] Input exploit {attack} blocked: INVALID_INPUT")
    result = unpack(await session.call_tool("upcoming_assignments", {"days": 7}))
    assert len(result["assignments"]) == 1
    print("[PASS] Invalid assignments did not enter the database")
    prompt = await session.get_prompt("weekly_study_plan", {"daily_hours": "2"})
    body = "\n".join(message.content.text for message in prompt.messages)
    assert "MCP MVP demo" in body and "2 remaining study hours" in body
    print("[PASS] Weekly prompt includes actual stored assignments")
    print("\n--- MCP prompt template (the client model produces the final plan) ---\n" + body)


# Verify persistence, duplicate rejection, deletion and re-adding through MCP.
async def reopened(session):
    result = unpack(await session.call_tool("upcoming_assignments", {}))
    assignment = result["assignments"][0]
    assert assignment["title"] == "MCP MVP demo"
    print("[PASS] Assignments persist across server restarts with the same .env key")
    args = {key: assignment[key] for key in ("course", "title", "due_date", "estimated_hours")}
    duplicate = unpack(await session.call_tool("add_assignment", args))
    assert not duplicate["ok"] and duplicate["error"]["code"] == "DUPLICATE_ASSIGNMENT"
    assert duplicate["error"]["existing_id"] == assignment["id"]
    print("[PASS] Duplicate rejected after restart despite randomized ciphertext")
    deleted = unpack(await session.call_tool("delete_assignment", {"assignment_id": assignment["id"]}))
    assert deleted["ok"] and deleted["deleted_assignment"]["id"] == assignment["id"]
    assert deleted["deleted_assignment"]["title"] == assignment["title"]
    missing = unpack(await session.call_tool("delete_assignment", {"assignment_id": assignment["id"]}))
    assert not missing["ok"] and missing["error"]["code"] == "NOT_FOUND"
    assert unpack(await session.call_tool("upcoming_assignments", {}))["assignments"] == []
    print("[PASS] Deleted the specified record; repeated deletion returns NOT_FOUND")
    assert unpack(await session.call_tool("add_assignment", args))["ok"]
    print("[PASS] Re-adding the assignment after deletion succeeds")


# Exhaust the shared request budget and verify blocking and timed recovery.
async def flood(session):
    for index in range(1, 4):
        assert unpack(await session.call_tool("upcoming_assignments", {}))["ok"]
        print(f"[PASS] Rate-limit demo: call {index}/3 accepted")
    blocked = unpack(await session.call_tool("upcoming_assignments", {}))
    assert not blocked["ok"] and blocked["error"]["code"] == "RATE_LIMITED"
    print("[PASS] Call 4 blocked: RATE_LIMITED (demo setting: 3 calls / 5 seconds)")
    blocked_delete = unpack(await session.call_tool("delete_assignment", {"assignment_id": 1}))
    assert not blocked_delete["ok"] and blocked_delete["error"]["code"] == "RATE_LIMITED"
    print("[PASS] Deletion cannot bypass the shared limit")
    try:
        await session.get_prompt("weekly_study_plan", {})
    except Exception as exc:
        assert "Rate limit exceeded" in str(exc)
    else:
        raise AssertionError("Prompt bypassed shared limiter")
    print("[PASS] Prompt cannot bypass the shared limit")
    await asyncio.sleep(5.1)
    assert unpack(await session.call_tool("upcoming_assignments", {}))["ok"]
    print("[PASS] Calls accepted again after the window expires")


# Run isolated live protocol checks for functionality, encryption and rate limits.
async def main():
    with tempfile.TemporaryDirectory(prefix="course-mcp-demo-") as folder:
        db = Path(folder) / "functionality.db"
        await with_server(db, 10, 60, functionality)
        with closing(sqlite3.connect(db)) as conn:
            row = conn.execute("SELECT course, title FROM assignments").fetchone()
        assert row[0] != "ENMGT 5405" and row[1] != "MCP MVP demo"
        print("[PASS] Course and title are encrypted using a real key from the local .env")
        await with_server(db, 10, 60, reopened)
        await with_server(Path(folder) / "rate.db", 3, 5, flood)
    print("\nAll live MCP checks passed. Your real database was not changed.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
