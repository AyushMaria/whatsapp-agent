from fastapi import FastAPI, Form, BackgroundTasks
from fastapi.responses import Response
from twilio.rest import Client
from dotenv import load_dotenv
from agent import run_agent, run_admin_agent
from sessions import get_session, update_session
import os

load_dotenv()

app = FastAPI()

twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").replace("+91", "").replace(" ", "")


async def process_message(user_message: str, sender: str):
    """Runs in the background — no Twilio timeout risk."""
    phone = sender.replace("whatsapp:", "")
    clean_phone = phone.replace("+91", "").replace(" ", "")

    history = get_session(sender)

    if clean_phone == ADMIN_PHONE:
        reply, updated_history = run_admin_agent(phone, user_message, history)
    else:
        reply, updated_history = run_agent(phone, user_message, history)

    update_session(sender, updated_history)

    if isinstance(reply, list):
        reply = "\n".join(str(item) for item in reply)
    elif not isinstance(reply, str):
        reply = str(reply)

    # Split on [SPLIT] and send all parts via REST API
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
    """Twilio WhatsApp webhook endpoint — responds instantly, processes in background."""
    background_tasks.add_task(process_message, Body.strip(), From)
    # Return empty 200 immediately — well under Twilio's 15s timeout
    return Response(content="", media_type="application/xml")


@app.get("/health")
def health():
    return {"status": "Ace is running 🎾"}