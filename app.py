import os
import time
from google import genai
from google.genai import types
import streamlit as st
from PIL import Image
from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE, SUMMARY_REQUEST_PROMPT

# Read secrets
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)

gemini_client = get_gemini_client()
MODEL_NAME = "gemini-3.6-flash"

def render_message(message):
    with st.chat_message(message["role"]):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])

def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])

def ask_gemini(contents):
    """Sends a prompt with automatic retry on temporary traffic spikes."""
    for attempt in range(6):
        try:
            response = st.session_state.chat.send_message(contents)
            return response.text
        except Exception as e:
            err_str = str(e)
            if ("503" in err_str or "UNAVAILABLE" in err_str) and attempt < 5:
                time.sleep((attempt + 1) * 3)
                continue
            st.error(f"Gemini error: {e}")
            return None

def send_whatsapp(to_number, message_body):
    """Sends a WhatsApp message using Twilio sandbox."""
    try:
        from twilio.rest import Client
        account_sid = st.secrets.get("TWILIO_ACCOUNT_SID")
        auth_token = st.secrets.get("TWILIO_AUTH_TOKEN")
        from_number = st.secrets.get("TWILIO_PHONE_NUMBER")
        
        if not account_sid or not auth_token or not from_number:
            return False, "Twilio credentials missing in secrets.toml"
        
        client = Client(account_sid, auth_token)
        
        # Clean number by removing all whitespace, dashes, and extra prefixes
        clean_to = "".join(filter(lambda c: c.isdigit() or c == '+', str(to_number)))
        if not clean_to.startswith("+"):
            clean_to = f"+{clean_to}"
            
        clean_from = "".join(filter(lambda c: c.isdigit() or c == '+', str(from_number)))
        if not clean_from.startswith("+"):
            clean_from = f"+{clean_from}"
            
        to_whatsapp = f"whatsapp:{clean_to}"
        from_whatsapp = f"whatsapp:{clean_from}"
        
        client.messages.create(
            body=message_body,
            from_=from_whatsapp,
            to=to_whatsapp
        )
        return True, "Message sent successfully"
    except Exception as e:
        return False, str(e)

# Step 1: Onboarding form
if 'onboarded' not in st.session_state:
    st.title("Welcome to MacroSnap 🥗")
    st.caption("Snap it. Track it. Know it. Your instant calorie & macro decoder.")
    with st.form("onboarding_form"):
        name = st.text_input("What's your name?")
        phone_number = st.text_input("WhatsApp number (with country code, e.g. +918073214435)")
        submitted = st.form_submit_button("Let's get started 🚀")
        if submitted:
            if not name or not phone_number:
                st.error("Please enter both your name and phone number.")
            else:
                st.session_state['name'] = name
                st.session_state['phone_number'] = phone_number
                st.session_state['onboarded'] = True
                st.session_state.messages = []
                st.session_state.chat = gemini_client.chats.create(
                    model=MODEL_NAME,
                    config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
                )
                st.rerun()
    st.stop()

# Step 2: Main Application Header & WhatsApp Trigger
header_col, button_col = st.columns([5, 2], vertical_alignment="center")

with header_col:
    st.title("MacroSnap 🥗")

with button_col:
    send_disabled = len(st.session_state.messages) <= 1
    if st.button("📲 Send to WhatsApp", disabled=send_disabled, use_container_width=True):
        with st.spinner("Summarizing your day..."):
            summary = ask_gemini([SUMMARY_REQUEST_PROMPT])
            if summary:
                success, info = send_whatsapp(st.session_state.phone_number, summary)
                if success:
                    st.success("Sent! Check your WhatsApp 📲")
                else:
                    st.error(f"Couldn't send that: {info}")

st.caption(f"Logged in as {st.session_state.name} - updates go to {st.session_state.phone_number}")

# Render chat history or initial greeting
if not st.session_state.messages:
    welcome_text = WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name)
    add_message("assistant", "text", welcome_text)
else:
    for message in st.session_state.messages:
        render_message(message)

# Single chat input
user_input = st.chat_input(
    "Ask a question, or attach a photo of your meal",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"]
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []

    # Display user uploads in chat
    if photo:
        add_message("user", "image", photo)
        parts.append(Image.open(photo))

    if text:
        add_message("user", "text", text)
        parts.append(text)

    # Prompt if only photo was attached
    if photo and not text:
        parts.append("Estimate the calories, protein, carbs, and fat in this meal.")

    # Call Gemini model
    with st.chat_message("assistant"):
        with st.spinner("Analyzing nutrition & macros..."):
            response_text = ask_gemini(parts)
            if response_text:
                st.write(response_text)
                st.session_state.messages.append({"role": "assistant", "kind": "text", "content": response_text})