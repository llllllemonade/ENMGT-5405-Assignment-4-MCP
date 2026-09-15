# Course Task Manager MCP Server

A local Python MCP server for recording coursework, finding approaching deadlines,
and preparing a weekly study-plan prompt. It exposes **three tools and one prompt**.

## Requirements

- Python 3.12 recommended; tested with Python 3.12.14 on Windows x86-64.
- [uv](https://docs.astral.sh/uv/getting-started/installation/).
- VS Code or Cursor with the Python extension, for the virtual-environment demonstration.
- Claude Desktop for the course's required client demonstration.

No external API account, API key, hosted VM, Node.js, or network server is required
by the application. Installing dependencies and using Claude's online model require
network access. Local unit tests and the protocol demo work offline after installation.

## 1. Create and activate the virtual environment in VS Code or Cursor

Open **this repository folder**, then open the editor's integrated PowerShell terminal:

```powershell
uv venv .venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install -r requirements.txt
python -c "import sys; print(sys.executable); print(sys.prefix != sys.base_prefix)"
```

The last command must display this repository's `.venv` Python path and `True`.
Select that same interpreter with **Python: Select Interpreter** in the editor.

If PowerShell blocks activation scripts, use a **Command Prompt** integrated terminal:

```bat
.venv\Scripts\activate.bat
python -c "import sys; print(sys.executable); print(sys.prefix != sys.base_prefix)"
```

On macOS/Linux, use `source .venv/bin/activate` instead. The application source is
portable, but the prepared environment was tested on Windows only.

`requirements.txt` declares every direct dependency. `requirements-lock.txt` records
all 30 versions used in the Windows test environment. To reproduce those exact versions:

```powershell
uv pip sync requirements-lock.txt
```

## 2. Initialize local secrets and generate client configuration

With the virtual environment active:

```powershell
python init_local.py
python make_config.py
```

`init_local.py` creates a real Fernet encryption key in a local `.env` file, without
printing it. Re-running the command preserves the existing key. `.env.example`
documents the settings but deliberately contains no usable key.

`config.py` locates `.env` with `pathlib.Path` and parses it with `dotenv_values`,
with interpolation disabled. **Secrets are not read from operating-system variables,
passed as tool arguments, or embedded in the MCP client configuration.** `.env`
and the database are excluded by `.gitignore`.

The key encrypts course names and assignment titles before SQLite writes. Deadlines,
estimated hours, IDs, and Fernet token timestamps remain visible. A database key-check
record rejects a mismatched key at startup. Keep the original `.env` with any private
database backup: losing it means losing access to the encrypted names. A person who
can read both `.env` and the database can decrypt them; this is not protection against
a compromised local OS account.

Authentication: the server uses **local stdio**, does not listen on a network port,
and uses the launching OS user's file permissions. The encryption key is a storage
secret, not an API authentication token. No remote service requires OAuth in this MVP.

## 3. Run and verify

```powershell
python -m unittest discover -v
python demo_checks.py
python server.py
```

The unit suite contains 23 tests. The demo starts actual MCP subprocesses and uses
the SDK client to check discovery, all three tools, prompt retrieval, persistence,
duplicate rejection, targeted deletion, invalid inputs, encryption and rate-limit recovery. It uses temporary `.env` files
and databases; your real assignments are untouched.

When `server.py` prints `Course Task Manager ready (stdio)`, waiting is normal:
the process expects MCP messages, not conversational input. Stop it with Ctrl+C.
Client applications launch their own server automatically, so do not keep a separate
manual process running for the client demo.

## 4. Connect Claude Desktop

1. In Claude Desktop, open **Settings > Developer > Edit Config**.
2. On Windows the configuration is normally `%APPDATA%\Claude\claude_desktop_config.json`.
3. Merge this repository's generated `course-task-manager` entry into the existing
   `mcpServers` object. Preserve other configured servers.
4. Fully quit and restart Claude Desktop, then confirm the server and its three tools appear.

The committed `claude_desktop_config.json` is a complete configuration for the prepared
checkout. After cloning or moving the project, **regenerate it** with `python make_config.py`
to replace machine-specific paths. The generator does not edit Claude's settings.
The `-X utf8` Python option handles Windows text encoding without storing system settings.

Official connection guide: https://modelcontextprotocol.io/docs/develop/connect-local-servers

Try these requests in Claude; replace dates with actual current deadlines:

> Use course-task-manager to add an assignment for ENMGT 5405 called Assignment 4 MCP,
> due 2026-09-18, requiring 4 hours.

> List assignments due in the next 7 calendar days, including overdue assignments.

### Use the MCP Prompt

Select `weekly_study_plan` in your client's MCP prompt interface and set
`daily_hours` to `2`. The returned template embeds the actual database records.
Send it to Claude to generate the plan. MCP prompts are client-selected templates.

If your client version does not show an MCP prompt picker, retrieve the real endpoint:

```powershell
python show_prompt.py --daily-hours 2
```

Paste the returned template into Claude. This fallback retrieves the prompt through
the supplied Python MCP client, then uses Claude for model generation.
`demo_checks.py` also verifies `prompts/list` and `prompts/get`.

## 5. Tool and prompt contract

- `add_assignment(course, title, due_date, estimated_hours)` creates one record. Dates
  use strict `YYYY-MM-DD`; estimated hours must be finite and within `(0, 1000]`.
  Identical course/title/date/hours are rejected with `DUPLICATE_ASSIGNMENT` and
  `existing_id`. Text is trimmed and case-sensitive; 3 and 3.0 hours are equivalent.
  Changing any field creates a distinct record. Past dates are allowed for overdue work.
- `upcoming_assignments(days=7, include_overdue=True)` returns today plus the following
  `days - 1` dates, with overdue work included by default. It sorts by deadline, then
  larger effort, then ID, and returns at most 200 records with a `truncated` indicator.
- `delete_assignment(assignment_id)` permanently deletes exactly one record and
  returns `deleted_assignment`. Use an ID supplied by the user or returned by a
  query. The ID must be an integer in `[1, 9223372036854775807]`; an unknown or
  already-deleted ID returns `NOT_FOUND`. Re-adding deleted data creates a new ID.
- `weekly_study_plan(daily_hours="2")` is an MCP prompt. It covers today
  through this Sunday, includes overdue work, and asks the model to respect deadlines,
  daily capacity, and each assignment's remaining hours. It explicitly surfaces conflicts.

Tool responses use `ok: true` for success. Expected business failures use
`ok: false` plus an error code: `INVALID_INPUT`, `DUPLICATE_ASSIGNMENT`, `NOT_FOUND`,
`RATE_LIMITED`, or `STORAGE_ERROR`.
SDK argument-type errors and failed prompt retrievals are MCP errors. Clients must
check the response rather than assume success. The server does not call an LLM itself.

## 6. Best practices and reproducible exploit checks

**Input sanitization / validation.** Reject impossible dates, noncanonical date formats,
nonpositive or nonfinite effort, empty/oversized text, and control characters before
inserting data. Deletion validates its positive integer ID. SQL uses bound
parameters, so text is not executed as SQL. Exact duplicates are rejected after
normalization. The server decrypts candidate names because randomized Fernet
ciphertext cannot be compared directly, and a `BEGIN IMMEDIATE` transaction
prevents concurrent duplicate insertion. Historical duplicate rows are preserved.

`demo_checks.py` submits `2026-02-30`, `estimated_hours=-3`, and a date containing a
SQL injection payload through the actual MCP tool. Each returns `INVALID_INPUT`.
The next query confirms only the legitimate record was saved. The unit suite also
stores a SQL-looking title as inert data and confirms the table remains usable.
The live demo also resubmits a saved assignment after restart and verifies
`DUPLICATE_ASSIGNMENT`, then checks deletion, repeated deletion and re-adding.

**Rate limiting.** One sliding-window budget is shared by all three tools and prompt retrieval:
10 admitted attempts per 60 seconds in the normal `.env`. Invalid business inputs and duplicates
count; SDK type failures before the business function do not. Initialization and
endpoint discovery are not rate-limited. A thread lock protects concurrent checks.

The demo uses a separate `.env` with 3 calls per 5 seconds: calls 1-3 pass, call 4 is
blocked, deletion and prompt retrieval are also blocked, and the next call passes after the window
expires. The production settings are unchanged. Rejected excess requests do not
extend the window. Limits are per process and reset at restart; this is not distributed
or network-level denial-of-service protection.

## 7. Project structure and limitations

- `server.py`: endpoint registration and safe client-facing error translation.
- `task_manager.py`: domain validation, limiter, SQLite storage, encryption and prompt content.
- `config.py` / `init_local.py`: `.env` loading, validation and one-time key generation.
- `make_config.py`: complete Claude configuration for the current checkout.
- `demo_checks.py` / `show_prompt.py`: actual MCP client examples.
- `test_task_manager.py` / `test_config.py`: domain, security and persistence tests.
- `CODE_CITATIONS.md` / `THIRD_PARTY_NOTICES.md`: specific source references and license notices.

The MVP supports adding, querying, duplicate rejection and permanent deletion.
It has no update/completion workflow, calendar integration, cross-device sync or
key rotation. Retrieval is limited to deadline windows and 200 records; additional
filters and pagination would support larger datasets. Dates use the local calendar.
Estimated remaining hours are not decremented automatically. Model-generated plans
are suggestions; deterministic capacity and deadline checks could validate them.
The prompt labels assignment text as untrusted, but model prompt-injection defense
is not guaranteed. The rate limiter is process-local and resets at restart.

## AI assistance and citations

Codex assisted with implementation, translation, debugging, tests and documentation.
The author reviewed the implementation and verified its functionality. Every
function and class definition includes a one-line English purpose comment.
The official FastMCP sample server was used as a reference, not deployed as a separate
third-party service. Specific adapted patterns and changes are identified in adjacent
code comments and `CODE_CITATIONS.md`. The repository's existing MIT license is preserved.
