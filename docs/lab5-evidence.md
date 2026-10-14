# Lab 5 — evidence

Function `successfulsuccess-report-builder`, log group
`/aws/lambda/successfulsuccess-report-builder` (us-east-1, JSON log format).

## Trigger 1: schedule (direct invoke, before SQS)

EventBridge Scheduler `successfulsuccess-weekly-report` invoking the builder directly, with input
`{"source": "schedule"}`. For this run the schedule was deployed with
`make aws-deploy-reports SCHEDULE="rate(5 minutes)"` (schedule modified 2026-10-13 16:54:27 UTC),
then set back to `cron(0 7 ? * MON *)` in Europe/Kyiv at 16:56:37 UTC.

The scheduler fired at 16:55:09 UTC. No manual invoke was made in that window, and the request id
differs from the two earlier manual invokes (`aaf18f0e-…` seed, `b2b37e43-…` schedule payload by hand).

```json
{"timestamp": "2026-10-13T16:55:09Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "7c6ace62-43d1-4e0b-97b6-48234c656dbb", "trigger": "schedule", "week": "2026-W41"}
```

The rest of that invocation:

```json
{"timestamp": "2026-10-13T16:55:10Z", "level": "INFO", "message": "report saved", "logger": "meetings.reports", "requestId": "7c6ace62-43d1-4e0b-97b6-48234c656dbb", "trigger": "schedule", "week": "2026-W41", "key": "reports/2026-W41.csv"}
{"time":"2026-10-13T16:55:10.284Z","type":"platform.report","record":{"requestId":"7c6ace62-43d1-4e0b-97b6-48234c656dbb","metrics":{"durationMs":835.454,"billedDurationMs":2133,"memorySizeMB":512,"maxMemoryUsedMB":143,"initDurationMs":1297.259},"status":"success"}}
```

## Trigger 2: SQS message (`make report-now`)

The schedule now sends `{"week": null, "source": "schedule"}` to the queue
`successfulsuccess-report-requests` instead of invoking the builder; an event source mapping
(batch size 1) hands each message to the builder. `make report-now WEEK=2026-W40` sent
`{"week":"2026-W40","source":"manual"}` at 2026-10-13 17:05 UTC:

```
Queued 2026-W40: MessageId 78d7dddc-bc3a-4a20-abff-d6314e84c8fa
```

The builder's first log line for that message, with the same `messageId`:

```json
{"timestamp": "2026-10-13T17:05:04Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "e9257686-887e-5da7-8457-15ceee8b3bcf", "trigger": "sqs", "week": "2026-W40", "source": "manual", "messageId": "78d7dddc-bc3a-4a20-abff-d6314e84c8fa", "receiveCount": 1}
```

## Reports in S3

`2026-W41.csv` was built by the schedule (Trigger 1 above), `2026-W40.csv` on demand with
`make report-now` (Trigger 2). Times are local (UTC+3).

```
$ aws s3 ls s3://successfulsuccess-reports-980553487282/reports/ --recursive
2026-10-13 20:05:05        645 reports/2026-W40.csv
2026-10-13 19:55:11        622 reports/2026-W41.csv
```

## Trigger 3: S3 upload (the mailer)

`make report-now WEEK=2026-W41` at 2026-10-13 17:13 UTC (`MessageId 12ac0ceb-c153-4744-b8ab-7131cd423b38`).
The builder, started by the SQS message, overwrote `reports/2026-W41.csv`:

```json
{"timestamp": "2026-10-13T17:13:43Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "2bbf8246-83ec-5232-9302-e10eeb112196", "trigger": "sqs", "week": "2026-W41", "source": "manual", "messageId": "12ac0ceb-c153-4744-b8ab-7131cd423b38", "receiveCount": 1}
```

That upload's `ObjectCreated:Put` event started `successfulsuccess-report-mailer` (outside the VPC),
which sent the CSV through SES:

```json
{"timestamp": "2026-10-13T17:13:45Z", "level": "INFO", "message": "report-mailer triggered", "logger": "meetings.mailer", "requestId": "ee06300a-f522-49b2-b121-29ba7724011c", "trigger": "s3", "bucket": "successfulsuccess-reports-980553487282", "key": "reports/2026-W41.csv", "eventName": "ObjectCreated:Put", "sequencer": "006ACE66C81B4AE099"}
{"timestamp": "2026-10-13T17:13:45Z", "level": "INFO", "message": "report emailed", "logger": "meetings.mailer", "requestId": "ee06300a-f522-49b2-b121-29ba7724011c", "trigger": "s3", "key": "reports/2026-W41.csv", "sesMessageId": "010001a1364184ad-cbc3ddad-8806-4ef4-992b-b9c8d1ad2ba6-000000"}
```

## Step 7: a failing week lands in the DLQ

`make aws-deploy-reports FAIL_WEEK=2026-W01` made the builder raise for that week, then
`make report-now WEEK=2026-W01` at 2026-10-14 08:12:59 UTC:

```
Queued 2026-W01: MessageId 84fe202c-f3fa-4572-bcea-ee6334e47ff0
```

Three attempts on the same message, each one 6 minutes (the visibility timeout) after the last:

```json
{"timestamp": "2026-10-14T08:13:04Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "4042e778-54bb-52c3-8ac2-84316f019d0d", "trigger": "sqs", "week": "2026-W01", "source": "manual", "messageId": "84fe202c-f3fa-4572-bcea-ee6334e47ff0", "receiveCount": 1}
{"timestamp": "2026-10-14T08:18:59Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "d1477b0f-7b51-5a8e-ad9e-18464678a109", "trigger": "sqs", "week": "2026-W01", "source": "manual", "messageId": "84fe202c-f3fa-4572-bcea-ee6334e47ff0", "receiveCount": 2}
{"timestamp": "2026-10-14T08:24:59Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "1c7834e1-f733-517d-b8c7-57a8c9bc4873", "trigger": "sqs", "week": "2026-W01", "source": "manual", "messageId": "84fe202c-f3fa-4572-bcea-ee6334e47ff0", "receiveCount": 3}
```

Each failed with:

```json
{"timestamp": "2026-10-14T08:24:59Z", "level": "ERROR", "errorMessage": "FAIL_WEEK test failure for 2026-W01", "errorType": "RuntimeError", "requestId": "1c7834e1-f733-517d-b8c7-57a8c9bc4873", "stackTrace": ["  File \"/var/task/app/reports/lambda_handler.py\", line 108, in handler\n    raise RuntimeError(f\"FAIL_WEEK test failure for {week}\")\n"]}
```

After the third failure the message did not come back to the builder; SQS moved it to the DLQ
(`make dlq-status`):

```
08:24:16Z successfulsuccess-report-requests        waiting=0 in-flight=1   successfulsuccess-report-requests-dlq  waiting=0 in-flight=0
08:31:35Z successfulsuccess-report-requests        waiting=0 in-flight=0   successfulsuccess-report-requests-dlq  waiting=1 in-flight=0
```

Then `make aws-deploy-reports` without `FAIL_WEEK`; the live builder configuration has `FAIL_WEEK` empty.

### Redrive from the DLQ

Started at 2026-10-14 08:49:29 UTC with the CLI, because the console was not available:

```
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:us-east-1:980553487282:successfulsuccess-report-requests-dlq \
  --destination-arn arn:aws:sqs:us-east-1:980553487282:successfulsuccess-report-requests
```

`start-message-move-task` is the same operation as **Start DLQ redrive** ("Redrive to source queue")
in the SQS console. `aws sqs list-message-move-tasks` reported `COMPLETED`, 1 of 1 messages moved.
A moved message gets a new message id and its receive count starts again; the body is unchanged.
This time the builder (no `FAIL_WEEK`) built the report, and the mailer sent it:

```json
{"timestamp": "2026-10-14T08:49:30Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "ed6f4c96-dc98-5ae0-b233-2fdf98de3bfa", "trigger": "sqs", "week": "2026-W01", "source": "manual", "messageId": "a5bcc0c2-06b8-474a-b3ea-db31c4ce9b4b", "receiveCount": 1}
{"timestamp": "2026-10-14T08:49:31Z", "level": "INFO", "message": "report saved", "logger": "meetings.reports", "requestId": "ed6f4c96-dc98-5ae0-b233-2fdf98de3bfa", "trigger": "sqs", "week": "2026-W01", "key": "reports/2026-W01.csv"}
{"timestamp": "2026-10-14T08:49:32Z", "level": "INFO", "message": "report-mailer triggered", "logger": "meetings.mailer", "requestId": "ea633f63-0cd7-42ff-ae28-a00554bacd0d", "trigger": "s3", "bucket": "successfulsuccess-reports-980553487282", "key": "reports/2026-W01.csv", "eventName": "ObjectCreated:Put", "sequencer": "006ACF421B09F61DCE"}
{"timestamp": "2026-10-14T08:49:32Z", "level": "INFO", "message": "report emailed", "logger": "meetings.mailer", "requestId": "ea633f63-0cd7-42ff-ae28-a00554bacd0d", "trigger": "s3", "key": "reports/2026-W01.csv", "sesMessageId": "010001a1399a408b-42da5456-de00-4c07-b8bc-c125ec073bb1-000000"}
```

Afterwards both queues are empty (`make dlq-status`: `waiting=0 in-flight=0` for each), and
`reports/2026-W01.csv` is in the bucket.

## Step 7: the same week twice

`make report-now WEEK=2026-W40` twice, about 10 seconds apart (2026-10-14 08:50:33 and 08:50:50 UTC):

```
Queued 2026-W40: MessageId a8580d0b-0ed9-4f43-b0a4-ffc72188f397
Queued 2026-W40: MessageId f1b3dad9-278f-468f-829b-5933b2430c69
```

Builder: two runs, both writing the same key.

```json
{"timestamp": "2026-10-14T08:50:42Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "46ba454c-1436-5553-ab33-260550a2b524", "trigger": "sqs", "week": "2026-W40", "source": "manual", "messageId": "a8580d0b-0ed9-4f43-b0a4-ffc72188f397", "receiveCount": 1}
{"timestamp": "2026-10-14T08:50:42Z", "level": "INFO", "message": "report saved", "logger": "meetings.reports", "requestId": "46ba454c-1436-5553-ab33-260550a2b524", "trigger": "sqs", "week": "2026-W40", "key": "reports/2026-W40.csv"}
{"timestamp": "2026-10-14T08:51:01Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "1f97fc31-58a6-5564-9857-9f781c031f81", "trigger": "sqs", "week": "2026-W40", "source": "manual", "messageId": "f1b3dad9-278f-468f-829b-5933b2430c69", "receiveCount": 1}
{"timestamp": "2026-10-14T08:51:01Z", "level": "INFO", "message": "report saved", "logger": "meetings.reports", "requestId": "1f97fc31-58a6-5564-9857-9f781c031f81", "trigger": "sqs", "week": "2026-W40", "key": "reports/2026-W40.csv"}
```

Mailer: two `ObjectCreated:Put` events with different sequencers, two SES sends.

```json
{"timestamp": "2026-10-14T08:50:43Z", "level": "INFO", "message": "report-mailer triggered", "logger": "meetings.mailer", "requestId": "1cf9c7e0-1492-4f87-85a2-7630252506b8", "trigger": "s3", "bucket": "successfulsuccess-reports-980553487282", "key": "reports/2026-W40.csv", "eventName": "ObjectCreated:Put", "sequencer": "006ACF4262AE3B6EC6"}
{"timestamp": "2026-10-14T08:50:43Z", "level": "INFO", "message": "report emailed", "logger": "meetings.mailer", "requestId": "1cf9c7e0-1492-4f87-85a2-7630252506b8", "trigger": "s3", "key": "reports/2026-W40.csv", "sesMessageId": "010001a1399b55be-ffb10cf0-e752-4485-ba27-d7626d0e24fc-000000"}
{"timestamp": "2026-10-14T08:51:02Z", "level": "INFO", "message": "report-mailer triggered", "logger": "meetings.mailer", "requestId": "7ae5974f-55e5-4034-9354-047882dd185c", "trigger": "s3", "bucket": "successfulsuccess-reports-980553487282", "key": "reports/2026-W40.csv", "eventName": "ObjectCreated:Put", "sequencer": "006ACF427577A20D8C"}
{"timestamp": "2026-10-14T08:51:02Z", "level": "INFO", "message": "report emailed", "logger": "meetings.mailer", "requestId": "7ae5974f-55e5-4034-9354-047882dd185c", "trigger": "s3", "key": "reports/2026-W40.csv", "sesMessageId": "010001a1399b9ef6-4514efc9-238c-403a-848b-08aa9109cf5c-000000"}
```

In S3 there is still one object, overwritten by the second run:

```
$ aws s3 ls s3://successfulsuccess-reports-980553487282/reports/2026-W40.csv
2026-10-14 11:51:02        645 2026-W40.csv
```

**Result: two emails** (two SES message ids above). Why: writing `reports/2026-W40.csv` is
idempotent — the same week always gives the same key and the same content, so the second run just
overwrites one object instead of creating a second file. But every `PutObject` is a new upload, and
S3 sends a new `ObjectCreated` event for each one (note the different `sequencer`). The mailer reacts
to every event, and sending an email is not idempotent: each send is a new email. So the builder step
is safe to repeat, the mailer step is not. Answer (a) in `lab5-answers.md` is how to fix that.

## Final S3 listing (for submission)

So that the bucket shows a report built by the schedule again, the schedule was deployed with
`make aws-deploy-reports SCHEDULE="rate(5 minutes)"` (2026-10-14 09:01:16 UTC) and, right after its
first run, set back to `cron(0 7 ? * MON *)` in Europe/Kyiv (09:03:29 UTC), so it fired exactly once.
It sent `{"week": null, "source": "schedule"}` to SQS; the builder resolved `week: null` to the
previous ISO week, 2026-W41:

```json
{"timestamp": "2026-10-14T09:01:58Z", "level": "INFO", "message": "report-builder triggered", "logger": "meetings.reports", "requestId": "3a19095a-a8ad-5a78-950c-6a13ef9fa25f", "trigger": "sqs", "week": "2026-W41", "source": "schedule", "messageId": "4a46098c-5ee2-47c6-9b2d-3ee7c9a19821", "receiveCount": 1}
```

The upload started the mailer, which emailed it:

```json
{"timestamp": "2026-10-14T09:02:00Z", "level": "INFO", "message": "report-mailer triggered", "logger": "meetings.mailer", "requestId": "871a8e14-b0b9-4876-ad8a-65956da7ce71", "trigger": "s3", "bucket": "successfulsuccess-reports-980553487282", "key": "reports/2026-W41.csv", "eventName": "ObjectCreated:Put", "sequencer": "006ACF4506E216F8A1"}
```

The bucket after that (times are local, UTC+3):

```
$ aws s3 ls s3://successfulsuccess-reports-980553487282/reports/ --recursive
2026-10-14 11:49:32        313 reports/2026-W01.csv
2026-10-14 11:51:02        645 reports/2026-W40.csv
2026-10-14 12:01:59        622 reports/2026-W41.csv
```

- `2026-W41.csv` — last written by the **schedule** (EventBridge Scheduler → SQS → builder), above.
- `2026-W40.csv` — last written by **`make report-now WEEK=2026-W40`** (Step 7, "the same week twice").
- `2026-W01.csv` — written by the **DLQ redrive** of the failed 2026-W01 request (Step 7).

## Submission checklist ("What you submit" in lab5.md)

1. **Commit link** — all Lab 5 work, compared with the last Lab 4 commit:
   https://github.com/anastasiiakvasovets/SuccessfulSuccess/compare/ff97abe...main
   Report code: `backend/app/reports/` (`weekly.py`, `lambda_handler.py` = the builder);
   template: `infra/reports.yml` (the mailer handler is inline in it).
2. **Email screenshot** — by hand: the "Weekly meetings report 2026-W41" email (and later ones) in the
   inbox or Spam, with `2026-W41.csv` attached.
3. **`aws s3 ls`** — see "Final S3 listing (for submission)" above: `2026-W41.csv` last written by
   the schedule (via SQS), `2026-W40.csv` by `make report-now`, `2026-W01.csv` by the DLQ redrive.
4. **Three log lines** — Trigger 1 (`trigger: schedule`), Trigger 2 (`trigger: sqs`) and
   Trigger 3 (`trigger: s3`, the mailer) above.
5. **Written answers** — `docs/lab5-answers.md`.

State after Step 7: schedule `cron(0 7 ? * MON *)` in Europe/Kyiv, targeting the SQS queue;
`FAIL_WEEK` empty; both queues empty.
