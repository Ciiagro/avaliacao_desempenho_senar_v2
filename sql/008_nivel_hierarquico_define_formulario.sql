-- =========================================================
-- Reorganiza Cargo x Nível Hierárquico:
-- - "cargo" passa a ser o cargo real da pessoa (texto livre, ex: Assistente Administrativo)
-- - "nivel_hierarquico" (Empregado / Gestor / Superintendente) passa a decidir
--   qual dos 3 formulários de avaliação é usado
-- Rode este arquivo no SQL Editor do Supabase (ou via psql), DEPOIS dos anteriores
-- =========================================================

-- 1) Formulário passa a ser ligado ao nível hierárquico, não ao cargo
alter table formularios
    add column if not exists nivel_hierarquico text;

update formularios f
    set nivel_hierarquico = c.nome
    from cargos c
    where f.cargo_id = c.id
      and f.nivel_hierarquico is null;

alter table formularios
    alter column cargo_id drop not null;

alter table formularios
    add constraint formularios_nivel_hierarquico_key unique (nivel_hierarquico);

-- 2) Preenche o nivel_hierarquico de cada funcionário a partir do cargo antigo
--    (nos cadastros feitos até agora, "cargo" guardava Empregado/Gestor/Superintendente)
update funcionarios fu
    set nivel_hierarquico = c.nome
    from cargos c
    where fu.cargo_id = c.id
      and fu.nivel_hierarquico is null
      and c.nome in ('Empregado', 'Gestor', 'Superintendente');

-- 3) Restringe nivel_hierarquico aos 3 valores válidos
alter table funcionarios
    drop constraint if exists funcionarios_nivel_hierarquico_check;

alter table funcionarios
    add constraint funcionarios_nivel_hierarquico_check
    check (nivel_hierarquico in ('Empregado', 'Gestor', 'Superintendente'));

-- 4) A partir de agora, "cargo" é livre (o admin pode cadastrar quantos cargos
--    reais quiser em Administração > Cargos/Funcionários — não precisa mais ser
--    só Empregado/Gestor/Superintendente).
