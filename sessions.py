# sessions.py — full replacement
from supabase import create_client
import os

supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

def get_session(phone: str) -> list:
    result = supabase.table("sessions").select("history").eq("phone", phone).execute()
    return result.data[0]["history"] if result.data else []

def update_session(phone: str, history: list):
    supabase.table("sessions").upsert({
        "phone": phone,
        "history": history,
        "updated_at": "NOW()"
    }).execute()

def is_admin_mode(phone: str) -> bool:
    result = supabase.table("sessions").select("is_admin").eq("phone", phone).execute()
    return result.data[0].get("is_admin", False) if result.data else False

def set_admin_mode(phone: str, value: bool):
    supabase.table("sessions").upsert({
        "phone": phone,
        "is_admin": value,
        "updated_at": "NOW()"
    }).execute()



