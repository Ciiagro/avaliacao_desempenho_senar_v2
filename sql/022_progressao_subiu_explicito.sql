-- Até agora, "subiu ou não" era inferido comparando nivel_anterior com
-- nivel_novo. Isso quebra pra quem já está no último nível_hierárquico
-- cadastrado (Superintendente) e mesmo assim progride (ex.: mudança
-- salarial dentro do mesmo título) — nesse caso os dois campos ficam
-- iguais mesmo tendo sido decidido "sim". Esse campo novo guarda a
-- decisão explicitamente, sem depender da comparação de texto.
--
-- Registros antigos ficam com subiu = NULL — o sistema continua usando a
-- comparação nivel_anterior != nivel_novo como veio antes só pra eles.

ALTER TABLE progressoes
    ADD COLUMN IF NOT EXISTS subiu BOOLEAN;
