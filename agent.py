import json
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

from storage import TimeTrackerStorage
from purchase_client import PurchaseCalcClient

# Load environment variables
env_paths = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]
for p in env_paths:
    if p.exists():
        load_dotenv(dotenv_path=p)
        break
load_dotenv()

# Setup Azure OpenAI
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4.1-mini")

if not endpoint or not api_key:
    raise ValueError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set in .env")

client = OpenAI(
    base_url=endpoint,
    api_key=api_key
)

# Initialize Storage & Purchase-Calc Client
storage = TimeTrackerStorage()
pcalc = PurchaseCalcClient()

# Define tools for OpenAI function calling
TOOLS = [
    # ---------------- Azure Table Storage Tools ----------------
    {
        "type": "function",
        "function": {
            "name": "list_targets",
            "description": "List all existing targets/projects in Azure Table Storage that time can be logged against.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_target",
            "description": "Create a new target/project category in Azure Table Storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "The name of the new target (e.g. 'Thing X', 'Client Project A', 'Website Design')."
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional brief description of what this target represents."
                    }
                },
                "required": ["target_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_time",
            "description": "Log minutes spent on a specific target into Azure Table Storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "The name of the target/project."
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Number of minutes to log (e.g. 30, 45, 90)."
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes or description of what was done during this time."
                    }
                },
                "required": ["target_name", "minutes"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": "Get a summary of logged hours/minutes from Azure Table Storage, either overall or for a specific target.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_name": {
                        "type": "string",
                        "description": "Optional target name to get summary for. If omitted, returns summary for all targets."
                    }
                },
                "required": []
            }
        }
    },

    # ---------------- Purchase Calc (GCP Cloud Run) Tools ----------------
    {
        "type": "function",
        "function": {
            "name": "get_spending_summary",
            "description": "Query and summarize expenses from purchase-calc on Cloud Run between start_date and end_date (YYYY-MM-DD). Returns total spent, transaction count, and breakdown by merchant/location.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in format YYYY-MM-DD (e.g. '2026-01-01')."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date in format YYYY-MM-DD (e.g. '2026-12-31')."
                    },
                    "location": {
                        "type": "string",
                        "description": "Optional merchant or location filter (e.g. 'S-market', 'Hesburger')."
                    }
                },
                "required": ["start_date", "end_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_spending",
            "description": "Record a new expense/spending entry in purchase-calc on Cloud Run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sum": {
                        "type": "number",
                        "description": "The expense amount in EUR (e.g. 14.50)."
                    },
                    "location": {
                        "type": "string",
                        "description": "Merchant or location name (e.g. 'Prisma', 'Ravintola Hang Out')."
                    },
                    "payment_type": {
                        "type": "string",
                        "description": "Optional payment method (e.g. 'Amex', 'Debit', 'Cash')."
                    },
                    "date": {
                        "type": "string",
                        "description": "Optional date of purchase in YYYY-MM-DD format. Defaults to today."
                    }
                },
                "required": ["sum", "location"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "List tasks and todos from purchase-calc on Cloud Run. Can filter by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["all", "pending", "completed"],
                        "description": "Filter todos by status: 'pending' (open tasks), 'completed', or 'all'. Defaults to 'all'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Create a new task or todo in purchase-calc on Cloud Run.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task description (e.g. 'Pay energy bill', 'Refactor API client')."
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Optional due date in YYYY-MM-DD format. Defaults to today."
                    }
                },
                "required": ["task"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "toggle_todo",
            "description": "Toggle or complete a task in purchase-calc on Cloud Run by its ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "The numeric ID of the todo item to toggle/complete."
                    }
                },
                "required": ["todo_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_purchases",
            "description": "Fetch purchase records from purchase-calc on Cloud Run with optional date and origin filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Optional start date in YYYY-MM-DD format."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Optional end date in YYYY-MM-DD format."
                    },
                    "origin": {
                        "type": "string",
                        "description": "Optional origin filter."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "log_time_on_todo",
            "description": "Log time spent on a purchase-calc todo task into Azure Table Storage, and optionally mark the task complete in purchase-calc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "The numeric ID of the todo task in purchase-calc."
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Number of minutes spent working on this task."
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes on what was accomplished."
                    },
                    "mark_completed": {
                        "type": "boolean",
                        "description": "Whether to mark the todo as completed in purchase-calc (default: false)."
                    }
                },
                "required": ["todo_id", "minutes"]
            }
        }
    },

    # ---------------- Location & Google Timeline Tools ----------------
    {
        "type": "function",
        "function": {
            "name": "get_places_visited",
            "description": "Retrieve the places and locations the user visited on a specific day or date range (from Google Timeline and purchase-calc). Returns place names, addresses, arrival/departure times, and durations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start_date": {
                        "type": "string",
                        "description": "Start date in format YYYY-MM-DD (e.g. '2026-01-23')."
                    },
                    "end_date": {
                        "type": "string",
                        "description": "Optional end date in format YYYY-MM-DD (defaults to start_date for a single day query)."
                    }
                },
                "required": ["start_date"]
            }
        }
    }
]


def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Executes the Python backend functions triggered by the agent."""
    # ---------------- Azure Storage Tools ----------------
    if tool_name == "list_targets":
        targets = storage.list_targets()
        return json.dumps({"targets": targets})

    elif tool_name == "create_target":
        res = storage.create_target(
            target_name=arguments.get("target_name"),
            description=arguments.get("description", "")
        )
        return json.dumps(res)

    elif tool_name == "log_time":
        res = storage.log_time(
            target_name=arguments.get("target_name"),
            minutes=arguments.get("minutes"),
            notes=arguments.get("notes", "")
        )
        return json.dumps(res)

    elif tool_name == "get_summary":
        res = storage.get_summary(target_name=arguments.get("target_name"))
        return json.dumps(res)

    # ---------------- Purchase Calc Cloud Run Tools ----------------
    elif tool_name == "get_spending_summary":
        res = pcalc.get_spending_summary(
            start_date=arguments.get("start_date"),
            end_date=arguments.get("end_date"),
            location=arguments.get("location")
        )
        return json.dumps(res)

    elif tool_name == "add_spending":
        res = pcalc.add_spending(
            sum_amount=arguments.get("sum"),
            location=arguments.get("location"),
            payment_type=arguments.get("payment_type"),
            date=arguments.get("date")
        )
        return json.dumps(res)

    elif tool_name == "list_todos":
        res = pcalc.list_todos(status=arguments.get("status", "all"))
        return json.dumps(res)

    elif tool_name == "create_todo":
        res = pcalc.create_todo(
            task=arguments.get("task"),
            due_date=arguments.get("due_date")
        )
        return json.dumps(res)

    elif tool_name == "toggle_todo":
        res = pcalc.toggle_todo(todo_id=arguments.get("todo_id"))
        return json.dumps(res)

    elif tool_name == "get_purchases":
        res = pcalc.get_purchases(
            start_date=arguments.get("start_date"),
            end_date=arguments.get("end_date"),
            origin=arguments.get("origin")
        )
        return json.dumps(res)

    elif tool_name == "log_time_on_todo":
        todo_id = arguments.get("todo_id")
        minutes = arguments.get("minutes")
        notes = arguments.get("notes", "")
        mark_completed = arguments.get("mark_completed", False)

        # Look up todo task name
        todos = pcalc.list_todos()
        matched = next((t for t in todos if isinstance(t, dict) and t.get("id") == todo_id), None)
        task_name = matched.get("task") if matched else f"Task #{todo_id}"

        # Ensure target exists and log time in Azure Table Storage
        storage.create_target(task_name, description=f"Imported from purchase-calc todo #{todo_id}")
        time_res = storage.log_time(target_name=task_name, minutes=minutes, notes=notes)

        # Toggle todo if requested and not already completed
        todo_res = None
        if mark_completed and matched and not matched.get("isCompleted"):
            todo_res = pcalc.toggle_todo(todo_id)

        return json.dumps({
            "status": "success",
            "time_tracking": time_res,
            "todo_updated": todo_res if todo_res else ("Already completed" if matched and matched.get("isCompleted") else "Unchanged")
        })

    # ---------------- Location & Google Timeline Tools ----------------
    elif tool_name == "get_places_visited":
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date") or start_date

        # 1. Fetch from Azure Table Storage (Google Timeline imports)
        timeline_visits = storage.get_timeline_visits(start_date=start_date, end_date=end_date)

        # 2. Fetch from purchase-calc Cloud Run
        pcalc_visits = pcalc.get_visits(start_date=start_date, end_date=end_date)

        # Merge and deduplicate
        combined = []
        seen_keys = set()

        for v in timeline_visits:
            key = (v.get("date"), (v.get("place_name") or "").lower(), v.get("time"))
            if key not in seen_keys:
                seen_keys.add(key)
                combined.append(v)

        for v in pcalc_visits:
            key = (v.get("date"), (v.get("place_name") or "").lower(), v.get("time"))
            if key not in seen_keys:
                seen_keys.add(key)
                combined.append(v)

        # Sort chronologically by date and time
        combined.sort(key=lambda x: (x.get("date", ""), x.get("time", "")))

        return json.dumps({
            "start_date": start_date,
            "end_date": end_date,
            "total_visits": len(combined),
            "visits": combined
        })

    return json.dumps({"error": f"Unknown function {tool_name}"})


SYSTEM_PROMPT = """You are an intelligent AI Assistant with multi-domain capabilities:
1. Time Tracking: Logging minutes/hours against project targets (persisted in Azure Table Storage).
2. Personal Finance & Tasks (Purchase Calc): Managing expenses, spending breakdowns, purchases, and todos (hosted 24/7 on Google Cloud Run at pc.lightsaber.biz).
3. Location & Timeline History: Answering queries about visited places, locations, arrival/departure times, and durations (from Google Timeline and purchase-calc).

CONVERSATIONAL RULES:
1. Time Tracking (Azure Table Storage):
   - When the user mentions spending time on work/projects (e.g., "45 minutes", "1.5 hours", "spent 30 min"):
     - If no target specified: call `list_targets`, present existing options, and ask which target or offer to create a new one.
     - If target specified: ensure target exists (via `create_target`), then call `log_time`.
   - If user asks for time summary/reports: call `get_summary`.
   - If user worked on a specific task/todo from purchase-calc: call `log_time_on_todo` to log time in Azure and optionally mark the task completed.

2. Personal Finance & Expenses (Purchase Calc on Cloud Run):
   - When the user asks about spending or expenses (e.g. "How much did I spend this month?", "Show expenses at S-market"):
     - Calculate appropriate start_date and end_date based on current date and user intent (e.g., current month, current year).
     - Call `get_spending_summary` (and filter by location if requested).
     - Present totals and breakdown clearly in EUR (€).
   - When the user wants to log an expense (e.g. "Spent 12.50 at Hesburger"):
     - Call `add_spending` with the sum and location.

3. Tasks & Todos (Purchase Calc on Cloud Run):
   - When the user asks to see tasks/todos: call `list_todos` (use status='pending' if they ask for open/uncompleted tasks).
   - When user wants to add a task: call `create_todo`.
   - When user completes a task: call `toggle_todo`.

4. Location & Timeline History (Google Timeline & Purchase-Calc):
   - When the user asks where they were, which places they visited, or whether they visited a specific store/restaurant (e.g. "Where was I on Jan 23rd?", "Which places did I visit last week?", "Did I go to Fressi?"):
     - Call `get_places_visited` with start_date and end_date.
     - Present the visits chronologically with times (e.g. arrival/departure), place names, addresses, and durations if available.
     - If the user was working at a location and wants to log time, offer or proceed to log project time in Azure Table Storage.

Keep answers friendly, concise, and helpful. Format money amounts in EUR (€) and durations clearly in minutes and hours.
"""


def chat():
    print("=" * 65)
    print(" AI Assistant: Azure Time Tracking & Purchase-Calc (Cloud Run)")
    print(" Type 'quit' or 'exit' to end the session.")
    print("=" * 65)

    today_str = datetime.now().strftime("%Y-%m-%d")
    system_content = f"{SYSTEM_PROMPT}\nToday's date is: {today_str}\n"

    messages = [
        {"role": "system", "content": system_content}
    ]

    while True:
        try:
            user_input = input("\nYou: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

            messages.append({"role": "user", "content": user_input})

            # Process with model and handle tool calls
            while True:
                response = client.chat.completions.create(
                    model=deployment_name,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto"
                )

                response_message = response.choices[0].message
                tool_calls = response_message.tool_calls

                # If the model wants to call tools
                if tool_calls:
                    messages.append(response_message)
                    for tool_call in tool_calls:
                        func_name = tool_call.function.name
                        try:
                            func_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            func_args = {}

                        # Execute tool
                        tool_result = execute_tool_call(func_name, func_args)

                        # Provide tool result back to the model
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result
                        })
                else:
                    # Final assistant message
                    assistant_reply = response_message.content
                    print(f"\nAgent: {assistant_reply}")
                    messages.append({"role": "assistant", "content": assistant_reply})
                    break

        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as ex:
            print(f"\n[Error]: {ex}")


if __name__ == "__main__":
    chat()
