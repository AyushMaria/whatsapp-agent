from fastapi import FastAPI, Form, BackgroundTasks, Header, HTTPException
from fastapi.responses import Response
from twilio.rest import Client
from dotenv import load_dotenv
from agent import run_agent, run_admin_agent
from sessions import get_session, update_session, is_admin_mode, set_admin_mode
from reminders import run_booking_reminders
import os

load_dotenv()

app = FastAPI()
twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").replace("+91", "").replace(" ", "")
CRON_SECRET = os.getenv("CRON_SECRET", "")


async def process_message(user_message: str, sender: str):
    """Runs in background — no Twilio timeout risk."""
    phone = sender.replace("whatsapp:", "")
    clean_phone = phone.replace("+91", "").replace(" ", "")

    # ── Admin login/logout intercept ──────────────────────────
    if user_message.strip().lower() in ["admin login", "login admin"]:
        if clean_phone == ADMIN_PHONE:
            set_admin_mode(sender, True)
            reply = "🔐 Admin mode activated. Welcome back, boss!"
        else:
            reply = "⛔ Unauthorized. This number is not registered as an admin."

    elif user_message.strip().lower() in ["admin logout", "logout admin", "logout"]:
        set_admin_mode(sender, False)
        reply = "✅ Logged out of admin mode. You're now in customer mode."

    # ── Route based on current session mode ───────────────────
    else:
        history = get_session(sender)

        if is_admin_mode(sender):
            reply, updated_history = run_admin_agent(phone, user_message, history)
        else:
            reply, updated_history = run_agent(phone, user_message, history)

        update_session(sender, updated_history)

    if isinstance(reply, list):
        reply = "\n".join(str(item) for item in reply)
    elif not isinstance(reply, str):
        reply = str(reply)

    # ── Send messages (split-aware) ───────────────────────────
    parts = [p.strip() for p in reply.split("[SPLIT]") if p.strip()]

    for part in parts:
        try:
            twilio_client.messages.create(
                from_=TWILIO_NUMBER,
                to=sender,
                body=part
            )
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")


@app.post("/webhook")
async def webhook(
    background_tasks: BackgroundTasks,
    Body: str = Form(...),
    From: str = Form(...)
):
    """Responds to Twilio instantly, processes in background."""
    background_tasks.add_task(process_message, Body.strip(), From)
    return Response(content="", media_type="application/xml")


@app.post("/cron/send-booking-reminders")
def send_booking_reminders(x_cron_secret: str = Header(default="")):
    if not CRON_SECRET or x_cron_secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = run_booking_reminders(window_start_mins=60, window_end_mins=120)
    return {
        "status": "ok",
        **result
    }


@app.get("/health")
def health():
    return {"status": "Ace is running 🎾"}