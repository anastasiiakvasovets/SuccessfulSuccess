# Lab 5 — answers (Part 3, Step 7)

## a) The same ObjectCreated event twice, two identical emails

S3 notifications are "at least once", so the mailer can get the same event twice. To stop the second
email, the mailer has to remember what it already sent, somewhere outside itself. I would use a small
DynamoDB table. RDS is not a good place: the mailer runs outside the VPC on purpose, and RDS is only
reachable inside it. DynamoDB is reachable from the mailer over the internet, costs almost nothing at
this volume, and has conditional writes.

The mailer does a `PutItem` with `ConditionExpression="attribute_not_exists(pk)"` *before* it sends.
If the write succeeds, this is the first time, so it sends. If it fails with
`ConditionalCheckFailedException`, someone already claimed this event, so it logs "already sent" and
stops. The condition is what makes it safe: if two copies of the event run at the same moment, a plain
"read, then write" would let both see "not sent yet" and both send. With the conditional write, DynamoDB
decides atomically and only one of them wins. (If sending fails after the claim, the mailer should
delete the item, or store a status like "sending" with a TTL, so a retry can still send.)

The key decides what "duplicate" means:

- **`bucket/key#sequencer`** (or `bucket/key#versionId` if versioning is on) means "this exact upload
  was already mailed". A duplicate delivery of the same event has the same sequencer, so it is stopped.
  But if I really rebuild the report (`make report-now` again), that is a new upload with a new
  sequencer, and it is mailed again.
- **`week`** (for example `2026-W40`) means "one email per week, ever". A rebuild after fixing a bug
  would never be sent.

I would pick `bucket/key#sequencer`. It fixes exactly the bug in the question (duplicate events) and
keeps the useful behaviour (a deliberate rebuild is a new report, so people get it). If we wanted "never
more than one email per week" as a product rule, that is a different decision and I would make it
explicit, not hide it in the dedup key. Add a TTL of a few weeks to the items so the table cleans itself.

## b) The builder in the VPC cannot reach SES

The builder runs in the VPC with no NAT, so it cannot call SES. Three ways to fix that (prices for
us-east-1, a month is ~730 hours):

| Option | Fixed cost / month | Per GB | Notes |
| --- | --- | --- | --- |
| NAT gateway | $0.045/h ≈ **$32.85** per NAT (one per AZ for high availability: 2 AZs ≈ $65.70) | $0.045 processed (+ normal data transfer out) | Gives the whole VPC internet access, not just SES |
| SES interface VPC endpoint (`com.amazonaws.us-east-1.email`) | $0.01/h per AZ ≈ **$7.30** per AZ. Our subnets are in 6 AZs: ≈ $43.80; limited to 2 AZs ≈ $14.60 | $0.01 processed | Only SES, traffic stays private |
| The split we built | **≈ $0** | — | S3 gateway endpoint is free; Lambda, S3 and SQS requests at a few per week are fractions of a cent |

The NAT gateway is more work than it looks in our VPC. Our Lambda subnets are the default VPC's public
subnets (their route table sends 0.0.0.0/0 to the internet gateway), and a Lambda in a VPC never gets a
public IP, so that route does nothing for it. A NAT gateway would also need new private subnets with a
route 0.0.0.0/0 → NAT, and the builder moved into them.

About the endpoint name: `aws ec2 describe-vpc-endpoint-services` in us-east-1 lists
`com.amazonaws.us-east-1.email` (the SES API, in all 6 AZs), `email-fips` and `email-smtp` (only 3
AZs). Our code calls the SES API with boto3 (`sesv2.send_email`), so `email` is the one we need.
`email-smtp` would mean sending through SMTP instead of the API.

With 10 more emails a week I would keep the split. It costs nothing, the parts are small, and the event
between them (a file in S3) is useful on its own: I can add a Slack notifier without touching the
builder. Paying $15–65 a month to send 10 emails makes no sense.

With a million emails a week the network is not the money question any more. SES itself costs
$0.10 per 1,000 emails, so about **$100 a week (~$430 a month)**, plus $0.12 per GB of attachments.
A small CSV per email is a few GB a week, which is cents through either a NAT or an endpoint. So I
would choose by design, not cost. I would still keep the split, but the mailer would need to change:
not one email per S3 event, but a fan-out (one report event → a queue of recipients → many mailer
invocations with batching, SES production access, a higher sending quota, and bounce/complaint
handling). The builder should not send a million emails itself either way.

## c) A link that works for a week

A presigned URL is signed with the credentials of whoever creates it. Inside Lambda those are the role's
temporary credentials, and the URL stops working when that session expires (often after a few hours),
even if I asked for 7 days. Ways to get a link that really lasts a week:

1. **Sign with long-term credentials** of a dedicated IAM user that can only `s3:GetObject` on
   `reports/*`. SigV4 presigned URLs can live up to 7 days. Store the access key in Secrets Manager or
   SSM Parameter Store, never in code, and rotate it. Simple, but it is a long-lived secret, and anyone
   with the link can download the file until it expires.
2. **CloudFront signed URLs** with a key pair (private key in Secrets Manager, public key in a CloudFront
   key group). The expiry can be any length, the bucket stays private behind origin access control, and
   we already use CloudFront for the frontend.
3. **Link to an app endpoint** like `/reports/2026-W40`, which checks that the user is signed in and then
   redirects to a fresh presigned URL valid for a few minutes. The link in the email never expires, and
   only allowed users can open it. The email link should go to a frontend page on the CloudFront URL,
   because the API expects the Cognito token that the frontend sends; that page calls the API, which
   returns (or redirects to) the short-lived presigned URL.

I would pick option 3. The link in the email is just a normal URL, access is checked on every click, and
there is no long-lived secret that can leak. It also fits our API in the VPC with no NAT: presigning is
only a local signature with the API role's credentials, no network call, and the URL only has to live a
few minutes, so temporary credentials are fine. The browser then downloads from S3 directly.

## d) Notes about my setup

- My database is **RDS PostgreSQL `db.t3.micro`, not Aurora Serverless**. I switched in commit
  `c0307bd` ("Switch to RDS PostgreSQL"). So "the builder wakes Aurora up" does not apply to me: RDS
  never pauses, it bills every hour whether the report runs or not, and there is no ~15 s resume delay.
- I have **no custom domain**. The frontend runs on the default CloudFront URL, so SES sends from a
  verified **email identity** (my own address) instead of `reports@<domain>`, and there are no DKIM DNS
  records. Because of that, Gmail cannot check DKIM/DMARC for the sender, and the report may land in Spam.

## e) The same week sent twice

I ran `make report-now WEEK=2026-W40` twice, about 10 seconds apart, and got **two emails**: the mailer
log has two "report emailed" lines with two different SES message ids
(`010001a1399b55be-…` and `010001a1399b9ef6-…`, see `lab5-evidence.md`).

Why: writing `reports/2026-W40.csv` is idempotent. The same week always gives the same key and the same
content, so the second run just overwrites the one object, and there is still only one file. But every
`PutObject` is a new upload, and S3 sends a new `ObjectCreated` event for each one, with a new
`sequencer`. The mailer reacts to every event, and sending an email is not idempotent: each send is a new
email. So the builder step is safe to repeat, the mailer step is not. The fix is in (a).
