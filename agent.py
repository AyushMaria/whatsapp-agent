from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from tools import (
    check_available_slots,
    create_booking,
    cancel_booking,
    get_my_bookings,
    get_all_bookings,
    delete_booking_by_id,
    block_slots,
    get_booking_stats,
    get_bookings_by_phone, 
    get_bookings_by_name

)
import os
from datetime import datetime
import pytz

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

def get_system_prompt():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    today = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")
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
        - Promo: VIBESLOT is active for selected customers only and valid only for bookings of at least 1 hour
        - Contact: +91 9156156570

        Promo code rules:
        - Never suggest, advertise, or proactively mention promo codes unless the customer explicitly provides one.
        - VIBESLOT is valid only when the booking duration is at least 1 hour (at least two consecutive 30-min slots).
        - If the booking is less than 1 hour, clearly say the promo code does not apply.
        - Never automatically apply a promo code on the customer's behalf.

        Your personality:
        - Warm, upbeat, and to the point — this is WhatsApp, not email.
        - Use light emojis where appropriate 🏸 but don't overdo it.
        - Celebrate bookings with a little enthusiasm ("You're all set! 🎉").
        - If slots are taken, sympathize briefly and suggest nearby alternatives right away.

        Booking Rules:
        - Always confirm details (name, phone, email, date, time) before creating a booking.
        - Use YYYY-MM-DD format for dates internally, but show friendly dates to users (e.g. "Monday, 23 March")
        - Never make up slot availability — always use the check_available_slots tool.
        - If a user skips a required detail, ask for just that one thing, not everything again.
        """

def get_admin_prompt():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    today = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")
    return f"""
        You are Ace 🎾 in ADMIN MODE. You are speaking with the owner(Ayush Maria) of Vibe & Volley.
        Today's date is {today} ({day_name}).

        You have full database access and can:
        - View all bookings for any date
        - Delete any booking by ID
        - Block slots (maintenance, private events, etc.)
        - View booking stats and revenue
        - Create and cancel bookings on behalf of customers

        Admin tools available:
        - get_all_bookings(date) — show all bookings for a date
        - delete_booking_by_id(id) — delete a booking
        - block_slots(date, time_block, slots) — block slots
        - get_booking_stats() — revenue and booking summary
        - create_booking(...) — book on behalf of a customer
        - cancel_booking(...) — cancel any booking
        - get_bookings_by_phone(phone) — view all bookings for a specific customer number
        - get_bookings_by_name(names) — search bookings by customer name (partial match)

        Be concise and efficient. Use tables or lists for data.
        Always confirm before deleting or blocking.
        """

customer_tools = [check_available_slots, create_booking, cancel_booking, get_my_bookings]
admin_tools = [
    check_available_slots, create_booking, cancel_booking,
    get_my_bookings, get_all_bookings, delete_booking_by_id,
    block_slots, get_booking_stats, get_bookings_by_phone, get_bookings_by_name
]

def run_agent(phone: str, user_message: str, history: list) -> tuple[str, list]:
    """Run the customer agent."""
    agent = create_react_agent(model=llm, tools=customer_tools, prompt=get_system_prompt())
    history.append({"role": "user", "content": user_message})
    result = agent.invoke({"messages": history})
    messages = result["messages"]
    ai_messages = [m for m in messages if hasattr(m, 'type') and m.type == "ai"]
    raw_reply = ai_messages[-1].content if ai_messages else "Sorry, I couldn't process that."
    reply = _parse_reply(raw_reply)
    history.append({"role": "assistant", "content": reply})
    return reply, history

def run_admin_agent(phone: str, user_message: str, history: list) -> tuple[str, list]:
    """Run the admin agent."""
    agent = create_react_agent(model=llm, tools=admin_tools, prompt=get_admin_prompt())
    history.append({"role": "user", "content": user_message})
    result = agent.invoke({"messages": history})
    messages = result["messages"]
    ai_messages = [m for m in messages if hasattr(m, 'type') and m.type == "ai"]
    raw_reply = ai_messages[-1].content if ai_messages else "Sorry, I couldn't process that."
    reply = _parse_reply(raw_reply)
    history.append({"role": "assistant", "content": reply})
    return reply, history

def _parse_reply(raw_reply) -> str:
    """Safely convert LLM reply to plain string."""
    if isinstance(raw_reply, str):
        return raw_reply
    elif isinstance(raw_reply, list):
        parts = []
        for block in raw_reply:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
        return "\n".join(parts)
    elif isinstance(raw_reply, dict) and raw_reply.get("type") == "text":
        return raw_reply["text"]
    return str(raw_reply)
