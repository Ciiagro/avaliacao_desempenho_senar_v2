-- Guarda, de forma estruturada, quais fatores o empregado contestou num
-- recurso e o motivo de cada um -- antes disso só existia o campo
-- `motivo` (texto livre concatenado), o que impedia destacar os itens
-- contestados direto na tabela de notas pra comissão/gestor.
--
-- O campo `motivo` em recursos_avaliacao continua existindo (usado no
-- e-mail e no PDF do recurso); esta tabela é um complemento, não substitui.

CREATE TABLE IF NOT EXISTS recurso_itens_contestados (
    id SERIAL PRIMARY KEY,
    recurso_id INTEGER NOT NULL REFERENCES recursos_avaliacao(id),
    fator_id INTEGER NOT NULL REFERENCES fatores(id),
    motivo TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recurso_id, fator_id)
);
