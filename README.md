# Azure Time Tracker & Purchase-Calc AI Agent

An intelligent, conversational AI assistant that logs time spent on projects and integrates with **Purchase-Calc** (hosted 24/7 on **Google Cloud Run**). It logs time in natural language into **Azure Table Storage**, queries expenses, summarizes merchant spending, and manages tasks/todos.

---

## Architecture & How It Works

```mermaid
flowchart LR
    subgraph Local["Local Machine"]
        User(["User (Terminal)"]) <--> Agent["agent.py\n(Python Script)"]
    end

    subgraph Azure["Microsoft Azure Cloud"]
        subgraph OpenAI["Azure OpenAI Service"]
            Model["gpt-4.1-mini\n(Tool Calling)"]
        end
        subgraph Storage["Azure Storage Account (Standard_LRS)"]
            T1[("TimeTargets Table")]
            T2[("TimeLogs Table")]
            T3[("ActiveTimers Table")]
        end
    end

    subgraph GCP["Google Cloud Platform (24/7)"]
        CloudRun["Cloud Run API: pc.lightsaber.biz\n(NestJS REST API)"]
        Postgres[("Cloud SQL PostgreSQL\n(purchases DB)")]
        CloudRun <--> Postgres
    end

    Agent <-->|"Natural Language & Tools"| Model
    Agent <-->|"Save / Query Logs"| Storage
    Agent <-->|"HTTPS + JWT Bearer Auth"| CloudRun
```

1. **Conversational Interface**: You chat with `agent.py` in natural language.
2. **Azure OpenAI Model**: Interprets intent and triggers backend functions/tools:
   - **Live Activity Metering & Time Tracking (Azure Table Storage)**:
     - `start_timer`: Starts live metering for an activity (e.g. `"started Project X"`), saved in `ActiveTimers`.
     - `stop_timer`: Stops the timer, computes elapsed duration, logs it to `TimeLogs`, and updates `TimeTargets` (e.g. `"end"`, `"stop"`).
     - `get_active_timer`: Checks currently running timer and elapsed duration (e.g. `"status"`).
     - `cancel_timer`: Discards active timer without logging.
     - `list_targets`, `create_target`, `log_time`, `get_summary`: Traditional manual time logging and project queries.
   - **Personal Finance & Tasks (GCP Cloud Run)**: `get_spending_summary`, `add_spending`, `list_todos`, `create_todo`, `toggle_todo`, `get_purchases`.
   - **Location & Google Timeline (Azure Tables & Cloud Run)**: `get_places_visited` (whereabouts, visited places, durations, addresses).
   - **Cross-Service Synergy**: `log_time_on_todo` (logs time in Azure against a purchase-calc task and optionally completes it on Cloud Run).

---

## Requirements

### 1. Does it need a model deployed on Azure?
**Yes.** 
The agent uses an Azure OpenAI chat model with **function calling (tool use)**:
- **Recommended Model**: `gpt-4.1-mini` or `gpt-4o-mini`.
- **Can it be created with Bicep?** **Yes!** You can deploy it using [`../infra/openai.bicep`](../infra/openai.bicep) or together with storage using [`../infra/main.bicep`](../infra/main.bicep).

### 2. Cloud Resources Required
| Resource | Provider | Purpose | Estimated Cost |
| :--- | :--- | :--- | :--- |
| **Azure Storage Account** | Azure | Stores `TimeTargets` and `TimeLogs` | **< $0.01 / month** (~$0.045/GB/month) |
| **Azure OpenAI Service** | Azure | AI agent reasoning and tool calling | **Pay-as-you-go** (fractions of a cent) |
| **Purchase-Calc API** | GCP Cloud Run | REST API for spending, budgets, todos | **24/7 Serverless** (free tier / minimal) |

---

## Installation & Setup

### 1. Create and Enter (Activate) Python Virtual Environment

Using a virtual environment keeps your project dependencies isolated from global Python packages.

#### Step A: Create the Virtual Environment (First Time Only)
Run this from your project or repository root:

```powershell
# Using Python
python -m venv .venv

# On Windows, if python is not in PATH, you can also use the Python launcher:
py -m venv .venv
```

#### Step B: Enter (Activate) the Virtual Environment
Run the activation script corresponding to your terminal and operating system:

- **Windows PowerShell:**
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
  > **PowerShell Execution Policy Note:** If you encounter an error stating that `running scripts is disabled on this system`, allow script execution for the current session:
  > ```powershell
  > Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
  > .\.venv\Scripts\Activate.ps1
  > ```

- **Windows Command Prompt (cmd.exe):**
  ```cmd
  .\.venv\Scripts\activate.bat
  ```

- **Linux / macOS / WSL (Bash or Zsh):**
  ```bash
  source .venv/bin/activate
  ```

Once activated, your terminal prompt will be prefixed with `(.venv)`.

#### Step C: Leave (Deactivate) the Virtual Environment
When you are done and want to return to your global Python environment, run:
```powershell
deactivate
```

### 2. Install Python Dependencies
With your virtual environment activated `(.venv)`, install the required packages:

```powershell
# Upgrade pip (optional but recommended)
python -m pip install --upgrade pip

# Install requirements
pip install -r requirements.txt
```

*(Packages used: `azure-data-tables`, `openai`, `python-dotenv`, `azure-identity`, `httpx`, `pyjwt`)*

### 3. Configure Environment Variables (`.env`)
Create or edit your `.env` file in the project root:

```env
# Azure OpenAI Service Configuration
AZURE_OPENAI_ENDPOINT="https://<your-openai-resource>.services.ai.azure.com/openai/v1"
AZURE_OPENAI_API_KEY="<your-azure-openai-api-key>"
AZURE_OPENAI_DEPLOYMENT_NAME="gpt-4.1-mini"

# Azure Storage Account Configuration
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=<storage-account-name>;AccountKey=<key>;EndpointSuffix=core.windows.net"

# GCP Cloud Run Purchase-Calc Backend Configuration
PURCHASE_CALC_API_URL="https://pc.lightsaber.biz"
PURCHASE_CALC_BEARER_TOKEN="<your-jwt-bearer-token>"
PURCHASE_CALC_JWT_SECRET="<your-jwt-secret>"
PURCHASE_CALC_USER_EMAIL="antti.tolamo@gmail.com"
```

---

## Usage Guide

### 1. Test Storage & Cloud Run Connectivity
Run the test scripts:
```powershell
# Check Azure Table Storage
python test_storage.py

# Check GCP Cloud Run Purchase-Calc REST API
python test_purchase_integration.py
```

### 2. Start the Agent
Launch the interactive assistant:
```powershell
python agent.py
```

### 3. Example Conversations

#### Scenario A: Live Activity Metering ("started X" and "end")
```text
You: started Website Redesign
Agent: Started timer for Website Redesign! Just say "end" when you finish.

You: status
Agent: You have an active timer running for Website Redesign (started 25.0 minutes ago).

You: end
Agent: Stopped timer for Website Redesign. Elapsed time: 25 minutes (0.42 hours). Successfully logged to Azure Table Storage! New total on Website Redesign is 1.25 hours.
```

#### Scenario B: Log time without a target (Manual entry)
```text
You: 45 minutes
Agent: Great! What was this for? Here are your current targets:
1. Thing X
2. Website Redesign
Which of these was this for? Or if none of these fit, you can give me a new target name to create.
```

#### Scenario C: Query spending from Purchase-Calc
```text
You: How much did I spend this month?
Agent: In March 2026, you had 32 transactions totaling 482.15 EUR:
- S-market: 215.40 EUR
- Ravintola Hang Out: 84.50 EUR
- Hesburger: 32.20 EUR
- Other locations: 150.05 EUR
```

#### Scenario D: View and manage Todos
```text
You: What tasks do I have pending?
Agent: Here are your open tasks from Purchase-Calc:
1. #4: Tarkista omaposti onko energia lasku maksettu (Due: 2026-06-02)
```

#### Scenario E: Log time on a Todo and mark it done
```text
You: I spent 30 minutes on task #4 and finished it
Agent: Done!
- Logged 30 minutes on "Tarkista omaposti onko energia lasku maksettu" in Azure Table Storage.
- Marked task #4 as completed in Purchase-Calc.
```

#### Scenario F: View time tracking summary
```text
You: show time summary
Agent: Here is your logged time summary from Azure Table Storage:
- Thing X: 75 minutes (1.25 hours)
- Tarkista omaposti onko energia lasku maksettu: 30 minutes (0.50 hours)
Total time logged: 105 minutes across 2 targets.
```

#### Scenario G: Query visited places & whereabouts (Google Timeline)
```text
You: Where was I on January 23rd, 2026?
Agent: On Friday, January 23rd, 2026, you visited:
1. MorriSon's (10:52 AM)
2. Kodan (12:48 PM)
3. Ravintola Hang Out (Mustalahdentie 10) from 16:45 to 18:45 (2 hours)
```

---

## Model Context Protocol (MCP) & Cline Integration

The agent's capabilities are exposed as an **MCP Server** (`mcp_server.py`), allowing autonomous coding agents like **Cline** in VS Code to:
- Automatically **start and stop timers** while coding using models like **Mistral Codestral**, **GPT-4o**, or **Claude 3.5 Sonnet**.
- Query **financial data & expenses** directly inside VS Code.
- Manage and complete **todos & tasks** from Purchase-Calc.

### Quick Start with Cline
1. The server is configured in your Cline settings (`cline_mcp_settings.json`).
2. Test the MCP server:
   ```powershell
   python test_mcp_server.py
   ```
3. Read the complete cross-platform setup guide in [`docs/CLINE_MCP_SETUP.md`](./docs/CLINE_MCP_SETUP.md).

---

## File Structure

```text
time_tracker_ai/
├── agent.py                      # Conversational agent (Azure OpenAI + multi-domain tools)
├── mcp_server.py                 # Model Context Protocol (MCP) Server for Cline / VS Code
├── storage.py                    # Azure Table Storage client (TimeTargets, TimeLogs, TimelineVisits, ActiveTimers)
├── purchase_client.py            # GCP Cloud Run REST API client (JWT Auth + HTTPS)
├── import_timeline.py            # Google Timeline Takeout ingestion CLI
├── test_storage.py               # Storage connectivity check
├── test_mcp_server.py            # MCP server & tool registration verification
├── test_purchase_integration.py  # Cloud Run API connectivity check
├── docs/
│   ├── CLINE_MCP_SETUP.md        # Comprehensive Cline MCP setup guide (Windows, macOS, Linux)
│   └── GOOGLE_TIMELINE_INTEGRATION.md # Detailed Google Timeline export & ingestion guide
├── .env                          # API keys, connection strings, Cloud Run URL
├── requirements.txt              # Python dependencies
└── README.md                     # Documentation
```

