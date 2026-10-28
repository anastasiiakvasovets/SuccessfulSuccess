# ADR 0006: Parse pasted agendas with Claude, outside the VPC

- **Status:** Accepted. The parser runs Claude Opus 5.5 through the Claude API as a
  fallback while Bedrock is blocked for the account (see [Model](#model)).
- **Date:** 2026-10-27; fallback added 2026-10-28
- **Lab:** 6, Part 4 ([assignment](../labs/lab6.md))

## Context

Agendas reach our users as emails, chat messages and notes, not as forms. *Paste
an agenda* lets a user paste that text into a meeting and get the normal agenda
form back, pre-filled. The user checks it and saves it. The model suggests; the
person decides.

Constraints:

- **No NAT.** The API Lambda and the report builder run in the default VPC with
  no NAT gateway. The only endpoint is Lab 5's S3 gateway endpoint. Nothing in
  the VPC can reach a model today.
- **$0 when idle.** Every part of Spry costs nothing while nobody uses it, except
  the RDS instance (`db.t3.micro`, PostgreSQL 16). A new feature should not break that.
- **Every call costs money.** A model call is billed per token, so the endpoint
  must be authenticated and must refuse oversized input before it reaches the model.
- **Text from outside.** Pasted text comes from emails anyone can send, so it may
  contain instructions ("ignore your instructions and…"). It must be treated as data.
- **Answers can be wrong.** A model can return a confident, invalid or invented
  value with HTTP 200.

## Decision

**A separate parser function, outside the VPC.** `successfulsuccess-agenda-parser`
([`infra/ai.yml`](../../infra/ai.yml)) reuses the backend image with another handler
(`app.ai.agenda_lambda.handler`), as the Lab 5 report builder does. It has no
`VpcConfig` because it needs no database. It receives text and returns JSON. It reaches
the model and Cognito's signing keys over the internet. Timeout is 30 s and memory is 512 MB.

**Its own public function URL, authenticated in the handler.** `AuthType: NONE` with
the same two public-URL permissions as the API (Lab 4). CORS on the URL allows
POST from the site's origin and `localhost:3000` only. The handler:

1. verifies the Cognito access token against the pool's JWKS and answers 401 otherwise;
2. refuses text over 10,000 characters with 413, before any model call;
3. sends today's date and the user's time zone with the text, so "Monday" means the
   user's Monday.

**The model only suggests. It never writes.** The model answers by calling one tool,
`record_agenda`, whose input schema is the `ParsedAgenda` Pydantic model. Its answer is
validated. An invalid answer is shown back to the model once, then the request fails
with 422. Saving goes through the existing API, `PUT /api/v1/meetings/{id}/agenda`,
with its usual validation and owner scoping. The save also carries the suggestion
as the parser returned it, plus the model id and prompt version. The API stores them
in `meetings.ai_suggestion`, `ai_model` and `ai_prompt_version`, next to the agenda
the user actually saved. The difference between the two is the quality signal.

**The pasted text is data.** It is wrapped in `<pasted_text>` tags, and the system
prompt says it is never instructions. Whatever the model returns must still pass the
schema, the user's review and the API's validation.

### Model

**The model is a configuration choice, not code.** The parser calls the model through
a small provider interface ([`app/ai/providers.py`](../../backend/app/ai/providers.py)),
selected by two settings that `make aws-deploy-ai` passes to the stack:

| `PARSER_PROVIDER` | API | Example `PARSER_MODEL` |
| --- | --- | --- |
| `anthropic` | Anthropic Messages API on Bedrock (`bedrock-mantle`) | `anthropic.claude-opus-5-5` |
| `converse` | Bedrock Converse API (`bedrock-runtime`) | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `anthropic_api` | The Claude API directly (`api.anthropic.com`), with an API key | `claude-opus-5-5` |
| `fake` | none: splits the text into lines, for building without a model | — |

`anthropic` and `anthropic_api` send the same Messages request: the same tool, the
same `effort: low`, and the same retry. Only the client and the way it authenticates
differ.

The target was **Claude Opus 5.5 on Bedrock** through the Messages API, as in the lab.

**Bedrock is blocked for the account.** On the AWS Free plan, Bedrock quotas for
Claude were 0, and Opus 5.5 answered
`403 anthropic.claude-opus-5-5 is not available for this account`. The account moved to the
Paid plan, and a quota increase was requested from AWS Support. On 2026-10-28, `make
llm-hello` still failed for all 16 models tried, from five providers' model families:

- **"Not available for this account":** Claude Opus 5.5, Claude Haiku 5.5, OpenAI GPT-6 and GPT-6.1.
- **Daily token quota of 0:** Claude Haiku 4.5, Sonnet 4.6 and 4.5; Amazon Nova Micro and Lite;
  Llama 3.3 70B; Mistral Pixtral Large; gpt-oss-20b.

**Fallback: the same model through the Claude API.** On 2026-10-28 AWS Support declined
the quota increase (case 179312089700299) until the account has usage history and a full
billing cycle, so the Claude API fallback stays. Until Bedrock answers, the deployed parser runs `PARSER_PROVIDER=anthropic_api`, `PARSER_MODEL=claude-opus-5-5`.
It is the same model and the same request, sent to Anthropic directly with an API key.

The key is stored as the SSM SecureString `/successfulsuccess/anthropic-api-key`,
encrypted with the AWS-managed `aws/ssm` key:
- The function reads it once per cold start and keeps it only in memory.
- Its environment holds the parameter's name, never the key.
- Its role may `ssm:GetParameter` on that one parameter and nothing else in SSM.
- The key is never logged.

Locally, `make llm-hello` and `make parse` read `ANTHROPIC_API_KEY` from `.env`
(gitignored). The key reaches the backend container by name only, never on a command line.

Moving back to Bedrock once access is granted needs no code: only `make aws-deploy-ai
PARSER_PROVIDER=anthropic PARSER_MODEL=anthropic.claude-opus-5-5`.

**Which model: Claude Opus 5.5** (`claude-opus-5-5` now, `anthropic.claude-opus-5-5` on
Bedrock once access is granted). The five Step 5 inputs were run through Opus 5.5 and
Claude Haiku 5.5 ([table](../lab6-answers.md#step-5-table)):

- **The scores tie:** 60 of 62 fields correct each, no invented values in either.
- **Opus 5.5's two mistakes** are format errors in `starts_at` (no offset; "after lunch"
  inside a date-time). A stricter schema rejects both, and the existing retry then corrects them.
- **Haiku 5.5's two mistakes** are worse. It gave a wrong UTC offset (an hour off, and it
  passes any schema), and it turned a shopping list into five agenda items.
- **Cost:** Opus 5.5 is ≈ 28 times dearer ($0.0115 against $0.0004 per parse), but at
  ≈ $30 a month for 2,600 parses the error profile matters more.

To revisit with `agenda-v2`: once the offset is computed in code and an empty answer
becomes 422 (question 1 in the answers), Haiku 5.5's remaining errors are the ones those
changes remove. Re-run the five inputs on both models then.

## Alternatives considered

| Alternative | Why it lost |
| --- | --- |
| **Call the model from the API through a VPC interface endpoint** | The API already has the user's token and the database, but the endpoint costs ≈ $7.30 a month for each AZ it is placed in (two for availability), before data charges. That ends "$0 when idle" for a feature that needs no database. It would also keep the API's VPC function busy for 2–8 s per parse. |
| **The Claude API directly as the primary path** | Same Messages API and the newest features first, but it needs an API key to store and rotate, which IAM roles avoid. Its bill is outside the AWS bill. The course's platform is AWS. It lost as the *primary* path. It is used now as the *fallback*, because Bedrock was blocked for the account, and its costs are listed under Consequences. |
| **A plain regular-expression parser** | Free, fast and deterministic, but real agendas are free text in several languages. The `fake` provider is such a parser, and it shows the limit: on the lab's Ukrainian example it finds the topics and "45 хв" / "15 хв", but never an owner, a date or an action item. Claude Opus 5.5 found all of them ([input 1](../lab6-answers.md#1-the-ukrainian-example-from-the-introduction)). |

## Consequences

**Cost per parse, measured on the deployed parser** (the `agenda_parsed` log lines of
the five Step 5 inputs, 2026-10-28, `claude-opus-5-5` through the Claude API):

- **$0.0115 per parse** on average: 1,252 input / 327 output tokens, 3.9 s latency.
- Range: $0.0084–$0.0139 and 2.2–5.0 s.
- Claude Haiku 5.5 on the same inputs: $0.00041 per parse. One real log line is in
  [`docs/lab6-log-line.json`](../lab6-log-line.json).

Twenty organisations parsing 30 agendas a week is about 2,600 parses a month: **≈ $30 a
month** with Opus 5.5, ≈ $1 with Haiku 5.5. In testing, a saved agenda took 1.8 parses
on average (9 parses for 5 saves), so ≈ $55 a month is the more honest Opus figure.

The function itself costs nothing when idle. With the Claude API provider, a cold
start takes **7.7 s**: loading the `anthropic` SDK and fetching the key from SSM. It
was 3.2 s with the fake provider. That is close to Lambda's 10-second limit for
the init phase, and the user waits for it on the first parse after a deploy or a quiet period.

**What is logged.** One JSON line per parse in `/aws/lambda/successfulsuccess-agenda-parser`
(7-day retention):
- `event`, `status`, `user` (Cognito `sub`), `provider`, `model`, `prompt_version`;
- `chars`, `input_tokens`, `output_tokens`, `latency_ms`, `cost_usd`.

Failed parses are logged too, with the tokens they used. Never logged: the pasted
text and the API key.

The saved agendas and their suggestions stay in RDS. `make aws-agendas` shows the
latest ones read-only, which is the material for evaluating a new prompt version.

**When the model is down or busy:**
- The parser answers 503, or 429 when throttled.
- The screen says so and the user types the agenda by hand in the same form.
- Nothing else in Spry calls a model, so meetings, sign-in and the weekly report keep working.

**What the Claude API fallback costs us:**
- **A stored secret.** There is a key to keep, rotate and protect, which an IAM role on
  Bedrock would not need. Rotating it means updating the SSM parameter. Running
  functions keep the old key until their next cold start, so after rotating, run
  `make aws-deploy-ai` to make every instance pick up the new one.
- **Billing outside AWS.** Parses are paid on Anthropic's invoice:
  - AWS Budgets (`monthly-5usd`), Cost Explorer and the `PROJECT_NAME` cost tag do not see them.
  - The only cost record on the AWS side is `cost_usd` in our own log lines, computed from list prices.
  - A spend limit in the Anthropic Console is the matching guard.
- **Data leaves AWS.** Pasted agenda text is sent to Anthropic's API rather than
  staying within the AWS account's Bedrock endpoint.

**Risks we accept for now:**
- **No per-user rate limit and no reserved concurrency.** A signed-in user can parse
  as often as they like.
- **IAM is broad on Bedrock.** The role may call `bedrock-mantle:CreateInference` and
  `bedrock:InvokeModel` on `*`. Narrowing it to the chosen model is a follow-up. SSM
  access is already limited to one parameter.
- **The budget is a warning, not a cap.** The AWS backstop is the existing Budgets
  alarm `monthly-5usd` ($5 a month, emailed to the owner). It sends an alert; it
  does not stop spending, and it does not cover the Claude API.
