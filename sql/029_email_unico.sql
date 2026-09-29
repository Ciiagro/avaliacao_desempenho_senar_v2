-- ---------------------------------------------------------
-- E-mail único por colaborador.
--
-- O e-mail é o login do sistema e o destino dos lembretes, então duas
-- pessoas não podem ter o mesmo. O aplicativo já bloqueia isso ao cadastrar,
-- editar e importar; este índice é a trava final no banco de dados.
--
-- PASSO 1 — veja se já existem e-mails repetidos (rode sozinho primeiro):
-- ---------------------------------------------------------
SELECT lower(btrim(email)) AS email,
       count(*)            AS quantidade,
       string_agg(nome, ' | ' ORDER BY nome) AS colaboradores
FROM funcionarios
WHERE email IS NOT NULL AND btrim(email) <> ''
GROUP BY lower(btrim(email))
HAVING count(*) > 1;

-- PASSO 2 — corrija os repetidos (em Administração > Funcionários > Editar)
-- e só então rode o comando abaixo. Se ainda houver repetidos, ele dá erro.
-- ---------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_funcionarios_email
    ON funcionarios (lower(btrim(email)))
    WHERE email IS NOT NULL AND btrim(email) <> '';
