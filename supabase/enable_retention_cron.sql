-- First enable the pg_cron extension in Supabase Dashboard -> Integrations -> Cron.
-- Then run this once in the SQL Editor. It permanently removes stale chats daily.

select cron.schedule(
    'delete-expired-lil-buddy-chats',
    '15 3 * * *',
    $$ select public.delete_expired_lil_buddy_chats(); $$
);
