"""Generate local Claude Desktop configuration without modifying the client."""

import json
from pathlib import Path
import sys


# Generate Claude Desktop configuration using this checkout's virtual environment.
def main():
    root = Path(__file__).resolve().parent
    python = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        raise SystemExit("Create .venv first; see README.md.")
    # JSON structure adapted from the official MCP local-server guide:
    # https://modelcontextprotocol.io/docs/develop/connect-local-servers
    # Only executable and file paths are passed; the secret remains in .env.
    config = {"mcpServers": {"course-task-manager": {
        "command": str(python),
        "args": ["-X", "utf8", str(root / "server.py"), "--env-file", str(root / ".env")],
    }}}
    output = root / "claude_desktop_config.json"
    output.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Generated: {output}")


if __name__ == "__main__":
    main()
