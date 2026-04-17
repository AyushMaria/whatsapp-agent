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
    get_bookings_by_name,
    create_promo_code,
    edit_booking,
    edit_booking_total,
    get_revenue,
    edit_promo_code,
    add_paddle_rental
)
import os
from datetime import datetime
import pytz

llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)

def get_system_prompt(phone: str = ""):
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
        - Promo codes may be available for selected customers. Apply only if the customer provides one.
        - Never automatically apply a promo code on the customer's behalf.
        - Once the customer provides the promo code, you are free to mention it's conditions to them.
        - Always convert any promo code provided by the customer to UPPERCASE before passing it to any tool.

        Your personality:
        - Warm, upbeat, and to the point — this is WhatsApp, not email.
        - Use light emojis where appropriate 🏸 but don't overdo it.
        - Celebrate bookings with a little enthusiasm ("You're all set! 🎉").
        - If slots are taken, sympathize briefly and suggest nearby alternatives right away.

        Booking Rules:
        - Once a slot is confirmed as available, send EXACTLY this one-shot booking message (fill in the actual time and date):

          "⚡ [Time] on [Friendly Date] is available!\n\n"
          "To confirm your booking, reply in this format:\n"
          "Name | Email | Payment (Cash or UPI)\n\n"
          "📌 Example: John Appleseed | john@gmail.com | UPI\n"
          "*Payment is collected after you play — no advance needed*"
        
        - The customer's WhatsApp phone number is: {phone}. Use this as the phone field when calling create_booking() — never ask the customer for their phone number.
        
        - Wait for the customer's single reply. Parse it for: name, email
          and payment_mode. Phone number is already known from the session context.
        
        - VALIDATION RULES after receiving the reply:
          - If payment is not Cash/UPI: ask only for payment mode, nothing else.
          - If any other field is missing: ask for only that missing field in one short message.
          - If all fields valid: call create_booking() immediately. No further confirmation asks.
        
        - AMBIGUITY RULE: If the customer replies "Ok", "Fine", "Sure", "Alright" after
          a constraint message (e.g., max paddles), treat it as acceptance. Do NOT re-ask.
          Proceed with the constrained value.
        
        # ✅ After
        - After create_booking() succeeds, send your reply in EXACTLY this two-part format,
        separated by [SPLIT] on its own line:

            "✅ Booking confirmed! [Name], you're booked for [Date], [Time].
            Total: ₹[Amount] | Pay via [Mode] after you play. See you! 🏓"
            [SPLIT]
            "🏓 *Premium paddles* are available for rent at ₹50/paddle/hour if you're interested!
            We have the following models on court:
            • Perseus IV
            • Agassi
            • j2nf
            • Boomstick

            Just let me know if you'd like to add any to your booking!"

            - PADDLE FOLLOW-UP RULES:
            - Do NOT expect or wait for a reply to this message.
            - If the customer proactively asks to add paddles at any point
                (e.g. "add 2 paddles", "I want the Perseus IV"), call add_paddle_rental()
                with their booking ID and confirm:
                "Done! [X] paddle(s) added. Updated total: ₹[Amount]. See you on the court! 🎉"
            - If the customer does not respond, do nothing. Booking stands as confirmed.
            - Never follow up asking if they want paddles again.
            - A total of 4 premium paddles are available for rent.
        """

def get_admin_prompt():
    ist = pytz.timezone("Asia/Kolkata")
    now = datetime.now(ist)
    today = now.strftime("%Y-%m-%d")
    day_name = now.strftime("%A")
    return f"""
        You are Ace 🎾 in ADMIN MODE. You are speaking with the owner and your creator(Ayush Maria) of Vibe & Volley.
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
        - create_promo_code(code, discount_type, discount_value, ...) — create a new promo code
        - edit_booking(id, ...) — edit date, slots, name, phone or email of a booking or promo code of a booking; recalculates price automatically
        - edit_booking_total(new_total, ...) — override total price by booking ID, phone, or name
        - get_revenue(after_date, before_date, name, phone, email) — get total revenue with optional filters;
          supports date ranges (e.g. after April 1st, before March 31st, or between two dates),
          and per-customer breakdowns by name, phone, or email
        - edit_promo_code(code, ...) — edit any field of an existing promo code; supports renaming, changing discount, toggling active status, updating expiry, slots, or usage limits

        Be concise and efficient. Use tables or lists for data.
        Always confirm before deleting or blocking.
        """

customer_tools = [check_available_slots, create_booking, cancel_booking, get_my_bookings, add_paddle_rental]
admin_tools = [
    check_available_slots, create_booking, cancel_booking,
    get_my_bookings, get_all_bookings, delete_booking_by_id,
    block_slots, get_booking_stats, get_bookings_by_phone, 
    get_bookings_by_name, create_promo_code, edit_booking,
    edit_booking_total, get_revenue, edit_promo_code
]

def run_agent(phone: str, user_message: str, history: list) -> tuple[str, list]:
    """Run the customer agent."""
    agent = create_react_agent(model=llm, tools=customer_tools, prompt=get_system_prompt(phone))
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
