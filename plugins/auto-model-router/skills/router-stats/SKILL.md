---
name: router-stats
description: Show token usage, cost per model, and savings vs Opus/Fable (/router-stats).
argument-hint: "[days]"
disable-model-invocation: true
model: claude-haiku-5-5
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" stats --days $ARGUMENTS`
Display the table above verbatim plus 1 sentence on the top saving opportunity.
