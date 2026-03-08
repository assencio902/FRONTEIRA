# 🔥 DIAGNÓSTICO: Push FCM Não Funciona

## Problema Identificado

**Status Atual:**
- ✅ App Flutter gera token FCM corretamente
- ✅ Token é registrado no backend (banco de dados)
- ✅ Lógica de alarme funciona (identifica usuários, busca tokens)
- ❌ **Backend NÃO consegue enviar push via Firebase**

---

## Causa Raiz (2 problemas críticos)

### 1️⃣ **Arquivo de Credencial Ausente**

O backend espera o arquivo:
```
D:\monitoramento\secrets\firebase-adminsdk.json
```

**Verificação realizada:**
```bash
docker compose exec ingest ls -la /app/secrets/
# Result: diretório VAZIO (só . e ..)
```

**Configuração atual (docker-compose.yml):**
```yaml
environment:
  FCM_CREDENTIALS_PATH: "/app/secrets/firebase-adminsdk.json"
  FCM_PROJECT_ID: "bpfron-monitoramento"
volumes:
  - ./secrets:/app/secrets:ro
```

O backend tenta carregar as credenciais em `fcm_service.py:_load_service_account_credentials()` mas o arquivo não existe, então:
- Nenhum access token é gerado
- Firebase HTTP API não é chamado
- Erro silencioso: "credentials_error" (não aparece nos logs porque a exceção é capturada)

---

### 2️⃣ **Mismatch de Project ID**

**App (google-services.json):**
```json
{
  "project_id": "bpfron"
}
```

**Backend (docker-compose.yml):**
```yaml
FCM_PROJECT_ID: "bpfron-monitoramento"
```

**Problema:** 
- O app gera tokens vinculados ao projeto Firebase `bpfron`
- O backend está configurado para enviar usando projeto `bpfron-monitoramento`
- Mesmo com credenciais corretas, haveria rejeição do Firebase (sender ID mismatch)

---

## Por Que os Logs Não Mostram Erro?

No código `fcm_service.py:_send_fcm_message()`:
```python
try:
    access_token, project_id = _get_access_token()
except Exception as exc:
    logger.error("[FCM] Credencial/Token indisponível: %s", exc)
    return False, f"credentials_error:{exc}"
```

- A exceção é capturada e retorna `(False, "credentials_error:...")`
- O log mostra apenas "Credencial/Token indisponível"
- Mas como o arquivo não existe, a exceção acontece em `_load_service_account_credentials()`
- E o código nunca chega até `_send_fcm_message()` porque falha antes

**Resultado:** O teste de alarme retorna:
```json
{
  "sent": 0,
  "failed": 1,
  "invalid_tokens": 0,
  "users": 3
}
```

Mas não há log específico mostrando qual foi o erro do Firebase.

---

## Solução Completa

### Opção A: Usar APENAS o projeto "bpfron" (Recomendado)

1. **Obter firebase-adminsdk.json do projeto "bpfron":**
   - Acesse Firebase Console: https://console.firebase.google.com/project/bpfron
   - Vá em: **Project Settings** > **Service Accounts**
   - Clique em **Generate New Private Key**
   - Baixe o arquivo JSON

2. **Colocar no local correto:**
   ```bash
   # Criar diretório secrets se não existir
   mkdir D:\monitoramento\secrets
   
   # Copiar arquivo baixado para:
   D:\monitoramento\secrets\firebase-adminsdk.json
   ```

3. **Corrigir FCM_PROJECT_ID no docker-compose.yml:**
   ```yaml
   environment:
     FCM_PROJECT_ID: "bpfron"  # ← mudar de "bpfron-monitoramento"
   ```

4. **Reiniciar backend:**
   ```bash
   docker compose restart ingest
   ```

5. **Testar novamente:**
   - Abrir dashboard web
   - Executar teste de alarme
   - Deve aparecer push no app!

---

### Opção B: Criar novo projeto Firebase "bpfron-monitoramento"

Se você quiser manter o backend com o project_id "bpfron-monitoramento":

1. Criar novo projeto no Firebase Console
2. Baixar novo `google-services.json` para o app
3. Substituir em: `flutter_app/android/app/google-services.json`
4. Gerar novo APK
5. Desinstalar app antigo de todos os dispositivos
6. Instalar novo APK
7. Logar novamente (para gerar novos tokens)
8. Obter firebase-adminsdk.json do novo projeto
9. Colocar em `secrets/firebase-adminsdk.json`
10. Reiniciar backend

**⚠️ Esta opção invalida TODOS os tokens existentes dos usuários!**

---

## Recomendação Final

**Use a Opção A** (projeto "bpfron" único), pois:
- ✅ Não precisa recompilar app
- ✅ Não precisa redistribuir APK
- ✅ Tokens existentes continuam válidos
- ✅ Apenas corrige backend (arquivo + variável)
- ✅ Usuários não precisam reinstalar nada

---

## Teste Final (após correção)

1. Verificar arquivo existe:
   ```bash
   ls -l D:\monitoramento\secrets\firebase-adminsdk.json
   cat D:\monitoramento\secrets\firebase-adminsdk.json | grep project_id
   # Deve mostrar: "project_id": "bpfron"
   ```

2. Reiniciar backend:
   ```bash
   docker compose restart ingest
   ```

3. Verificar logs do backend:
   ```bash
   docker compose logs ingest --tail 50 | grep FCM
   # Não deve ter erro de credencial
   ```

4. Testar push no dashboard:
   - Ir em Configurações > Alarmes
   - Clicar em "Testar Alarme"
   - Deve chegar push instantâneo no app!

5. Verificar logs do envio bem-sucedido:
   ```bash
   docker compose logs ingest --tail 100 | grep "Push enviado"
   # Deve aparecer: [FCM] Push enviado token=...
   ```

---

## Fluxo Correto (após correção)

```
┌─────────────────────────────────────────────────────────────────┐
│ App Flutter (br.gov.bpfron.monitoramento)                       │
│  └─ google-services.json → project_id: "bpfron"                 │
│     └─ Firebase.initializeApp()                                 │
│        └─ FirebaseMessaging.getToken()                          │
│           └─ Gera token FCM vinculado ao projeto "bpfron"      │
│              └─ POST /api/fcm/register-token                    │
│                 └─ Salva no PostgreSQL: fcm_device_tokens       │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Backend FastAPI (ingest)                                         │
│  └─ Recebe teste de alarme                                      │
│     └─ Busca usuários vinculados ao alarme                      │
│        └─ Busca tokens FCM ativos (SELECT FROM fcm_device_tokens)│
│           └─ fcm_service._send_fcm_message()                    │
│              └─ _get_access_token()                             │
│                 └─ _load_service_account_credentials()          │
│                    ├─ Lê: secrets/firebase-adminsdk.json ✅     │
│                    ├─ project_id: "bpfron" ✅ (DEVE SER IGUAL!)│
│                    └─ Gera Google OAuth2 access token           │
│                       └─ POST https://fcm.googleapis.com/v1/... │
│                          └─ Firebase valida: sender = "bpfron"  │
│                             └─ Token é do projeto "bpfron" ✅   │
│                                └─ Push entregue ao device! 🎉   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Resumo Executivo

| Item | Status Atual | Status Desejado | Ação Necessária |
|------|--------------|-----------------|-----------------|
| App google-services.json | `project_id: "bpfron"` ✅ | Sem mudança | Nenhuma |
| Backend firebase-adminsdk.json | ❌ **AUSENTE** | `project_id: "bpfron"` ✅ | Obter do Firebase Console |
| Backend FCM_PROJECT_ID | ❌ `"bpfron-monitoramento"` | `"bpfron"` ✅ | Editar docker-compose.yml |
| Token FCM registration | ✅ Funciona | Sem mudança | Nenhuma |
| Token FCM delivery | ❌ **FALHA** | ✅ Funciona | Corrigir acima |

**Tempo estimado para correção:** ~5 minutos
**Necessita rebuild/redeploy app:** ❌ NÃO
**Necessita reinstalar app:** ❌ NÃO
**Necessita relogin usuários:** ❌ NÃO
