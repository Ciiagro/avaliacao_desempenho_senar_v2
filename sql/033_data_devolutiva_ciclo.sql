-- ---------------------------------------------------------
-- Período da devolutiva por ciclo: datas definidas pelo RH (nada é calculado).
-- Vem antes da janela de recursos. Rode no banco antes de usar os campos.
-- Se você já tinha rodado a versão antiga (coluna data_devolutiva), pode
-- apagá-la: ALTER TABLE ciclos_avaliacao DROP COLUMN IF EXISTS data_devolutiva;
-- ---------------------------------------------------------
ALTER TABLE ciclos_avaliacao ADD COLUMN IF NOT EXISTS data_inicio_devolutiva DATE;
ALTER TABLE ciclos_avaliacao ADD COLUMN IF NOT EXISTS data_fim_devolutiva DATE;
