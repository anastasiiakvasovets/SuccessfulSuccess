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
