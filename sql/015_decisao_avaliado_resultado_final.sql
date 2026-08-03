-- Registra qual das duas opções o avaliado escolheu ao dar ciência do
-- resultado final: 'aceito' (satisfeito, encerra) ou 'recorreu' (abriu
-- recurso). Fica gravado junto com ciente_avaliado/ciente_em.

ALTER TABLE resultados_finais
    ADD COLUMN IF NOT EXISTS decisao_avaliado TEXT;
