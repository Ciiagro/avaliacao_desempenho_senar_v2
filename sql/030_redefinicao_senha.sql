-- =========================================================
-- "Esqueci minha senha" + proteção contra tentativas de login
-- Rode este arquivo no SQL Editor do Supabase (ou via psql).
-- =========================================================

-- Tokens de redefinição de senha. Guardamos só o HASH do token (o token em
-- si vai apenas no link enviado por e-mail), então ninguém consegue usar
-- um vazamento do banco para redefinir senhas.
create table if not exists redefinicoes_senha (
    id             uuid primary key default gen_random_uuid(),
    funcionario_id uuid not null references funcionarios(id) on delete cascade,
    token_hash     text not null unique,
    expira_em      timestamptz not null,
    usado_em       timestamptz,
    criado_em      timestamptz not null default now()
);

create index if not exists ix_redefinicoes_senha_funcionario
    on redefinicoes_senha (funcionario_id);

-- Controle de tentativas de login erradas.
alter table funcionarios
    add column if not exists tentativas_login integer not null default 0,
    add column if not exists bloqueado_ate    timestamptz;

-- ---------------------------------------------------------
-- OPCIONAL, MAS RECOMENDADO: acabar com o "123456" já gravado.
--
-- Quem ainda não trocou a senha provisória continua com "123456".
-- O comando abaixo apaga essas senhas; depois, em
-- Administração > Funcionários, clique em "Gerar senhas pendentes" e
-- o sistema cria uma senha aleatória diferente para cada pessoa.
-- (Quem já trocou a própria senha NÃO é afetado.)
--
-- update funcionarios set senha_hash = null where senha_provisoria = true;
-- ---------------------------------------------------------
