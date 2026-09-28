-- Dharshan's lil buddy: usage analytics
-- Run this once in the Supabase SQL Editor (after schema.sql).
--
-- usage_events records only *when* a chat or message happened and which anonymous
-- visitor it belonged to - never any message text. It has no foreign keys, so the
-- 30-day chat cleanup and "Delete this chat" don't remove anything from the stats.

create table if not exists public.usage_events (
    id uuid primary key default gen_random_uuid(),
    visitor_id uuid not null,
    event_type text not null check (event_type in ('conversation', 'message')),
    created_at timestamptz not null default now()
);

create index if not exists usage_events_created_idx
    on public.usage_events (created_at);

create index if not exists usage_events_visitor_created_idx
    on public.usage_events (visitor_id, created_at);

alter table public.usage_events enable row level security;

grant select, insert on table public.usage_events to service_role;

-- Seed the stats with the chats that still exist, only if the table is empty,
-- so running this file again never double counts.
do $$
begin
    if not exists (select 1 from public.usage_events) then
        insert into public.usage_events (visitor_id, event_type, created_at)
        select visitor_id, 'conversation', created_at
        from public.conversations;

        insert into public.usage_events (visitor_id, event_type, created_at)
        select c.visitor_id, 'message', m.created_at
        from public.messages m
        join public.conversations c on c.id = m.conversation_id;
    end if;
end
$$;

-- Daily totals for the analytics page, grouped by day in the viewer's time zone.
-- Pass p_visitor_id for one visitor's stats, or null for everybody.
create or replace function public.lil_buddy_daily_usage(
    p_since timestamptz,
    p_time_zone text default 'UTC',
    p_visitor_id uuid default null
)
returns table (day date, conversations bigint, messages bigint)
language sql
stable
security definer
set search_path = public
as $$
    select
        (created_at at time zone p_time_zone)::date as day,
        count(*) filter (where event_type = 'conversation') as conversations,
        count(*) filter (where event_type = 'message') as messages
    from public.usage_events
    where created_at >= p_since
      and (p_visitor_id is null or visitor_id = p_visitor_id)
    group by 1
    order by 1;
$$;

revoke all on function public.lil_buddy_daily_usage(timestamptz, text, uuid) from public, anon, authenticated;
grant execute on function public.lil_buddy_daily_usage(timestamptz, text, uuid) to service_role;
