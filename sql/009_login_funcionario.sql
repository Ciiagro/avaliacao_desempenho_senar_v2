-- =========================================================
-- Login individual por funcionário (e-mail + senha)
-- Rode este arquivo no SQL Editor do Supabase (ou via psql)
-- =========================================================

alter table funcionarios
    add column if not exists senha_hash text,
    add column if not exists senha_provisoria boolean not null default true;
