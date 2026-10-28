# Spry: container diagram (C4, level 2)

The whole system as deployed in `us-east-1`, including Lab 6's agenda parser. The
two Lab 6 paths are:

- **parse:** browser → agenda parser → Bedrock (for now the Claude API, the fallback
  while Bedrock is blocked for the account);
- **save:** browser → API → RDS.

The parser never writes. See [ADR 0006](../adr/0006-llm-agenda-parsing.md).

```mermaid
C4Container
  title Spry (SuccessfulSuccess): containers, us-east-1

  Person(user, "Team member", "Plans meetings and agendas in a browser")

  System_Ext(cognito, "Amazon Cognito", "User pool, hosted sign-in, Google federation")
  System_Ext(bedrock, "Amazon Bedrock", "Claude: Messages API (bedrock-mantle) or Converse")
  System_Ext(claudeapi, "Claude API", "api.anthropic.com: the fallback while Bedrock is blocked")
  System_Ext(ssm, "SSM Parameter Store", "SecureString with the Claude API key")
  System_Ext(ses, "Amazon SES", "Sends the weekly report email")

  System_Boundary(spry, "Spry on AWS") {
    Container(spa, "Web app", "Next.js static export, S3 + CloudFront", "Meetings, agenda form, Paste an agenda")
    Container(parser, "Agenda parser", "Python Lambda + function URL, outside the VPC", "Checks the token, limits the text, asks Claude for record_agenda, validates the answer")
    Container(mailer, "Report mailer", "Python Lambda, outside the VPC", "Emails each new report CSV")
    ContainerQueue(queue, "Report requests", "SQS + dead-letter queue", "Which ISO week to build")
    Container(bucket, "Reports bucket", "S3", "reports/<week>.csv")
    Container(scheduler, "Weekly schedule", "EventBridge Scheduler", "Monday 07:00 Europe/Kyiv")

    Boundary(vpc, "Default VPC, no NAT") {
      Container(api, "Meetings API", "FastAPI on Lambda + function URL", "Meetings, participants, agendas; owner-scoped")
      Container(builder, "Report builder", "Python Lambda (backend image)", "Builds the weekly CSV")
      ContainerDb(db, "Database", "RDS PostgreSQL 16, db.t3.micro", "users, meetings (+ agenda, ai_suggestion), participants")
    }
  }

  Rel(user, spa, "Uses", "HTTPS")
  Rel(spa, cognito, "Signs in, gets an access token", "HTTPS")
  Rel(spa, parser, "Parse: pasted text, today, time zone", "HTTPS POST, Bearer token")
  Rel(parser, cognito, "Fetches signing keys", "HTTPS, JWKS")
  Rel(parser, bedrock, "Calls Claude, tool record_agenda", "HTTPS, IAM role")
  Rel(parser, claudeapi, "Same request (fallback, deployed now)", "HTTPS, API key")
  Rel(parser, ssm, "Reads the API key at cold start", "HTTPS, IAM role")
  Rel(spa, api, "Meetings; Save: agenda + AI suggestion", "HTTPS JSON, Bearer token")
  Rel(api, db, "Reads and writes", "SQL, asyncpg")
  Rel(scheduler, queue, "Weekly message")
  Rel(queue, builder, "Week to build", "SQS event source")
  Rel(builder, db, "Reads the week's meetings", "SQL")
  Rel(builder, bucket, "Writes the CSV", "S3 gateway endpoint")
  Rel(bucket, mailer, "ObjectCreated", "S3 event")
  Rel(mailer, ses, "Sends the CSV", "HTTPS, IAM role")

  UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Containers

| Container | Runs as | Lab | Notes |
| --- | --- | --- | --- |
| Web app | Static export in S3, served by CloudFront | 2, 4 | Gets Cognito tokens with Amplify; calls the API and the parser with the access token |
| Meetings API | Lambda (container image) + public function URL, in the VPC | 3, 4 | Checks the Cognito token itself; signing keys are passed in at deploy, since it has no internet |
| Database | RDS PostgreSQL 16, `db.t3.micro` | 4 | Reached only from the API's and the builder's security group. It is RDS, not Aurora |
| Agenda parser | Lambda (same image, handler `app.ai.agenda_lambda.handler`) + public function URL, **outside** the VPC | **6** | No database access. 401 without a token, 413 over 10,000 characters, one JSON log line per parse. Model set by `PARSER_PROVIDER` / `PARSER_MODEL`; deployed now: `anthropic_api` / `claude-opus-5-5`, key from SSM |
| Report builder | Lambda (same image), in the VPC | 5 | Triggered by SQS; writes to S3 through the gateway endpoint |
| Report mailer | Lambda (inline code), outside the VPC | 5 | Triggered by S3; sends through SES |
| Report requests | SQS queue + DLQ | 5 | Filled by the schedule and `make report-now` |

## The two Lab 6 paths

```mermaid
sequenceDiagram
  actor U as User
  participant W as Web app
  participant P as Agenda parser
  participant B as Claude (Bedrock, or the Claude API)
  participant A as Meetings API
  participant D as RDS

  U->>W: Pastes text, presses Parse
  W->>P: POST {text, today, tz} + access token
  P->>P: Verify token (401), check length (413)
  P->>B: system prompt + text inside pasted_text tags, tool record_agenda
  B-->>P: tool_use input
  P->>P: Validate against ParsedAgenda (one retry, else 422)
  P-->>W: {agenda, model, prompt_version}
  W->>U: Pre-filled form, fields marked "suggested"
  U->>W: Corrects a field, presses Save
  W->>A: PUT /meetings/{id}/agenda {agenda, ai_suggestion, ai_model, ai_prompt_version}
  A->>D: UPDATE meetings (owner-scoped)
  A-->>W: Meeting with its agenda
```
