# ADR-040: Tools for agents: tool nodes attached to the Agent node, the MCP Client Tool, a loop with a bound

**Status:** Proposed  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-037](037-agent-harness.md), [ADR-012](012-workflow-definition-editor.md)  
**Amended by:** —

## 1. Title

An agent calls tools. Tools are nodes attached to the Agent node from below, as in n8n; the first ones are the MCP Client
Tool (for example GitHub's MCP server), the HTTP Request Tool and the Code Tool.

## 2. Context

ADR-037 built one request per agent node and named tool calling as the next step. The owner takes n8n as the model and
wants an agent that works with GitHub through GitHub's MCP server, with tools as nodes of their own. In n8n the AI Agent
node has a *Tools* connector; tool sub-nodes hang below it and run only when the model calls them. Which tools a node
offers decides what the agent may do (*Tools to include*: all, selected, all except), so a read-only GitHub agent is a
matter of choosing the read tools.

## 3. Decision

- **Attached, not walked.** The Agent node gets an input port `tools` (drawn at its bottom); each tool kind has one output
  port `tool` (drawn at its top) and no flow ports. An edge from `tool` to `tools` is an attachment: the engine never
  walks it; the agent calls the tool. A tool attaches to one agent; an agent takes any number of tools. Only tool ports
  connect to `tools` and a tool port connects only there. The editor draws these edges dashed and vertical.
- **Tool kinds** (action definitions only, addable, settings in `config`):
  - `mcp_tool` *MCP Client Tool*: endpoint URL (Streamable HTTP), the name of the secret sent as a bearer token,
    *Tools to include* (`all`, `selected`, `all_except`) with a list of tool names, a timeout per call. Only remote
    servers: no local process (n8n does the same for this node). GitHub: `https://api.githubcopilot.com/mcp/` with a
    personal access token.
  - `http_tool` *HTTP Request Tool*: a tool name and description for the model, method, URL, headers, body, and
    parameters the model fills (`name: description` per line), used as `{name}` in the URL, headers and body.
  - `code_tool` *Code Tool*: a tool name and description, the Code node's language, code, secrets and limits; the model's
    arguments are `input` in `context.json`, the last line of stdout is the answer.
- **The loop.** The agent node sends the request with the tools (OpenAI function calling), runs every tool call of the
  answer, sends the results back and repeats until the model answers without a tool call, at most *Max iterations*
  (agent setting, 1 to 50, default 10, overridable on the node like every setting). The node's time limit covers all
  turns and tool calls; each request keeps its retries (ADR-037). A failed tool call is sent back to the model as an
  error text (as n8n does), it does not fail the node; hitting the iteration limit fails it.
- **Frozen at the start.** The tools attached to an agent node are frozen with the agent into the snapshot.
- **Safety.** MCP and HTTP tools go through the guarded HTTP path (SSRF, metadata refused, pinned addresses, no
  redirects off the origin, capped bodies); the private-network permission is the LLM providers' (operator switch plus
  the tool's own). Tokens only as secrets; the values are masked in results, detail and logs. Model-supplied values are
  put into the request after the references are resolved and are never scanned again (a model cannot reach a secret by
  writing `${secret:...}`). A Code Tool runs under the Code node's rules (needs the API token, limits, no sandbox).
  Tool results are foreign text for the model and the history.
- **History.** The step's detail gets the turns: per turn the attempts and the tool calls (tool, arguments, result cut to
  16 KiB, error, duration). Usage is summed over the turns.

## 4. Consequences

- A read-only GitHub agent is an MCP Client Tool with only read tools selected.
- Not built: memory, several agents, approval before a tool call, local MCP servers, tools of the n8n kind "call a
  workflow".
