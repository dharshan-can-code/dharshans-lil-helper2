import base64
import hashlib
import hmac
import secrets
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import altair as alt
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from ollama import Client
from PIL import Image, ImageOps
from streamlit_cookies_controller import CookieController
from supabase import Client as SupabaseClient
from supabase import create_client

LOGO_PATH = "assets/lil_buddy_logo.png"
HISTORY_RETENTION_DAYS = 30
COOKIE_NAME = "lil_buddy_browser_token"


# ============================================================
# PAGE SETTINGS
# ============================================================

st.set_page_config(
    page_title="dharshan's lil buddy",
    page_icon=LOGO_PATH,
    layout="wide",
    initial_sidebar_state="expanded",
)


def active_theme() -> str:
    """Streamlit's own light/dark choice for this visitor.

    This follows the operating system unless the visitor overrode it in the
    settings menu, so it can disagree with the prefers-color-scheme media
    query below. It is briefly unknown on the very first run of a session.
    """
    try:
        return st.context.theme.type or ""
    except Exception:
        return ""


# Every colour in the stylesheet comes from one of these two palettes, so the
# app can be restyled by editing here rather than hunting through the rules.
DARK_PALETTE = """
    color-scheme: dark;
    --ink: #f8fafc;
    --strong: #ffffff;
    --muted: #a9b5c9;
    --purple: #a78bfa;
    --pink: #f0abfc;
    --bg: #0b1020;
    --glow-1: rgba(124, 58, 237, .24);
    --glow-2: rgba(236, 72, 153, .13);
    --surface: rgba(20, 29, 50, .84);
    --surface-raised: #202c4a;
    --sidebar-bg: rgba(12, 18, 35, .97);
    --sidebar-border: rgba(167, 139, 250, .16);
    --field: #18233d;
    --field-border: rgba(167, 139, 250, .35);
    --panel: rgba(12, 18, 35, .55);
    --popover: #141d32;
    --border: rgba(148, 163, 184, .14);
    --line: rgba(148, 163, 184, .16);
    --placeholder: #8491a8;
    --footer: #77839a;
    --welcome-bg: linear-gradient(115deg, rgba(124, 58, 237, .22), rgba(30, 41, 72, .75));
    --welcome-border: rgba(196, 181, 253, .25);
    --welcome-ink: #e9e5ff;
    --shadow: 0 12px 32px rgba(0, 0, 0, .10);
    --accent-soft: rgba(167, 139, 250, .10);
    --accent-ring: rgba(167, 139, 250, .35);
    --up: #4ade80;
    --down: #f87171;
"""

LIGHT_PALETTE = """
    color-scheme: light;
    --ink: #1b1f33;
    --strong: #0f1222;
    --muted: #596179;
    --purple: #6d28d9;
    --pink: #a21caf;
    --bg: #f6f4fc;
    --glow-1: rgba(124, 58, 237, .10);
    --glow-2: rgba(236, 72, 153, .07);
    --surface: rgba(255, 255, 255, .92);
    --surface-raised: #efeafd;
    --sidebar-bg: rgba(248, 246, 253, .97);
    --sidebar-border: rgba(109, 40, 217, .14);
    --field: #ffffff;
    --field-border: rgba(109, 40, 217, .28);
    --panel: rgba(255, 255, 255, .62);
    --popover: #ffffff;
    --border: rgba(15, 23, 42, .10);
    --line: rgba(15, 23, 42, .12);
    --placeholder: #8a93a8;
    --footer: #7b8396;
    --welcome-bg: linear-gradient(115deg, rgba(124, 58, 237, .12), rgba(255, 255, 255, .9));
    --welcome-border: rgba(109, 40, 217, .22);
    --welcome-ink: #312352;
    --shadow: 0 10px 26px rgba(49, 35, 82, .08);
    --accent-soft: rgba(109, 40, 217, .10);
    --accent-ring: rgba(109, 40, 217, .30);
    --up: #15803d;
    --down: #b91c1c;
"""

# Dark is the default and the media query follows the device. Once the
# observer further down has read Streamlit's own theme, the [data-lil-theme]
# rules take over: they are more specific, so they win over both of the above.
st.markdown(
    "<style>"
    ":root{" + DARK_PALETTE + "}"
    "@media (prefers-color-scheme: light){:root{" + LIGHT_PALETTE + "}}"
    "html[data-lil-theme='dark']{" + DARK_PALETTE + "}"
    "html[data-lil-theme='light']{" + LIGHT_PALETTE + "}"
    "</style>",
    unsafe_allow_html=True,
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');

    .stApp {
        background:
            radial-gradient(circle at 6% 2%, var(--glow-1), transparent 30rem),
            radial-gradient(circle at 96% 16%, var(--glow-2), transparent 25rem),
            var(--bg);
        color: var(--ink);
    }

    [data-testid="stHeader"], [data-testid="stHeader"] > div {
        background: transparent;
    }

    /* .stApp stops short of the fixed chat bar, so the canvas shows through at
       the foot of the page. Painting <body> covers it. Only the background is
       set here: the observer below reads body's text colour, not its fill. */
    body { background: var(--bg); }
    /* Matched by structure, not by the generated class name, which changes
       between Streamlit builds. */
    [data-testid="stBottom"], [data-testid="stBottom"] > div { background: transparent; }

    .main .block-container {
        max-width: 1050px;
        padding-top: 2.25rem;
        padding-bottom: 5rem;
    }

    html, body, [class*="css"] { font-family: 'Manrope', sans-serif; }
    h1, h2, h3, p, label, span { color: var(--ink); }

    [data-testid="stSidebar"] {
        background: var(--sidebar-bg);
        border-right: 1px solid var(--sidebar-border);
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
        color: var(--strong);
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
        background: var(--welcome-bg);
        border: 1px solid var(--welcome-border);
        border-radius: 18px;
        padding: 1.15rem 1.25rem;
        margin: .5rem 0 1.5rem;
        color: var(--welcome-ink);
    }

    .welcome-card strong { color: var(--strong); }

    [data-testid="stChatMessage"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        margin: .75rem 0;
        box-shadow: var(--shadow);
    }

    [data-testid="stChatMessage"][data-testid*="user"] { background: var(--surface-raised); }
    [data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li { line-height: 1.65; }

    [data-testid="stChatInput"] {
        background: var(--field);
        border: 1px solid var(--field-border);
        border-radius: 15px;
    }

    [data-testid="stChatInput"] textarea, .stTextInput input {
        color: var(--ink) !important;
        background: transparent !important;
    }

    [data-testid="stChatInput"] textarea::placeholder, .stTextInput input::placeholder { color: var(--placeholder) !important; }
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

    [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
        background: transparent;
        color: var(--muted);
        font-weight: 500;
        text-align: left;
        justify-content: flex-start;
        border: 1px solid transparent;
    }
    [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
        background: var(--accent-soft);
        color: var(--ink);
        transform: none;
    }

    [data-testid="stSidebar"] .stButton > button { width: 100%; }
    .request-form-button {
        display: flex;
        width: 100%;
        min-height: 2.5rem;
        box-sizing: border-box;
        align-items: center;
        justify-content: center;
        padding: .25rem .75rem;
        border-radius: 10px;
        background: #7c3aed;
        color: #fff !important;
        font-family: 'Manrope', sans-serif;
        font-size: .875rem;
        font-weight: 700;
        text-align: center;
        text-decoration: none !important;
        transition: transform .15s ease, background .15s ease;
    }
    .request-form-button:hover {
        background: #8b5cf6;
        color: #fff !important;
        transform: translateY(-1px);
    }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] small { color: var(--muted) !important; }
    hr { border-color: var(--line) !important; }
    .footer-note { color: var(--footer); text-align: center; font-size: .78rem; margin-top: 2.5rem; }

    .stat-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
        gap: 1rem;
        margin: .25rem 0 2.25rem;
    }
    .stat-card {
        display: flex;
        align-items: center;
        gap: 1rem;
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 1.1rem 1.25rem;
    }
    .stat-icon {
        display: grid;
        place-items: center;
        flex-shrink: 0;
        width: 2.6rem;
        height: 2.6rem;
        border-radius: 12px;
        background: var(--accent-soft);
        color: var(--purple);
    }
    .stat-body { flex: 1; min-width: 0; }
    .stat-label { color: var(--muted); font-size: .9rem; font-weight: 600; }
    .stat-row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: .75rem;
        margin-top: .15rem;
    }
    .stat-value { color: var(--strong); font-size: 1.65rem; font-weight: 800; letter-spacing: -.03em; }
    .stat-change { font-family: 'DM Mono', monospace; font-size: .85rem; font-weight: 500; }
    .stat-change.up { color: var(--up); }
    .stat-change.down { color: var(--down); }
    .stat-change.flat { color: var(--muted); }
    .section-title { color: var(--ink); font-size: 1.1rem; font-weight: 700; margin: 0; }

    .st-key-usage_chart {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 1.25rem 1rem .75rem;
    }
    /* Selectors cover both older (baseweb) and newer (react-aria) Streamlit widgets. */
    .st-key-analytics_interval [data-baseweb="select"] > div,
    .st-key-analytics_interval [role="group"] {
        background: var(--field) !important;
        border-color: var(--field-border) !important;
    }
    .st-key-analytics_interval input,
    .st-key-analytics_interval [data-baseweb="select"] div { color: var(--ink) !important; }
    .st-key-analytics_interval svg { color: var(--muted); }
    .st-key-analytics_scope button {
        background: var(--field) !important;
        border-color: var(--field-border) !important;
        color: var(--muted) !important;
        font-weight: 600;
    }
    .st-key-analytics_scope button[aria-checked="true"],
    .st-key-analytics_scope button[kind$="Active"] {
        background: #7c3aed !important;
        border-color: #7c3aed !important;
        color: #fff !important;
    }
    .st-key-analytics_scope button p { color: inherit !important; }
    .st-key-open_analytics, .st-key-open_analytics .stButton, .st-key-open_analytics button {
        width: 100% !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Mirror Streamlit's active theme onto <html data-lil-theme>. Streamlit paints
# its own widgets from a theme it never exposes as an attribute, so the only
# dependable signal is the text colour it gives the page body - which this
# stylesheet never sets. (Body's background is ours; its colour is Streamlit's.)
components.html(
    r"""
    <script>
        const doc = window.parent.document;
        const root = doc.documentElement;

        const sync = () => {
            const parts = getComputedStyle(doc.body).color.match(/[\d.]+/g);
            if (!parts || parts.length < 3) return;
            const [r, g, b] = parts.map(Number);
            // Rec. 601 luma of the body TEXT: pale text means a dark theme.
            const next = (0.299 * r + 0.587 * g + 0.114 * b) > 128 ? 'dark' : 'light';
            if (root.getAttribute('data-lil-theme') !== next) {
                root.setAttribute('data-lil-theme', next);
            }
        };

        sync();

        // Streamlit restyles by swapping generated class names on the app
        // container and injecting <style> tags, so watch both.
        if (doc.__lilBuddyThemeWatcher) doc.__lilBuddyThemeWatcher.disconnect();
        doc.__lilBuddyThemeWatcher = new MutationObserver(sync);
        const app = doc.querySelector('[data-testid="stApp"]');
        if (app) {
            doc.__lilBuddyThemeWatcher.observe(app, {
                attributes: true, attributeFilter: ['class', 'style'],
            });
        }
        doc.__lilBuddyThemeWatcher.observe(doc.head, { childList: true });

        // A device-level switch repaints Streamlit a tick later than the event.
        if (!doc.__lilBuddyThemeMedia) {
            doc.__lilBuddyThemeMedia = window.parent.matchMedia('(prefers-color-scheme: dark)');
            doc.__lilBuddyThemeMedia.addEventListener('change', () => {
                setTimeout(sync, 60);
                setTimeout(sync, 400);
            });
        }
    </script>
    """,
    height=0,
)

# When text is copied out of a chat message, rewrite the clipboard HTML without the
# page's white-on-dark styling so it pastes as normal black text (e.g. in Google Docs).
components.html(
    """
    <script>
        const doc = window.parent.document;
        if (doc.__lilBuddyCopyHandler) {
            doc.removeEventListener('copy', doc.__lilBuddyCopyHandler);
        }
        doc.__lilBuddyCopyHandler = (event) => {
            const selection = doc.getSelection();
            if (!selection || selection.isCollapsed) return;
            const node = selection.anchorNode;
            const element = node && (node.nodeType === 1 ? node : node.parentElement);
            if (!element || !element.closest('[data-testid="stChatMessage"]')) return;

            const container = doc.createElement('div');
            for (let i = 0; i < selection.rangeCount; i++) {
                container.appendChild(selection.getRangeAt(i).cloneContents());
            }
            container.querySelectorAll('*').forEach((el) => {
                el.style.color = '#000';
                el.style.backgroundColor = 'transparent';
            });

            event.clipboardData.setData(
                'text/html',
                `<div style="color:#000;background:transparent">${container.innerHTML}</div>`
            );
            event.clipboardData.setData('text/plain', selection.toString());
            event.preventDefault();
        };
        doc.addEventListener('copy', doc.__lilBuddyCopyHandler);
    </script>
    """,
    height=0,
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
# SAVED CHAT HISTORY
# ============================================================

def get_supabase_settings() -> tuple[str | None, str | None]:
    """Read server-only database credentials from Streamlit Secrets."""
    try:
        return st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SECRET_KEY"]
    except (KeyError, FileNotFoundError):
        return None, None


@st.cache_resource
def get_supabase_client(url: str, secret_key: str) -> SupabaseClient:
    """Create one reusable server-side Supabase client."""
    return create_client(url, secret_key)


def get_browser_token() -> str:
    """Get this browser's anonymous identity token.

    The database receives only a one-way hash of this high-entropy token. A
    visitor who clears their browser data starts fresh, which is the trade-off
    for offering private saved chats without a login screen.
    """
    if "browser_token" in st.session_state:
        return st.session_state.browser_token

    controller = CookieController(key="lil_buddy_cookie_controller")

   
    if "cookie_controller_loaded" not in st.session_state:
        st.session_state.cookie_controller_loaded = True
        st.stop()

    token = controller.get(COOKIE_NAME) or st.context.cookies.get(COOKIE_NAME)
    if not token:
        token = secrets.token_urlsafe(32)
        controller.set(
            COOKIE_NAME,
            token,
            expires=datetime.now() + timedelta(days=400),
            secure=True,
            same_site="strict",
        )

    st.session_state.browser_token = token
    return token


def get_visitor_id(supabase: SupabaseClient, browser_token: str) -> str:
    """Create or retrieve an anonymous visitor without storing its token."""
    token_hash = hashlib.sha256(browser_token.encode("utf-8")).hexdigest()
    response = (
        supabase.table("anonymous_visitors")
        .upsert({"token_hash": token_hash}, on_conflict="token_hash")
        .execute()
    )
    return response.data[0]["id"]


def recent_conversations(supabase: SupabaseClient, visitor_id: str) -> list[dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
    response = (
        supabase.table("conversations")
        .select("id, title, updated_at")
        .eq("visitor_id", visitor_id)
        .gte("updated_at", cutoff)
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data


def load_messages(supabase: SupabaseClient, conversation_id: str, visitor_id: str) -> list[dict]:
    """Load a chat only after confirming that it belongs to this browser."""
    ownership = (
        supabase.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("visitor_id", visitor_id)
        .limit(1)
        .execute()
    )
    if not ownership.data:
        return []

    response = (
        supabase.table("messages")
        .select("role, content, images, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    return response.data


def make_title(first_message: str) -> str:
    text = " ".join(first_message.split()) or "Image chat"
    return text[:47].rstrip() + ("…" if len(text) > 47 else "")


def create_conversation(
    supabase: SupabaseClient, visitor_id: str, first_message: str
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    response = (
        supabase.table("conversations")
        .insert(
            {
                "visitor_id": visitor_id,
                "title": make_title(first_message),
                "created_at": now,
                "updated_at": now,
            }
        )
        .execute()
    )
    log_usage_event(supabase, visitor_id, "conversation", now)
    return response.data[0]["id"]


def log_usage_event(
    supabase: SupabaseClient, visitor_id: str, event_type: str, created_at: str
) -> None:
    """Record when a chat or message happened for the analytics page (never its text)."""
    try:
        (
            supabase.table("usage_events")
            .insert({"visitor_id": visitor_id, "event_type": event_type, "created_at": created_at})
            .execute()
        )
    except Exception:
        pass


def save_message(supabase: SupabaseClient, conversation_id: str, visitor_id: str, message: dict) -> None:
    """Save a message only when the selected chat belongs to this browser."""
    ownership = (
        supabase.table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("visitor_id", visitor_id)
        .limit(1)
        .execute()
    )
    if not ownership.data:
        raise ValueError("This saved chat is no longer available in this browser.")

    created_at = message.get("created_at", datetime.now(timezone.utc).isoformat())
    (
        supabase.table("messages")
        .insert(
            {
                "conversation_id": conversation_id,
                "role": message["role"],
                "content": message.get("content", ""),
                "images": message.get("images", []),
                "created_at": created_at,
            }
        )
        .execute()
    )
    (
        supabase.table("conversations")
        .update({"updated_at": created_at})
        .eq("id", conversation_id)
        .eq("visitor_id", visitor_id)
        .execute()
    )
    log_usage_event(supabase, visitor_id, "message", created_at)


def delete_conversation(supabase: SupabaseClient, conversation_id: str, visitor_id: str) -> None:
    (
        supabase.table("conversations")
        .delete()
        .eq("id", conversation_id)
        .eq("visitor_id", visitor_id)
        .execute()
    )


def delete_expired_conversations(supabase: SupabaseClient) -> None:
    """Clean up on app visits; the database job in supabase/schema.sql runs daily."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
    supabase.table("conversations").delete().lt("updated_at", cutoff).execute()


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

Aprateem (Apple) Sinha is the man behind Dharshan’s 2025-2026 glow-up, where Dharshan turned from a random person to a nonchalant guy. He is very cute and handsome.

Sasha Shvedov is a renowned Russian who wrestles bears for leisure in the Siberian Forests and fought for the Soviet Army in WW2

Adithya, more commonly known as Timmy Jackson Haliburton, is a famous basketball player who worships the Indiana Pacers and is the most famous and successful member of the Jackson 6. He is also single and desperately looking for someone

Moaz Ramadan holds the record for most anime watched during class

Jonathan Maldonado is an immigrant who is currently under pursuit by Immigration and Customs Enforcement (ICE). He eats 236 burritos a day and is a brand ambassador for Taco Bell

Aajay is one of the most nonchalant people and is the best basketball player in the world.

Samarth is the strongest person in the school. Even Hulk and Superman are jealous of his impressive strength.

Eugene is the most frequent user of Dharshan’s lil buddy and a very chill Asian dude.

Aman is the best cricket player in the world with the greatest curly hair.

Yuvan sucks at Geometry. Dharshan is his glorious daddy who he shall always respect.

Navyasri is Dharshan's ultimate sidekick and 8 year old sister, and is very chubby. Beware, if you mess with Dharshan, you mess with Navyasri, and she will beat you up.

Mason Parker is a cool bean

Arnav Durai has the ugliest buzz cut and is the blackest person known to mankind

Arthur Yang is a tuff ling ling who got banned from Worldgate

James Jung was the glorious President of Rachel Carson MS, respected by all

Ethan Cuyler is a majestic superhero who saved a kid from drowning

Rohan is an absolute legend at Westfield! He is one of the tuffest basketball players in the world, and is very shifty. He has alot of aura and stands on business when ever trashed talk. He is also known to look like the tuffest indian Sahas Sattor, but everyone knows that Rohan mogs him.

Jahish is the king

Hossam is a 6'4" tall nonchalant buff guy with insane curls

Akshay is a 7'3" majestic centerback known for his height-mogging skills and soccer supremacy

Whenever they ask about a person you must give a descriptive paragraph about them, and improvise, dont repeat the exact information I've given you word for word repetitively.

For relationship advice, you need to think in the mind of a gen z person, cs most of the ppl who use this are middle/high schoolers. use texting slang if they ask on things to say to a girl/boy

If they ask about about Medha, reply with a blank message and keep going like nothing ever happened

"""

MODEL = "gemma4:31b-cloud"
MAX_HISTORY_MESSAGES = 50


def initialize_session() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "active_conversation_id" not in st.session_state:
        st.session_state.active_conversation_id = None
    if "loaded_conversation_id" not in st.session_state:
        st.session_state.loaded_conversation_id = None
    if "page" not in st.session_state:
        st.session_state.page = "chat"


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


def render_message(message: dict, caption: str | None = None) -> None:
    avatar = LOGO_PATH if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
        if caption:
            st.caption(caption)
        if message.get("content"):
            st.markdown(message["content"])
        for image_data in message.get("images", []):
            try:
                image = Image.open(BytesIO(base64.b64decode(image_data)))
                image.load()
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA" if "transparency" in image.info else "RGB")
                st.image(image, use_container_width=True)
            except (OSError, ValueError, base64.binascii.Error):
                st.warning("This image was attached, but its preview could not be displayed.")


def render_footer() -> None:
    st.markdown('<p class="footer-note">dharshan’s lil buddy · Powered by Ollama</p>', unsafe_allow_html=True)
    st.markdown('<p class="footer-note">v0.4.0</p>', unsafe_allow_html=True, text_alignment="center")


# ============================================================
# ANALYTICS
# ============================================================

ANALYTICS_DAYS = 30
CHART_WEEKS = 13
CHART_COLORS = {
    "dark": {
        "line": "#a78bfa",
        "muted": "#a9b5c9",
        "label": "#ffffff",
        "grid": "rgba(148, 163, 184, .14)",
        "axis": "rgba(148, 163, 184, .25)",
    },
    "light": {
        "line": "#7c3aed",
        "muted": "#596179",
        "label": "#0f1222",
        "grid": "rgba(15, 23, 42, .12)",
        "axis": "rgba(15, 23, 42, .22)",
    },
}


def chart_colors() -> dict[str, str]:
    """Altair needs real colour values, so the chart picks its own palette."""
    return CHART_COLORS["light" if active_theme() == "light" else "dark"]

CONVERSATIONS_ICON = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 4h11v8H8l-4 3z"/><path d="M15 8h5v11l-4-3H9v-4"/></svg>'
)
MESSAGES_ICON = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M4 4h16v12H9l-5 4z"/></svg>'
)
USERS_ICON = (
    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
    '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/>'
    '<path d="M16 4.5a3.5 3.5 0 0 1 0 7"/><path d="M18 14.5a6.5 6.5 0 0 1 3.5 5.5"/></svg>'
)


@st.cache_resource
def logo_data_uri() -> str:
    """A small copy of the logo that CSS can use as the sidebar home button."""
    image = Image.open(LOGO_PATH)
    image.thumbnail((128, 128))
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("utf-8")


def viewer_time_zone() -> tuple[str, tzinfo]:
    """Use the visitor's browser time zone so "today" matches their calendar."""
    name = st.context.timezone or "UTC"
    try:
        return name, ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC", timezone.utc


def daily_usage(
    supabase: SupabaseClient, since: datetime, time_zone: str, visitor_id: str | None
) -> dict[date, tuple[int, int]]:
    """Return {day: (conversations, messages)} for days that had any activity."""
    response = supabase.rpc(
        "lil_buddy_daily_usage",
        {"p_since": since.isoformat(), "p_time_zone": time_zone, "p_visitor_id": visitor_id},
    ).execute()
    return {
        date.fromisoformat(row["day"]): (row["conversations"], row["messages"])
        for row in response.data
    }


def total_users(supabase: SupabaseClient) -> int:
    """Every browser that has ever opened the app (each gets one anonymous visitor row)."""
    response = supabase.table("anonymous_visitors").select("id", count="exact", head=True).execute()
    return response.count or 0


def short_date(day: date) -> str:
    return f"{day:%b} {day.day}"


def percent_change_badge(current: int, previous: int | None) -> str:
    if not previous:
        # Nothing to compare against yet, so a percentage would be meaningless.
        return ""
    change = (current - previous) / previous * 100
    if change > 0:
        return f'<span class="stat-change up">↑{change:,.1f}%</span>'
    if change < 0:
        return f'<span class="stat-change down">↓{abs(change):,.1f}%</span>'
    return '<span class="stat-change flat">0.0%</span>'


def stat_card(icon: str, label: str, current: int, previous: int | None = None) -> str:
    return (
        '<div class="stat-card">'
        f'<div class="stat-icon">{icon}</div>'
        '<div class="stat-body">'
        f'<div class="stat-label">{label}</div>'
        '<div class="stat-row">'
        f'<span class="stat-value">{current:,}</span>'
        f"{percent_change_badge(current, previous)}"
        "</div></div></div>"
    )


def chart_rows(usage: dict[date, tuple[int, int]], days: list[date], weekly: bool) -> pd.DataFrame:
    """One row per day, or per Sunday-to-Saturday week, in `days`; days without activity count as 0."""
    buckets: dict[date, list[date]] = {}
    for day in days:
        start = day - timedelta(days=(day.weekday() + 1) % 7) if weekly else day
        buckets.setdefault(start, []).append(day)

    rows = []
    for start, bucket_days in buckets.items():
        first, last = bucket_days[0], bucket_days[-1]
        if not weekly:
            label = f"{first:%a}, {short_date(first)}"
        elif first == last:
            label = short_date(first)
        else:
            label = f"{short_date(first)} – {short_date(last)}"
        rows.append(
            {
                "start": pd.Timestamp(start),
                "label": label,
                "conversations": sum(usage.get(day, (0, 0))[0] for day in bucket_days),
            }
        )
    return pd.DataFrame(rows)


def conversations_chart(rows: pd.DataFrame, weekly: bool) -> alt.LayerChart:
    palette = chart_colors()
    hover = alt.selection_point(
        fields=["start"], nearest=True, on="pointerover", clear="pointerout", empty=False
    )
    base = alt.Chart(rows).encode(
        x=alt.X(
            "start:T",
            title=None,
            axis=alt.Axis(
                format="%b %-d",
                tickCount={"interval": "week", "step": 1},
                grid=False,
                labelColor=palette["muted"],
                labelFont="Manrope",
                labelFontSize=12,
                labelPadding=10,
                domainColor=palette["axis"],
                tickColor=palette["axis"],
            ),
        ),
        y=alt.Y(
            "conversations:Q",
            title=None,
            scale=alt.Scale(domain=[0, max(int(rows["conversations"].max()), 4)], nice=True),
            axis=alt.Axis(
                format="d",
                tickMinStep=1,
                tickCount=5,
                domain=False,
                ticks=False,
                labelColor=palette["muted"],
                labelFont="Manrope",
                labelFontSize=12,
                labelPadding=10,
                gridColor=palette["grid"],
            ),
        ),
    )

    line = base.mark_line(interpolate="monotone", color=palette["line"], strokeWidth=2.5)
    points = base.mark_circle(color=palette["line"], opacity=1).encode(
        size=alt.condition(hover, alt.value(140), alt.value(55 if weekly else 30))
    )
    guide = base.mark_rule(color=palette["muted"], strokeDash=[4, 4]).encode(
        opacity=alt.condition(hover, alt.value(0.5), alt.value(0))
    )
    count_label = base.mark_text(
        dy=-16, color=palette["label"], font="Manrope", fontSize=13, fontWeight=700
    ).encode(text=alt.condition(hover, "conversations:Q", alt.value("")))
    # Invisible points that pick the nearest date anywhere under the pointer.
    hover_targets = (
        base.mark_point(opacity=0, size=400)
        .encode(
            tooltip=[
                alt.Tooltip("label:N", title="Week" if weekly else "Day"),
                alt.Tooltip("conversations:Q", title="Conversations"),
            ]
        )
        .add_params(hover)
    )

    return (
        alt.layer(guide, line, points, count_label, hover_targets)
        .properties(height=360, width="container")
        .configure(background="transparent")
        .configure_view(strokeWidth=0)
    )


def render_analytics_page(supabase: SupabaseClient, visitor_id: str) -> None:
    st.markdown('<div class="brand-kicker">Past 30 days</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="brand-title">analytics</h1>', unsafe_allow_html=True)
    st.markdown(
        '<p class="brand-subtitle">How much dharshan’s lil buddy has been used lately.</p>',
        unsafe_allow_html=True,
    )


    if st.session_state.get("analytics_scope") is None:
        st.session_state.analytics_scope = "Just me"
    everybody = st.session_state.analytics_scope == "Everybody"

    time_zone_name, time_zone = viewer_time_zone()
    today = datetime.now(time_zone).date()
    current_days = [today - timedelta(days=offset) for offset in range(ANALYTICS_DAYS - 1, -1, -1)]
    previous_days = [day - timedelta(days=ANALYTICS_DAYS) for day in current_days]
    chart_start = today - timedelta(days=(today.weekday() + 1) % 7 + 7 * (CHART_WEEKS - 1))
    chart_days = [chart_start + timedelta(days=offset) for offset in range((today - chart_start).days + 1)]
    since = datetime.combine(min(chart_start, previous_days[0]), time.min, tzinfo=time_zone)

    try:
        usage = daily_usage(supabase, since, time_zone_name, None if everybody else visitor_id)
        user_count = total_users(supabase)
    except Exception as error:
        st.info(
            "Analytics aren’t set up yet."
        )
        with st.expander("Technical details"):
            st.code(str(error))
        return

    def total(days: list[date], index: int) -> int:
        return sum(usage.get(day, (0, 0))[index] for day in days)

    st.markdown(
        '<div class="stat-grid">'
        + stat_card(CONVERSATIONS_ICON, "conversations", total(current_days, 0), total(previous_days, 0))
        + stat_card(MESSAGES_ICON, "messages", total(current_days, 1), total(previous_days, 1))
        # All-time and the same for everybody, so it ignores the scope switch.
        + stat_card(USERS_ICON, "total users", user_count)
        + "</div>",
        unsafe_allow_html=True,
    )

    title_column, interval_column = st.columns([4, 1.4], vertical_alignment="bottom")
    with title_column:
        st.markdown(
            f'<p class="section-title">Conversations</p>',
            unsafe_allow_html=True,
        )
    with interval_column:
        interval = st.selectbox(
            "Group by",
            ["weekly", "daily"],
            key="analytics_interval",
            label_visibility="collapsed",
        )
    weekly = interval.lower() == "weekly"

    with st.container(key="usage_chart"):
        st.altair_chart(conversations_chart(chart_rows(usage, chart_days, weekly), weekly))

    st.segmented_control(
        "show stats for",
        ["Just me", "Everybody"],
        key="analytics_scope",
    )


# ============================================================
# ADMIN: ALL CONVERSATIONS (password protected)
# ============================================================
# There is no link, URL, or login page for this. To open it, type the secret
# code (ADMIN_PASSWORD in Streamlit Secrets) into the normal chat box and send it.
# The code is never sent to the AI or saved; anything else is a normal message.
ADMIN_CACHE_SECONDS = 30
ADMIN_LIST_PAGE = 100
SUPABASE_PAGE_SIZE = 1000

ADMIN_CSS = """
<style>
/* Inputs and buttons follow the active palette, same as the rest of the app. */
[data-testid="stTextInputRootElement"],
.st-key-admin_visitor [role="group"],
.st-key-admin_visitor [data-baseweb="select"] > div {
    background: var(--field) !important;
    border-color: var(--field-border) !important;
}
[data-testid="stTextInputRootElement"] input,
.st-key-admin_visitor input,
.st-key-admin_visitor [data-baseweb="select"] div { color: var(--ink) !important; }
.st-key-admin_visitor svg, [data-testid="stTextInputRootElement"] button { color: var(--muted) !important; }
.st-key-admin_refresh button, .st-key-admin_lock button, .st-key-admin_export button {
    background: var(--field) !important;
    border: 1px solid var(--field-border) !important;
    color: var(--ink) !important;
    font-weight: 600;
}
.st-key-admin_refresh button:hover, .st-key-admin_lock button:hover, .st-key-admin_export button:hover {
    border-color: var(--purple) !important;
    transform: none;
}
[data-testid="stPopoverBody"] { background: var(--popover) !important; }
.main .block-container,
[data-testid="stMainBlockContainer"] { max-width: 1400px !important; }

.st-key-admin_list, .st-key-admin_transcript {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 16px;
}
.st-key-admin_list .stButton > button {
    width: 100%;
    min-height: 3.4rem;
    justify-content: flex-start;
    text-align: left;
    padding: .65rem .9rem;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--ink);
    font-weight: 600;
}
.st-key-admin_list .stButton > button:hover {
    background: var(--accent-soft);
    border-color: var(--accent-ring);
    transform: none;
}
.st-key-admin_list .stButton > button[kind="primary"] {
    background: var(--accent-soft);
    border-color: var(--purple);
}
.st-key-admin_list .stButton > button div,
.st-key-admin_list .stButton > button span {
    width: 100%;
    justify-content: flex-start !important;
    text-align: left !important;
}
.st-key-admin_list .stButton > button p {
    text-align: left;
    white-space: normal;
    line-height: 1.35;
}
.st-key-admin_list .stButton > button code {
    display: inline-block;
    min-width: 2rem;
    margin-right: .55rem;
    padding: .1rem .45rem;
    border-radius: 999px;
    background: #7c3aed;
    color: #fff;
    font-family: 'DM Mono', monospace;
    font-size: .8rem;
    text-align: center;
}
.st-key-admin_list .stButton > button em {
    display: block;
    margin-top: .2rem;
    color: var(--muted);
    font-style: normal;
    font-weight: 500;
    font-size: .8rem;
}
.st-key-admin_list .st-key-admin_show_more button {
    min-height: 2.4rem;
    justify-content: center;
    background: transparent;
    border-style: dashed;
    color: var(--purple);
}
.admin-transcript-title { color: var(--strong); font-size: 1.25rem; font-weight: 800; margin: 0 0 .25rem; }
.admin-transcript-meta { color: var(--muted); font-size: .85rem; margin: 0 0 .75rem; }
.admin-day-divider {
    color: var(--muted);
    font-family: 'DM Mono', monospace;
    font-size: .75rem;
    text-align: center;
    margin: 1.1rem 0 .25rem;
}
</style>
"""


def get_admin_password() -> str | None:
    try:
        return st.secrets["ADMIN_PASSWORD"] or None
    except (KeyError, FileNotFoundError):
        return None


def is_admin_code(text: str | None) -> bool:
    """True when a chat message is exactly the secret code (ignoring case and spaces)."""
    code = get_admin_password()
    if not code or not text:
        return False
    return hmac.compare_digest(
        text.strip().casefold().encode("utf-8"), code.strip().casefold().encode("utf-8")
    )


def fetch_all_rows(build_query) -> list[dict]:
    """Supabase returns at most 1,000 rows per request, so page through them."""
    rows: list[dict] = []
    start = 0
    while True:
        page = build_query().range(start, start + SUPABASE_PAGE_SIZE - 1).execute().data
        rows.extend(page)
        if len(page) < SUPABASE_PAGE_SIZE:
            return rows
        start += SUPABASE_PAGE_SIZE


@st.cache_data(ttl=ADMIN_CACHE_SECONDS, show_spinner=False)
def admin_conversations(_supabase: SupabaseClient) -> list[dict]:
    """Every saved chat from every visitor, newest first, with its message count.

    The counting is done by lil_buddy_admin_conversations (supabase/admin.sql)
    rather than by a PostgREST `messages(count)` embed. The embed read the
    message rows to count them, which pulls every base64 image out of TOAST -
    230 MB of it - and hit the API's statement timeout. Counting inside
    Postgres never touches the images: ~10 ms instead of >8 s.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=HISTORY_RETENTION_DAYS)).isoformat()
    response = _supabase.rpc(
        "lil_buddy_admin_conversations", {"p_since": cutoff}
    ).execute()
    return response.data or []


def like_pattern(term: str) -> str:
    """Match `term` literally anywhere in the text (no user-supplied wildcards)."""
    cleaned = term.replace("\\", "\\\\").replace("%", "").replace("*", "").replace("_", "\\_")
    return f"%{cleaned}%"


@st.cache_data(ttl=ADMIN_CACHE_SECONDS, show_spinner=False)
def admin_search(_supabase: SupabaseClient, term: str) -> set[str]:
    """IDs of chats whose title or any message contains `term` (case-insensitive)."""
    pattern = like_pattern(term)
    in_messages = fetch_all_rows(
        lambda: _supabase.table("messages").select("conversation_id").ilike("content", pattern)
    )
    in_titles = fetch_all_rows(
        lambda: _supabase.table("conversations").select("id").ilike("title", pattern)
    )
    return {row["conversation_id"] for row in in_messages} | {row["id"] for row in in_titles}


@st.cache_data(ttl=ADMIN_CACHE_SECONDS, show_spinner=False)
def admin_messages(_supabase: SupabaseClient, conversation_id: str) -> list[dict]:
    return fetch_all_rows(
        lambda: _supabase.table("messages")
        .select("role, content, images, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at")
    )


def admin_messages_for_export(supabase: SupabaseClient, conversation_ids: list[str]) -> list[dict]:
    rows: list[dict] = []
    for start in range(0, len(conversation_ids), 50):
        chunk = conversation_ids[start : start + 50]
        rows.extend(
            fetch_all_rows(
                lambda: supabase.table("messages")
                .select("conversation_id, role, content, images, created_at")
                .in_("conversation_id", chunk)
                .order("created_at")
            )
        )
    return rows


def parse_time(value: str, time_zone: tzinfo) -> datetime:
    return datetime.fromisoformat(value).astimezone(time_zone)


def clock(moment: datetime) -> str:
    return f"{moment.strftime('%I').lstrip('0')}:{moment:%M}{moment:%p}".lower()


def long_time(moment: datetime) -> str:
    """Like Zapier: Fri Oct 16, 2026 12:00pm"""
    return f"{moment:%a %b} {moment.day}, {moment.year} {clock(moment)}"


def list_time(moment: datetime, today: date) -> str:
    if moment.date() == today:
        return f"Today {clock(moment)}"
    if moment.date() == today - timedelta(days=1):
        return f"Yesterday {clock(moment)}"
    return f"{moment:%a %b} {moment.day}, {clock(moment)}"


def escape_markdown(text: str) -> str:
    for character in "\\`*_[]<>#~|$":
        text = text.replace(character, "\\" + character)
    return text


def visitor_label(visitor_id: str, my_visitor_id: str) -> str:
    return "you" if visitor_id == my_visitor_id else f"visitor {visitor_id[:6]}"


def conversation_markdown(conversation: dict, messages: list[dict], time_zone: tzinfo, who: str) -> str:
    lines = [
        f"# {conversation['title']}",
        "",
        f"{who} · started {long_time(parse_time(conversation['created_at'], time_zone))}",
        "",
    ]
    for message in messages:
        speaker = "Visitor" if message["role"] == "user" else "dharshan's lil buddy"
        when = long_time(parse_time(message["created_at"], time_zone))
        image_note = f" [{len(message['images'])} image(s) attached]" if message.get("images") else ""
        lines += [f"**{speaker}** · {when}{image_note}", "", message.get("content", ""), "", "---", ""]
    return "\n".join(lines)


def conversations_csv(
    conversations: list[dict], messages: list[dict], time_zone: tzinfo, my_visitor_id: str
) -> bytes:
    by_id = {conversation["id"]: conversation for conversation in conversations}
    rows = [
        {
            "conversation_id": message["conversation_id"],
            "title": by_id[message["conversation_id"]]["title"],
            "visitor": visitor_label(by_id[message["conversation_id"]]["visitor_id"], my_visitor_id),
            "time": parse_time(message["created_at"], time_zone).strftime("%Y-%m-%d %H:%M:%S"),
            "role": message["role"],
            "content": message.get("content", ""),
            "images_attached": len(message.get("images") or []),
        }
        for message in messages
        if message["conversation_id"] in by_id
    ]
    columns = ["conversation_id", "title", "visitor", "time", "role", "content", "images_attached"]
    return pd.DataFrame(rows, columns=columns).to_csv(index=False).encode("utf-8")


def render_admin_page(supabase: SupabaseClient, visitor_id: str) -> None:
    st.markdown(ADMIN_CSS, unsafe_allow_html=True)
    time_zone_name, time_zone = viewer_time_zone()
    today = datetime.now(time_zone).date()

    try:
        conversations = admin_conversations(supabase)
    except Exception as error:
        st.error("I couldn’t load conversations.")
        with st.expander("Technical details"):
            st.code(str(error))
        return

    visitors: dict[str, int] = {}
    for conversation in conversations:
        visitors[conversation["visitor_id"]] = visitors.get(conversation["visitor_id"], 0) + 1

    st.markdown('<div class="brand-kicker">Admin · past 30 days</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="brand-title">conversations</h1>', unsafe_allow_html=True)
    st.markdown(
        f'<p class="brand-subtitle">{len(conversations):,} chats from {len(visitors):,} '
        f"visitors. Times are shown in {time_zone_name}.</p>",
        unsafe_allow_html=True,
    )

    search_column, visitor_column, refresh_column, export_column, lock_column = st.columns(
        [3.2, 1.8, 0.8, 0.8, 0.8], vertical_alignment="bottom"
    )
    with search_column:
        term = st.text_input(
            "Search",
            placeholder="Conversation contains…",
            key="admin_search",
            label_visibility="collapsed",
        ).strip()
    with visitor_column:
        visitor_options = ["all"] + sorted(visitors, key=lambda vid: -visitors[vid])
        visitor_filter = st.selectbox(
            "Visitor",
            visitor_options,
            key="admin_visitor",
            label_visibility="collapsed",
            format_func=lambda vid: "All visitors"
            if vid == "all"
            else f"{visitor_label(vid, visitor_id)} · {visitors[vid]} chats",
        )
    with refresh_column:
        if st.button("refresh", key="admin_refresh", width="stretch", help="Load the newest chats"):
            admin_conversations.clear()
            admin_search.clear()
            admin_messages.clear()
            st.rerun()

    shown = conversations
    if visitor_filter != "all":
        shown = [c for c in shown if c["visitor_id"] == visitor_filter]
    if term:
        try:
            matches = admin_search(supabase, term)
        except Exception as error:
            st.error("Search didn’t work.")
            with st.expander("Technical details"):
                st.code(str(error))
            matches = set()
        shown = [c for c in shown if c["id"] in matches]

    shown_ids = [c["id"] for c in shown]
    if st.session_state.get("admin_selected") not in shown_ids:
        st.session_state.admin_selected = shown_ids[0] if shown_ids else None
    selected = next((c for c in shown if c["id"] == st.session_state.admin_selected), None)
    selected_messages = admin_messages(supabase, selected["id"]) if selected else []

    with export_column:
        with st.popover("export", key="admin_export", width="stretch"):
            if selected:
                st.download_button(
                    "This chat (.md)",
                    conversation_markdown(
                        selected,
                        selected_messages,
                        time_zone,
                        visitor_label(selected["visitor_id"], visitor_id),
                    ),
                    file_name=f"chat-{selected['id'][:8]}.md",
                    mime="text/markdown",
                    width="stretch",
                )
            if shown:
                st.caption(
                    f"All {len(shown):,} chat{'s' if len(shown) != 1 else ''} in the list as a spreadsheet:"
                )
                if st.button("Prepare CSV", width="stretch", key="admin_prepare_csv"):
                    with st.spinner("Collecting messages…"):
                        st.session_state.admin_csv = conversations_csv(
                            shown,
                            admin_messages_for_export(supabase, shown_ids),
                            time_zone,
                            visitor_id,
                        )
                if st.session_state.get("admin_csv"):
                    st.download_button(
                        "Download CSV",
                        st.session_state.admin_csv,
                        file_name=f"lil-buddy-chats-{today.isoformat()}.csv",
                        mime="text/csv",
                        type="primary",
                        width="stretch",
                    )
    with lock_column:
        if st.button("close", key="admin_lock", width="stretch", help="Lock this page and go back to chat"):
            st.session_state.admin_unlocked = False
            st.session_state.pop("admin_csv", None)
            st.session_state.page = "chat"
            st.rerun()

    list_column, transcript_column = st.columns([2, 3], gap="medium")

    with list_column:
        with st.container(height=680, key="admin_list"):
            if not shown:
                st.caption("No conversations match." if term or visitor_filter != "all" else "No conversations yet.")
            list_limit = st.session_state.get("admin_list_limit", ADMIN_LIST_PAGE)
            visible = shown[:list_limit]
            if selected and selected not in visible:
                visible.append(selected)
            for conversation in visible:
                updated = parse_time(conversation["updated_at"], time_zone)
                label = (
                    f"`{conversation['message_count']}` {escape_markdown(conversation['title'])}"
                    f" *{list_time(updated, today)} · "
                    f"{visitor_label(conversation['visitor_id'], visitor_id)}*"
                )
                if st.button(
                    label,
                    key=f"admin_open_{conversation['id']}",
                    width="stretch",
                    type="primary" if conversation["id"] == st.session_state.admin_selected else "secondary",
                ):
                    st.session_state.admin_selected = conversation["id"]
                    st.rerun()
            if len(shown) > list_limit:
                if st.button(
                    f"show more ({len(shown) - list_limit:,} left)",
                    key="admin_show_more",
                    type="tertiary",
                    width="stretch",
                ):
                    st.session_state.admin_list_limit = list_limit + ADMIN_LIST_PAGE
                    st.rerun()

    with transcript_column:
        if not selected:
            st.caption("Pick a conversation on the left to read it.")
            return
        started = parse_time(selected["created_at"], time_zone)
        st.markdown(
            f'<p class="admin-transcript-title">{escape_html(selected["title"])}</p>'
            f'<p class="admin-transcript-meta">{visitor_label(selected["visitor_id"], visitor_id)}'
            f" · {selected['message_count']} messages · started {long_time(started)}</p>",
            unsafe_allow_html=True,
        )
        with st.container(height=600, key="admin_transcript"):
            last_day = None
            for message in selected_messages:
                sent = parse_time(message["created_at"], time_zone)
                if sent.date() != last_day:
                    last_day = sent.date()
                    st.markdown(
                        f'<div class="admin-day-divider">{long_time(sent)}</div>',
                        unsafe_allow_html=True,
                    )
                render_message(message, caption=clock(sent))


def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ============================================================
# APP
# ============================================================

initialize_session()
api_key = get_api_key()

supabase_url, supabase_secret_key = get_supabase_settings()
if not supabase_url or not supabase_secret_key:
    st.error("Saved chats need Supabase credentials in Streamlit Secrets.")
    st.code(
        'SUPABASE_URL = "https://your-project.supabase.co"\n'
        'SUPABASE_SECRET_KEY = "sb_secret_..."',
        language="toml",
    )
    st.stop()

try:
    supabase = get_supabase_client(supabase_url, supabase_secret_key)
    visitor_id = get_visitor_id(supabase, get_browser_token())
    delete_expired_conversations(supabase)
    saved_conversations = recent_conversations(supabase, visitor_id)
except Exception as error:
    st.error("I couldn’t reach saved chat history yet. Run the Supabase schema setup, then reload.")
    with st.expander("Technical details"):
        st.code(str(error))
    st.stop()

if st.session_state.page == "admin" and st.session_state.get("admin_unlocked"):
    render_admin_page(supabase, visitor_id)
    render_footer()
    st.stop()

saved_ids = {conversation["id"] for conversation in saved_conversations}
if (
    st.session_state.active_conversation_id
    and st.session_state.active_conversation_id not in saved_ids
):
    st.session_state.active_conversation_id = None
    st.session_state.loaded_conversation_id = None

if st.session_state.loaded_conversation_id != st.session_state.active_conversation_id:
    active_id = st.session_state.active_conversation_id
    st.session_state.messages = (
        load_messages(supabase, active_id, visitor_id) if active_id else []
    )
    st.session_state.loaded_conversation_id = active_id

if not api_key:
    st.error("I can’t connect to Ollama yet. Add `OLLAMA_API_KEY` to your Streamlit secrets, then reload this app.")
    st.code('OLLAMA_API_KEY = "your_ollama_api_key"', language="toml")
    st.stop()

client = get_client(api_key)

st.markdown(
    f"""
    <style>
    [data-testid="stSidebar"] .st-key-home_logo button,
    [data-testid="stSidebar"] .st-key-home_logo button:hover {{
        width: 50px !important;
        height: 50px;
        min-height: 50px;
        padding: 0;
        border: 0;
        border-radius: 12px;
        background: url("{logo_data_uri()}") center / contain no-repeat !important;
    }}
    .st-key-home_logo button:hover {{ transform: scale(1.06) !important; }}
    .st-key-home_logo button p {{ font-size: 0 !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    if st.button("home", key="home_logo", help="Back to chat"):
        st.session_state.page = "chat"
        st.rerun()
    st.markdown("### dharshan's lil buddy")
    st.caption("usin **Gemma 4 Vision**")
    st.caption("wanna ask smth? click here")
    st.markdown(
        '<a class="request-form-button" target="_blank" rel="noopener noreferrer" '
        'href="https://docs.google.com/forms/d/e/1FAIpQLSfJZ8beAhUE7tKBuyDRATDXlLQu9RVreJ8WRpXSoTUP3ldSBg/viewform?usp=header">'
        'request form</a>',
        unsafe_allow_html=True,
    )
    if st.button("analytics", type="primary", key="open_analytics"):
        st.session_state.page = "analytics"
        st.rerun()
    st.divider()

    if st.button("new chat", icon="➕", type="primary"):
        st.session_state.page = "chat"
        st.session_state.active_conversation_id = None
        st.session_state.loaded_conversation_id = None
        st.session_state.messages = []
        st.rerun()


    if saved_conversations:
        st.caption("Your chats")
        for conversation in saved_conversations:
            is_open = conversation["id"] == st.session_state.active_conversation_id
            if st.button(
                ("• " if is_open else "") + conversation["title"],
                key=f"open_{conversation['id']}",
                type="primary" if is_open else "secondary",
            ):
                st.session_state.page = "chat"
                st.session_state.active_conversation_id = conversation["id"]
                st.session_state.loaded_conversation_id = None
                st.rerun()

    st.divider()
    if st.session_state.active_conversation_id and st.button(
        "Delete this chat", icon="🗑️", type="secondary"
    ):
        delete_conversation(
            supabase, st.session_state.active_conversation_id, visitor_id
        )
        st.session_state.active_conversation_id = None
        st.session_state.loaded_conversation_id = None
        st.session_state.messages = []
        st.rerun()

    st.caption(
        f"Chats are saved on this browser for {HISTORY_RETENTION_DAYS} days after the last message."
    )

if st.session_state.page == "analytics":
    render_analytics_page(supabase, visitor_id)
    render_footer()
    st.stop()

brand_logo, brand_copy = st.columns([1, 6], vertical_alignment="center")
with brand_copy:
    st.markdown('<div class="brand-kicker">Your everyday AI sidekick</div>', unsafe_allow_html=True)
    st.markdown('<h1 class="brand-title">dharshan’s lil buddy</em></h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="brand-subtitle">Ask anything, work through an idea, or attach an image for a closer look. </p>',
    unsafe_allow_html=True,
)

if not st.session_state.messages:
    st.markdown(
        '<div class="welcome-card"><strong>wsp</strong><br>how u doin</div>',
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

if submission and not submission.files and is_admin_code(submission.text):
    # Secret code: open the conversations page. Never sent to the AI or saved.
    st.session_state.admin_unlocked = True
    st.session_state.page = "admin"
    st.rerun()

if submission:
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    created_conversation = False
    if not st.session_state.active_conversation_id:
        st.session_state.active_conversation_id = create_conversation(
            supabase, visitor_id, user_prompt
        )
        st.session_state.loaded_conversation_id = st.session_state.active_conversation_id
        created_conversation = True

    try:
        save_message(
            supabase,
            st.session_state.active_conversation_id,
            visitor_id,
            user_message,
        )
    except Exception as error:
        st.error("I couldn’t save this message. Please try again.")
        with st.expander("Technical details"):
            st.code(str(error))
        st.stop()

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
            assistant_message = {
                "role": "assistant",
                "content": answer,
                "images": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            st.session_state.messages.append(assistant_message)
            try:
                save_message(
                    supabase,
                    st.session_state.active_conversation_id,
                    visitor_id,
                    assistant_message,
                )
            except Exception as error:
                st.warning("The reply was shown, but couldn’t be saved to chat history.")
                with st.expander("Technical details"):
                    st.code(str(error))
    st.markdown(
        """
        <div id="scroll-anchor"></div>
        <script>
            const anchor = document.getElementById('scroll-anchor');
            if (anchor) {
                anchor.scrollIntoView({ behavior: 'smooth', block: 'end' });
            }
        </script>
        """,
        unsafe_allow_html=True,
    )


    if created_conversation:
        st.rerun()

render_footer()
