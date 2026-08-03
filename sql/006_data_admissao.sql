-- =========================================================
-- Adiciona a data de admissão ao funcionário
-- Rode este arquivo no SQL Editor do Supabase (ou via psql)
-- =========================================================

alter table funcionarios
    add column if not exists data_admissao date;
