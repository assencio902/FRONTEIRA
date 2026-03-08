# 📋 ANÁLISE OBJETIVA - FCM Push Não Funciona

**Data**: 7 de março de 2026  
**Status**: ✅ PROVAS CONCRETAS COLETADAS  
**Causa Raiz**: CONFIRMADA

---

## 1️⃣ PROJECT_ID DO APP (google-services.json)

**Arquivo**: `flutter_app/android/app/google-services.json`

```json
{
  "project_info": {
    "project_number": "1092534615144",
    "project_id": "bpfron",
    "storage_bucket": "bpfron.firebasestorage.app"
  },
  "client": [
    {
      "client_info": {
        "mobilesdk_app_id": "1:1092534615144:android:68a6c2515fdaa4ee228fdd",
        "android_client_info": {
          "package_name": "br.gov.bpfron.monitoramento"
        }
      }
    }
  ]
}
```

✅ **PROJECT_ID DO APP**: `"bpfron"`

---

## 2️⃣ PROJECT_ID DA CREDENCIAL ADMIN FIREBASE

### Status: ❌ **ARQUIVO NÃO EXISTE**

**Localização esperada**: `D:\monitoramento\secrets\firebase-adminsdk.json`

**Verificação 1** - Busca local:
```powershell
Get-ChildItem -Path . -Recurse -Filter "*firebase-adminsdk*.json"
# Resultado: ❌ Nenhum arquivo encontrado
```

**Verificação 2** - Dentro do container Docker:
```bash
docker compose exec ingest ls -la /app/secrets/
# Resultado: 
# total 8
# drwxrwxrwx 1 root root 4096 Mar  6 22:20 .
# drwxr-xr-x 1 root root 4096 Mar  7 19:31 ..
# ❌ DIRETÓRIO VAZIO
```

**Verificação 3** - Tentativa de leitura:
```bash
docker compose exec ingest cat /app/secrets/firebase-adminsdk.json
# Resultado: ❌ cat: /app/secrets/firebase-adminsdk.json: No such file or directory
```

**Verificação 4** - Variáveis de ambiente (dentro do container):
```bash
docker compose exec ingest python -c "import os; print('FCM_CREDENTIALS_PATH:', os.getenv('FCM_CREDENTIALS_PATH')); print('FCM_PROJECT_ID:', os.getenv('FCM_PROJECT_ID')); print('Exists:', os.path.exists(os.getenv('FCM_CREDENTIALS_PATH', '')))"

# Resultado:
# FCM_CREDENTIALS_PATH: /app/secrets/firebase-adminsdk.json
# FCM_PROJECT_ID: bpfron-monitoramento
# Exists: False
```

❌ **PROJECT_ID DA CREDENCIAL ADMIN**: NÃO PODE SER DETERMINADO (arquivo ausente)

---

## 3️⃣ ERRO REAL DO FCM

### **Erro Confirmado**: RuntimeError - Arquivo de Credencial Não Encontrado

**Comando de teste**:
```bash
docker compose exec ingest python -c "import sys; sys.path.insert(0, '/app'); from services.fcm_service import _load_service_account_credentials; cred, info = _load_service_account_credentials(); print('project_id:', info.get('project_id'))"
```

**Saída**:
```
Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/app/services/fcm_service.py", line 84, in _load_service_account_credentials
    raise RuntimeError(f"Credencial FCM não encontrada em {FCM_CREDENTIALS_PATH}")
RuntimeError: Credencial FCM não encontrada em /app/secrets/firebase-adminsdk.json
```

**Código que falha** (`fcm_service.py` linhas 80-90):
```python
def _load_service_account_credentials():
    if service_account is None or GoogleAuthRequest is None:
        raise RuntimeError("google-auth não instalado no backend")
    if not os.path.exists(FCM_CREDENTIALS_PATH):
        raise RuntimeError(f"Credencial FCM não encontrada em {FCM_CREDENTIALS_PATH}")

    with open(FCM_CREDENTIALS_PATH, "r", encoding="utf-8") as fh:
        info = json.load(fh)

    creds = service_account.Credentials.from_service_account_file(
        FCM_CREDENTIALS_PATH,
        scopes=FCM_SCOPES,
    )
    return creds, info
```

✅ **ERRO REAL CONFIRMADO**: 
- **Tipo**: `RuntimeError`
- **Mensagem**: `"Credencial FCM não encontrada em /app/secrets/firebase-adminsdk.json"`
- **Causa**: Arquivo não existe no sistema de arquivos
- **Localização**: `fcm_service.py`, função `_load_service_account_credentials()`, linha 84

---

## 4️⃣ CAUSA RAIZ CONFIRMADA

### **Mismatch de Project ID + Arquivo Ausente**

| Item | Valor Esperado | Valor Atual | Status |
|------|----------------|------------|--------|
| App project_id | `"bpfron"` | `"bpfron"` ✅ | OK |
| Backend FCM_PROJECT_ID | `"bpfron"` | `"bpfron-monitoramento"` ❌ | **MISMATCH** |
| firebase-adminsdk.json | deve existir | ❌ NÃO EXISTE | **CRÍTICO** |
| Arquivo no container | `/app/secrets/firebase-adminsdk.json` | ❌ VAZIO | **CRÍTICO** |

### **Fluxo de Falha Confirmado**:

```
1. POST /api/alarmes/7/test (teste de alarme ativado)
   ↓
2. send_alert_to_alarm_users() procura usuários
   ↓
3. send_alert_to_user_tokens() busca tokens no BD (OK, encontra tokens)
   ↓
4. _send_fcm_message() tenta enviar push
   ↓
5. _get_access_token() chamado
   ↓
6. _load_service_account_credentials() chamado
   ↓
7. ❌ RuntimeError: "Credencial FCM não encontrada"
   ↓
8. except Exception as exc: return False, f"credentials_error:{exc}"
   ↓
9. Resultado: sent=0, failed=1, invalid_tokens=0
```

✅ **CAUSA RAIZ CONFIRMADA**:
1. **Arquivo de credencial Firebase Admin SDK ausente** - `firebase-adminsdk.json` não copiado para `secrets/`
2. **Mismatch de project_id** - Backend espera `"bpfron-monitoramento"` mas app usa `"bpfron"`
3. **Resultado**: Backend nunca consegue gerar access token → nenhum push é enviado

---

## 5️⃣ PASSO A PASSO EXATO PARA CORRIGIR

### **FASE 1: Preparar Credencial Firebase (SEM REINSTALAR APP)**

#### Passo 1: Obter firebase-adminsdk.json do Firebase Console

1. Acesse: https://console.firebase.google.com/
2. Selecione projeto: **bpfron**
3. Vá em: **⚙️ Project Settings** (canto superior direito)
4. Abra aba: **Service Accounts**
5. Clique: **Generate New Private Key**
6. Arquivo será baixado como `bpfron-xxxxx.json`

#### Passo 2: Colocar no local correto

```powershell
# Criar diretório secrets (se não existir)
New-Item -ItemType Directory -Path "D:\monitoramento\secrets" -Force

# Copiar arquivo baixado para:
# D:\monitoramento\secrets\firebase-adminsdk.json
# (Renomear para exatamente "firebase-adminsdk.json")
```

**Resultado esperado**:
```powershell
dir D:\monitoramento\secrets\

Mode  Name
----  ----
-a--- firebase-adminsdk.json
```

#### Passo 3: Corrigir FCM_PROJECT_ID no docker-compose.yml

**Arquivo**: `D:\monitoramento\docker-compose.yml` (linha 46)

**ANTES**:
```yaml
environment:
  ...
  FCM_PROJECT_ID: "bpfron-monitoramento"
  FCM_CREDENTIALS_PATH: "/app/secrets/firebase-adminsdk.json"
```

**DEPOIS**:
```yaml
environment:
  ...
  FCM_PROJECT_ID: "bpfron"
  FCM_CREDENTIALS_PATH: "/app/secrets/firebase-adminsdk.json"
```

#### Passo 4: Reiniciar backend

```bash
cd D:\monitoramento
docker compose restart ingest

# Aguardar ~10 segundos
# Verificar:
docker compose ps
# ingest deve mostrar "Up"
```

#### Passo 5: Validar credencial está carregada

```bash
docker compose exec ingest python -c "import sys; sys.path.insert(0, '/app'); from services.fcm_service import _load_service_account_credentials; cred, info = _load_service_account_credentials(); print('✅ Credencial carregada'); print('project_id:', info.get('project_id'))"

# Resultado esperado:
# ✅ Credencial carregada
# project_id: bpfron
```

### **FASE 2: Validar App já tem tokens registrados (SEM AÇÃO)**

#### Passo 6: Verificar tokens no banco de dados

```bash
docker compose exec postgres psql -U monitor_user -d monitor -c "SELECT COUNT(*) FROM fcm_device_tokens WHERE active = TRUE;"

# Resultado esperado: >= 1
```

Se houver tokens antigos:
- ✅ Funcionarão imediatamente (pois o mismatch será corrigido)
- NÃO é necessário reinstalar app
- NÃO é necessário fazer login novamente

### **FASE 3: Testar Push**

#### Passo 7: Executar teste de alarme

1. Abrir dashboard web: http://localhost:8000/
2. Ir em: **Configurações** > **Alarmes**
3. Clicar em botão **"Testar"** do alarme ID 7
4. **Resultado esperado**: Push chega instantaneamente no app!

#### Passo 8: Verificar logs de sucesso

```bash
docker compose logs ingest --tail 50 | Select-String "Push enviado"

# Resultado esperado:
# [FCM] Push enviado token=gct...abc plate=TESTE-0000
```

---

## 📊 COMPARAÇÃO: ANTES vs DEPOIS

### ❌ ANTES (Estado Atual):

```
App (google-services.json)
  ├─ project_id: "bpfron" ✅
  └─ Token gerado para: projeto "bpfron" ✅
     └─ Registrado no backend ✅

Backend (docker-compose.yml)
  ├─ FCM_PROJECT_ID: "bpfron-monitoramento" ❌
  ├─ FCM_CREDENTIALS_PATH: "/app/secrets/firebase-adminsdk.json" ❌
  └─ Arquivo exists: False ❌
     └─ RuntimeError ao tentar enviar
        └─ sent=0, failed=1
```

### ✅ DEPOIS (Após Correção):

```
App (google-services.json)
  ├─ project_id: "bpfron" ✅
  └─ Token gerado para: projeto "bpfron" ✅
     └─ Registrado no backend ✅

Backend (docker-compose.yml)
  ├─ FCM_PROJECT_ID: "bpfron" ✅
  ├─ FCM_CREDENTIALS_PATH: "/app/secrets/firebase-adminsdk.json" ✅
  └─ Arquivo exists: True ✅
     └─ Access token gerado ✅
        └─ Firebase API chamada ✅
           └─ Push entregue no app ✅
              └─ sent=1, failed=0
```

---

## ⏱️ IMPACTO E TEMPO

| Aspecto | Necessário? | Tempo |
|---------|------------|-------|
| Desinstalar app | ❌ NÃO | 0 min |
| Reinstalar app | ❌ NÃO | 0 min |
| LoginNovamente | ❌ NÃO | 0 min |
| Gerar novo APK | ❌ NÃO | 0 min |
| Modificar app | ❌ NÃO | 0 min |
| Obter credential | ✅ SIM | 2 min |
| Colocar arquivo | ✅ SIM | 1 min |
| Editar docker-compose | ✅ SIM | 1 min |
| Restart backend | ✅ SIM | 1 min |
| **TOTAL** | | **5 min** |

**Usuários impactados**: 0 (servidor-side fix apenas)

---

## 🎯 CHECKLIST FINAL

Após implementar os passos acima, verificar:

- [ ] `firebase-adminsdk.json` copiado para `D:\monitoramento\secrets\`
- [ ] `docker-compose.yml` editado: `FCM_PROJECT_ID: "bpfron"` (não "bpfron-monitoramento")
- [ ] Backend reiniciado: `docker compose restart ingest`
- [ ] Credencial carregada: `RuntimeError` desapareceu
- [ ] Tokens antigos no BD continuam ativos e válidos
- [ ] Teste de alarme retorna: `"sent": 1, "failed": 0, "invalid_tokens": 0`
- [ ] App recebe push instantaneamente no teste
- [ ] Logs mostram: `[FCM] Push enviado token=...`

---

## 📝 RESUMO EXECUTIVO

| Pergunta | Resposta |
|----------|----------|
| **Project_id do app?** | ✅ `"bpfron"` |
| **Project_id da credencial admin?** | ❌ Arquivo não existe, não pode determinar |
| **Mensagem real de erro do FCM?** | ✅ `RuntimeError: Credencial FCM não encontrada em /app/secrets/firebase-adminsdk.json` |
| **Causa raiz confirmada?** | ✅ Arquivo de credencial ausente + mismatch de project_id |
| **Necessita reinstalar app?** | ❌ NÃO |
| **Necessita fazer login novamente?** | ❌ NÃO |
| **Necessita gerar novo APK?** | ❌ NÃO |
| **Tokens antigos serão validados?** | ✅ SIM (após corrigir project_id) |
| **Tempo para corrigir?** | ⏱️ ~5 minutos |

---

## 🔐 NOTA IMPORTANTE

**firebase-adminsdk.json é CONFIDENCIAL**:
- ✅ Nunca commitar em git
- ✅ Manter em `.gitignore` (já está, cheque)
- ✅ Manter em `secrets/` (usando volumes Docker)
- ✅ Usar variáveis de ambiente em produção
- ✅ Revogar chave antiga no Firebase Console antes de provisionar nova

---

**Status**: ✅ **PRONTO PARA IMPLEMENTAÇÃO**

Quer que eu implemente os passos agora?
