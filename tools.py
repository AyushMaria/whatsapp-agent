from supabase import create_client
from langchain_core.tools import tool
from datetime import date, datetime, timedelta
import pytz
import os, httpx, json
from dotenv import load_dotenv
from typing import List

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
    \"\"\"
    Check which slots are available for a given date and time block.
    booking_date: YYYY-MM-DD format
    time_block: 'morning', 'afternoon', or 'evening'
    \"\"\"
    try:
        ist = pytz.timezone(\"Asia/Kolkata\")
        now = datetime.now(ist)

        if (time_block == \"morning\" and
            now.hour >= 23 and
            booking_date == (now + timedelta(days=1)).strftime(\"%Y-%m-%d\")
        ):
            return \"Morning slots for tomorrow are not available for booking after 11:00 PM. Please consider afternoon (4:00 PM onwards) or evening slots.\"

        response = supabase.table(\"bookings\") \\
            .select(\"slots\") \\
            .eq(\"booking_date\", booking_date) \\
            .eq(\"time_block\", time_block) \\
            .execute()

        booked = []
        for row in response.data:
            slots = row[\"slots\"]
            if isinstance(slots, list):
                booked.extend(slots)
            elif isinstance(slots, str):
                booked.extend(json.loads(slots))

        all_slots = TIME_SLOTS.get(time_block, [])
        available = [s for s in all_slots if s not in booked]

        if not available:
            return f\"No slots available for {time_block} on {booking_date}.\"
        return f\"Available {time_block} slots on {booking_date}:\
\" + \\
               \"\
\".join(f\"- {s}\" for s in available)

    except Exception as e:
        return f\"Error checking slots: {str(e)}\"


@tool
def create_booking(
    name: str,
    phone: str,
    email: str,
    booking_date: str,
    time_block: str,
    slots: List[str],
    promo_code: str = \"\",
    paddle_rental: int = 0,
    payment_mode: str = None
) -> str:
    \"\"\"
    Create a booking in the database and send email confirmation.
    slots: list of slot strings e.g. [\"7:00 PM - 7:30 PM\"]
    \"\"\"
    try:
        response = supabase.table(\"bookings\") \\
            .select(\"slots\") \\
            .eq(\"booking_date\", booking_date) \\
            .eq(\"time_block\", time_block) \\
            .execute()

        booked = []
        for row in response.data:
            s = row[\"slots\"]
            booked.extend(s if isinstance(s, list) else json.loads(s))

        conflict = [s for s in slots if s in booked]
        if conflict:
            return f\"Sorry, these slots were just taken: {', '.join(conflict)}. Please choose different slots.\"

        total_price = len(slots) * 250

        if paddle_rental < 0 or paddle_rental > 2:
            return \"❌ Only 0, 1, or 2 premium paddles are available for rent.\"

        paddle_hours = len(slots) * 0.5
        paddle_cost = round(paddle_rental * 50 * paddle_hours)
        total_price += paddle_cost
        price_display = f\"₹{total_price}\"

        if promo_code:
            promo = supabase.table(\"promo_codes\") \\
                .select(\"*\") \\
                .eq(\"code\", promo_code.upper()) \\
                .eq(\"active\", True) \\
                .execute()

            if not promo.data:
                return \"❌ Invalid or inactive promo code.\"

            p = promo.data[0]

            if p[\"expires_at\"] and date.fromisoformat(p[\"expires_at\"]) < date.today():
                return \"❌ This promo code has expired.\"

            if len(slots) < p[\"min_slots\"]:
                return f\"❌ This promo code requires at least {p['min_slots']} slots ({p['min_slots'] * 30} minutes minimum).\"

            if p[\"weekends_only\"]:
                booking_weekday = date.fromisoformat(booking_date).weekday()
                if booking_weekday not in (5, 6):
                    return \"❌ This promo code is only valid on weekends (Saturday & Sunday).\"

            if p[\"valid_slots\"]:
                invalid = [s for s in slots if s not in p[\"valid_slots\"]]
                if invalid:
                    return (
                        f\"❌ Promo code {promo_code.upper()} is only valid for these slots: \"
                        f\"{', '.join(p['valid_slots'])}\"
                    )

            if p[\"max_uses_per_phone\"]:
                usage = supabase.table(\"promo_usage\") \\
                    .select(\"id\") \\
                    .eq(\"promo_code\", promo_code.upper()) \\
                    .eq(\"phone\", phone) \\
                    .execute()
                if len(usage.data) >= p[\"max_uses_per_phone\"]:
                    return \"❌ You've already used this promo code the maximum number of times allowed.\"

            if p[\"discount_type\"] == \"flat\":
                total_price = max(0, total_price - p[\"discount_value\"])
            elif p[\"discount_type\"] == \"percent\":
                total_price = round(total_price * (1 - p[\"discount_value\"] / 100))

            price_display = f\"₹{total_price}\"

            supabase.table(\"promo_usage\").insert({
                \"promo_code\": promo_code.upper(),
                \"phone\": phone
            }).execute()

        supabase.table(\"bookings\").insert({
            \"name\": name,
            \"phone\": phone,
            \"email\": email,
            \"booking_date\": booking_date,
            \"time_block\": time_block,
            \"slots\": slots,
            \"promo_code\": promo_code or None,
            \"total_price\": total_price,
            \"paddle_rental\": paddle_rental,
            \"payment_mode\": payment_mode
        }).execute()

        send_email_confirmation(
            to_email=email,
            to_name=name,
            booking_date=booking_date,
            time_block=time_block,
            selected_slots=\", \".join(slots),
            total_price=price_display,
            phone=phone,
            promo_code=promo_code or \"None\"
        )

        paddle_line = f\"\
🏓 Premium Paddles: {paddle_rental} (₹{paddle_cost})\" if paddle_rental else \"\"
        payment_line = f\"\
💳 Payment: {payment_mode} (pay after you play)\" if payment_mode else \"\"

        return (
            f\"✅ Booking confirmed!\
\"
            f\"📅 Date: {booking_date}\
\"
            f\"⏰ Slots: {', '.join(slots)}\
\"
            f\"{paddle_line}\"
            f\"💰 Price: {price_display}\
\"
            f\"{payment_line}\
\"
            f\"📧 Confirmation sent to {email}\"
        )

    except Exception as e:
        return f\"Booking failed: {str(e)}\"


@tool
def cancel_booking(phone: str, booking_date: str) -> str:
    \"\"\"
    Cancel a booking by phone number and date.
    \"\"\"
    try:
        result = supabase.table(\"bookings\") \\
            .select(\"id, slots, booking_date\") \\
            .eq(\"phone\", phone) \\
            .eq(\"booking_date\", booking_date) \\
            .execute()

        if not result.data:
            return f\"No bookings found for {phone} on {booking_date}.\"

        booking_id = result.data[0][\"id\"]
        supabase.table(\"bookings\").delete().eq(\"id\", booking_id).execute()
        return f\"✅ Booking on {booking_date} has been cancelled successfully.\"

    except Exception as e:
        return f\"Cancellation failed: {str(e)}\"


@tool
def get_my_bookings(phone: str) -> str:
    \"\"\"
    Get all upcoming bookings for a phone number.
    \"\"\"
    try:
        today = date.today().isoformat()
        result = supabase.table(\"bookings\") \\
            .select(\"*\") \\
            .eq(\"phone\", phone) \\
            .gte(\"booking_date\", today) \\
            .order(\"booking_date\") \\
            .execute()

        if not result.data:
            return \"No upcoming bookings found for this number.\"

        lines = []
        for b in result.data:
            slots = b[\"slots\"] if isinstance(b[\"slots\"], list) else json.loads(b[\"slots\"])
            lines.append(
                f\"📅 {b['booking_date']} | {b['time_block'].capitalize()} | \"
                f\"{', '.join(slots)} | ₹{b['total_price']}\"
            )
        return \"Your upcoming bookings:\
\" + \"\
\".join(lines)

    except Exception as e:
        return f\"Error fetching bookings: {str(e)}\"


@tool
def get_all_bookings(booking_date: str) -> str:
    \"\"\"
    Admin: Get all bookings for a specific date.
    booking_date: YYYY-MM-DD format
    \"\"\"
    try:
        result = supabase.table(\"bookings\") \\
            .select(\"*\") \\
            .eq(\"booking_date\", booking_date) \\
            .order(\"time_block\") \\
            .execute()

        if not result.data:
            return f\"No bookings found for {booking_date}.\"

        lines = []
        for b in result.data:
            slots = b[\"slots\"] if isinstance(b[\"slots\"], list) else json.loads(b[\"slots\"])
            lines.append(
                f\"🆔 ID: {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | \"
                f\"⏰ {', '.join(slots)} | 💰 ₹{b['total_price']}\"
            )
        return f\"Bookings for {booking_date}:\
\" + \"\
\".join(lines)

    except Exception as e:
        return f\"Error fetching bookings: {str(e)}\"


@tool
def delete_booking_by_id(booking_id: int) -> str:
    \"\"\"
    Admin: Delete any booking by its ID.
    \"\"\"
    try:
        result = supabase.table(\"bookings\") \\
            .select(\"id, name, booking_date\") \\
            .eq(\"id\", booking_id) \\
            .execute()

        if not result.data:
            return f\"No booking found with ID {booking_id}.\"

        b = result.data[0]
        supabase.table(\"bookings\").delete().eq(\"id\", booking_id).execute()
        return f\"✅ Booking ID {booking_id} for {b['name']} on {b['booking_date']} has been deleted.\"

    except Exception as e:
        return f\"Error deleting booking: {str(e)}\"


@tool
def block_slots(booking_date: str, time_block: str, slots: List[str]) -> str:
    \"\"\"
    Admin: Block specific slots on a date so customers can't book them.
    booking_date: YYYY-MM-DD
    time_block: 'morning', 'afternoon', or 'evening'
    slots: list of slot strings to block
    \"\"\"
    try:
        supabase.table(\"bookings\").insert({
            \"name\": \"BLOCKED\",
            \"phone\": \"0000000000\",
            \"email\": \"admin@vibeandvolley.com\",
            \"booking_date\": booking_date,
            \"time_block\": time_block,
            \"slots\": slots,
            \"promo_code\": None,
            \"total_price\": 0
        }).execute()
        return f\"🚫 Slots blocked on {booking_date} ({time_block}): {', '.join(slots)}\"

    except Exception as e:
        return f\"Error blocking slots: {str(e)}\"


@tool
def get_booking_stats() -> str:
    \"\"\"
    Admin: Get total bookings count and revenue summary.
    \"\"\"
    try:
        result = supabase.table(\"bookings\") \\
            .select(\"total_price, booking_date, name\") \\
            .neq(\"name\", \"BLOCKED\") \\
            .execute()

        if not result.data:
            return \"No bookings found.\"

        total_bookings = len(result.data)
        total_revenue = sum(b[\"total_price\"] for b in result.data)
        today = date.today().isoformat()
        today_bookings = [b for b in result.data if b[\"booking_date\"] == today]

        return (
            f\"📊 Booking Stats:\
\"
            f\"📅 Total bookings: {total_bookings}\
\"
            f\"💰 Total revenue: ₹{total_revenue}\
\"
            f\"🏸 Today's bookings: {len(today_bookings)}\"
        )

    except Exception as e:
        return f\"Error fetching stats: {str(e)}\"


@tool
def get_bookings_by_phone(phones: List[str]) -> str:
    \"\"\"
    Admin: Get all bookings for one or more phone numbers.
    phones: list of phone numbers e.g. [\"9876543210\", \"9123456789\"]
    \"\"\"
    try:
        clean_phones = [p.replace(\"+91\", \"\").replace(\" \", \"\").strip() for p in phones]

        result = supabase.table(\"bookings\") \\
            .select(\"*\") \\
            .in_(\"phone\", clean_phones) \\
            .order(\"booking_date\", desc=True) \\
            .execute()

        if not result.data:
            return f\"No bookings found for: {', '.join(clean_phones)}\"

        lines = []
        for b in result.data:
            slots = b[\"slots\"] if isinstance(b[\"slots\"], list) else json.loads(b[\"slots\"])
            lines.append(
                f\"🆔 ID: {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | \"
                f\"📅 {b['booking_date']} | ⏰ {', '.join(slots)} | 💰 ₹{b['total_price']}\"
            )
        return \"Bookings found:\
\" + \"\
\".join(lines)

    except Exception as e:
        return f\"Error fetching bookings: {str(e)}\"


@tool
def get_bookings_by_name(names: List[str]) -> str:
    \"\"\"
    Admin: Get all bookings for one or more customer names (partial match supported).
    names: list of name strings e.g. [\"Rahul\", \"Priya Sharma\"]
    \"\"\"
    try:
        all_results = []
        for name in names:
            result = supabase.table(\"bookings\") \\
                .select(\"*\") \\
                .ilike(\"name\", f\"%{name}%\") \\
                .neq(\"name\", \"BLOCKED\") \\
                .order(\"booking_date\", desc=True) \\
                .execute()
            if result.data:
                all_results.extend(result.data)

        if not all_results:
            return f\"No bookings found for: {', '.join(names)}\"

        seen = set()
        unique = []
        for b in all_results:
            if b[\"id\"] not in seen:
                seen.add(b[\"id\"])
                unique.append(b)

        lines = []
        for b in unique:
            slots = b[\"slots\"] if isinstance(b[\"slots\"], list) else json.loads(b[\"slots\"])
            lines.append(
                f\"🆔 ID: {b['id']} | 👤 {b['name']} | 📞 {b['phone']} | \"
                f\"📅 {b['booking_date']} | ⏰ {', '.join(slots)} | 💰 ₹{b['total_price']}\"
            )
        return \"Bookings found:\
\" + \"\
\".join(lines)

    except Exception as e:
        return f\"Error fetching bookings: {str(e)}\"


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
    \"\"\"
    Admin: Create a new promo code.
    code: promo code string e.g. 'SUMMER50'
    discount_type: 'flat' (₹ off) or 'percent' (% off)
    discount_value: amount or percentage
    min_slots: minimum slots required (default 2 = 1 hour)
    max_uses_per_phone: max uses per phone number (None = unlimited)
    expires_at: expiry date in YYYY-MM-DD format (None = no expiry)
    valid_slots: list of slot strings this promo is restricted to (None = no restriction)
    weekends_only: if True, promo is only valid on Saturdays and Sundays
    \"\"\"
    try:
        supabase.table(\"promo_codes\").insert({
            \"code\": code.upper(),
            \"discount_type\": discount_type,
            \"discount_value\": discount_value,
            \"min_slots\": min_slots,
            \"max_uses_per_phone\": max_uses_per_phone,
            \"expires_at\": expires_at,
            \"valid_slots\": valid_slots,
            \"weekends_only\": weekends_only
        }).execute()

        slot_info = f\"\
🕐 Valid slots: {', '.join(valid_slots)}\" if valid_slots else \"\"
        weekend_info = \"\
📅 Valid on: Weekends only\" if weekends_only else \"\"

        return (
            f\"✅ Promo code *{code.upper()}* created!\
\"
            f\"💰 Discount: {'₹' if discount_type == 'flat' else ''}{discount_value}{'%' if discount_type == 'percent' else ' off'}\
\"
            f\"⏱ Min slots: {min_slots} | Max uses: {max_uses_per_phone or 'Unlimited'} | Expires: {expires_at or 'Never'}\"
            f\"{slot_info}\"
            f\"{weekend_info}\"
        )
    except Exception as e:
        return f\"Error creating promo code: {str(e)}\"


@tool
def edit_promo_code(
    code: str,
    new_code: str = None,
    discount_type: str = None,
    discount_value: float = None,
    min_slots: int = None,
    max_uses_per_phone: int = None,
    expires_at: str = None,
    valid_slots: List[str] = None,
    weekends_only: bool = None,
    active: bool = None
) -> str:
    \"\"\"
    Admin: Edit an existing promo code. Only provided fields will be updated.
    code: the existing promo code to edit (e.g. 'VIBESLOT')
    new_code: rename the promo code (optional)
    discount_type: 'flat' or 'percent' (optional)
    discount_value: new discount amount or percentage (optional)
    min_slots: minimum slots required (optional)
    max_uses_per_phone: max uses per phone number, None = unlimited (optional)
    expires_at: new expiry date in YYYY-MM-DD format (optional)
    valid_slots: list of slot strings to restrict to (optional)
    weekends_only: True/False (optional)
    active: True to activate, False to deactivate (optional)
    \"\"\"
    try:
        existing = supabase.table(\"promo_codes\") \\
            .select(\"*\") \\
            .eq(\"code\", code.upper()) \\
            .execute()

        if not existing.data:
            return f\"❌ No promo code found with code '{code.upper()}'.\"

        updates = {}
        if new_code is not None:            updates[\"code\"] = new_code.upper()
        if discount_type is not None:       updates[\"discount_type\"] = discount_type
        if discount_value is not None:      updates[\"discount_value\"] = discount_value
        if min_slots is not None:           updates[\"min_slots\"] = min_slots
        if max_uses_per_phone is not None:  updates[\"max_uses_per_phone\"] = max_uses_per_phone
        if expires_at is not None:          updates[\"expires_at\"] = expires_at
        if valid_slots is not None:         updates[\"valid_slots\"] = valid_slots
        if weekends_only is not None:       updates[\"weekends_only\"] = weekends_only
        if active is not None:              updates[\"active\"] = active

        if not updates:
            return \"⚠️ No changes provided.\"

        supabase.table(\"promo_codes\") \\
            .update(updates) \\
            .eq(\"code\", code.upper()) \\
            .execute()

        changed = \", \".join(f\"{k} → {v}\" for k, v in updates.items())
        display_code = updates.get(\"code\", code.upper())
        return f\"✅ Promo code *{display_code}* updated successfully.\
📝 Changes: {changed}\"

    except Exception as e:
        return f\"Error editing promo code: {str(e)}\"


@tool
def edit_booking(
    booking_id: int,
    new_date: str = None,
    new_slots: List[str] = None,
    new_name: str = None,
    new_phone: str = None,
    new_email: str = None
) -> str:
    \"\"\"
    Admin: Edit an existing booking by ID. Only provided fields will be updated.
    Automatically recalculates total price if slots are changed.
    booking_id: ID of the booking to edit
    new_date: new date in YYYY-MM-DD format (optional)
    new_slots: new list of slot strings (optional)
    new_name: updated customer name (optional)
    new_phone: updated phone number (optional)
    new_email: updated email address (optional)
    \"\"\"
    try:
        existing = supabase.table(\"bookings\") \\
            .select(\"*\").eq(\"id\", booking_id).execute()

        if not existing.data:
            return f\"No booking found with ID {booking_id}.\"

        b = existing.data[0]
        updates = {}

        if new_date:  updates[\"booking_date\"] = new_date
        if new_name:  updates[\"name\"] = new_name
        if new_phone: updates[\"phone\"] = new_phone
        if new_email: updates[\"email\"] = new_email

        promo_warning = \"\"
        if new_slots:
            updates[\"slots\"] = new_slots
            base_price = len(new_slots) * 250
            new_total = base_price

            promo_code = b.get(\"promo_code\")
            if promo_code:
                promo = supabase.table(\"promo_codes\") \\
                    .select(\"*\") \\
                    .eq(\"code\", promo_code.upper()) \\
                    .eq(\"active\", True) \\
                    .execute()

                if promo.data:
                    p = promo.data[0]
                    if len(new_slots) < p[\"min_slots\"]:
                        promo_warning = (
                            f\"\
⚠️ Promo code {promo_code.upper()} requires at least {p['min_slots']} slots \"
                            f\"— not applied. Full price ₹{base_price} applies.\"
                        )
                    else:
                        if p[\"discount_type\"] == \"flat\":
                            new_total = max(0, base_price - p[\"discount_value\"])
                        elif p[\"discount_type\"] == \"percent\":
                            new_total = round(base_price * (1 - p[\"discount_value\"] / 100))

            updates[\"total_price\"] = new_total

        if not updates:
            return \"No changes provided.\"

        supabase.table(\"bookings\").update(updates).eq(\"id\", booking_id).execute()

        old_slots = b[\"slots\"] if isinstance(b[\"slots\"], list) else json.loads(b[\"slots\"])
        summary_parts = [f\"✅ Booking ID {booking_id} updated successfully.\"]
        if new_name:   summary_parts.append(f\"👤 Name: {b['name']} → {new_name}\")
        if new_date:   summary_parts.append(f\"📅 Date: {b['booking_date']} → {new_date}\")
        if new_slots:  summary_parts.append(f\"⏰ Slots: {', '.join(old_slots)} → {', '.join(new_slots)}\")
        if new_phone:  summary_parts.append(f\"📞 Phone: {b['phone']} → {new_phone}\")
        if new_email:  summary_parts.append(f\"📧 Email: {b['email']} → {new_email}\")
        if new_slots:  summary_parts.append(f\"💰 New price: ₹{updates['total_price']}\")
        if promo_warning: summary_parts.append(promo_warning)

        return \"\
\".join(summary_parts)

    except Exception as e:
        return f\"Error editing booking: {str(e)}\"


@tool
def edit_booking_total(
    new_total: int,
    booking_ids: List[int] = None,
    phone: str = None,
    name: str = None
) -> str:
    \"\"\"
    Admin: Override the total price for bookings by ID, phone number, or customer name.
    At least one filter (booking_ids, phone, or name) must be provided.
    new_total: the new total price to set (in ₹)
    booking_ids: list of specific booking IDs to update (optional)
    phone: update all bookings for this phone number (optional)
    name: update all bookings matching this name (optional)
    \"\"\"
    try:
        if not any([booking_ids, phone, name]):
            return \"❌ Please provide at least one filter: booking_ids, phone, or name.\"

        matched_ids = set()

        if booking_ids:
            result = supabase.table(\"bookings\") \\
                .select(\"id\") \\
                .in_(\"id\", booking_ids) \\
                .execute()
            for b in result.data:
                matched_ids.add(b[\"id\"])

        if phone:
            clean_phone = phone.replace(\"+91\", \"\").replace(\" \", \"\").strip()
            result = supabase.table(\"bookings\") \\
                .select(\"id\") \\
                .eq(\"phone\", clean_phone) \\
                .neq(\"name\", \"BLOCKED\") \\
                .execute()
            for b in result.data:
                matched_ids.add(b[\"id\"])

        if name:
            result = supabase.table(\"bookings\") \\
                .select(\"id\") \\
                .ilike(\"name\", f\"%{name}%\") \\
                .neq(\"name\", \"BLOCKED\") \\
                .execute()
            for b in result.data:
                matched_ids.add(b[\"id\"])

        if not matched_ids:
            return \"❌ No matching bookings found.\"

        supabase.table(\"bookings\") \\
            .update({\"total_price\": new_total}) \\
            .in_(\"id\", list(matched_ids)) \\
            .execute()

        return f\"✅ Total updated to ₹{new_total} for {len(matched_ids)} booking(s).\"

    except Exception as e:
        return f\"Error updating totals: {str(e)}\"


@tool
def get_revenue(
    after_date: str = None,
    before_date: str = None,
    name: str = None,
    phone: str = None,
    email: str = None
) -> str:
    \"\"\"
    Admin: Get total revenue filtered by date range, customer name, phone, or email.
    \"\"\"
    try:
        if not any([after_date, before_date, name, phone, email]):
            return \"❌ Please provide at least one filter.\"

        query = supabase.table(\"bookings\") \\
            .select(\"id, name, phone, email, booking_date, total_price\") \\
            .neq(\"name\", \"BLOCKED\")

        if after_date:  query = query.gte(\"booking_date\", after_date)
        if before_date: query = query.lte(\"booking_date\", before_date)
        if phone:
            clean_phone = phone.replace(\"+91\", \"\").replace(\" \", \"\").strip()
            query = query.eq(\"phone\", clean_phone)
        if email:       query = query.eq(\"email\", email)

        result = query.execute()
        data = result.data

        if name:
            data = [b for b in data if name.lower() in b[\"name\"].lower()]

        if not data:
            return \"No bookings found.\"

        total_revenue = sum(b[\"total_price\"] for b in data)
        return (
            f\"📊 Revenue Report\
\"
            f\"📦 Bookings: {len(data)}\
\"
            f\"💰 Total Revenue: ₹{total_revenue}\"
        )

    except Exception as e:
        return f\"Error fetching revenue: {str(e)}\"
