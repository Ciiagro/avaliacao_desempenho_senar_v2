-- =========================================================
-- Adiciona CPF, data de nascimento, sexo e salário ao funcionário
-- Rode este arquivo no SQL Editor do Supabase (ou via psql)
-- =========================================================

alter table funcionarios
    add column if not exists cpf text unique,
    add column if not exists data_nascimento date,
    add column if not exists sexo text check (sexo in ('Feminino', 'Masculino', 'Outro')),
    add column if not exists salario numeric(12, 2);
