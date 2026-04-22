# OpenCode Memento Plugin

This plugin connects OpenCode to the Memento Core. It implements hooks for the OpenCode Plugin architecture.

## Installation

Add this to your `~/.config/opencode/opencode.json`:

```json
{
  "plugin": [
    "/path/to/memento/src/memento/plugins/opencode/index.js"
  ]
}
```

## Features

- Extracts memories from tool usage implicitly
- Automatically primes the session with relevant memories on start
- Automatically flushes and runs background epochs
