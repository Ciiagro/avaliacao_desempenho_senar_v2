-- Quando o resultado final é liberado para o avaliado, ele precisa marcar
-- uma caixinha dando ciência de que recebeu sua avaliação. Isso fica
-- registrado aqui (com data/hora) e é estampado no PDF do resultado final.

ALTER TABLE resultados_finais
    ADD COLUMN IF NOT EXISTS ciente_avaliado BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ciente_em TIMESTAMPTZ;
