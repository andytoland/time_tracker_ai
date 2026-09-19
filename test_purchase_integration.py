import json
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env
env_paths = [
    Path(__file__).resolve().parent / ".env",
    Path(__file__).resolve().parent.parent / ".env",
]
for p in env_paths:
    if p.exists():
        load_dotenv(dotenv_path=p)
        break
load_dotenv()

from purchase_client import PurchaseCalcClient

def main():
    print("=" * 60)
    print(" Testing Connection to Purchase Calc on Cloud Run")
    print(f" URL: {os.getenv('PURCHASE_CALC_API_URL', 'https://pc.lightsaber.biz')}")
    print("=" * 60)

    client = PurchaseCalcClient()

    # 1. Test fetching Todos
    print("\n1. Fetching Todos (/todo)...")
    todos = client.list_todos()
    print(f"Result: {len(todos)} items received.")
    if isinstance(todos, list) and todos:
        for t in todos[:5]:
            if "error" in t:
                print(f"  [Error]: {t['error']}")
            else:
                status = "Done" if t.get("isCompleted") else "Open"
                print(f"  - [{status}] #{t.get('id')}: {t.get('task')} (Due: {t.get('dueDate')})")
    elif isinstance(todos, list):
        print("  No todos currently found in database.")

    # 2. Test fetching Spending
    print("\n2. Fetching Recent Spending (/spending/list)...")
    spending_summary = client.get_spending_summary("2026-01-01", "2026-12-31")
    if "error" in spending_summary:
        print(f"  [Error]: {spending_summary['error']}")
    else:
        print(f"  Total Spending (2026): {spending_summary.get('total_spending')} EUR")
        print(f"  Transactions count: {spending_summary.get('transaction_count')}")
        print(f"  Top Locations: {list(spending_summary.get('by_location', {}).keys())[:5]}")

    print("\n" + "=" * 60)
    print(" Cloud Run API Test Complete")
    print("=" * 60)

if __name__ == "__main__":
    main()

