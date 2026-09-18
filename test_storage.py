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

from storage import TimeTrackerStorage

def main():
    print("Testing connection to Azure Table Storage...")
    try:
        storage = TimeTrackerStorage()
        print("Connected to Azure Table Storage successfully!")
        
        # Test listing targets
        targets = storage.list_targets()
        print(f"Current targets count: {len(targets)}")
        for t in targets:
            print(f" - {t['name']} (Total: {t['total_minutes']} mins / {round(t['total_minutes']/60, 2)} hrs)")
        
        print("\nAll checks passed! Tables are ready.")
    except Exception as ex:
        print(f"Error connecting to Azure Table Storage: {ex}")

if __name__ == "__main__":
    main()

