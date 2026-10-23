-- Dharshan's lil buddy: admin conversation list
-- Run this once in the Supabase SQL Editor (after schema.sql).
--
-- The admin page used to ask PostgREST for the message counts with an embed:
--
--     .select("id, title, ..., messages(count)")
--
-- To count the rows, PostgREST reads them, and every message row carries its
-- base64 images in a jsonb column. Those live in TOAST storage - 230 MB of it
-- against 5 MB of actual message heap - so counting dragged the whole lot off
-- disk and blew past the Data API statement timeout (SQLSTATE 57014).
--
-- Counting inside Postgres uses messages_conversation_created_idx and never
-- touches the images. Measured on 768 conversations / 8,456 messages:
-- the embed timed out at 8 s, this returns in about 10 ms.

create or replace function public.lil_buddy_admin_conversations(p_since timestamptz)
returns table (
    id uuid,
    title text,
    visitor_id uuid,
    created_at timestamptz,
    updated_at timestamptz,
    message_count bigint
)
language sql
stable
security definer
set search_path = public
as $$
    select
        c.id,
        c.title,
        c.visitor_id,
        c.created_at,
        c.updated_at,
        (select count(*) from public.messages m where m.conversation_id = c.id)
    from public.conversations c
    where c.updated_at >= p_since
    order by c.updated_at desc;
$$;

-- Only the Streamlit server, which holds the secret key, may read every
-- visitor's chats. Same posture as lil_buddy_daily_usage in analytics.sql.
revoke all on function public.lil_buddy_admin_conversations(timestamptz)
    from public, anon, authenticated;
grant execute on function public.lil_buddy_admin_conversations(timestamptz)
    to service_role;

-- Supports the 30-day cutoff filter here and the retention delete in
-- delete_expired_conversations(), neither of which can use the existing
-- (visitor_id, updated_at) index because neither filters on visitor_id.
create index if not exists conversations_updated_idx
    on public.conversations (updated_at desc);
