# Items API su Lambda Web Functions, testata in CI con AWS Emulator

Una piccola API CRUD su `/items` con DynamoDB, scritta in due forme con lo stesso contratto HTTP:

- `functions/web/`: Lambda Web Function in Node.js 24, un server HTTP normale che ascolta su `AWS_LAMBDA_HTTP_ENDPOINT`;
- `functions/event/`: Lambda classica (Event Function) in Python 3.13, esposta con una Function URL.

Ogni pull request verso `main` passa da GitHub Actions, che fa lint e unit test e poi lancia [AWS Emulator](https://docs.aws.amazon.com/emulator/latest/userguide/) direttamente sul runner, senza Docker e senza account AWS. Se i tre job sono verdi, GitHub fa il merge da solo.

## Cosa fa la pipeline

```
PR verso main
  ├─ lint       ruff, ruff format, node --check, shellcheck
  ├─ unit       pytest (routing Python, regole del gate) + node --test (server della Web Function)
  └─ emulator   installa aws-emulator (.deb, versione fissata) e lo avvia
                capability gate: verifica le API AWS che usiamo, una per una
                deploy: tabella DynamoDB, Web Function, Event Function + Function URL
                integrazione: stato delle risorse create sull'emulatore
                e2e: la stessa suite pytest contro due target
                  - web-function: server Node avviato nel runner, dati sul DynamoDB emulato
                  - function-url: Event Function servita dalla Function URL dell'emulatore
  → auto-merge (squash) quando lint, unit ed emulator sono verdi
```

Il workflow `nightly-emulator-latest.yml` ripete il job emulator ogni notte con l'ultima release dell'emulatore. Non è un check obbligatorio, quindi non blocca i merge, e con `--strict-gaps` fallisce quando un limite noto sparisce: è il segnale per togliere un workaround.

## Limiti dell'emulatore che il gate tiene d'occhio

Verificati con aws-emulator 1.0.522 (19 novembre 2026). Il riepilogo del job su GitHub mostra la tabella completa a ogni run.

| Comportamento | Cosa succede oggi | Come lo gestiamo |
|---|---|---|
| Traffico HTTP sull'endpoint della Web Function | 501: l'emulatore non esegue il codice delle Web Functions | il server Node gira come processo nel runner; un test `xfail(strict=True)` diventa rosso quando l'emulatore inizia a servirlo |
| `ListWebFunctionEndpoints` | `NotImplemented` | usiamo `GetWebFunctionEndpoint` |
| `rawPath` delle Function URL | contiene il prefisso `/_aws/lambda-url/<id>` | `items_api.py` lo toglie; su AWS il prefisso non c'è e la riga non fa nulla |

Il create/get delle Web Functions, DynamoDB con scritture condizionali, Invoke di Lambda Python e Function URL (compreso il 403 senza resource policy, come su AWS) funzionano.

## Mettere il repository su GitHub

1. Crea un repository pubblico vuoto e fai push di `main`.
2. In **Settings → General → Pull Requests** attiva *Allow auto-merge* e lascia attivo solo *Allow squash merging*.
3. Importa il ruleset di `main` (con la CLI `gh`, oppure da **Settings → Rules → Rulesets → Import a ruleset**):
   ```bash
   gh api -X POST repos/<owner>/<repo>/rulesets --input .github/rulesets/main.json
   ```
   Il ruleset obbliga a passare da una PR e richiede i check `lint`, `unit` ed `emulator`. Su un account free funziona solo con repository pubblici.
4. Per ogni modifica:
   ```bash
   git switch -c feature/qualcosa
   git commit -am "..."
   git push -u origin feature/qualcosa
   gh pr create --fill
   gh pr merge --auto --squash
   ```

## Lanciare la pipeline su una macchina Linux

`scripts/ci_local.sh` esegue gli stessi passi del workflow, nello stesso ordine, e simula `$GITHUB_ENV`. Serve una macchina Ubuntu con Python 3.13+, Node 24, `curl` e `sudo` per installare il pacchetto dell'emulatore.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
bash scripts/ci_local.sh
```

Per lavorare a mano contro l'emulatore:

```bash
bash scripts/emulator/install.sh
bash scripts/emulator/start.sh
. scripts/emulator/env.sh          # endpoint, credenziali e CA di questo avvio
python -m tools.capability_gate
```

Le credenziali e il certificato cambiano a ogni avvio, quindi `env.sh` va ricaricato dopo ogni `start.sh`. Lo script toglie dall'ambiente le credenziali AWS reali e disattiva l'instance metadata; nello spike il codice eseguito dall'emulatore non riusciva comunque a raggiungere la rete dell'host.

## Struttura

```
functions/web/        Web Function (Node.js 24): src/app.js routing, src/repo.js DynamoDB, src/server.js avvio
functions/event/      Event Function (Python 3.13) per la Function URL
tools/                capability_gate.py, deploy.py, aws_helpers.py
scripts/emulator/     install, start, env, stop
tests/unit/           nessun emulatore
tests/integration/    risorse create da tools/deploy.py
tests/e2e/            contratto HTTP contro entrambi i target
spike/FINDINGS.md     risultati grezzi delle prove esplorative fatte prima di scrivere la pipeline
```
