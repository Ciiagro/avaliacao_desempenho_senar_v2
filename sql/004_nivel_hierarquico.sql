-- =========================================================
-- Adiciona o nível hierárquico ao funcionário
-- (independente do "cargo", que continua definindo o formulário
-- de avaliação usado)
-- Rode este arquivo no SQL Editor do Supabase (ou via psql)
-- =========================================================

alter table funcionarios
    add column if not exists nivel_hierarquico text
    check (nivel_hierarquico in ('Colaborador', 'Coordenador', 'Gestor', 'Superintendente', 'Presidente'));
