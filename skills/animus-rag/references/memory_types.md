# Animus Memory Types Reference

The Animus memory network unifies developer memories across machines, assistants, and workspaces.

## Memory Types & Sources

| Memory Type | Origin / Assistant | Content Description | Typical Use Cases |
| :--- | :--- | :--- | :--- |
| `copilot_chat` | GitHub Copilot | Chat turns, prompts, and assistant answers. | Recalling past solutions, explanations, and code generation. |
| `claude_chat` | Claude Code CLI | Complete conversation turns, tool calls, edits, and terminal outputs. | Understanding previous system debugging, commands executed, and file modifications. |
| `antigravity_chat` | Google Antigravity / AGY | Transcripts, agent reasoning, tool calls, and workflows. | Recalling Antigravity tasks, agent decisions, and workspace interactions. |
| `antigravity_memory` | Google Antigravity | Explicit agent memory artifacts, scratchpads, and project notes. | Architectural constraints, saved workflows, and project rules. |
| `claude_memory` | Claude Code | Auto-memory files and global preferences. | Persistent user preferences and recurring codebase conventions. |
| `user_note` | Manual / CLI (`animus remember`) | Explicit notes, decisions, credentials references, and architecture logs. | Important human-authored guidelines and operational runbooks. |
| `copilot_cli_chat` | GitHub Copilot CLI | Interactive terminal session turns and checkpoints. | Terminal commands and CLI troubleshooting history. |
| `workspace_memory` | Workspace files | `.animus-context.md`, `CLAUDE.md`, `GEMINI.md`, etc. | Workspace-specific documentation and boundaries. |
| `session_note` | Automated / MCP | Summaries or high-level milestones of complete sessions. | Fast navigation across past multi-turn tasks. |
| `repo_note` | Repository root | Repo-level instructions and conventions. | Project context and build/test instructions. |
