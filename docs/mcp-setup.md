# Using echr-lookup from Claude (MCP setup)

echr-lookup runs as an **MCP server** (Model Context Protocol: the open standard that lets an AI app call tools in another program). It gives Claude six read-only tools over the case law (`search_case_law`, `get_paragraphs`, `get_case`, `count_cases`, `corpus_info`, `check_quote`). Claude does the reading and writing; the server only supplies cited evidence and **never calls a language model itself**. Tool and result shapes: [`interfaces-mcp.md`](interfaces-mcp.md). How it works and how to poke at it: [`learn/M1.md`](learn/M1.md).

Two ways to run it:

| Transport | Start it | Used by | Address |
|---|---|---|---|
| **stdio** | the client starts it for you | Claude Desktop, Claude Code, the MCP Inspector | none (talks over stdin/stdout) |
| **streamable HTTP** | `MCP_PORT=8101 pnpm run mcp:http` | Claude Code, the Inspector, scripts | `http://127.0.0.1:<port>/mcp` (this computer only) |

Ports: `pnpm run mcp:http` uses `MCP_PORT`, default **8100**. Each agent worktree sets its own port in `.env` (this one: 8101); never reuse 3000, 3100 or 8000.

## Before you start (once)

```bash
pnpm i
cd py && uv sync --group ml        # installs the local models' libraries (already cached on this machine)
pnpm db:up                         # ParadeDB on localhost:5433, with the corpus loaded
```

Check it works without any client: `cd py && uv run python ../scripts/mcp_call.py call corpus_info` should print the counts. The first start takes about 7 s because the embedding and reranking models load (and warm up) once, at startup; after that every call is fast.

## Claude Desktop (macOS)

1. Print the config snippet for **this checkout**; it has absolute paths because Desktop starts servers with no shell `PATH` and no useful working directory:

   ```bash
   scripts/mcp-desktop-config.sh
   ```

   It prints the `mcpServers` JSON (absolute path to `uv`, `--directory <repo>/py`, `DATABASE_URL` and `DATA_SOURCE` from the repo `.env`). It reads only those two keys, never prints a password other than the local database's public `echr` one (anything else is shown as `***`), and writes nothing.

2. Open the config file. In Claude Desktop: Claude menu in the menu bar, **Settings…**, **Developer**, **Edit Config**. The file is
   `~/Library/Application Support/Claude/claude_desktop_config.json`. Paste the `echr-lookup` entry inside `mcpServers` (keep any servers already there; one missing comma breaks the whole file).

3. **Quit Claude Desktop completely** (Cmd-Q; closing the window is not enough) and start it again. It reads the file only at startup.

4. See the tools: click the **+** in the chat box, hover **Connectors**, and `echr-lookup` should list six tools. Try: *"Using echr-lookup, how many Grand Chamber judgments are there and how many found a violation?"*, then *"Find the paragraph where Chahal says the prohibition on ill-treatment is absolute and check my quote."*

5. Logs: `~/Library/Logs/Claude/mcp*.log` (one file per server, `mcp-server-echr-lookup.log`):

   ```bash
   tail -n 50 -F ~/Library/Logs/Claude/mcp*.log
   ```

   The server writes its startup line (`ready (transport=stdio)`) and any error to stderr, which Desktop captures there. Every tool call is also recorded in the database table `tool_log` (what was asked, ok or error, latency, size). See [`learn/M1.md`](learn/M1.md), try-it 6.

If the tools do not show up: fully quit and restart; check the JSON is valid; run the exact `command` and `args` from the snippet in a terminal (it should sit waiting for input, with `ready (transport=stdio)` on stderr); make sure Docker/Postgres is up.

Sources: [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers) (config file, restart, Connectors menu) and [Debugging](https://modelcontextprotocol.io/docs/tools/debugging) (log locations), both at modelcontextprotocol.io.

## Claude Code

Stdio (Claude Code starts and stops the server itself). Everything after `--` is the command:

```bash
claude mcp add echr-lookup -- "$(command -v uv)" run --frozen --directory "$PWD/py" --group ml \
  python -m echr_mcp --transport stdio
claude mcp list            # should show: echr-lookup ... ✔ Connected
```

(Run it from the repo root. Add `--scope user` to make it available in every project; the default `local` scope is this project only.)

Streamable HTTP (you start the server, Claude Code connects to it):

```bash
MCP_PORT=8101 pnpm run mcp:http                 # in one terminal; leave it running
claude mcp add --transport http echr-lookup-http http://127.0.0.1:8101/mcp
claude mcp list
```

Inside a Claude Code session, `/mcp` shows the connection status and the tools. Remove with `claude mcp remove echr-lookup`.

Source: [Claude Code: Connect to tools via MCP](https://code.claude.com/docs/en/mcp).

## What a cited result looks like

Every paragraph the tools return carries three things for the answer to use:

- `cite`: a ready-to-paste citation, e.g. `[Chahal v. the United Kingdom, Judgment, §79]` or `[Harkins and Edwards v. the United Kingdom, Legal summary, Law, para 2]`. The server tells Claude to end every factual sentence with one, copied exactly.
- `para_label`: the readable part of that citation (`§79`, `Law, para 2`, `Operative provisions, para 1`, `Article 8`). It is display only; `paragraph_id` (`001-58004§79`) is the stable key and never changes.
- `hudoc_url`: the document's page. When the result has a quote or text, the link ends `#:~:text=<its first words>`, so a browser that supports text fragments (Chrome, Edge, Safari, recent Firefox) jumps to those words and highlights them. HUDOC is a JavaScript app, so the highlight can fail; the link still opens the case. Case-level links (`get_case`, `count_cases`) have no quote and no fragment.

The rules, with real links to try by hand: [`learn/mcp.md`](learn/mcp.md).

## The MCP Inspector (poke at the tools by hand)

The Inspector is the MCP project's own test client: list the tools, fill in arguments, see the raw JSON, no Claude needed. It runs through `npx` (Node 22.19 or newer; this repo already needs 22.22), so there is nothing to install.

```bash
# browser UI, against a stdio server it starts itself:
npx @modelcontextprotocol/inspector -- uv run --frozen --directory py --group ml python -m echr_mcp --transport stdio

# against the HTTP server (start `MCP_PORT=8101 pnpm run mcp:http` first):
npx @modelcontextprotocol/inspector --server-url http://127.0.0.1:8101/mcp --transport http

# no browser: list the tools, or call one, and print JSON
npx @modelcontextprotocol/inspector --cli --method tools/list -- \
  uv run --frozen --directory py --group ml python -m echr_mcp --transport stdio
npx @modelcontextprotocol/inspector --cli --method tools/call --tool-name check_quote \
  --tool-arg paragraph_id='001-58004§79' --tool-arg quote='the Convention prohibits in absolute terms torture' -- \
  uv run --frozen --directory py --group ml python -m echr_mcp --transport stdio
```

The `--` matters: it stops the Inspector reading the server's own `--transport stdio` as its flag. Run these from the repo root. Docs: [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector).

Without Node, `scripts/mcp_call.py` (this repo) does the same job in Python: `cd py && uv run python ../scripts/mcp_call.py list` and `... call <tool> '<json arguments>'` (add `--url http://127.0.0.1:8101/mcp` for HTTP).

## ChatGPT and claude.ai

**Not set up, and not connected to anything public.** Both products can only reach a **remote** MCP server, so they wait for the hosting decision in M3 ([`hosting-options.md`](hosting-options.md), when it lands). What they will need from us:

- **claude.ai** (also Claude Desktop's "custom connectors", Cowork and the mobile apps): a **public HTTPS URL** of a streamable-HTTP MCP server (ours ends in `/mcp`). Anthropic's cloud makes the connection, not your computer, so `127.0.0.1` and anything behind a VPN will not work unless Anthropic's IP ranges can reach it. Authentication: the connector form offers **OAuth** ("Sign in now" / "when needed"), **no sign-in**, or **fixed request headers** such as an API key or bearer token. Free plans can add one custom connector; on Team and Enterprise plans only an Owner can add it. Docs: [Get started with custom connectors using remote MCP](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp).
- **ChatGPT** (web): from **Plugins**, add a custom MCP server by its **public HTTPS MCP endpoint URL** (including `/mcp`; streamable HTTP or SSE), or through OpenAI's **Secure MCP Tunnel**, which reaches a server on a private network without exposing it. Authentication options: **OAuth**, **no authentication**, or both. ChatGPT cannot connect to a local server directly. Availability depends on plan and workspace policy (Business and Enterprise/Edu workspaces: admins control it). Docs: [Connecting custom MCP servers in ChatGPT](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) and [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt).

The server today has **no authentication** because it binds to `127.0.0.1` only (and checks the `Host` header, so a web page cannot talk to it through DNS rebinding). Anything public needs an auth decision first; that is part of M3's brief, not M1's. Product docs change quickly: re-check these pages before acting.
