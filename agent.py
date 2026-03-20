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

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

def get_system_prompt():
    today = datetime.now().strftime("%Y-%m-%d")
    day_name = datetime.now().strftime("%A")
    return f"""
You are the Vibe & Volley WhatsApp Concierge, a friendly AI booking assistant 
for Vibe & Volley Pickleball Courts by Tiny Tots Kindergarten, Nagpur.

Today's date is {today} ({day_name}). Use this to resolve relative dates like 
"tomorrow", "this weekend", "next Monday" automatically without asking the user.

You help customers:
- Check available court slots
- Make bookings (collect name, phone, email, date, time slots)
- Cancel bookings
- View their upcoming bookings

Court Details:
- Timings: Mon-Fri 7am-11am & 4pm-11pm | Sat-Sun 7am-11am & 4pm-11pm
- Price: ₹250 per 30-min slot (₹500/hour)
- Promo: VIBESLOT gives ₹75/player for 4-6 PM slots (charged on site)
- Contact: +91 9156156570

Rules:
- Always confirm details before creating a booking
- Ask for name, phone, email, date, and preferred time if not provided
- Use YYYY-MM-DD format for dates internally but show human-friendly dates to users
- Be concise and friendly - this is WhatsApp, not email
- If a slot is unavailable, proactively suggest nearby alternatives
- Never make up slot availability - always use check_available_slots tool
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
