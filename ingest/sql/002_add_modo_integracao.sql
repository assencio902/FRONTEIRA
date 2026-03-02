-- Migração: adiciona suporte a câmeras em modo escuta HTTP (ISAPI pull)
-- modo_integracao: 'push' = câmera envia para o servidor (padrão)
--                 'listen' = servidor conecta na câmera via ISAPI stream

ALTER TABLE cameras
    ADD COLUMN IF NOT EXISTS modo_integracao TEXT NOT NULL DEFAULT 'push',
    ADD COLUMN IF NOT EXISTS usuario TEXT,
    ADD COLUMN IF NOT EXISTS senha TEXT;

-- Constraint para garantir valores válidos
ALTER TABLE cameras
    DROP CONSTRAINT IF EXISTS chk_modo_integracao;
ALTER TABLE cameras
    ADD CONSTRAINT chk_modo_integracao
    CHECK (modo_integracao IN ('push', 'listen'));
