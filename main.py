from fastapi import FastAPI, Request, Form
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
from agent import run_agent, run_admin_agent
from sessions import get_session, update_session
import os

load_dotenv()

app = FastAPI()

twilio_client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
TWILIO_NUMBER = os.environ["TWILIO_WHATSAPP_NUMBER"]

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").replace("+91", "").replace(" ", "")


@app.post("/webhook")
async def webhook(
    Body: str = Form(...),
    From: str = Form(...)
):
    """Twilio WhatsApp webhook endpoint."""
    user_message = Body.strip()
    sender = From

    history = get_session(sender)

    clean_sender = sender.replace("whatsapp:", "").replace("+91", "").replace(" ", "")
    phone = sender.replace("whatsapp:", "")
    
    if clean_sender == ADMIN_PHONE:
        reply, updated_history = run_admin_agent(phone, user_message, history)
    else:
        reply, updated_history = run_agent(phone, user_message, history)

    update_session(sender, updated_history)

    if isinstance(reply, list):
        reply = "\n".join(str(item) for item in reply)
    elif not isinstance(reply, str):
        reply = str(reply)

    # Split on [SPLIT] to send two separate WhatsApp messages
    parts = [p.strip() for p in reply.split("[SPLIT]") if p.strip()]

    if len(parts) >= 2:
        # Send the first message via TwiML (synchronous response)
        resp = MessagingResponse()
        resp.message(parts[0])

        # Send all subsequent parts via Twilio REST API
        try:
            twilio_client.messages.create(
                from_=TWILIO_NUMBER,
                to=sender,
                body=extra
            )
        except Exception as e:
            print(f"[ERROR] Failed to send split message: {e}")

        return Response(content=str(resp), media_type="application/xml")

    else:
        # Normal single message
        resp = MessagingResponse()
        resp.message(parts[0] if parts else reply)
        return Response(content=str(resp), media_type="application/xml")


@app.get("/health")
def health():
    return {"status": "Ace is running 🎾"}
