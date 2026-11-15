---
name: router-mode
description: View or set router mode: eco, balanced, quality, or off (/router-mode).
argument-hint: "[eco|balanced|quality|off]"
disable-model-invocation: true
model: claude-haiku-5-5
allowed-tools: Bash(python3:*)
---
!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/router.py" mode $ARGUMENTS`
Confirm the active mode in 1 line.
