# Cline MCP Server Setup Guide

This guide explains how to connect your **Azure Time Tracker & Personal Assistant** to **Cline** (the autonomous coding extension for VS Code) using the **Model Context Protocol (MCP)**.

With this integration, Cline can:
- Automatically **start and stop timers** on projects while you code (e.g., using Mistral Codestral, GPT-4o, or Claude).
- Query and summarize **financial data & expenses** (via Purchase-Calc on Cloud Run).
- Manage **Todos & Tasks**, and log time directly against them.
- Look up **location history** from Google Timeline.

---

## 1. How to Access Cline MCP Settings

Cline stores its MCP configuration in a JSON file called `cline_mcp_settings.json`.

You can access it in two ways:
1. **Via the VS Code UI**:
   - In the Cline sidebar panel, click the **MCP Servers** tab (or the server icon).
   - Click the gear/settings icon or "Configure MCP Servers" to open `cline_mcp_settings.json`.
2. **Direct File Path**:
   - **Windows**:
     `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`
     *(Expanded: `C:\Users\<Username>\AppData\Roaming\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`)*
   - **macOS**:
     `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`
   - **Linux**:
     `~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json`

---

## 2. Configuration (`cline_mcp_settings.json`)

### Windows Configuration (Already applied to your local system)

```json
{
  "mcpServers": {
    "azure-time-tracker": {
      "command": "C:/Users/antti/Kehitys/oma/AI/.venv/Scripts/python.exe",
      "args": [
        "C:/Users/antti/Kehitys/oma/AI/time_tracker/mcp_server.py"
      ],
      "cwd": "C:/Users/antti/Kehitys/oma/AI/time_tracker",
      "disabled": false,
      "autoApprove": [
        "start_activity_timer",
        "stop_activity_timer",
        "get_active_timer",
        "cancel_activity_timer",
        "log_work_time",
        "list_tracked_targets",
        "create_tracked_target",
        "get_time_summary",
        "get_spending_summary",
        "add_spending",
        "get_purchases",
        "list_todos",
        "create_todo",
        "toggle_todo",
        "log_time_on_todo",
        "get_places_visited"
      ]
    }
  }
}
```

### macOS / Linux Configuration Template

For macOS or Linux machines, adjust the Python virtual environment path and project path:

```json
{
  "mcpServers": {
    "azure-time-tracker": {
      "command": "/path/to/your/project/.venv/bin/python",
      "args": [
        "/path/to/your/project/time_tracker/mcp_server.py"
      ],
      "cwd": "/path/to/your/project/time_tracker",
      "disabled": false,
      "autoApprove": [
        "start_activity_timer",
        "stop_activity_timer",
        "get_active_timer",
        "cancel_activity_timer",
        "log_work_time",
        "list_tracked_targets",
        "create_tracked_target",
        "get_time_summary",
        "get_spending_summary",
        "add_spending",
        "get_purchases",
        "list_todos",
        "create_todo",
        "toggle_todo",
        "log_time_on_todo",
        "get_places_visited"
      ]
    }
  }
}
```

> **Tip on `autoApprove`:** Adding tool names to the `autoApprove` list allows Cline to invoke these tools seamlessly without prompting you with a popup button each time. If you prefer to manually approve certain actions (like `add_spending` or `log_work_time`), simply remove them from the `autoApprove` list.

---

## 3. Configuring Coding Models in Cline

Cline lets you pair these MCP tools with any leading coding model. Open **Cline Settings** (the gear icon at the top of the panel):

### Option A: Mistral AI (Codestral)
1. **API Provider**: Select `Mistral AI` (or `OpenRouter`).
2. **API Key**: Enter your Mistral API key (obtain from [console.mistral.ai](https://console.mistral.ai)).
3. **Model**: Select `codestral-latest` (specifically optimized for code generation and multi-step agent workflows).

### Option B: OpenAI (GPT-4o / o3-mini)
1. **API Provider**: Select `OpenAI` or `OpenAI Compatible`.
2. **API Key**: Enter your OpenAI API key.
3. **Model**: Select `gpt-4o` or `o3-mini`.

### Option C: Azure OpenAI Service
1. **API Provider**: Select `Azure OpenAI`.
2. **Base URL**: Your Azure OpenAI endpoint URL.
3. **API Key**: Your Azure OpenAI resource key.
4. **Deployment Name**: e.g., `gpt-4.1-mini` or `gpt-4o`.

### Option D: Local Models via Ollama
1. Run a coding model locally: `ollama run qwen2.5-coder:32b` or `ollama run codestral`
2. **API Provider**: Select `Ollama`.
3. **Base URL**: `http://localhost:11434`
4. **Model**: `qwen2.5-coder:32b` or `codestral:22b`.

---

## 4. Configuring in Antigravity (Google DeepMind in VS Code)

Antigravity natively reads MCP configurations from:
`C:\Users\<Username>\.gemini\config\mcp_config.json`

The following configuration is already saved on your system:

```json
{
  "mcpServers": {
    "azure-time-tracker": {
      "command": "C:/Users/antti/Kehitys/oma/AI/.venv/Scripts/python.exe",
      "args": [
        "C:/Users/antti/Kehitys/oma/AI/time_tracker/mcp_server.py"
      ],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

Once loaded, Antigravity has direct access to all 16 tools in any conversation!

---

## 5. Available MCP Tools Reference

| Category | Tool Name | Description |
| :--- | :--- | :--- |
| **Live Timing** | `start_activity_timer` | Starts live meter for an activity (persisted in `ActiveTimers`). |
| | `stop_activity_timer` | Stops timer, computes duration, logs to `TimeLogs`, updates `TimeTargets`. |
| | `get_active_timer` | Checks currently active running timer and elapsed minutes. |
| | `cancel_activity_timer` | Discards current timer without saving. |
| **Time Tracking** | `log_work_time` | Manually records minutes against a target in Azure Table Storage. |
| | `list_tracked_targets` | Lists all registered targets and total hours/minutes. |
| | `create_tracked_target` | Creates a new project category in Azure Table Storage. |
| | `get_time_summary` | Detailed report overall or per project target. |
| **Finance (Purchase-Calc)** | `get_spending_summary` | Summary of expenses, totals in EUR, transaction counts, and merchant breakdown. |
| | `add_spending` | Records a new expense in EUR with merchant and payment type. |
| | `get_purchases` | Queries raw purchase transactions with date and origin filters. |
| **Tasks & Todos** | `list_todos` | Lists tasks from purchase-calc (`pending`, `completed`, or `all`). |
| | `create_todo` | Creates a new task or reminder. |
| | `toggle_todo` | Marks a task completed or toggles status. |
| | `log_time_on_todo` | Records time against a todo and optionally marks it complete. |
| **Location** | `get_places_visited` | Queries whereabouts and visited places from Google Timeline. |

---

## 6. Real-World Prompts to Use with Cline & Antigravity

Once configured, you can ask Cline or Antigravity anything:

### While Coding:
> *"I'm going to start refactoring the authentication module. Start tracking time on 'Auth Refactor'."*

> *"How long have I been working on the current task?"*

> *"I'm done with the refactor and tests pass. Stop the timer and commit the changes."*

### For Finances:
> *"How much have I spent on groceries this month?"*

> *"Log an expense of 18.50 EUR at S-market today."*

### For Tasks:
> *"What pending tasks do I have in purchase-calc?"*

> *"Log 45 minutes on task #3 and mark it as completed."*

