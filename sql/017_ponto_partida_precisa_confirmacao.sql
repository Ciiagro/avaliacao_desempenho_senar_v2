-- Distingue duas situações que antes ficavam iguais (as duas com
-- exercicio_inicio NULL): (a) o RH marcou explicitamente "?" na planilha
-- porque a situação é AMBÍGUA e precisa de decisão humana (ex.: Fracisca,
-- Luciana); (b) o funcionário simplesmente ainda não tirou conceito A em
-- nenhum ano, então não há par pra contar ainda — isso é normal, não uma
-- pendência de ninguém resolver.
ALTER TABLE progressao_ponto_partida
    ADD COLUMN IF NOT EXISTS precisa_confirmacao BOOLEAN NOT NULL DEFAULT FALSE;
