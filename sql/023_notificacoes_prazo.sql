-- ---------------------------------------------------------
-- Registro dos lembretes de prazo já enviados por e-mail (5 dias, 2 dias
-- e no dia do prazo de autoavaliacao/avaliacao do gestor).
--
-- Existe só pra não mandar o mesmo lembrete duas vezes pra mesma pessoa
-- caso a rotina de verificação seja chamada mais de uma vez no mesmo dia
-- (ex: o cron reexecuta depois de uma falha, ou alguém aciona a rota na
-- mão) -- a chave única (ciclo, tipo, avaliador, dias_restantes) garante
-- isso.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS notificacoes_prazo (
    id SERIAL PRIMARY KEY,
    ciclo_id INTEGER NOT NULL REFERENCES ciclos_avaliacao(id),
    tipo TEXT NOT NULL,              -- 'auto' | 'gestor'
    avaliador_id UUID NOT NULL REFERENCES funcionarios(id),
    dias_restantes INTEGER NOT NULL, -- 5, 2 ou 0
    enviado_em TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ciclo_id, tipo, avaliador_id, dias_restantes)
);
