import base64
from datetime import datetime
from io import BytesIO

import streamlit as st
from ollama import Client
from PIL import Image, ImageOps


# ============================================================
# PAGE SETTINGS
# ============================================================

st.set_page_config(
    page_title="dharshan's lil helper 2",
    page_icon="✨",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

    :root {
        --ink: #f8fafc;
        --muted: #a9b5c9;
        --surface: rgba(20, 29, 50, .84);
        --surface-raised: #202c4a;
        --purple: #a78bfa;
        --pink: #f0abfc;
    }

    .stApp {
        background:
            radial-gradient(circle at 6% 2%, rgba(124, 58, 237, .24), transparent 30rem),
            radial-gradient(circle at 96% 16%, rgba(236, 72, 153, .13), transparent 25rem),
            #0b1020;
        color: var(--ink);
    }

    [data-testid="stHeader"], [data-testid="stHeader"] > div {
        background: transparent;
    }

    .main .block-container {
        max-width: 1050px;
        padding-top: 2.25rem;
        padding-bottom: 5rem;
    }

    html, body, [class*="css"] { font-family: 'Manrope', sans-serif; }
    h1, h2, h3, p, label, span { color: var(--ink); }

    [data-testid="stSidebar"] {
        background: rgba(12, 18, 35, .97);
        border-right: 1px solid rgba(167, 139, 250, .16);
    }

    [data-testid="stSidebar"] > div:first-child { padding-top: 1.4rem; }

    .brand-kicker {
        color: var(--purple);
        font-family: 'DM Mono', monospace;
        font-size: .72rem;
        letter-spacing: .13em;
        text-transform: uppercase;
        margin-bottom: .7rem;
    }

    .brand-title {
        font-size: clamp(2.15rem, 5vw, 3.55rem);
        font-weight: 800;
        letter-spacing: -.065em;
        line-height: 1.04;
        margin: 0;
        color: #fff;
    }

    .brand-title em { color: var(--purple); font-style: normal; }

    .brand-subtitle {
        color: var(--muted);
        font-size: 1rem;
        line-height: 1.65;
        max-width: 39rem;
        margin: 1rem 0 1.75rem;
    }

    .welcome-card {
        background: linear-gradient(115deg, rgba(124, 58, 237, .22), rgba(30, 41, 72, .75));
        border: 1px solid rgba(196, 181, 253, .25);
        border-radius: 18px;
        padding: 1.15rem 1.25rem;
        margin: .5rem 0 1.5rem;
        color: #e9e5ff;
    }

    .welcome-card strong { color: #fff; }

    [data-testid="stChatMessage"] {
        background: var(--surface);
        border: 1px solid rgba(148, 163, 184, .12);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        margin: .75rem 0;
        box-shadow: 0 12px 32px rgba(0, 0, 0, .10);
    }

    [data-testid="stChatMessage"][data-testid*="user"] { background: var(--surface-raised); }
    [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { line-height: 1.65; }

    [data-testid="stChatInput"] {
        background: #18233d;
        border: 1px solid rgba(167, 139, 250, .35);
        border-radius: 15px;
    }

    [data-testid="stChatInput"] textarea, .stTextInput input {
        color: var(--ink) !important;
        background: transparent !important;
    }

    [data-testid="stChatInput"] textarea::placeholder, .stTextInput input::placeholder { color: #8491a8 !important; }
    [data-testid="stFileUploader"] { background: rgba(30, 41, 72, .56); border-radius: 12px; padding: .35rem; }
    [data-testid="stFileUploader"] small { color: var(--muted) !important; }

    .stButton > button {
        background: #7c3aed;
        color: #fff;
        border: 0;
        border-radius: 10px;
        font-weight: 700;
        transition: transform .15s ease, background .15s ease;
    }
    .stButton > button:hover { background: #8b5cf6; color: #fff; transform: translateY(-1px); }

    [data-testid="stSidebar"] .stButton > button { width: 100%; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] small { color: var(--muted) !important; }
    hr { border-color: rgba(148, 163, 184, .16) !important; }
    .footer-note { color: #77839a; text-align: center; font-size: .78rem; margin-top: 2.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# OLLAMA CONNECTION
# ============================================================

@st.cache_resource
def get_client(api_key: str) -> Client:
    """Create one reusable client for the hosted Ollama API."""
    return Client(
        host="https://ollama.com",
        headers={"Authorization": f"Bearer {api_key}"},
    )


def get_api_key() -> str | None:
    """Read the key from Streamlit secrets without displaying it."""
    try:
        return st.secrets["OLLAMA_API_KEY"]
    except (KeyError, FileNotFoundError):
        return None


# ============================================================
# CONVERSATION HELPERS
# ============================================================

SYSTEM_PROMPT = """You are Dharshan's Lil Helper: a capable, friendly, practical AI assistant.
Help with everyday questions, learning, writing, brainstorming, planning, coding, and explaining images.
Use the conversation history to maintain context. Be honest when you are uncertain, never claim to see an
image that was not included, and give clear, useful answers. Format with Markdown only when it improves readability."""

# Fixed image-capable model used by every conversation.
MODEL = "gemma4:31b-cloud"
MAX_HISTORY_MESSAGES = 30


def initialize_session() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []


def encode_image(uploaded_file) -> str:
    """Validate and normalize an upload before sending it to Ollama.

    Converting supported uploads to PNG ensures palette, grayscale, transparency,
    and camera-orientation variations all have one reliable display/send format.
    """
    try:
        source_image = Image.open(BytesIO(uploaded_file.getvalue()))
        source_image.load()
        source_image = ImageOps.exif_transpose(source_image)

        has_transparency = source_image.mode in ("RGBA", "LA") or "transparency" in source_image.info
        normalized_image = source_image.convert("RGBA" if has_transparency else "RGB")
        normalized_bytes = BytesIO()
        normalized_image.save(normalized_bytes, format="PNG", optimize=True)
        return base64.b64encode(normalized_bytes.getvalue()).decode("utf-8")
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("Please choose a valid PNG, JPG, JPEG, or WEBP image.") from error


def history_for_model() -> list[dict]:
    """Return a bounded copy of this conversation in Ollama's chat format."""
    history = []
    for message in st.session_state.messages[-MAX_HISTORY_MESSAGES:]:
        model_message = {
            "role": message["role"],
            "content": message["content"],
        }
        if message.get("images"):
            model_message["images"] = message["images"]
        history.append(model_message)
    return history


def ask_helper(client: Client) -> str:
    """Ask the model using the conversation stored for this browser session."""
    response = client.chat(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history_for_model()],
        options={"temperature": 0.7},
    )
    return response.message.content


def render_message(message: dict) -> None:
    with st.chat_message(message["role"], avatar="✨" if message["role"] == "assistant" else "🙂"):
        if message.get("content"):
            st.markdown(message["content"])
        for image_data in message.get("images", []):
            try:
                # Keep older saved messages safe to preview too.
                image = Image.open(BytesIO(base64.b64decode(image_data)))
                image.load()
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                st.image(image, use_container_width=True)
            except (OSError, ValueError, base64.binascii.Error):
                st.warning("This image was attached, but its preview could not be displayed.")


# ============================================================
# APP
# ============================================================

initialize_session()
api_key = get_api_key()

with st.sidebar:
    st.markdown("### ✨ Lil Helper")
    st.caption("Your private chat controls")
    st.divider()

    st.caption("Using **Gemma 4 Vision** for text and image questions.")

    if st.button("New conversation", icon="➕"):
        st.session_state.messages = []
        st.rerun()

    if st.session_state.messages:
        st.caption(f"This conversation has {len(st.session_state.messages)} messages.")

    st.divider()
    st.markdown("**What I can help with**")
    st.caption("Answer questions, explain concepts, draft writing, brainstorm ideas, help with code, and analyze uploaded images.")

    st.divider()
    st.caption("Your messages are kept in this browser session. Starting a new conversation clears them from the app.")

st.markdown('<div class="brand-kicker">Your everyday AI sidekick</div>', unsafe_allow_html=True)
st.markdown('<h1 class="brand-title">Dharshan’s<br><em>Lil Helper</em></h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="brand-subtitle">Ask anything, work through an idea, or attach an image for a closer look. I remember the conversation while this chat is open.</p>',
    unsafe_allow_html=True,
)

if not api_key:
    st.error("I can’t connect to Ollama yet. Add `OLLAMA_API_KEY` to your Streamlit secrets, then reload this app.")
    st.code('OLLAMA_API_KEY = "your_ollama_api_key"', language="toml")
    st.stop()

client = get_client(api_key)

if not st.session_state.messages:
    st.markdown(
        '<div class="welcome-card"><strong>Hey! I’m ready when you are.</strong><br>Try “Help me make a plan for today,” “Explain this homework problem,” or upload an image and ask what you’d like to know about it.</div>',
        unsafe_allow_html=True,
    )

for saved_message in st.session_state.messages:
    render_message(saved_message)

uploaded_image = st.file_uploader(
    "Attach an image for this message (optional)",
    type=["png", "jpg", "jpeg", "webp"],
    help="Ask a question with the image so the assistant knows what to examine.",
)

user_prompt = st.chat_input("Message Lil Helper…")

if user_prompt:
    try:
        image_payloads = [encode_image(uploaded_image)] if uploaded_image else []
    except ValueError as error:
        st.error(str(error))
        st.stop()

    user_message = {
        "role": "user",
        "content": user_prompt,
        "images": image_payloads,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    st.session_state.messages.append(user_message)
    render_message(user_message)

    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Thinking…"):
            try:
                answer = ask_helper(client)
            except Exception as error:
                answer = None
                st.error(
                    "I couldn’t reach Ollama. Check your API key and connection, then try again."
                )
                with st.expander("Technical details"):
                    st.code(str(error))

        if answer:
            st.markdown(answer)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": answer,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
            )

st.markdown('<p class="footer-note">Dharshan’s Lil Helper · Powered by Ollama</p>', unsafe_allow_html=True)
