-- Quando dois ciclos ficam "aberto" ao mesmo tempo (ex: 2025 ainda sendo
-- avaliado e 2026 já criado), o sistema precisa saber qual dos dois é o
-- padrão a exibir/usar quando ninguém escolhe o ciclo explicitamente.
-- Antes disso, o sistema sempre pegava o de exercício mais recente, o que
-- forçava a abrir 2026 mesmo estando 2025 em avaliação.
ALTER TABLE ciclos_avaliacao
    ADD COLUMN IF NOT EXISTS padrao BOOLEAN NOT NULL DEFAULT FALSE;

-- Marca como padrão o ciclo aberto mais antigo (o que provavelmente está
-- em avaliação agora). Ajuste manualmente depois se não for o caso.
UPDATE ciclos_avaliacao
SET padrao = TRUE
WHERE id = (
    SELECT id FROM ciclos_avaliacao
    WHERE status = 'aberto'
    ORDER BY exercicio ASC
    LIMIT 1
);
