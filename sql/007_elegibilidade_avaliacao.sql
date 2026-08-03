-- =========================================================
-- Campo de override manual para elegibilidade de avaliação.
-- Quando NULL, o sistema calcula automaticamente pela data_admissao
-- (precisa de 1 ano de casa). Quando true/false, força o valor.
-- Rode este arquivo no SQL Editor do Supabase (ou via psql)
-- =========================================================

alter table funcionarios
    add column if not exists elegivel_avaliacao boolean;
