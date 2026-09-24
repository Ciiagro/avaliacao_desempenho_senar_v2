-- Guarda o documento de comprovação dentro do banco (o servidor é serverless
-- e não mantém arquivos em disco). arquivo_comprovacao continua sendo o nome
-- original do arquivo; arquivo_tipo só é preenchido quando o arquivo foi de
-- fato guardado (registros antigos têm só o nome, sem o conteúdo).

ALTER TABLE capacitacoes
    ADD COLUMN IF NOT EXISTS arquivo_tipo TEXT,
    ADD COLUMN IF NOT EXISTS arquivo_dados BYTEA;
