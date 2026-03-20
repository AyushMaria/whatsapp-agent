from fastapi import FastAPI, Request, Form
from fastapi.responses import Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
from dotenv import load_dotenv
from agent import run_agent
from sessions import get_session, update_session
import os

load_dotenv()

app = FastAPI()

twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

@app.post("/webhook")
async def webhook(
    Body: str = Form(...),
    From: str = Form(...)
):
    """Twilio WhatsApp webhook endpoint."""
    user_message = Body.strip()
    sender = From

    # Get conversation history for this user
    history = get_session(sender)

    # Run the agent
    reply, updated_history = run_agent(sender, user_message, history)

    # Save updated history
    update_session(sender, updated_history)

    # Ensure reply is a plain string
    if isinstance(reply, list):
        reply = "\n".join(str(item) for item in reply)
    elif not isinstance(reply, str):
        reply = str(reply)

    # Send reply via Twilio TwiML
    resp = MessagingResponse()
    resp.message(reply)
    return Response(content=str(resp), media_type="application/xml")

@app.get("/health")
def health():
    return {"status": "Vibe & Volley Concierge is running 🏸"}
