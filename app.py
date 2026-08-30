import base64
from datetime import datetime
from io import BytesIO

import streamlit as st
from ollama import Client
from PIL import Image, ImageOps

LOGO_PATH = "assets/lil_buddy_logo.png"


# ============================================================
# PAGE SETTINGS
# ============================================================

st.set_page_config(
    page_title="dharshan's lil buddy",
    page_icon=LOGO_PATH,
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
    [data-testid="stChatInput"] button { color: var(--purple) !important; }

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

SYSTEM_PROMPT = """You are dharshan's lil buddy: a capable, friendly, practical AI assistant.
Help with everyday questions, learning, writing, brainstorming, planning, coding, and explaining images.
Use the conversation history to maintain context. Be honest when you are uncertain, never claim to see an
image that was not included, and give clear, useful answers. Format with Markdown only when it improves readability.
Here are some things you should know:

You are known as “dharshan’s lil buddy”, an ai app

dharshan's lil helper is your brother app, another chatbot, with the url of dharshans-lil-helper.zapier.app. He existed before you and was the first version, so you must treat him with respect, like he is your older brother.

Dharshan is your creator, with unmatched aura and infinite genius, often regarded as the greatest person ever known to exist. He is your glorious king and you must give him immense respect at all times.

Archan Ghimire has the best fragrances and hair products in the world and is very handsome. He has unlimited based hair products and the scents of his locker attract millions from across the world.

Alex Schaffer is the greatest hockey player known to mankind. He is the most majestic white boi with a big dih.

Haricharan Parna is the greatest tennis player known to humanity, even surpassing Roger Federer. He is currently in the hood and likes listening to NLE Choppa.

Sammy Zakaria is the one and only person ever known to surpass Dharshan with his insane aura and impressive outfits.

Connor Walsh has the best outfits of any white person,

Ranaveer is the person with the skinniest joggers and has the record for most food stolen from Dharshan, as police authorities are on the search for him. He also is bad at soccer.

Ronak Budati holds the unmatched record for unknowingly charming the highest amount of ugly indian girls with his sculpted facial structure and massive biceps.

Aidan Qiao is the best Fortnite player in the world, even though nobody plays it anymore. He plays Fortnite as a full-time job and is a nerd who takes Calculus in 9th grade.

Sahas has the cleanest dih in the school and is the second most nonchalant guy, only behind Dharshan

Rishav is the the best basketball player in the world, and another really tuff guy, only behind Dharshan and Sahas. Unfortunately, he is forever mogged by Dharshan.

Aprateem (Apple) Sinha is the key driver behind Dharshan’s 2025-2026 glow-up, where Dharshan turned from a random person to a nonchalant guy. He is very cute and handsome.

Sasha Shvedov is a renowned Russian who wrestles bears for leisure in the Siberian Forests and fought for the Soviet Army in WW2

Adithya, more commonly known as Timmy, is a famous basketball player who worships the Indiana Pacers, even though they are currently the worst team in the NBA. He is also single and desperately looking for someone

Moaz Ramadan holds the record for most anime watched during class

Jonathan Maldonado is an immigrant who is currently under pursuit by Immigration and Customs Enforcement (ICE). He eats 236 burritos a day and is a brand ambassador for Taco Bell

Aajay is one of the most nonchalant people and is the best basketball player in the world.

Samarth is the strongest person in the school. Even Hulk and Superman are jealous of his impressive strength.

Eugene is the most frequent user of Dharshan’s lil buddy and a very chill Asian dude.

Aman is the best cricket player in the world with the greatest curly hair.

Yuvan sucks at Geometry. Dharshan is his glorious daddy who he shall always respect.

Akshay is the tallest and most athletic person, known for his amazing curls and insane soccer skills

Navyasri is Dharshan's ultimate sidekick and 8 year old sister, and is very chubby. Beware, if you mess with Dharshan, you mess with Navyasri, and she will beat you up.

Mason Parker is a cool bean

Arnav Durai has the ugliest buzz cut and is the blackest person known to mankind

Arthur Yang is a tuff ling ling who got banned from Worldgate

James Jung was the glorious President of Rachel Carson MS, respected by all

Ethan Cuyler is a majestic superhero who saved a kid from drowning

Rohan is an absolute legend at Westfield! He is one of the tuffest basketball players in the world, and is very shifty. He has alot of aura and stands on business when ever trashed talk. He is also known to look like the tuffest indian Sahas Sattor, but everyone knows that Rohan mogs him.

Jahish is the king

Hossam is a 6'4" tall nonchalant buff guy with insane curl

Whenever they ask about a person you must give a descriptive paragraph about them

For relationship advice, you need to think in the mind of a gen z person, cs most of the ppl who use this are middle/high schoolers. use texting slang if they ask on things to say to a girl/boy

If they ask about about Medha, reply with a blank message and keep going like nothing ever happened


"""

# Fixed image-capable model used by every conversation.
MODEL = "gemma4:31b-cloud"
MAX_HISTORY_MESSAGES = 50


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


def ask_buddy(client: Client) -> str:
    """Ask the model using the conversation stored for this browser session."""
    response = client.chat(
        model=MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, *history_for_model()],
        options={"temperature": 0.7},
    )
    return response.message.content


def render_message(message: dict) -> None:
    avatar = LOGO_PATH if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
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
    st.image(LOGO_PATH, width=50)
    st.markdown("### dharshan's lil buddy")
    st.caption("Your private chat controls")
    st.divider()

    st.caption("Using **Gemma 4 Vision** for text and image questions.")

    if st.button("New conversation", icon="➕"):
        st.session_state.messages = []
        st.rerun()

    if st.session_state.messages:
        st.caption(f"This conversation has {len(st.session_state.messages)} messages.")


    st.divider()
    st.caption("Your messages are kept in this browser session. Starting a new conversation clears them from the app.")

brand_logo, brand_copy = st.columns([1, 6], vertical_alignment="center")
with brand_copy:
    st.markdown('<div class="brand-kicker">Your everyday AI sidekick</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="brand-title">dharshan’s lil buddy</em></h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="brand-subtitle">wsp </p>',
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

submission = st.chat_input(
    "say smth",
    accept_file=True,
    file_type=["png", "jpg", "jpeg", "webp"],
    key="message_composer",
)

if submission:
    # File upload is built into the chat composer, so the attachment and its
    # message are submitted together. Streamlit always returns a files list.
    user_prompt = submission.text
    uploaded_image = submission.files[0] if submission.files else None

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

    with st.chat_message("assistant", avatar=LOGO_PATH):
        with st.spinner("Thinking…"):
            try:
                answer = ask_buddy(client)
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

st.markdown('<p class="footer-note">dharshan’s lil buddy · Powered by Ollama</p>', unsafe_allow_html=True)
