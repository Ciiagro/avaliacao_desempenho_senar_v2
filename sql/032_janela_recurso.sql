-- ---------------------------------------------------------
-- Janela de recursos por ciclo: datas definidas pelo RH (nada é calculado).
-- Ex: recursos de 11/11/2026 a 17/11/2026.
-- Sem as duas datas preenchidas, vale a regra antiga (5 dias úteis).
-- ---------------------------------------------------------
ALTER TABLE ciclos_avaliacao ADD COLUMN IF NOT EXISTS data_inicio_recurso DATE;
ALTER TABLE ciclos_avaliacao ADD COLUMN IF NOT EXISTS data_fim_recurso DATE;
