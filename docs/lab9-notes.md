# Lab 9 — нотатки перед перенесенням ядра на Google Cloud

Що є в репозиторії станом на коміт `82d7b36` (2026-11-18). Ядро, яке переносимо: фронтенд, FastAPI API,
PostgreSQL. Код ще не змінювали.

## 0. Уточнення до вихідних припущень

Деякі пункти з постановки не збігаються з тим, що є в репозиторії:

| Припущення | Насправді |
| --- | --- |
| Aurora Serverless v2 | **RDS PostgreSQL 16, `db.t3.micro`** (`successfulsuccess-db`), приватна, `PubliclyAccessible: false`. Опис і коментарі в `infra/backend.yml` і `.env.example` досі згадують Aurora, але ресурс там `AWS::RDS::DBInstance`. |
| Усе описано в Terraform | Terraform (`infra/*.tf`, HCP Terraform) описує тільки **auth, reports, ai**. Ядро (ECR, backend Lambda + RDS, S3 + CloudFront) — це **CloudFormation**: `infra/ecr.yml`, `infra/backend.yml`, `infra/frontend.yml`, деплой через `make aws-*`. |
| Mangum або Lambda Web Adapter | **Mangum** (`backend/app/lambda_handler.py`). |
| Secrets Manager / SSM | Secrets Manager не використовується. SSM тримає тільки ключ Claude API для парсера. Пароль БД лежить відкритим текстом у змінній `DATABASE_URL` функції. |
| Bedrock (парсер) | Bedrock заблоковано на рівні акаунта; парсер працює через Claude API (`PARSER_PROVIDER=anthropic_api`). Він не входить у ядро. |

## 1. Структура репозиторію і збірка фронтенду

```
backend/    FastAPI (Python 3.12, uv), Alembic, тести; Dockerfile (uvicorn) і Dockerfile.lambda
frontend/   Next.js 16.3.4 + React 19, Tailwind 4, shadcn/ui, Amplify (Cognito)
infra/      CloudFormation: ecr.yml, backend.yml, frontend.yml
            Terraform:      auth.tf, reports.tf, ai.tf, versions.tf, variables.tf, outputs.tf
Makefile    локальна розробка (docker compose) і деплой на AWS
docker-compose.yml  db (postgres:17) + backend (:8000) + frontend (:3000)
```

**Фронтенд**

- Фреймворк: Next.js (App Router), тільки клієнтські компоненти: SSR і API routes не використовуються.
  Маршрути: `/`, `/login/`, `/auth/callback/`, `/today/`, `/meetings/new/`, `/privacy/`. Динамічних
  сегментів (`[id]`) немає, тому статичний експорт працює без `generateStaticParams`.
- `frontend/next.config.ts`: `output` дорівнює `"export"`, коли `NEXT_OUTPUT=export`, інакше
  `"standalone"`. `trailingSlash: true`, тому кожен маршрут стає папкою з `index.html`
  (`meetings/new/index.html`).
- Команда збірки: `npm run build` (= `next build`) з `NEXT_OUTPUT=export`. Результат лежить у
  **`frontend/out/`**.
- На AWS збирає `make aws-deploy-frontend`:
  `docker build --target export --output type=local,dest=frontend/out --build-arg NEXT_PUBLIC_...`
  (стадії `export-builder` і `export` у `frontend/Dockerfile`), потім `s3 sync` і інвалідація CloudFront.
  Можна зібрати й без Docker: `cd frontend && NEXT_OUTPUT=export npm run build`.
- Змінні, які вшиваються в бандл під час збірки (`NEXT_PUBLIC_*`, у рантаймі не змінюються):
  - **`NEXT_PUBLIC_API_BASE_URL`** — базовий URL API (`frontend/lib/api.ts`). Запити йдуть на
    `${API_BASE_URL}/api/v1/...`. Якщо змінну не задано зовсім, береться `http://localhost:8000`
    (`??`). Порожній рядок лишається порожнім, тоді запити стають відносними (`/api/v1/...`):
    саме це потрібно для одного origin через rewrite Firebase Hosting. Docker-збірка передає
    незаданий `ARG` як порожній рядок.
  - `NEXT_PUBLIC_COGNITO_USER_POOL_ID`, `NEXT_PUBLIC_COGNITO_CLIENT_ID`, `NEXT_PUBLIC_COGNITO_DOMAIN`,
    `NEXT_PUBLIC_COGNITO_GOOGLE_ENABLED` (`frontend/lib/auth.ts`).
  - `NEXT_PUBLIC_PARSER_URL` — function URL парсера agenda (Lab 6). Якщо порожній, кнопка
    "Paste an agenda" прихована.
- CloudFront Function `IndexRewriteFunction` (`infra/frontend.yml`) дописує `index.html` до шляхів
  без розширення, бо S3 REST endpoint не має index documents. На Firebase Hosting вона не потрібна:
  Firebase сам віддає `index.html` для папок.

## 2. Що специфічне для Lambda

| Що | Де | Що з цим на Cloud Run |
| --- | --- | --- |
| `mangum>=0.19.0` у залежностях | `backend/pyproject.toml` | Не потрібен. Можна залишити: він нікому не заважає. |
| `handler(event, context)`: Mangum (`lifespan="off"`) + дві службові дії: `{"action": "migrate"}` (Alembic у окремому потоці) і `{"action": "show-agendas"}` | `backend/app/lambda_handler.py` | Не використовується. Міграції запускаються через `entrypoint.sh` або Cloud Run Job (див. п. 3). |
| Образ `public.ecr.aws/lambda/python:3.12`, `CMD ["app.lambda_handler.handler"]`, залежності ставляться в `LAMBDA_TASK_ROOT`, байткод компілюється під час збірки (у Lambda read-only FS) | `backend/Dockerfile.lambda` | Замість нього береться **`backend/Dockerfile`** (python:3.12-slim, uvicorn, `entrypoint.sh`, користувач `appuser`). |
| Інші обробники в тому самому образі: `app.reports.lambda_handler.handler` (звіт), `app.ai.agenda_lambda.handler` (парсер) | `ImageConfig.Command` у `reports.tf` і `ai.tf` | Ці функції не входять у ядро і лишаються на AWS. |
| `COGNITO_JWKS`: ключі пулу передаються в env, бо VPC-Lambda без NAT не має виходу в інтернет | `infra/backend.yml`, `Makefile` (`aws-deploy-backend`) | Cloud Run має egress в інтернет, тож змінну можна не задавати: `CognitoVerifier` сам завантажить `jwks.json`. |
| Function URL (`AuthType: NONE`, `BUFFERED`), `ApiUrl` = `https://<id>.lambda-url.us-east-1.on.aws` | `infra/backend.yml` | Його замінює URL сервісу Cloud Run, або rewrite Firebase Hosting на нього. |
| VPC, security groups, пул з'єднань, «один інстанс = одне з'єднання», `Timeout: 60` | `infra/backend.yml` | Див. п. 3 (Cloud SQL) і п. 6. |
| Make-цілі `aws-push` (`--platform linux/amd64 --provenance=false`), `aws-deploy-backend`, `aws-migrate`, `aws-url`, `aws-logs` | `Makefile` | Потрібні нові цілі `gcp-*` (див. п. 6). |

Збірка: **контейнерний образ** (не zip), ECR `successfulsuccess-backend`, функція закріплена на digest.
Zip використовує тільки mailer звіту (`infra/lambda/report_mailer/`), а він не входить у ядро.

`backend/Dockerfile` майже готовий для Cloud Run. Що варто знати:
- `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` слухає **8000**, а Cloud Run
  за замовчуванням чекає 8080 (`$PORT`). Найпростіше задати `--port 8000` у `gcloud run deploy`.
  Інший варіант — shell-форма CMD з `${PORT:-8000}`.
- `ENTRYPOINT entrypoint.sh` запускає `alembic upgrade head`, коли `RUN_MIGRATIONS_ON_START` не дорівнює
  `false` (за замовчуванням `true`).
- `ARG INSTALL_DEV=false`: для проду dev-залежності не ставляться. Тоді `boto3` не потрапляє в образ,
  і це нормально для ядра: його імпортує тільки код звітів і Bedrock.
- Образ збирати під `linux/amd64` (Cloud Run його підтримує).

## 3. Підключення до БД

- **Змінна:** `DATABASE_URL` (pydantic-settings, `backend/app/config.py`). Значення за замовчуванням:
  `postgresql+asyncpg://app:app@db:5432/meetings`.
  На AWS: `postgresql+asyncpg://app:<AWS_DB_PASSWORD>@successfulsuccess-db.cq5sm6qqgpxq.us-east-1.rds.amazonaws.com:5432/meetings`.
  Пароль обмежено до `[a-zA-Z0-9_-]`, бо він вставляється в URL без екранування.
- Інші змінні ядра: `APP_TIMEZONE` (Europe/Kyiv), `CORS_ORIGINS`, `LOG_LEVEL`,
  `RUN_MIGRATIONS_ON_START`, `COGNITO_REGION`, `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`,
  `COGNITO_JWKS` (необов'язкова). Змінні `PARSER_*` ядру не потрібні.
- **ORM:** SQLAlchemy 2 async + **asyncpg** (`backend/app/db.py`). Один модульний `create_async_engine`
  з `pool_pre_ping=True` і стандартним пулом (5 + 10 overflow на процес). Розмір пулу в налаштуваннях
  не винесено. Увесь код асинхронний.
- **Міграції: Alembic**, `backend/alembic/` (`0001_create_meetings`, `0002_users_and_meeting_owner`,
  `0003_meeting_agenda`). `alembic/env.py` бере URL з `settings.database_url` (async engine, `NullPool`),
  тож Alembic і застосунок читають ту саму змінну.
  Запуск: `entrypoint.sh` під час старту контейнера (compose), `make migrate` локально,
  `make aws-migrate` (виклик Lambda з `{"action": "migrate"}`) на AWS.
- **Схема:** `users` (pk = Cognito `sub`), `meetings` (`owner_id` → `users.id`, JSONB `agenda`,
  `ai_suggestion`), `participants`. Використовуються JSONB і `timestamptz`, тому потрібен саме PostgreSQL
  (Cloud SQL for PostgreSQL 16 або 17).
- **Сид-дані:**
  - `python -m app.seed <cognito-sub>` (`make seed owner=...`) додає 3 демо-зустрічі на сьогодні
    одному користувачу. Потрібен справжній `sub` з Cognito.
  - `python -m app.reports.seed_weeks` (`make seed-weeks`) додає ~15 зустрічей за два минулі ISO-тижні
    двом демо-користувачам `seed-olena` / `seed-taras` (для звіту).
- **Cloud SQL без змін у коді.** Cloud Run підключає інстанс як Unix-сокет
  (`--add-cloudsql-instances PROJECT:REGION:INSTANCE`), а SQLAlchemy+asyncpg розуміє такий URL:
  `postgresql+asyncpg://app:<PASS>@/meetings?host=/cloudsql/PROJECT:REGION:INSTANCE`.
  Альтернативи: Cloud SQL Python Connector (`cloud-sql-python-connector[asyncpg]`, треба переписати
  `db.py` під `async_creator`) або приватний IP + Direct VPC egress.

## 4. Префікс `/api`

Так. Усі бізнес-маршрути зібрані в `APIRouter(prefix="/api/v1")` (`backend/app/api/v1/__init__.py`):

```
GET/POST        /api/v1/meetings
GET/PUT/DELETE  /api/v1/meetings/{id}
PUT             /api/v1/meetings/{id}/agenda
GET             /api/v1/me
POST            /api/v1/me/sync
```

Поза `/api` лежать тільки `/health` (перевірка живості й БД), `/docs`, `/redoc`, `/openapi.json`.
Фронтенд їх не викликає. Тому rewrite `"/api/**" → Cloud Run` у `firebase.json` покриває все, що
потрібно фронтенду, і при `NEXT_PUBLIC_API_BASE_URL=""` браузер ходить на той самий origin.
`/health` і `/docs` доступні напряму за URL `*.run.app`.

На що звернути увагу:
- Маршрути FastAPI **без кінцевого слеша** (`/api/v1/meetings`, `/api/v1/me`), а фронтенд зібраний з
  `trailingSlash: true`. Не вмикати `"trailingSlash": true` у `firebase.json`. Інакше Firebase може
  перенаправити `/api/v1/me` на `/api/v1/me/`, а FastAPI відповість 307 на інший URL.
- `POST /api/v1/meetings` повертає заголовок `Location` (його відкрито в `expose_headers`).

## 5. CORS і перевірка токенів Cognito

**CORS** налаштовано тільки в FastAPI (`CORSMiddleware` у `backend/app/main.py`): `allow_origins` з
`CORS_ORIGINS` (через кому), `allow_credentials=True`, усі методи й заголовки. На AWS значення —
CloudFront-домен (`make aws-deploy-backend` читає `AllowedOrigins` зі стека frontend); локально —
`http://localhost:3000`.
- Якщо фронтенд і API на одному origin (Firebase Hosting + rewrite), браузер не надсилає preflight,
  і CORS не відіграє ролі. `CORS_ORIGINS` можна залишити для `http://localhost:3000`.
- Якщо фронтенд ходить напряму на `*.run.app`, у `CORS_ORIGINS` треба внести
  `https://<project>.web.app,https://<project>.firebaseapp.com`.

**Токени.** `backend/app/auth.py`: `CognitoVerifier` перевіряє RS256 JWT за ключами пулу (JWKS з
`COGNITO_JWKS` або з `https://cognito-idp.<region>.amazonaws.com/<pool>/.well-known/jwks.json`),
`iss`, `exp`, `token_use == "access"` і `client_id`. `/api/v1/me/sync` додатково перевіряє ID-токен.

**Чи працюватиме API без Cognito? Ні.** Кожен маршрут `/api/v1/*` залежить від `get_current_user`
(через `MeetingServiceDep` або напряму). Без `COGNITO_USER_POOL_ID` / `COGNITO_CLIENT_ID` функція
`get_verifier()` кидає `AuthNotConfiguredError`, і API відповідає **503 «Sign-in is not configured on
the server»**. Без токена відповідь — 401. Режиму обходу для розробки немає. Без Cognito працює тільки
`/health`.

Фронтенд без `NEXT_PUBLIC_COGNITO_*` теж непридатний: `isAuthConfigured = false`, `RequireAuth`
перенаправляє на `/login/`, а там написано «Sign-in isn't configured on this deployment».
`meetings.owner_id` — це Cognito `sub`, тож дані прив'язані до користувачів Cognito.

Як можна вчинити:
1. **Залишити Cognito на AWS** (найменше змін). Cloud Run бачить інтернет, тож перевірка токенів
   працює. Треба додати Firebase-домен у `callback_urls` / `logout_urls` app client: зараз їх будує
   `local.site_origins = [CloudFront, var.local_origin]` у `infra/versions.tf`, тобто потрібна нова
   змінна Terraform і push у `main` (apply робить HCP).
2. **Firebase Auth / Identity Platform.** Переписати `frontend/lib/auth.ts`, `auth-provider.tsx`,
   `auth-page.tsx`, `login-redirect.tsx` (Amplify → Firebase SDK), а також `CognitoVerifier`
   (issuer `https://securetoken.google.com/<project>`, `aud = <project>`, ключі Google). Наявні
   `owner_id` не збігатимуться з новими uid.
3. Тимчасовий dev-обхід автентифікації. Зараз його в коді немає, і робити його в проді не варто.

## 6. Зміни для Cloud Run + Cloud SQL (від найважливіших)

1. **Cloud SQL for PostgreSQL** (16, `db-f1-micro` / `db-g1-small`), база `meetings`, користувач `app`.
   Пароль — у **Secret Manager**, у Cloud Run передається через `--set-secrets`. Краще зберігати в
   секреті весь `DATABASE_URL`: код читає одну змінну і не збирає URL з частин.
2. **`DATABASE_URL` під Cloud SQL**: Unix-сокет
   `postgresql+asyncpg://app:<PASS>@/meetings?host=/cloudsql/<PROJECT>:<REGION>:<INSTANCE>` +
   `--add-cloudsql-instances`. Сервісному акаунту Cloud Run потрібна роль `roles/cloudsql.client`.
   Код не змінюється.
3. **Образ для Cloud Run** з `backend/Dockerfile` (не `.lambda`), `--platform linux/amd64`,
   push в **Artifact Registry**. У `gcloud run deploy` задати `--port 8000` (або перевести CMD на `$PORT`).
4. **Міграції**: не запускати на кожному старті кількох інстансів. Поставити
   `RUN_MIGRATIONS_ON_START=false` на сервісі й зробити **Cloud Run Job** з тим самим образом і
   командою `alembic upgrade head` (аналог `make aws-migrate`). Для першого деплою з одним інстансом
   `true` теж спрацює.
5. **Автентифікація** (див. п. 5): мінімально — Cognito лишається, у сервіс передаються
   `COGNITO_REGION=us-east-1`, `COGNITO_USER_POOL_ID`, `COGNITO_CLIENT_ID`, а Firebase-домени
   додаються в callback/logout URLs у `infra/auth.tf`/`versions.tf`.
6. **Firebase Hosting**: `firebase.json` з `"public": "frontend/out"` і rewrite
   `{"source": "/api/**", "run": {"serviceId": "<service>", "region": "<region>"}}`, без
   `trailingSlash: true`. Фронтенд збирати з `NEXT_OUTPUT=export`, `NEXT_PUBLIC_API_BASE_URL=""`
   і тими самими `NEXT_PUBLIC_COGNITO_*`.
7. **Ліміти з'єднань**: на `db-f1-micro` приблизно 25 з'єднань, а кожен інстанс Cloud Run може
   відкрити до 15 (пул 5 + 10) при concurrency 80. Обмежити `--max-instances` (наприклад, 2–3) і/або
   винести `pool_size` / `max_overflow` у `Settings`.
8. **Перенесення даних з RDS** (за потреби): RDS приватна і без публічного доступу, тож для
   `pg_dump` знадобиться тимчасовий доступ (bastion або тимчасово `PubliclyAccessible` + правило SG
   на свою IP). Потім `pg_restore` у Cloud SQL. Або почати з порожньої БД і `app.seed` /
   `app.reports.seed_weeks`.
9. **CORS**: `CORS_ORIGINS` = Firebase-домени (тільки якщо API викликається напряму, а не через rewrite)
   плюс `http://localhost:3000`.
10. **Парсер agenda** (лишається на AWS): у CORS його function URL (`infra/ai.tf`) додати
    Firebase-домен, або збирати фронтенд з `NEXT_PUBLIC_PARSER_URL=""`, щоб сховати функцію.
    Збереження agenda йде через API (`PUT /api/v1/meetings/{id}/agenda`), тож воно потрапить у Cloud SQL.
11. **Make-цілі `gcp-*`** у стилі наявних (POSIX shell, мають працювати з PowerShell через `make`):
    build/push в Artifact Registry, `run deploy`, migrate job, `firebase deploy`, URL, логи.
    Інфраструктуру GCP описати в Terraform (провайдер `google`): окремий каталог або workspace,
    щоб не змішувати зі state AWS.
12. **Тижневий звіт** (поза ядром): report builder на AWS читає RDS. Після перенесення він або
    звітуватиме за застарілими даними, або його треба вимкнути чи перенести (Cloud Scheduler +
    Pub/Sub + Cloud Run Job). Задокументувати рішення.
13. Прибирання (необов'язково): `mangum` і `Dockerfile.lambda` потрібні, поки працюють Lambda-воркери
    звіту й парсера; не видаляти, поки вони живі. Виправити застарілі згадки Aurora.
