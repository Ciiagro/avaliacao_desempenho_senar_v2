-- =====================================================================
-- Criar tabela: devolutiva_funcionario
-- =====================================================================
-- Esta tabela armazena a data de devolutiva POR FUNCIONÁRIO (não por recurso)
-- Todos os recursos do funcionário usam a mesma data

CREATE TABLE IF NOT EXISTS devolutiva_funcionario (
    id SERIAL PRIMARY KEY,
    funcionario_id UUID NOT NULL UNIQUE,
    data_devolutiva DATE NOT NULL,
    data_limite_recorrer DATE NOT NULL,
    marcado_em TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    marcado_por VARCHAR(255),
    
    FOREIGN KEY (funcionario_id) REFERENCES funcionarios(id) ON DELETE CASCADE
);

-- =====================================================================
-- Criar índices para performance
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_devolutiva_funcionario_id 
    ON devolutiva_funcionario(funcionario_id);

CREATE INDEX IF NOT EXISTS idx_devolutiva_data_devolutiva 
    ON devolutiva_funcionario(data_devolutiva);

CREATE INDEX IF NOT EXISTS idx_devolutiva_data_limite 
    ON devolutiva_funcionario(data_limite_recorrer);

-- =====================================================================
-- Fim da migração
-- =====================================================================
-- Execute este arquivo com:
-- psql -U seu_usuario -d seu_banco -f 025_devolutiva_por_funcionario.sql
