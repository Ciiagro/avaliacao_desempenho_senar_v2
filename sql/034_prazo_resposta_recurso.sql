-- ---------------------------------------------------------
-- Prazo para responder aos recursos, por ciclo: data definida pelo RH
-- (nada é calculado). Ex: até 15/11/2026.
-- ---------------------------------------------------------
ALTER TABLE ciclos_avaliacao ADD COLUMN IF NOT EXISTS data_limite_resposta_recurso DATE;
