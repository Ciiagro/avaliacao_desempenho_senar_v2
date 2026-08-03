-- =========================================================
-- Seed: cargos, formulários e fatores (Exercício 2024 - SENAR-AR/CE)
-- Rode DEPOIS do 001_schema.sql
-- =========================================================

insert into cargos (nome) values
    ('Empregado'),
    ('Gestor'),
    ('Superintendente')
on conflict (nome) do nothing;

insert into formularios (cargo_id, nome)
select id, 'Avaliação de Desempenho - Empregados' from cargos where nome = 'Empregado'
on conflict do nothing;

insert into formularios (cargo_id, nome)
select id, 'Avaliação de Desempenho - Gestores' from cargos where nome = 'Gestor'
on conflict do nothing;

insert into formularios (cargo_id, nome)
select id, 'Avaliação de Desempenho - Superintendente' from cargos where nome = 'Superintendente'
on conflict do nothing;

-- ---------------------------------------------------------
-- Fatores - EMPREGADOS (14 fatores)
-- ---------------------------------------------------------
insert into fatores (formulario_id, ordem, nome, descricao)
select f.id, x.ordem, x.nome, x.descricao
from formularios f
join cargos c on c.id = f.cargo_id and c.nome = 'Empregado'
join (values
(1,'ASSIDUIDADE','Considere o comparecimento diário ao trabalho, levando em conta as faltas justificadas conforme a Legislação.'),
(2,'OBSERVÂNCIA ÀS NORMAS','Considere o cumprimento das regras internas da Instituição, garantindo fidelidade à mesma.'),
(3,'RELACIONAMENTO INTERPESSOAL / NEGOCIAÇÃO','Considere a habilidade do empregado na condução de negociações e nas tratativas de relacionamento junto a clientes externos e internos.'),
(4,'RESPONSABILIDADE POR RESULTADOS','Considere a responsabilidade atribuída à sua atuação referente a resultados, considerando a amplitude do impacto de suas ações e área de atuação de importância estratégica para o negócio.'),
(5,'CONHECIMENTO DO TRABALHO','Domínio técnico/administrativo do seu campo de atuação, com conhecimento de todos os processos e rotinas de trabalho e interação com os objetivos do órgão.'),
(6,'INICIATIVA','Capacidade de prever oportunidades e ameaças, apresentar ideias e sugestões e agir prontamente, buscando soluções para que o trabalho seja realizado dentro dos prazos e com qualidade.'),
(7,'ZELO PELA ECONOMIA E CONSERVAÇÃO DO MATERIAL E PATRIMÔNIO','Considere se agiu com economia e zelou pela conservação de materiais e equipamentos da Instituição.'),
(8,'COMPROMETIMENTO','Demonstra vínculo, lealdade e identificação com a organização, crença nos valores e diretrizes que balizam as atitudes e decisões corporativas, disposição para envidar esforços visando o sucesso da Instituição e de suas iniciativas, observando discrição, autenticidade e resolutividade nas suas atitudes.'),
(9,'EFICIÊNCIA NOS RECURSOS / PROCESSOS','Capacidade de realizar atividades, otimizando os recursos disponíveis, observando os processos e condições de melhorias que viabilizem os resultados da Instituição de forma objetiva e com qualidade.'),
(10,'TRABALHO EM EQUIPE','Capacidade de desenvolver trabalhos em conjunto, comprometido com a equipe, visando melhores resultados, reconhecendo e respeitando as diferenças e limitações dos outros, ajudando-os a superá-las.'),
(11,'CONHECIMENTO DAS FERRAMENTAS / SISTEMAS INFORMATIZADOS DA ÁREA','Saber manusear as ferramentas de trabalho ou utilizar os sistemas de tecnologia e informações requeridas ao exercício das atividades, conforme o cargo e função, observando a agilidade e qualidade dos resultados gerados.'),
(12,'FLEXIBILIDADE E CAPACIDADE DE ADAPTAÇÃO','Capacidade de adaptar-se a novas áreas, métodos e ideias. Aceitação de mudanças.'),
(13,'CRIATIVIDADE E INOVAÇÃO','Capacidade para conceber soluções inovadoras, viáveis e adequadas para as situações apresentadas e identificadas.'),
(14,'PLANEJAMENTO E ORGANIZAÇÃO','Capacidade para planejar e organizar as ações para o trabalho, atingindo resultados através do estabelecimento de prioridades, metas tangíveis, mensuráveis e dentro de critérios de desempenho.')
) as x(ordem, nome, descricao) on true
on conflict (formulario_id, ordem) do nothing;

-- ---------------------------------------------------------
-- Fatores - GESTORES (15 fatores)
-- ---------------------------------------------------------
insert into fatores (formulario_id, ordem, nome, descricao)
select f.id, x.ordem, x.nome, x.descricao
from formularios f
join cargos c on c.id = f.cargo_id and c.nome = 'Gestor'
join (values
(1,'ASSIDUIDADE','Considere o comparecimento diário ao trabalho, levando em conta as faltas justificadas conforme a Legislação.'),
(2,'OBSERVÂNCIA ÀS NORMAS','Considere o cumprimento das regras internas da Instituição, garantindo fidelidade à mesma.'),
(3,'RELACIONAMENTO INTERPESSOAL / NEGOCIAÇÃO','Considere a habilidade do empregado na condução de negociações e nas tratativas de relacionamento junto a clientes externos e internos.'),
(4,'RESPONSABILIDADE POR RESULTADOS','Considere a responsabilidade atribuída à sua atuação referente a resultados, considerando a amplitude do impacto de suas ações e área de atuação de importância estratégica para o negócio.'),
(5,'CONHECIMENTO DO TRABALHO','Domínio técnico/administrativo do seu campo de atuação, com conhecimento de todos os processos e rotinas de trabalho e interação com os objetivos do órgão.'),
(6,'INICIATIVA','Capacidade de prever oportunidades e ameaças, apresentar ideias e sugestões e agir prontamente, buscando soluções para que o trabalho seja realizado dentro dos prazos e com qualidade.'),
(7,'COMPROMETIMENTO','Demonstra vínculo, lealdade e identificação com a organização, crença nos valores e diretrizes que balizam as atitudes e decisões corporativas, disposição para envidar esforços visando o sucesso da Instituição e de suas iniciativas, observando discrição, autenticidade e resolutividade nas suas atitudes.'),
(8,'CONHECIMENTO DAS FERRAMENTAS / SISTEMAS INFORMATIZADOS DA ÁREA','Saber manusear as ferramentas de trabalho ou utilizar os sistemas de tecnologia e informações requeridas ao exercício das atividades, conforme o cargo e função, observando a agilidade e qualidade dos resultados gerados.'),
(9,'FLEXIBILIDADE E CAPACIDADE DE ADAPTAÇÃO','Capacidade de adaptar-se a novas áreas, métodos e ideias. Aceitação de mudanças.'),
(10,'CRIATIVIDADE E INOVAÇÃO','Capacidade para conceber soluções inovadoras, viáveis e adequadas para as situações apresentadas e identificadas.'),
(11,'PLANEJAMENTO E ORGANIZAÇÃO','Capacidade para planejar e organizar as ações para o trabalho, atingindo resultados através do estabelecimento de prioridades, metas tangíveis, mensuráveis e dentro de critérios de desempenho.'),
(12,'TOMADA DE DECISÃO','Capacidade de buscar e selecionar alternativas, identificando aquela que garanta o melhor resultado, cumprindo prazos definidos e considerando limites e riscos.'),
(13,'GESTÃO DE PROCESSOS E RESULTADOS','Entende e gerencia de maneira plena todos os processos da área, bem como as conexões destas com as outras áreas da Instituição, visando a maximização dos resultados.'),
(14,'GESTÃO DO CONHECIMENTO','Facilidade para identificar novas oportunidades de ação e capacidade para propor e implementar soluções aos problemas e necessidades que se apresentam, de forma assertiva e adequada ao contexto.'),
(15,'LIDERANÇA E DESENVOLVIMENTO DE EQUIPES','Capacidade para catalisar os esforços grupais, de forma a atingir ou superar os objetivos organizacionais, estabelecendo um clima motivador, formando parcerias e estimulando o desenvolvimento da equipe.')
) as x(ordem, nome, descricao) on true
on conflict (formulario_id, ordem) do nothing;

-- ---------------------------------------------------------
-- Fatores - SUPERINTENDENTE (11 fatores)
-- ---------------------------------------------------------
insert into fatores (formulario_id, ordem, nome, descricao)
select f.id, x.ordem, x.nome, x.descricao
from formularios f
join cargos c on c.id = f.cargo_id and c.nome = 'Superintendente'
join (values
(1,'DELEGAÇÃO DE FUNÇÕES','Capacidade de distribuir responsabilidade e dá autonomia aos membros da equipe na realização das tarefas, respeitando o potencial, os conhecimentos e habilidades de cada um deles.'),
(2,'PLANEJAMENTO','Capacidade de determinar, em função dos objetivos estabelecidos, planos e programas, definindo o que fazer, como fazer, os recursos necessários, prazos, equipe, critérios de acompanhamento, controle e ações contingenciais.'),
(3,'CONHECIMENTO DO TRABALHO','Domínio técnico do seu campo de atuação, com conhecimento de todos os processos e rotinas de trabalho e interação com os objetivos do órgão.'),
(4,'DESENVOLVIMENTO DE PESSOAS','Habilidade para identificar e reconhecer potencialidades e estimular as pessoas com quem trabalha e envolver-se em atividades que promovam a melhoria de suas capacidades e habilidades, para melhor conhecimento e execução do trabalho.'),
(5,'FLEXIBILIDADE','Capacidade para encarar situações e mudanças sem atitudes preconcebidas ou rígidas, demonstrando disposição, interesse e abertura para entender as situações e adaptar-se em novos contextos.'),
(6,'COMUNICAÇÃO','Capacidade de expressar ideias com lógica e objetividade, por escrito e oralmente, preocupando-se em verificar o entendimento das mensagens transmitidas e recebidas.'),
(7,'INICIATIVA','Capacidade de prever oportunidades e ameaças, apresentar ideias e sugestões e agir prontamente, buscando soluções para que o trabalho seja realizado dentro dos prazos e com qualidade.'),
(8,'TOMADA DE DECISÃO','Capacidade de buscar e selecionar alternativas, identificando aquela que garanta o melhor resultado, cumprindo prazos definidos e considerando limites e riscos.'),
(9,'CONHECIMENTO DAS FERRAMENTAS/SISTEMAS INFORMATIZADOS DA ÁREA','Saber manusear as ferramentas de trabalho ou utilizar os sistemas de tecnologia e informações requeridas ao exercício das atividades, conforme o cargo e função, observando a agilidade e qualidade dos resultados gerados.'),
(10,'CRIATIVIDADE E INOVAÇÃO','Capacidade para conceber soluções inovadoras, viáveis e adequadas para as situações apresentadas identificadas.'),
(11,'GESTÃO DO CONHECIMENTO','Facilidade para identificar novas oportunidades de ação e capacidade para propor e implementar soluções aos problemas e necessidades que se apresentam, de forma assertiva e adequada ao contexto.')
) as x(ordem, nome, descricao) on true
on conflict (formulario_id, ordem) do nothing;

-- ---------------------------------------------------------
-- Ciclo de avaliação atual (ajuste as datas conforme sua empresa)
-- ---------------------------------------------------------
insert into ciclos_avaliacao (exercicio, data_inicio, data_fim, status)
values (2026, '2026-01-01', '2026-12-31', 'aberto')
on conflict (exercicio) do nothing;
