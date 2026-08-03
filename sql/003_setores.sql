-- =========================================================
-- Migração: Setores/Departamentos
-- Rode DEPOIS do 001_schema.sql e 002_seed_fatores.sql
-- =========================================================

create table if not exists setores (
    id serial primary key,
    nome text not null unique
);

alter table funcionarios
    add column if not exists setor_id int references setores(id);

create index if not exists idx_funcionarios_setor on funcionarios(setor_id);

-- Alguns setores de exemplo (edite/apague conforme a estrutura real da empresa)
insert into setores (nome) values
    ('Superintendência'),
    ('Presidência do Conselho Administrativo'),
    ('Diretoria Técnica'),
    ('Diretoria Administrativa Financeira'),
    ('Assessoria Jurídica'),
    ('Coordenação de T.I.'),
    ('Coordenação de Compras e Patrimônio'),
    ('Coordenação de Execução Financeira'),
    ('Coordenação de Contabilidade'),
    ('Coordenação de FPR/PS'),
    ('Coordenação de ATeG')
on conflict (nome) do nothing;
