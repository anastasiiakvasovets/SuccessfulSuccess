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
