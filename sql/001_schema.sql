-- =========================================================
-- Sistema de Avaliação de Desempenho - Schema (Supabase/Postgres)
-- Rode este arquivo no SQL Editor do Supabase (ou via psql)
-- =========================================================

create extension if not exists pgcrypto; -- necessário para gen_random_uuid()

-- ---------------------------------------------------------
-- Cargos / perfis de avaliação (Empregado, Gestor, Superintendente)
-- ---------------------------------------------------------
create table if not exists cargos (
    id serial primary key,
    nome text not null unique
);

-- ---------------------------------------------------------
-- Funcionários (dados básicos - a "base de vidas")
-- ---------------------------------------------------------
create table if not exists funcionarios (
    id uuid primary key default gen_random_uuid(),
    nome text not null,
    email text,
    matricula text,
    cargo_id int references cargos(id),
    ativo boolean not null default true,
    criado_em timestamptz not null default now()
);

create index if not exists idx_funcionarios_cargo on funcionarios(cargo_id);

-- ---------------------------------------------------------
-- Formulários (um por cargo) e seus fatores de avaliação
-- ---------------------------------------------------------
create table if not exists formularios (
    id serial primary key,
    cargo_id int not null references cargos(id),
    nome text not null
);

create table if not exists fatores (
    id serial primary key,
    formulario_id int not null references formularios(id) on delete cascade,
    ordem int not null,
    nome text not null,
    descricao text,
    unique(formulario_id, ordem)
);

-- ---------------------------------------------------------
-- Ciclo de avaliação (exercício/ano)
-- ---------------------------------------------------------
create table if not exists ciclos_avaliacao (
    id serial primary key,
    exercicio int not null unique,
    data_inicio date,
    data_fim date,
    status text not null default 'aberto' check (status in ('aberto','encerrado'))
);

-- ---------------------------------------------------------
-- Vínculo: quem avalia quem, em cada ciclo
-- (permite avaliação dupla: um mesmo avaliado com 2 linhas,
--  um avaliador diferente em cada uma)
-- ---------------------------------------------------------
create table if not exists vinculos_avaliacao (
    id serial primary key,
    ciclo_id int not null references ciclos_avaliacao(id),
    avaliado_id uuid not null references funcionarios(id),
    avaliador_id uuid not null references funcionarios(id),
    unique(ciclo_id, avaliado_id, avaliador_id)
);

create index if not exists idx_vinculos_ciclo_avaliador on vinculos_avaliacao(ciclo_id, avaliador_id);
create index if not exists idx_vinculos_ciclo_avaliado on vinculos_avaliacao(ciclo_id, avaliado_id);

-- ---------------------------------------------------------
-- Avaliações (uma por combinação avaliado + avaliador + tipo)
-- tipo = 'auto'   -> autoavaliação (avaliador_id = avaliado_id)
-- tipo = 'gestor' -> avaliação feita pelo gestor
-- ---------------------------------------------------------
create table if not exists avaliacoes (
    id uuid primary key default gen_random_uuid(),
    ciclo_id int not null references ciclos_avaliacao(id),
    avaliado_id uuid not null references funcionarios(id),
    avaliador_id uuid not null references funcionarios(id),
    tipo text not null check (tipo in ('auto','gestor')),
    formulario_id int not null references formularios(id),
    status text not null default 'em_andamento' check (status in ('em_andamento','concluida')),
    pontos_fortes text,
    oportunidades_desenvolvimento text,
    plano_acao text,
    plano_prazo text,
    resultados_alcancados text,
    criado_em timestamptz not null default now(),
    atualizado_em timestamptz not null default now(),
    unique(ciclo_id, avaliado_id, avaliador_id, tipo)
);

create index if not exists idx_avaliacoes_avaliador on avaliacoes(avaliador_id, ciclo_id);
create index if not exists idx_avaliacoes_avaliado on avaliacoes(avaliado_id, ciclo_id);

-- ---------------------------------------------------------
-- Respostas de cada fator dentro de uma avaliação
-- pontuacao segue a escala do formulário: 10 / 8 / 6 / 4
-- ---------------------------------------------------------
create table if not exists respostas_fatores (
    id serial primary key,
    avaliacao_id uuid not null references avaliacoes(id) on delete cascade,
    fator_id int not null references fatores(id),
    pontuacao int not null check (pontuacao in (4,6,8,10)),
    unique(avaliacao_id, fator_id)
);
