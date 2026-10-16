-- Apaga os cursos de TESTE criados na tela nova de Minhas Capacitacoes.
-- Pega qualquer curso que tenha a palavra "teste" no nome (TESTE 01, Teste 70, etc).
-- 1) Rode primeiro SO o SELECT e confira se aparecem apenas linhas de teste.
--    Se aparecer algum curso REAL que tenha "teste" no nome (ex.: "Testes de software"),
--    NAO rode o DELETE desse jeito: me chame para ajustar.
-- 2) Rode o DELETE. Nao tem volta, entao confira o SELECT antes.

SELECT c.id, f.nome AS funcionario, c.nome_curso, c.ano, c.trimestre, c.carga_horaria, c.previsto, c.status
FROM capacitacoes c
LEFT JOIN funcionarios f ON f.id = c.funcionario_id
WHERE c.nome_curso ILIKE '%teste%'
ORDER BY c.nome_curso, c.ano, c.trimestre;

DELETE FROM capacitacoes
WHERE nome_curso ILIKE '%teste%';
