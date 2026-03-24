from supabase import create_client
from langchain_core.tools import tool
from datetime import date
import os, httpx
from dotenv import load_dotenv
from typing import List

load_dotenv()  

from supabase import create_client

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
                import json
                booked.extend(json.loads(slots))

        all_slots = TIME_SLOTS.get(time_block, [])
        available = [s for s in all_slots if s not in booked]

        if not available:
            return f"No slots available for {time_block} on {booking_date}."
        return f"Available {time_block} slots on {booking_date}:\n" + \
               "\n".join(f"- {s}" for s in available)

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
    promo_code: str = "") -> str:

    """
    Create a booking in the database and send email confirmation.
    slots: list of slot strings e.g. ["7:00 PM - 7:30 PM"]
    """
    try:
        # Check for conflicts first
        response = supabase.table("bookings") \
            .select("slots") \
            .eq("booking_date", booking_date) \
            .eq("time_block", time_block) \
            .execute()

        booked = []
        for row in response.data:
            s = row["slots"]
            booked.extend(s if isinstance(s, list) else __import__('json').loads(s))

        conflict = [s for s in slots if s in booked]
        if conflict:
            return f"Sorry, these slots were just taken: {', '.join(conflict)}. Please choose different slots."

        # Base price
        total_price = len(slots) * 250
        price_display = f"₹{total_price}"

        # Dynamic promo logic
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

            if p["max_uses"] and p["uses_count"] >= p["max_uses"]:
                return "❌ This promo code has reached its usage limit."

            if p["discount_type"] == "flat":
                total_price = max(0, total_price - p["discount_value"])
            elif p["discount_type"] == "percent":
                total_price = round(total_price * (1 - p["discount_value"] / 100))

            price_display = f"₹{total_price}"

            # Increment uses_count
            supabase.table("promo_codes") \
                .update({"uses_count": p["uses_count"] + 1}) \
                .eq("code", promo_code.upper()) \
                .execute()

        # Insert booking
        supabase.table("bookings").insert({
            "name": name,
            "phone": phone,
            "email": email,
            "booking_date": booking_date,
            "time_block": time_block,
            "slots": slots,
            "promo_code": promo_code or None,
            "total_price": total_price
        }).execute()

        # Send email confirmation
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

        return (
            f"✅ Booking confirmed!\n"
            f"📅 Date: {booking_date}\n"
            f"⏰ Slots: {', '.join(slots)}\n"
            f"💰 Price: {price_display}\n"
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
            .select("id, slots, booking_date") \
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
    Get all upcoming bookings for a phone number.
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
            return "No upcoming bookings found for this number."

        lines = []
        for b in result.data:
            slots = b["slots"] if isinstance(b["slots"], list) else __import__('json').loads(b["slots"])
            lines.append(
                f"📅 {b['booking_date']} | {b['time_block'].capitalize()} | "
                f"{', '.join(slots)} | ₹{b['total_price']}"
            )
        return "Your upcoming bookings:\n" + "\n".join(lines)

    except Exception as e:
        return f"Error fetching bookings: {str(e)}"
    

@tool
def get_all_bookings(booking_date: str) -> str:
    """
    Admin: Get all bookings for a specific date.
    booking_date: YYYY-MM-DD format
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
            slots = b["slots"] if isinstance(b["slots"], list) else __import__('json').loads(b["slots"])
            lines.append(
                f"🆔 ID: {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | "
                f"⏰ {', '.join(slots)} | 💰 ₹{b['total_price']}"
            )
        return f"Bookings for {booking_date}:\n" + "\n".join(lines)

    except Exception as e:
        return f"Error fetching bookings: {str(e)}"


@tool
def delete_booking_by_id(booking_id: int) -> str:
    """
    Admin: Delete any booking by its ID.
    """
    try:
        result = supabase.table("bookings") \
            .select("id, name, booking_date") \
            .eq("id", booking_id) \
            .execute()

        if not result.data:
            return f"No booking found with ID {booking_id}."

        b = result.data[0]
        supabase.table("bookings").delete().eq("id", booking_id).execute()
        return f"✅ Booking ID {booking_id} for {b['name']} on {b['booking_date']} has been deleted."

    except Exception as e:
        return f"Error deleting booking: {str(e)}"


@tool
def block_slots(booking_date: str, time_block: str, slots: List[str]) -> str:
    """
    Admin: Block specific slots on a date so customers can't book them.
    booking_date: YYYY-MM-DD
    time_block: 'morning', 'afternoon', or 'evening'
    slots: list of slot strings to block
    """
    try:
        supabase.table("bookings").insert({
            "name": "BLOCKED",
            "phone": "0000000000",
            "email": "admin@vibeandvolley.com",
            "booking_date": booking_date,
            "time_block": time_block,
            "slots": slots,
            "promo_code": None,
            "total_price": 0
        }).execute()
        return f"🚫 Slots blocked on {booking_date} ({time_block}): {', '.join(slots)}"

    except Exception as e:
        return f"Error blocking slots: {str(e)}"


@tool
def get_booking_stats() -> str:
    """
    Admin: Get total bookings count and revenue summary.
    """
    try:
        result = supabase.table("bookings") \
            .select("total_price, booking_date, name") \
            .neq("name", "BLOCKED") \
            .execute()

        if not result.data:
            return "No bookings found."

        total_bookings = len(result.data)
        total_revenue = sum(b["total_price"] for b in result.data)

        today = date.today().isoformat()
        today_bookings = [b for b in result.data if b["booking_date"] == today]

        return (
            f"📊 Booking Stats:\n"
            f"📅 Total bookings: {total_bookings}\n"
            f"💰 Total revenue: ₹{total_revenue}\n"
            f"🏸 Today's bookings: {len(today_bookings)}"
        )

    except Exception as e:
        return f"Error fetching stats: {str(e)}"

@tool
def get_bookings_by_phone(phones: List[str]) -> str:
    """
    Admin: Get all bookings for one or more phone numbers.
    phones: list of phone numbers e.g. ["9876543210", "9123456789"]
    """
    try:
        clean_phones = [p.replace("+91", "").replace(" ", "").strip() for p in phones]

        result = supabase.table("bookings") \
            .select("*") \
            .in_("phone", clean_phones) \
            .order("booking_date", desc=True) \
            .execute()

        if not result.data:
            return f"No bookings found for: {', '.join(clean_phones)}"

        lines = []
        for b in result.data:
            slots = b["slots"] if isinstance(b["slots"], list) else __import__('json').loads(b["slots"])
            lines.append(
                f"🆔 ID: {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | "
                f"📅 {b['booking_date']} | ⏰ {', '.join(slots)} | 💰 ₹{b['total_price']}"
            )
        return f"Bookings found:\n" + "\n".join(lines)

    except Exception as e:
        return f"Error fetching bookings: {str(e)}"
    



@tool
def get_bookings_by_name(names: List[str]) -> str:
    """
    Admin: Get all bookings for one or more customer names (partial match supported).
    names: list of name strings e.g. ["Rahul", "Priya Sharma"]
    """
    try:
        all_results = []

        for name in names:
            result = supabase.table("bookings") \
                .select("*") \
                .ilike("name", f"%{name}%") \
                .neq("name", "BLOCKED") \
                .order("booking_date", desc=True) \
                .execute()

            if result.data:
                all_results.extend(result.data)

        if not all_results:
            return f"No bookings found for: {', '.join(names)}"

        # Deduplicate by booking ID
        seen = set()
        unique = []
        for b in all_results:
            if b["id"] not in seen:
                seen.add(b["id"])
                unique.append(b)

        lines = []
        for b in unique:
            slots = b["slots"] if isinstance(b["slots"], list) else __import__('json').loads(b["slots"])
            lines.append(
                f"🆔 ID: {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | "
                f"📅 {b['booking_date']} | ⏰ {', '.join(slots)} | 💰 ₹{b['total_price']}"
            )
        return f"Bookings found:\n" + "\n".join(lines)

    except Exception as e:
        return f"Error fetching bookings: {str(e)}"


@tool
def create_promo_code(
    code: str,
    discount_type: str,
    discount_value: float,
    min_slots: int = 2,
    max_uses: int = None,
    expires_at: str = None
) -> str:
    """
    Admin: Create a new promo code.
    code: promo code string e.g. 'SUMMER50'
    discount_type: 'flat' (₹ off) or 'percent' (% off)
    discount_value: amount or percentage
    min_slots: minimum slots required (default 2 = 1 hour)
    max_uses: max number of times it can be used (None = unlimited)
    expires_at: expiry date in YYYY-MM-DD format (None = no expiry)
    """
    try:
        supabase.table("promo_codes").insert({
            "code": code.upper(),
            "discount_type": discount_type,
            "discount_value": discount_value,
            "min_slots": min_slots,
            "max_uses": max_uses,
            "expires_at": expires_at
        }).execute()
        return (
            f"✅ Promo code *{code.upper()}* created!\n"
            f"💰 Discount: {'₹' if discount_type == 'flat' else ''}{discount_value}{'%' if discount_type == 'percent' else ' off'}\n"
            f"⏱ Min slots: {min_slots} | Max uses: {max_uses or 'Unlimited'} | Expires: {expires_at or 'Never'}"
        )
    except Exception as e:
        return f"Error creating promo code: {str(e)}"


@tool
def edit_booking(
    booking_id: int,
    new_date: str = None,
    new_slots: List[str] = None,
    new_name: str = None,
    new_phone: str = None,
    new_email: str = None
) -> str:
    """
    Admin: Edit an existing booking by ID. Only provided fields will be updated.
    booking_id: ID of the booking to edit
    new_date: new date in YYYY-MM-DD format (optional)
    new_slots: new list of slot strings (optional)
    new_name: updated customer name (optional)
    new_phone: updated phone number (optional)
    new_email: updated email address (optional)
    """
    try:
        existing = supabase.table("bookings") \
            .select("*").eq("id", booking_id).execute()

        if not existing.data:
            return f"No booking found with ID {booking_id}."

        updates = {}
        if new_date: updates["booking_date"] = new_date
        if new_slots: updates["slots"] = new_slots
        if new_name: updates["name"] = new_name
        if new_phone: updates["phone"] = new_phone
        if new_email: updates["email"] = new_email

        if not updates:
            return "No changes provided."

        supabase.table("bookings").update(updates).eq("id", booking_id).execute()
        return f"✅ Booking ID {booking_id} updated successfully.\nChanges: {updates}"

    except Exception as e:
        return f"Error editing booking: {str(e)}"




def send_email_confirmation(to_email, to_name, booking_date,
                             time_block, selected_slots,
                             total_price, phone, promo_code):
    """Send email via EmailJS REST API."""
    try:
        response = httpx.post(
            "https://api.emailjs.com/api/v1.0/email/send",
            json={
                "service_id": os.getenv("EMAILJS_SERVICE_ID"),
                "template_id": os.getenv("EMAILJS_TEMPLATE_ID"),
                "user_id": os.getenv("EMAILJS_PUBLIC_KEY"),
                "accessToken": os.getenv("EMAILJS_PRIVATE_KEY"),
                "template_params": {
                    "to_email": to_email,
                    "to_name": to_name,
                    "booking_date": booking_date,
                    "time_block": time_block,
                    "selected_slots": selected_slots,
                    "total_price": str(total_price),
                    "phone": phone,
                    "promo_code": promo_code or "None",
                }
            },
            timeout=10
        )
        print(f"EmailJS status: {response.status_code}")
        print(f"EmailJS response: {response.text}")
    except Exception as e:
        print(f"Email send failed: {e}")

