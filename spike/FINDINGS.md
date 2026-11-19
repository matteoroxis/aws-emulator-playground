# Spike AWS Emulator: Lambda Web Functions, Function URL, DynamoDB

Data: 2026-11-19. Host: devbox EC2 t3.large, Ubuntu 24.04 x86_64.
Versioni: aws-emulator 1.0.522 (release 2026.11.19, commit 2a51eb7), AWS CLI 2.41.1, boto3/botocore 1.44.6, Node 24.22.3.

## Setup
- Su Linux l'emulatore si installa come pacchetto nativo (`.deb`), niente Docker: `aws-emulator -p 9297 --telemetry off`.
- Diventa healthy in meno di un secondo (`/__admin/health` risponde 200 al secondo tentativo, con polling ogni 0,5 s).
- Ogni avvio genera nuove credenziali e una nuova CA in `~/.aws/emulator/<port>/`: vedi `emulator_env.sh`.

## Lambda Web Functions (`lambda-web`)
| Operazione | Esito |
|---|---|
| ListWebFunctions, GetWebAccountSettings | OK |
| CreateWebFunction (con revisionConfig + endpointConfig) | OK, stato Pending, poi Active in circa 0,5 s |
| GetWebFunction, GetWebFunctionEndpoint, GetWebFunctionRevision, ListWebFunctionRevisions, ListTags | OK |
| ListWebFunctionEndpoints | NotImplemented: "scaffolded but not implemented in this emulator" |
| Traffico HTTP sull'endpoint (`domainName` = `127.0.0.1:<porta>`) | **501**: "the emulator runs no web function code, so the handler's own response cannot be served." |

In sintesi: il control plane è emulato, il data plane no. Il codice della Web Function non viene eseguito.

## Event Function Python + DynamoDB + Function URL
- `CreateFunction` con `python3.13`: OK, Active. `Invoke` esegue davvero il codice.
- Dalla funzione, `boto3.client("dynamodb")` raggiunge il DynamoDB dell'emulatore senza variabili `AWS_ENDPOINT_URL*` nel sandbox. L'item scritto dalla funzione è visibile con uno `Scan` dall'esterno.
- `CreateFunctionUrlConfig` (AuthType NONE): URL `https://127.0.0.1:<porta>/_aws/lambda-url/<id>/`.
  - Senza resource policy risponde **403**, come su AWS (log: "no resource-based policy allows the lambda:InvokeFunctionUrl action").
  - Dopo `add-permission` (`lambda:InvokeFunctionUrl`, Principal `*`, FunctionUrlAuthType NONE) risponde **200** con un evento in formato payload 2.0.

## Sicurezza
- Il codice Python eseguito dall'emulatore non ha rete verso l'host: anche `socket.gethostname()` fallisce con "a Lambda function in this emulator has no host network to reach". Quindi non raggiunge l'IMDS della devbox (il ruolo IAM reale) né Internet.
- Le chiamate verso i servizi AWS fatte dal codice della funzione vengono instradate dall'emulatore.
- Nota: InfoWorld scrive che il codice non è in sandbox. Questo vale almeno per il runtime Python di Lambda in questa versione. Da riverificare a ogni release.

## Conseguenze per il progetto
- Per una Web Function non si può fare un test end-to-end sull'endpoint dell'emulatore.
- Però una Web Function è un normale server HTTP: in CI si può avviare come processo e puntarla al DynamoDB dell'emulatore. Così si testano HTTP e logica dati, mentre sull'emulatore si verifica il deploy del control plane.
- Il percorso Event Function + Function URL è invece testabile end-to-end per intero sull'emulatore.
