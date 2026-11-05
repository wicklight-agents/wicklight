# Tutorial: build a meal-planning agent

In this capstone you'll build a real agent from scratch — one that plans a week
of dinners from what's in your kitchen, shops within a budget, and eventually
runs itself every Sunday — and you'll meet each of Wicklight's safety features
exactly when the agent needs it.

It's written for someone **comfortable with LLMs but new to agents**. By the end
you'll understand what an agent *is* (beyond a single model call), how to give it
tools safely, and how to read, trust, and deploy one.

## What you'll build

A `meal-planner` agent that, step by step across seven chapters, learns to:

1. **Suggest meals** from your pantry — your first agent and its trace.
2. **Shop on a budget** — and get stopped when a cart goes over.
3. **Order groceries** — but only with your approval.
4. **Read recipes off the web** — and shrug off a page that tries to hijack it.
5. **Protect your allergy data** — keeping it on a local model.
6. **Run on tools you wrote yourself** — the tool contract, up close.
7. **Deploy itself** — a scheduled run in a locked-down container.

Each chapter adds one capability and the safety feature it demands, so the
safety stack never feels bolted on — it's the natural answer to "wait, what stops
the agent from doing something dumb or dangerous here?"

## Before you start

Install Wicklight (Python 3.10+). Everything through chapter 6 runs **offline on
the fake provider** — no API key, no network, no cost. Chapter 7 adds Docker.

```bash
pip install wicklight          # or: uv tool install wicklight
wicklight --version            # 0.1.0
```

Make a project folder to work in:

```bash
mkdir meal-planner && cd meal-planner
```

You'll create a handful of small files here as you go: an agent file, a tools
module, some data, and a runner script. The finished versions all live in the
Wicklight repo under [`examples/tutorial/`](https://github.com/wicklight-agents/wicklight/tree/main/examples/tutorial)
if you want to compare.

Ready? Start with **[Chapter 1: Suggest meals](1-suggest-meals.md)**.
