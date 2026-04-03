from supabase import create_client
from langchain_core.tools import tool
from datetime import date, datetime, timedelta
import pytz
import os, json
from dotenv import load_dotenv
from typing import List, optional
from main import send_email_confirmation

load_dotenv()

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_ANON_KEY"))

TIME_SLOTS = {
    "morning":   ["7:00 AM - 7:30 AM","7:30 AM - 8:00 AM","8:00 AM - 8:30 AM",
                  "8:30 AM - 9:00 AM","9:00 AM - 9:30 AM","9:30 AM - 10:00 AM",
                  "10:00 AM - 10:30 AM","10:30 AM - 11:00 AM"],
    "afternoon": ["4:00 PM - 4:30 PM","4:30 PM - 5:00 PM"],
    "evening":   ["5:00 PM - 5:30 PM","5:30 PM - 6:00 PM","6:00 PM - 6:30 PM",
                  "6:30 PM - 7:00 PM","7:00 PM - 7:30 PM","7:30 PM - 8:00 PM",
                  "8:00 PM - 8:30 PM","8:30 PM - 9:00 PM","9:00 PM - 9:30 PM",
                  "9:30 PM - 10:00 PM","10:00 PM - 10:30 PM","10:30 PM - 11:00 PM"],
}


@tool
def check_available_slots(booking_date: str, time_block: str) -> str:
    """
    Check which slots are available for a given date and time block.
    booking_date: YYYY-MM-DD format
    time_block: 'morning', 'afternoon', or 'evening'
    """
    try:
        ist = pytz.timezone("Asia/Kolkata")
        now = datetime.now(ist)

        if (time_block == "morning" and
            now.hour >= 23 and
            booking_date == (now + timedelta(days=1)).strftime("%Y-%m-%d")
        ):
            return "Morning slots for tomorrow are not available for booking after 11:00 PM. Please consider afternoon (4:00 PM onwards) or evening slots."

        response = supabase.table("bookings") \
            .select("slots") \
            .eq("booking_date", booking_date) \
            .eq("time_block", time_block) \
            .execute()

        booked = []
        for row in response.data:
            slots = row["slots"]
            if isinstance(slots, list):
                booked.extend(slots)
            elif isinstance(slots, str):
                booked.extend(json.loads(slots))

        all_slots = TIME_SLOTS.get(time_block, [])
        available = [s for s in all_slots if s not in booked]

        if not available:
            return f"No slots available for {time_block} on {booking_date}."
        return f"Available {time_block} slots on {booking_date}:\n" + "\n".join(f"- {s}" for s in available)

    except Exception as e:
        return f"Error checking slots: {str(e)}"


@tool
def create_booking(
    name: str,
    phone: str,
    email: str,
    booking_date: str,
    time_block: str,
    slots: List[str],
    promo_code: str = "",
    paddle_rental: int = 0,
    payment_mode: str = optional(str)
) -> str:
    """
    Create a booking in the database and send email confirmation.
    """
    try:
        response = supabase.table("bookings") \
            .select("slots") \
            .eq("booking_date", booking_date) \
            .eq("time_block", time_block) \
            .execute()

        booked = []
        for row in response.data:
            s = row["slots"]
            booked.extend(s if isinstance(s, list) else json.loads(s))

        conflict = [s for s in slots if s in booked]
        if conflict:
            return f"Sorry, these slots were just taken: {', '.join(conflict)}. Please choose different slots."

        total_price = len(slots) * 250

        if paddle_rental < 0 or paddle_rental > 2:
            return "❌ Only 0, 1, or 2 premium paddles are available for rent."

        paddle_hours = len(slots) * 0.5
        paddle_cost = round(paddle_rental * 50 * paddle_hours)
        total_price += paddle_cost
        price_display = f"₹{total_price}"

        if promo_code:
            promo = supabase.table("promo_codes") \
                .select("*") \
                .eq("code", promo_code.upper()) \
                .eq("active", True) \
                .execute()

            if not promo.data:
                return "❌ Invalid or inactive promo code."

            p = promo.data[0]

            if p["expires_at"] and date.fromisoformat(p["expires_at"]) < date.today():
                return "❌ This promo code has expired."

            if len(slots) < p["min_slots"]:
                return f"❌ This promo code requires at least {p['min_slots']} slots ({p['min_slots'] * 30} minutes minimum)."

            if p["weekends_only"]:
                booking_weekday = date.fromisoformat(booking_date).weekday()
                if booking_weekday not in (5, 6):
                    return "❌ This promo code is only valid on weekends (Saturday & Sunday)."

            if p["valid_slots"]:
                invalid = [s for s in slots if s not in p["valid_slots"]]
                if invalid:
                    return (
                        f"❌ Promo code {promo_code.upper()} is only valid for these slots: "
                        f"{', '.join(p['valid_slots'])}"
                    )

            if p["max_uses_per_phone"]:
                usage = supabase.table("promo_usage") \
                    .select("id") \
                    .eq("promo_code", promo_code.upper()) \
                    .eq("phone", phone) \
                    .execute()
                if len(usage.data) >= p["max_uses_per_phone"]:
                    return "❌ You've already used this promo code the maximum number of times allowed."

            if p["discount_type"] == "flat":
                total_price = max(0, total_price - p["discount_value"])
            elif p["discount_type"] == "percent":
                total_price = round(total_price * (1 - p["discount_value"] / 100))

            price_display = f"₹{total_price}"

            supabase.table("promo_usage").insert({
                "promo_code": promo_code.upper(),
                "phone": phone
            }).execute()

        supabase.table("bookings").insert({
            "name": name,
            "phone": phone,
            "email": email,
            "booking_date": booking_date,
            "time_block": time_block,
            "slots": slots,
            "promo_code": promo_code or None,
            "total_price": total_price,
            "paddle_rental": paddle_rental,
            "payment_mode": payment_mode
        }).execute()

        
        send_email_confirmation(
            to_email=email,
            to_name=name,
            booking_date=booking_date,
            time_block=time_block,
            selected_slots=", ".join(slots),
            total_price=price_display,
            phone=phone,
            promo_code=promo_code or "None"
        )

        paddle_line = f"
🏓 Premium Paddles: {paddle_rental} (₹{paddle_cost})" if paddle_rental else ""
        payment_line = f"
💳 Payment: {payment_mode} (pay after you play)" if payment_mode else ""

        return (
            f"✅ Booking confirmed!
"
            f"📅 Date: {booking_date}
"
            f"⏰ Slots: {', '.join(slots)}
"
            f"{paddle_line}"
            f"💰 Price: {price_display}
"
            f"{payment_line}
"
            f"📧 Confirmation sent to {email}"
        )

    except Exception as e:
        return f"Booking failed: {str(e)}"


@tool
def cancel_booking(phone: str, booking_date: str) -> str:
    """
    Cancel a booking by phone number and date.
    """
    try:
        result = supabase.table("bookings") \
            .select("id") \
            .eq("phone", phone) \
            .eq("booking_date", booking_date) \
            .execute()

        if not result.data:
            return f"No bookings found for {phone} on {booking_date}."

        booking_id = result.data[0]["id"]
        supabase.table("bookings").delete().eq("id", booking_id).execute()
        return f"✅ Booking on {booking_date} has been cancelled successfully."

    except Exception as e:
        return f"Cancellation failed: {str(e)}"


@tool
def get_my_bookings(phone: str) -> str:
    """
    Get upcoming bookings for a phone number.
    """
    try:
        today = date.today().isoformat()
        result = supabase.table("bookings") \
            .select("*") \
            .eq("phone", phone) \
            .gte("booking_date", today) \
            .order("booking_date") \
            .execute()

        if not result.data:
            return "No upcoming bookings found."

        lines = []
        for b in result.data:
            slots = b["slots"] if isinstance(b["slots"], list) else json.loads(b["slots"])
            lines.append(f"📅 {b['booking_date']} | {b['time_block']} | {', '.join(slots)}")
        return "
".join(lines)

    except Exception as e:
        return f"Error: {str(e)}"


@tool
def get_all_bookings(booking_date: str) -> str:
    """
    Admin: Get all bookings for a specific date.
    """
    try:
        result = supabase.table("bookings") \
            .select("*") \
            .eq("booking_date", booking_date) \
            .order("time_block") \
            .execute()

        if not result.data:
            return f"No bookings found for {booking_date}."

        lines = []
        for b in result.data:
            slots = b["slots"] if isinstance(b["slots"], list) else json.loads(b["slots"])
            lines.append(f"🆔 {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | ⏰ {', '.join(slots)}")
        return "
".join(lines)

    except Exception as e:
        return f"Error: {str(e)}"


@tool
def create_promo_code(
    code: str,
    discount_type: str,
    discount_value: float,
    min_slots: int = 2,
    max_uses_per_phone: int = None,
    expires_at: str = None,
    valid_slots: List[str] = None,
    weekends_only: bool = False
) -> str:
    """
    Admin: Create a new promo code.
    """
    try:
        supabase.table("promo_codes").insert({
            "code": code.upper(),
            "discount_type": discount_type,
            "discount_value": discount_value,
            "min_slots": min_slots,
            "max_uses_per_phone": max_uses_per_phone,
            "expires_at": expires_at,
            "valid_slots": valid_slots,
            "weekends_only": weekends_only
        }).execute()
        return f"✅ Promo code {code.upper()} created."
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def edit_promo_code(
    code: str,
    **kwargs
) -> str:
    """
    Admin: Edit an existing promo code.
    """
    try:
        supabase.table("promo_codes").update(kwargs).eq("code", code.upper()).execute()
        return f"✅ Promo code {code.upper()} updated."
    except Exception as e:
        return f"Error: {str(e)}"


@tool
def edit_booking(
    booking_id: int,
    booking_date: str = None,
    time_block: str = None,
    slots: List[str] = None,
    payment_mode: str = None
) -> str:
    updates = {k: v for k, v in {
        "booking_date": booking_date,
        "time_block": time_block,
        "slots": slots,
        "payment_mode": payment_mode
    }.items() if v is not None}
    supabase.table("bookings").update(updates).eq("id", booking_id).execute()
    return f"✅ Booking {booking_id} updated."

@tool
def get_revenue(
    after_date: str = None,
    before_date: str = None
) -> str:
    """
    Admin: Get revenue report.
    """
    try:
        query = supabase.table("bookings").select("total_price").neq("name", "BLOCKED")
        if after_date:  query = query.gte("booking_date", after_date)
        if before_date: query = query.lte("booking_date", before_date)
        result = query.execute()
        total = sum((b["total_price"] or 0) for b in result.data)
        return f"💰 Total Revenue: ₹{total}"
    except Exception as e:
        return str(e)
