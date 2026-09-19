import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Try importing httpx if available, otherwise fall back to urllib
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


def generate_jwt_token(secret: str, email: str = "antti.tolamo@gmail.com", sub: str = "agent-token") -> str:
    """Generate a valid HS256 JWT bearer token for purchase-calc using Python standard library."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub,
        "email": email,
        "iat": int(time.time()),
        # 30 day expiration
        "exp": int(time.time()) + (30 * 24 * 60 * 60)
    }

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    h_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    p_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    h_b64 = b64url(h_bytes)
    p_b64 = b64url(p_bytes)

    signing_input = f"{h_b64}.{p_b64}".encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = b64url(signature)

    return f"{h_b64}.{p_b64}.{sig_b64}"


class PurchaseCalcClient:
    """Client for interacting with the purchase-calc REST API deployed on GCP Cloud Run."""

    def __init__(
        self,
        base_url: str = None,
        token: str = None,
        jwt_secret: str = None,
        user_email: str = None
    ):
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

        self.base_url = (base_url or os.getenv("PURCHASE_CALC_API_URL", "https://pc.lightsaber.biz")).rstrip("/")
        self.static_token = token or os.getenv("PURCHASE_CALC_BEARER_TOKEN")
        self.jwt_secret = jwt_secret or os.getenv("PURCHASE_CALC_JWT_SECRET")
        self.user_email = user_email or os.getenv("PURCHASE_CALC_USER_EMAIL", "antti.tolamo@gmail.com")

    def _get_token(self) -> str:
        """Returns the configured token or dynamically generates a fresh JWT."""
        if self.static_token:
            # Strip any extraneous chat prefix if present
            clean_token = self.static_token.strip()
            if "]" in clean_token and "eyJ" in clean_token:
                clean_token = clean_token[clean_token.find("eyJ"):]
            return clean_token

        if self.jwt_secret:
            return generate_jwt_token(secret=self.jwt_secret, email=self.user_email)

        raise ValueError("Neither PURCHASE_CALC_BEARER_TOKEN nor PURCHASE_CALC_JWT_SECRET is configured.")

    def _request(self, method: str, path: str, params: dict = None, json_body: dict = None, timeout: float = 15.0) -> dict | list:
        url = f"{self.base_url}/{path.lstrip('/')}"
        token = self._get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "TimeTrackerAI-Agent/1.0"
        }

        if HTTPX_AVAILABLE:
            with httpx.Client(timeout=timeout) as client:
                resp = client.request(method=method, url=url, params=params, json=json_body, headers=headers)
                resp.raise_for_status()
                if resp.status_code == 204 or not resp.content:
                    return {"success": True}
                return resp.json()
        else:
            # Fallback to urllib.request
            if params:
                query_string = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
                url = f"{url}?{query_string}"

            data = json.dumps(json_body).encode("utf-8") if json_body is not None else None
            req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode("utf-8")
                if not content:
                    return {"success": True}
                return json.loads(content)

    # -------------------------------------------------------------------------
    # Todo Endpoints
    # -------------------------------------------------------------------------

    def list_todos(self, status: str = "all") -> list[dict]:
        """Fetch todos. Status filter can be 'all', 'pending', or 'completed'."""
        try:
            todos = self._request("GET", "/todo")
            if not isinstance(todos, list):
                return []

            if status == "pending":
                return [t for t in todos if not t.get("isCompleted", False)]
            elif status == "completed":
                return [t for t in todos if t.get("isCompleted", False)]
            return todos
        except Exception as ex:
            return [{"error": f"Failed to list todos: {ex}"}]

    def create_todo(self, task: str, due_date: str = None) -> dict:
        """Create a new task in purchase-calc."""
        if not due_date:
            due_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            return self._request("POST", "/todo", json_body={"task": task, "dueDate": due_date})
        except Exception as ex:
            return {"error": f"Failed to create todo: {ex}"}

    def toggle_todo(self, todo_id: int) -> dict:
        """Toggle completed status of a todo."""
        try:
            return self._request("PATCH", f"/todo/{todo_id}/toggle")
        except Exception as ex:
            return {"error": f"Failed to toggle todo #{todo_id}: {ex}"}

    def delete_todo(self, todo_id: int) -> dict:
        """Delete a todo."""
        try:
            return self._request("DELETE", f"/todo/{todo_id}")
        except Exception as ex:
            return {"error": f"Failed to delete todo #{todo_id}: {ex}"}

    # -------------------------------------------------------------------------
    # Spending Endpoints
    # -------------------------------------------------------------------------

    def get_spending_list(self, start_date: str, end_date: str) -> list[dict]:
        """Retrieve spending entries between start_date and end_date (YYYY-MM-DD)."""
        try:
            return self._request("GET", "/spending/list", params={"startDate": start_date, "endDate": end_date})
        except Exception as ex:
            return [{"error": f"Failed to fetch spending list: {ex}"}]

    def add_spending(self, sum_amount: float, location: str, payment_type: str = None, date: str = None) -> dict:
        """Log a new expense in purchase-calc."""
        body = {
            "sum": float(sum_amount),
            "location": location,
        }
        if payment_type:
            body["paymentType"] = payment_type
        if date:
            body["date"] = date
        try:
            return self._request("POST", "/spending/add", json_body=body)
        except Exception as ex:
            return {"error": f"Failed to add spending: {ex}"}

    def get_spending_summary(self, start_date: str, end_date: str, location: str = None) -> dict:
        """Calculates aggregated spending statistics between two dates."""
        try:
            items = self.get_spending_list(start_date, end_date)
            if items and isinstance(items, list) and "error" in items[0]:
                return items[0]

            filtered = items
            if location:
                loc_lower = location.lower()
                filtered = [i for i in items if loc_lower in str(i.get("locationName", "")).lower()]

            total_sum = sum(float(i.get("sum", 0)) for i in filtered)

            # Breakdown by location
            by_loc = {}
            for i in filtered:
                loc = i.get("locationName") or "Unknown"
                by_loc[loc] = round(by_loc.get(loc, 0) + float(i.get("sum", 0)), 2)

            return {
                "start_date": start_date,
                "end_date": end_date,
                "total_spending": round(total_sum, 2),
                "transaction_count": len(filtered),
                "by_location": by_loc,
                "items": filtered[:20]  # First 20 items to prevent token overflow
            }
        except Exception as ex:
            return {"error": f"Failed to summarize spending: {ex}"}

    # -------------------------------------------------------------------------
    # Daily Budget Endpoints
    # -------------------------------------------------------------------------

    def get_daily_budget(self, date_str: str = None) -> dict:
        """Fetch daily budget entries from date_str (YYYY-MM-DD)."""
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            budgets = self._request("POST", "/dailybudget/listbudget", json_body={"date": date_str})
            return {"date": date_str, "budgets": budgets}
        except Exception as ex:
            return {"error": f"Failed to get daily budget: {ex}"}

    # -------------------------------------------------------------------------
    # Purchase Endpoints
    # -------------------------------------------------------------------------

    def get_purchases(self, start_date: str = None, end_date: str = None, origin: str = None) -> list[dict]:
        """Fetch purchase records from /purchase/get."""
        params = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        if origin:
            params["origin"] = origin
        try:
            return self._request("GET", "/purchase/get", params=params)
        except Exception as ex:
            return [{"error": f"Failed to get purchases: {ex}"}]

