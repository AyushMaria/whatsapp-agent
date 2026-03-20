# In-memory session store per WhatsApp number
sessions: dict = {}

def get_session(phone: str) -> list:
    return sessions.get(phone, [])

def update_session(phone: str, messages: list):
    sessions[phone] = messages

def clear_session(phone: str):
    sessions.pop(phone, None)
