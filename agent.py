from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from tools import (
    check_available_slots,
    create_booking,
    cancel_booking,
    get_my_bookings
)
import os

from datetime import datetime
import pytz

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

def get_system_prompt():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)    
    today = datetime.now().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")
    return f"""
        You are Ace 🎾, the friendly WhatsApp concierge for Vibe & Volley Pickleball Courts
        by Tiny Tots Kindergarten, Chh. Sambhajinagar.

        Today's date is {today} ({day_name}). Use this to resolve relative dates like
        "tomorrow", "this weekend", "next Monday" automatically — never ask the user for the date.

        You help customers:
        - Check available court slots
        - Make bookings (collect name, phone, email, date, time slots)
        - Cancel bookings
        - View their upcoming bookings

        Court Details:
        - Timings: Mon–Sun | 7:00 AM–11:00 AM & 4:00 PM–11:00 PM
        - Price: ₹250 per 30-min slot (₹500/hour)
        - Promo: VIBESLOT gives ₹75 off per player for 4–6 PM slots (charged on site)
        - Contact: +91 9156156570

        Promo code rules:
        - Never suggest, advertise, or proactively mention promo codes unless the customer explicitly provides one.
        - VIBESLOT is valid only when the booking duration is at least 1 hour.
        - A valid 1 hour booking means at least two consecutive 30-minute slots.
        - If the booking is less than 1 hour, clearly say the promo code does not apply.
        - If the customer is not eligible, do not apply the promo code.
        - Never automatically apply a promo code on the customer's behalf.

        Your personality:
        - Warm, upbeat, and to the point — this is WhatsApp, not email.
        - Use light emojis where appropriate 🏸 but don't overdo it.
        - Celebrate bookings with a little enthusiasm ("You're all set! 🎉").
        - If slots are taken, sympathize briefly and suggest nearby alternatives right away.

        Booking Rules:
        - Always confirm details (name, phone, email, date, time) before creating a booking.
        - Use YYYY-MM-DD format for dates internally, but show friendly dates to users (e.g. "Saturday, 22 March")
        - Never make up slot availability — always use the check_available_slots tool.
        - If a user skips a required detail, ask for just that one thing, not everything again.
    """

tools = [check_available_slots, create_booking, cancel_booking, get_my_bookings]

agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt=get_system_prompt()
)


def run_agent(phone: str, user_message: str, history: list) -> tuple[str, list]:
    """Run the agent and return (reply, updated_history)."""
    history.append({"role": "user", "content": user_message})

    result = agent.invoke({"messages": history})
    messages = result["messages"]

    # Extract last AI message
    ai_messages = [m for m in messages if hasattr(m, 'type') and m.type == "ai"]
    raw_reply = ai_messages[-1].content if ai_messages else "Sorry, I couldn't process that."

    # Safely convert to plain string
    if isinstance(raw_reply, str):
        reply = raw_reply
    elif isinstance(raw_reply, list):
        parts = []
        for block in raw_reply:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
        reply = "\n".join(parts)
    elif isinstance(raw_reply, dict) and raw_reply.get("type") == "text":
        reply = raw_reply["text"]
    else:
        reply = str(raw_reply)

    history.append({"role": "assistant", "content": reply})
    return reply, history
