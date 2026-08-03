-- Corrige o fluxo do recurso: a Comissão entra logo na abertura, para
-- encaminhar o caso ao gestor (o gestor não é acionado direto).
--
-- Isso também corrige qualquer recurso que já tenha sido aberto antes
-- dessa correção e ainda esteja com status 'aguardando_gestor' sem ter
-- passado pela Comissão — ele volta para aguardar a Comissão primeiro.

UPDATE recursos_avaliacao
SET status = 'aguardando_comissao_inicial'
WHERE status = 'aguardando_gestor';
