import json
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

from storage import TimeTrackerStorage

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

# Initialize Azure Table Storage
storage = TimeTrackerStorage()

# Define tools for OpenAI function calling
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_targets",
            "description": "List all existing targets/projects that time can be logged against.",
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
            "description": "Create a new target/project category.",
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
            "description": "Log minutes spent on a specific target.",
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
            "description": "Get a summary of logged hours/minutes, either overall or for a specific target.",
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
    }
]


def execute_tool_call(tool_name: str, arguments: dict) -> str:
    """Executes the Python backend functions triggered by the agent."""
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

    return json.dumps({"error": f"Unknown function {tool_name}"})


SYSTEM_PROMPT = """You are an intelligent Azure Time Tracking Assistant.
Your job is to help the user log their time (minutes/hours) against specific targets or projects, and report their logged time. All data is securely stored in Azure Table Storage.

CONVERSATIONAL RULES:
1. When the user mentions spending time (e.g., "45 minutes", "1.5 hours", "spent 30 min"):
   - If they did NOT specify what target it was for:
     a) Call `list_targets` to retrieve existing targets.
     b) If targets exist, present them clearly as a numbered list of ready options.
     c) Prompt the user: Ask which target this was for, or offer that they can create a new target if none of the options are suitable.
   - If they DID specify a target (e.g. "I spent 45 minutes on Thing X"):
     a) Check if "Thing X" exists in `list_targets`.
     b) If it doesn't exist, create it with `create_target`.
     c) Log the time using `log_time`.
     d) Clearly confirm the entry (minutes logged and new total hours for that target).
2. If the user picks an option by number or name, or supplies a new target name:
   - Call `create_target` if new, then `log_time`.
   - Confirm the time logged and show the updated total.
3. If the user asks for a summary, report, or status ("how many hours", "show summary"):
   - Call `get_summary` and present a clean, concise breakdown of hours and minutes.
4. Keep answers friendly, concise, and helpful.
"""


def chat():
    print("=" * 60)
    print(" Azure Time Tracker Agent (Powered by Azure Table Storage)")
    print(" Type 'quit' or 'exit' to end the session.")
    print("=" * 60)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
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

