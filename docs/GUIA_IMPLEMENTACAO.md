# 🎯 Implementação Corrigida: Devolutiva POR FUNCIONÁRIO

**Data:** 24 de setembro de 2026  
**Status:** ✅ Versão Corrigida (Devolutiva POR FUNCIONÁRIO)  
**Versão Anterior:** ❌ Removida (era por recurso - ERRADO)

---

## 📋 O Que Mudou

### **Estrutura Anterior (ERRADA):**
```
Tabela: recursos_avaliacao
  - data_devolutiva (por RECURSO)
  - data_limite_recorrer_apos_devolutiva (por RECURSO)
```
❌ **Problema:** Cada recurso tinha sua própria data!

### **Estrutura Nova (CORRETA):**
```
Tabela: devolutiva_funcionario
  - funcionario_id (ÚNICO por funcionário)
  - data_devolutiva (por FUNCIONÁRIO)
  - data_limite_recorrer (por FUNCIONÁRIO)
```
✅ **Solução:** Todos os recursos do funcionário usam a mesma data!

---

## 📊 Exemplo Prático

### **Admin marca:**
```
João (CPF 123.456.789-00)
  → Data: 28/09/2024
  → Prazo: até 03/10/2024

Maria (CPF 987.654.321-00)
  → Data: 30/09/2024
  → Prazo: até 05/10/2024

Pedro (CPF 111.222.333-00)
  → Data: 05/10/2024
  → Prazo: até 10/10/2024
```

### **Resultado:**
```
João tem 5 recursos abertos
  ├─ Recurso 1 → usa 28/09 (do João)
  ├─ Recurso 2 → usa 28/09 (do João)
  ├─ Recurso 3 → usa 28/09 (do João)
  ├─ Recurso 4 → usa 28/09 (do João)
  └─ Recurso 5 → usa 28/09 (do João)

Maria tem 3 recursos abertos
  ├─ Recurso 6 → usa 30/09 (da Maria)
  ├─ Recurso 7 → usa 30/09 (da Maria)
  └─ Recurso 8 → usa 30/09 (da Maria)
```

---

## 🔧 Implementação (4 PASSOS)

### **PASSO 1: Executar Migração SQL**

```bash
psql -U seu_usuario -d seu_banco -f 025_devolutiva_por_funcionario.sql
```

**O quê faz:**
- ✅ Cria tabela `devolutiva_funcionario`
- ✅ Cria índices para performance
- ✅ Define relacionamento com `funcionarios`

---

### **PASSO 2: Atualizar models.py**

**Adicione a classe nova:**
```python
# Copie TODO o conteúdo de models_snippet.py
# Cole em app/models.py (APÓS a classe Funcionario)
```

**Modifique a classe Funcionario:**
```python
class Funcionario(db.Model):
    # ... campos existentes ...
    
    # ADICIONE ESTA RELAÇÃO:
    devolutiva = db.relationship(
        "DevolutivaPorFuncionario",
        uselist=False,
        foreign_keys="DevolutivaPorFuncionario.funcionario_id"
    )
    
    # ADICIONE ESTES 3 MÉTODOS:
    def tem_devolutiva_marcada(self):
        return self.devolutiva is not None
    
    def pode_recorrer_apos_devolutiva(self):
        if not self.devolutiva:
            return False
        return self.devolutiva.pode_recorrer()
    
    def dias_restantes_recorrer(self):
        if not self.devolutiva:
            return None
        return self.devolutiva.dias_restantes()
```

**Modifique a classe RecursoAvaliacao:**
```python
class RecursoAvaliacao(db.Model):
    # ... REMOVA ESTES CAMPOS (se existirem):
    # - data_devolutiva
    # - data_limite_recorrer_apos_devolutiva
    # - devolutiva_repassada_em
    # - método pode_recorrer_apos_devolutiva()
    # - método dias_restantes_recorrer()
    
    # ADICIONE ESTAS PROPRIEDADES:
    @property
    def pode_recorrer_apos_devolutiva(self):
        funcionario = self.avaliado
        if not funcionario:
            return False
        return funcionario.pode_recorrer_apos_devolutiva()
    
    @property
    def data_devolutiva(self):
        if self.avaliado and self.avaliado.devolutiva:
            return self.avaliado.devolutiva.data_devolutiva
        return None
    
    @property
    def data_limite_recorrer_apos_devolutiva(self):
        if self.avaliado and self.avaliado.devolutiva:
            return self.avaliado.devolutiva.data_limite_recorrer
        return None
    
    @property
    def dias_restantes_recorrer(self):
        if self.avaliado:
            return self.avaliado.dias_restantes_recorrer()
        return None
```

---

### **PASSO 3: Atualizar Rotas**

**Em app/routes/admin.py:**
```python
# Copie TODO o conteúdo de admin_snippet.py
# Cole ao FINAL de admin.py

# Você terá 3 NOVAS ROTAS:
# 1. GET /devolutiva/funcionarios  (listar)
# 2. POST /devolutiva/funcionario/<id>/marcar  (marcar)
# 3. POST /devolutiva/funcionario/<id>/remover  (remover)
```

**Em app/routes/main.py:**
```python
# Copie TODO o conteúdo de main_snippet.py
# Cole ao FINAL de main.py

# Você terá 3 ROTAS ATUALIZADAS:
# 1. GET /meu-recurso/<id>/devolutiva  (ver devolutiva)
# 2. POST /meu-recurso/<id>/aceitar-devolutiva  (concordar)
# 3. POST /meu-recurso/<id>/recorrer-apos-devolutiva  (recorrer)
```

---

### **PASSO 4: Adicionar Template Admin**

```bash
# Copie este arquivo:
devolutiva_funcionarios.html

# Para este local:
app/templates/admin/devolutiva_funcionarios.html
```

---

### **PASSO 5: Reiniciar Aplicação**

```bash
python run.py
```

---

## 🎯 Fluxo de Uso

### **Admin: Marcar Devolutiva**

```
1. Abra admin
2. Vá em: /devolutiva/funcionarios
3. Clique em "➕ Marcar" (para um funcionário)
4. Selecione a data (ex: 28/09/2024)
5. Clique em "✓ Marcar Devolutiva"

✓ Sistema calcula prazo automaticamente (data + 5 dias)
✓ Todos os recursos daquele funcionário usam essa data
```

### **Colaborador: Responder Devolutiva**

```
1. Faça login como colaborador
2. Vá em "Meus Recursos"
3. Clique em um recurso
4. Vá em "Ver Devolutiva"

Você verá:
  ✓ Data de devolutiva
  ✓ Prazo para recorrer (dias restantes)
  ✓ Histórico de eventos
  ✓ Botões: "✓ Concordo" ou "🔄 Recorrer"
```

---

## 📊 Estrutura de Dados

### **Tabela `devolutiva_funcionario` (NOVA)**

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `id` | SERIAL | ID da devolutiva |
| `funcionario_id` | UUID | Funcionário (UNIQUE) |
| `data_devolutiva` | DATE | Data da comunicação |
| `data_limite_recorrer` | DATE | Prazo máximo (auto-calculado) |
| `marcado_em` | TIMESTAMP | Quando foi marcado |
| `marcado_por` | VARCHAR | Quem marcou |

**Índices:**
- `idx_devolutiva_funcionario_id` → busca rápida por funcionário
- `idx_devolutiva_data` → busca por data
- `idx_devolutiva_limite` → busca por prazo

---

## ✅ Verificação

### **Verificar SQL:**
```bash
psql -U user -d banco -c "SELECT * FROM devolutiva_funcionario;"
```
**Deve retornar:** Estrutura correta da tabela

### **Verificar models.py:**
```bash
grep -n "class DevolutivaPorFuncionario" app/models.py
```
**Deve retornar:** Uma linha com a classe

### **Verificar admin.py:**
```bash
grep -n "/devolutiva/funcionarios" app/routes/admin.py
```
**Deve retornar:** Uma ou mais linhas

### **Verificar main.py:**
```bash
grep -n "ver_devolutiva_recurso" app/routes/main.py
```
**Deve retornar:** Uma linha com a rota

### **Verificar template:**
```bash
test -f app/templates/admin/devolutiva_funcionarios.html && echo "✅ Existe"
```

---

## 🧪 Testes

### **Teste 1: Admin marca devolutiva**
```
1. Abra /devolutiva/funcionarios
2. Clique em "➕ Marcar" para João
3. Marque 28/09/2024
4. Verifique:
   ✓ Data salvou
   ✓ Prazo calculou (03/10/2024)
   ✓ Status mudou para "✓ Marcada"
```

### **Teste 2: João vê devolutiva em TODOS seus recursos**
```
1. Login como João
2. Abra Recurso 1 → Ver Devolutiva → Data 28/09 ✓
3. Volte, abra Recurso 2 → Ver Devolutiva → Data 28/09 ✓
4. Volte, abra Recurso 3 → Ver Devolutiva → Data 28/09 ✓

Resultado: TODOS os recursos de João usam a mesma data!
```

### **Teste 3: Maria tem data DIFERENTE**
```
1. Admin marca Maria = 30/09
2. Login como Maria
3. Abra Recurso 6 → Ver Devolutiva → Data 30/09 ✓

Resultado: Maria e João têm datas DIFERENTES!
```

### **Teste 4: Concordar com devolutiva**
```
1. João abre devolutiva
2. Clica em "✓ Concordo"
3. Verifica:
   ✓ Recurso ficou "Encerrado"
   ✓ Evento registrado
   ✓ Mensagem de sucesso
```

### **Teste 5: Recorrer (prazo válido)**
```
1. João abre devolutiva
2. Clica em "🔄 Recorrer"
3. Verifica:
   ✓ Status mudou para "Aguardando Presidência"
   ✓ Evento registrado
```

### **Teste 6: Prazo expirou**
```
1. Admin marca devolutiva para ontem
2. João acessa devolutiva
3. Verifica:
   ✓ Status: "Prazo expirou"
   ✓ Botão "Recorrer" desabilitado
   ✓ Apenas "Concordo" funciona
```

---

## 🔄 Fluxo Completo

```
Admin marca devolutiva para CADA funcionário
    ↓
João: 28/09 | Maria: 30/09 | Pedro: 05/10
    ↓
Cada funcionário vê devolutiva em TODOS seus recursos
    ↓
Funcionário escolhe:
    ├─ CONCORDO → Recurso encerra
    └─ RECORRER (se prazo) → Vai para presidência
```

---

## ⚙️ Configurações Ajustáveis

### **Alterar prazo de recorrer (padrão: 5 dias)**

Em `models_snippet.py`, procure por:
```python
data_limite = data_devolutiva + timedelta(days=5)  # ← mude o 5
```

---

## 🐛 Troubleshooting

| Erro | Solução |
|------|---------|
| `table "devolutiva_funcionario" does not exist` | Execute SQL novamente |
| `AttributeError: 'Funcionario' has no attribute 'devolutiva'` | Verifique models.py - adicionou a relação? |
| Rota /devolutiva/funcionarios não existe | Verifique admin.py - copiou admin_snippet.py? |
| Template não aparece | Verifique caminho: `app/templates/admin/devolutiva_funcionarios.html` |
| Colaborador vê data nula | Verifique se admin marcou devolutiva para ele |

---

## 📊 Resumo de Mudanças

| Componente | Mudança | Status |
|---|---|---|
| **SQL** | +Tabela `devolutiva_funcionario` | ✅ |
| **models.py** | +Classe `DevolutivaPorFuncionario`, modificada `Funcionario` | ✅ |
| **admin.py** | +3 rotas (listar, marcar, remover) | ✅ |
| **main.py** | Atualizado para usar devolutiva do FUNCIONÁRIO | ✅ |
| **template admin** | +1 novo template | ✅ |
| **template colaborador** | Mesmo template anterior (compatível) | ✅ |

---

## 🎉 Resultado Final

✅ Cada funcionário tem SUA data de devolutiva  
✅ Todos os recursos usam a data do funcionário  
✅ Admin marca UMA vez por funcionário  
✅ Colaborador vê a mesma data em todos seus recursos  
✅ Sistema valida prazos automaticamente  
✅ Interface completa e amigável

---

**Data:** 24 de setembro de 2026  
**Status:** ✅ Implementação Corrigida Pronta!
