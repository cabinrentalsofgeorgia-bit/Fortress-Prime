# Shared: MCP Servers

Last updated: 2026-04-26

## Technical overview

Model Context Protocol (MCP) servers expose tooling to LLM agents (Claude Code, Cursor, etc.). Fortress Prime's MCP integration footprint is **stub-status in this architecture-foundation pass** — needs operator confirmation of what is currently deployed vs aspirational.

Signals of MCP presence:

- Vercel-plugin session-context note (in agent system reminders) references `mcp__plugin_vercel-plugin_vercel__authenticate` and `mcp__plugin_vercel-plugin_vercel__complete_authentication` — suggests at least the Vercel MCP plugin is configured for the development agent
- No MCP-server source files found via `find -name "*mcp*"` in the repo (search ran 2026-04-26)
- No `mcp.json` / `claude_desktop_config.json` style config files found via grep

## Open questions for operator

1. Are MCP servers running on `spark-node-2` (or another node), or only configured at the developer-tool layer (Cursor / Claude Code locally)?
2. Which MCP plugins are active for which agents (Architect / Sovereign / Council)?
3. Is there a proposed MCP integration for Fortress-internal tools (e.g. a `fortress-vault` MCP that exposes `process_vault_upload`)?
4. Should any of the existing tooling (Captain, Sentinel, Council, vault scripts) migrate from REST to MCP for agent invocation?

## Stub-status

This doc is intentionally light. When operator answers come in, sections to add:

- Active MCP servers + endpoints
- Per-agent plugin configuration
- Auth model for MCP access
- Examples of MCP-mediated workflows

## Cross-references

- Vercel plugin notes appear in agent session reminders (when the user invokes `/`-prefixed Vercel-related skills)
- Anthropic MCP spec: https://modelcontextprotocol.io/

Last updated: 2026-04-26
