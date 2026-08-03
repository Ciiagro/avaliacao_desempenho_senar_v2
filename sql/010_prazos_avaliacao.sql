-- ---------------------------------------------------------
-- Prazos separados para autoavaliação e avaliação do gestor.
-- Cada ciclo pode ter uma data limite diferente para cada uma;
-- se ficar em branco, não há bloqueio por data (só o status do
-- ciclo, como já era antes).
-- ---------------------------------------------------------
alter table ciclos_avaliacao
    add column if not exists data_limite_autoavaliacao date,
    add column if not exists data_limite_gestor date;
