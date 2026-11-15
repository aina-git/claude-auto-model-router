---
name: route
description: Preview difficulty score and target model tier for a task (/route).
argument-hint: "<task>"
disable-model-invocation: true
model: claude-haiku-5-5
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" explain "$ARGUMENTS"`
Show the output above concisely. Mention `@haiku/@sonnet/@opus/@fable` to force a tier.
