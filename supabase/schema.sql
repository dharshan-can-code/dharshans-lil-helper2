-- Dharshan's lil buddy: anonymous saved chat history

create extension if not exists pgcrypto;

create table if not exists public.anonymous_visitors (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique,
    created_at timestamptz not null default now()
);

create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    visitor_id uuid not null references public.anonymous_visitors(id) on delete cascade,
    title text not null default 'New chat',
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists conversations_visitor_updated_idx
    on public.conversations (visitor_id, updated_at desc);

create table if not exists public.messages (
    id uuid primary key default gen_random_uuid(),
    conversation_id uuid not null references public.conversations(id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null default '',
    images jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists messages_conversation_created_idx
    on public.messages (conversation_id, created_at);

-- These tables are only accessed by the Streamlit server using its secret key.
-- No browser receives that key, and no public read/write policies are created.
alter table public.anonymous_visitors enable row level security;
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

create or replace function public.delete_expired_lil_buddy_chats()
returns void
language sql
security definer
set search_path = public
as $$
    delete from public.conversations
    where updated_at < now() - interval '30 days';
$$;

revoke all on function public.delete_expired_lil_buddy_chats() from public;
grant execute on function public.delete_expired_lil_buddy_chats() to service_role;
