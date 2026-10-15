# Pulsonix skill

An agent skill for Claude Code and Codex to work with Pulsonix schematics, component libraries, and PCB exports.

## Capabilities

- Rename parts, edit properties, and replace compatible components in schematics offline.
- Rename existing library attributes without the Pulsonix scripting API.
- Create component variants and prepare parts for library import.
- Inspect libraries and update existing part attributes.
- Look up component specifications through a component-search MCP server.
- Extract PLX files from ZIP archives.
- Simplify PCB STEP exports by removing small holes, removing selected components, and sharing repeated geometry.

Offline edits do not require Pulsonix scripting. Some library import and update workflows use standard scripting; Advanced Scripting Features are never used. Native file editing requires Windows.

## Installation

Install Git, then clone the repository into the shared `.agents/skills` directory.

### Windows (PowerShell)

```powershell
git clone https://github.com/denis-cognimade/pulsonix-skill.git "$env:USERPROFILE\.agents\skills\pulsonix"
```

### Linux (sh)

```sh
git clone https://github.com/denis-cognimade/pulsonix-skill.git "$HOME/.agents/skills/pulsonix"
```

Start a new agent session after installation.
