# BytsOne Automation Bot 🤖

An automated bot that solves LeetCode problems on [BytsOne](https://bytsone.com) — a coding platform used at Karunya University. It navigates course chapters, opens each LeetCode problem in a new tab, uses an LLM (OpenAI/Anthropic) to generate a solution, injects the code into the Monaco editor, submits it, and marks the problem as complete — all automatically.

## Features

- 🔐 **Session persistence** — logs in once, reuses session across runs
- 🔄 **Resume support** — picks up from where it left off via `progress.json`
- 🧠 **LLM-powered solving** — supports OpenAI and Anthropic APIs
- 🔁 **Auto re-auth** — detects and handles expired sessions mid-run
- 🛡️ **Graceful degradation** — failed problems are skipped and retried next run

## Quick Start

See [QUICKSTART.md](QUICKSTART.md) for setup and usage instructions.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for a detailed breakdown of the design.
