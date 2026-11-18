# Cost comparison: Spry's core on AWS and on Google Cloud

- **Lab:** 9 (decision: [ADR 0008](adr/0008-gcp-core.md), findings: [lab9-notes.md](lab9-notes.md))
- **Scope:** the core only: frontend, API, database. Sign-in (Cognito), the weekly report and
  the agenda parser stay on AWS in both cases and are not counted.
- **Units:** USD per month, without tax, **730 hours a month**. AWS in `us-east-1`, GCP in
  `us-central1`.
- **Computed by** [cost-comparison.py](cost-comparison.py) (standard library only):
  `python docs/cost-comparison.py` prints every table below.
- **Calculator estimates:** [Google Cloud](#5-pricing-calculator-estimates) ($9.37 a month for
  Cloud SQL) and [AWS](#5-pricing-calculator-estimates) (≈ $15.4 a month for RDS), see section 5.

## Inputs

**What runs today (AWS).** It is **RDS PostgreSQL 16 `db.t3.micro`, not Aurora**: it never
pauses and bills every hour.

| Part | Configuration (from the repo) | Price used |
| --- | --- | --- |
| Frontend | S3 + CloudFront, flat-rate **Free plan** (`infra/frontend.yml`) | $0: 1M requests and 100 GB a month, no overage |
| API | Lambda, image, x86_64, 512 MB (`infra/backend.yml`) | Free tier: 1M requests + 400,000 GB-s a month; then **$0.20 per 1M requests** |
| DB compute | RDS `db.t3.micro`, Single-AZ, on-demand, private | **$0.018 / h** × 730 h = $13.14 |
| DB storage | `AllocatedStorage: "20"` GB; no `StorageType`, so the RDS default (gp2); backups 1 day | **$0.115 / GB-month** × 20 GB = $2.30 |
| Registry | ECR, lifecycle keeps 15 images | Free tier 500 MB (see assumptions) |

The AWS prices come from the AWS Pricing Calculator (us-east-1, RDS for PostgreSQL
`db.t3.micro`, Single-AZ, OnDemand, 100% utilization, 20 GB gp2, no RDS Proxy, Database Insights
or Extended Support): ≈ **$15.4 a month**.

**What runs on GCP (Lab 9).**

| Part | Configuration (from `gcp/`) | Price |
| --- | --- | --- |
| Frontend | Firebase Hosting, free plan | $0 |
| API | Cloud Run, 1 vCPU / 512 MiB, min 0, max 2, `cpu_idle = true` (request-based billing) | Free: 2M requests, 180,000 vCPU-s, 360,000 GiB-s a month; then $0.40 / 1M requests, $0.000024 / vCPU-s, $0.0000025 / GiB-s |
| DB compute | Cloud SQL `db-f1-micro`, `activation_policy` ALWAYS / NEVER | $0.0105 / h while running |
| DB storage | 10 GB SSD, no autoresize, backups off | $0.17 / GB-month, **billed while stopped too** |
| Secrets | Secret Manager, two secrets (`spry-database-url`, `spry-db-password`), one version each | Free: 6 versions, 10,000 accesses |
| Registry | Artifact Registry `spry` | Free: 0.5 GB |
| Alternative DB | Firestore | Free per **day**: 50k reads, 20k writes, 20k deletes; 1 GiB stored |

## 1. Spry's core, nobody using it

| Line | AWS (RDS db.t3.micro) | GCP Cloud SQL running | GCP Cloud SQL stopped | GCP with Firestore |
| --- | --- | --- | --- | --- |
| Frontend + CDN + HTTPS | $0 (CloudFront Free plan, S3) | $0 (Firebase Hosting) | $0 | $0 |
| API | $0 (Lambda, no requests) | $0 (Cloud Run, min 0) | $0 | $0 |
| DB compute | $13.14 | $7.67 | $0.00 | $0 (Firestore) |
| DB storage | $2.30 | $1.70 | $1.70 | $0 (< 1 GiB) |
| Registry / secrets / logs | $0 (in free tiers) | $0 | $0 | $0 |
| **Total** | **$15.44** | **$9.37** | **$1.70** | **$0** |
| *AWS with Aurora Serverless v2 (Lab 4 reference)* | *≈ $0.30* (paused: storage only) | | | |

Formulas:

- AWS: `0.018 × 730 = $13.14` compute + `0.115 × 20 = $2.30` storage = **$15.44**. Lambda,
  CloudFront and S3 cost nothing without requests.
- Cloud SQL running: `0.0105 × 730 = $7.665` compute + `0.17 × 10 = $1.70` storage = **$9.37**.
- Cloud SQL stopped: `0 h × 0.0105` + `$1.70` storage = **$1.70**.
- Firestore: an empty project stores far less than 1 GiB and reads nothing: **$0**.

The Aurora row is the Lab 4 design (a cluster that paused after 5 idle minutes). Spry no longer
runs it: since commit `c0307bd` the database is the RDS instance in the first column, which costs
about 50 times as much when nobody uses it.

## 2. The four Lab 4 profiles

### Usage model

The profiles give the hours of use. The request volume is an assumption, the same for both
clouds, and every number is a constant in the script:

| Profile | Hours in use | Requests while in use | Sessions (Cloud SQL start/stop) |
| --- | --- | --- | --- |
| Nobody | 0 | — | 0 |
| Class demos | 10 × 2 h = 20 h | 1,000 / h (a class of ~20 clicking through) | 10 |
| Office hours | 8 h × 22 days = 176 h | 1,000 / h | 22 |
| Busy 24/7 | 730 h | 3,600 / h (1 request per second on average) | always on |

- `requests = hours × requests_per_hour`
- Billable time **0.2 s per request**: Cloud Run rounds up to 100 ms, a request makes several DB
  round trips, and cold starts are spread over it. Overlap between concurrent requests is
  ignored, so the vCPU-seconds are an upper bound.
- Cloud Run: `vCPU-s = requests × 0.2 × 1 vCPU`, `GiB-s = requests × 0.2 × 0.5 GiB`.
- Lambda: `GB-s = requests × 0.2 × 0.5 GB`.
- Cloud Run cost = `max(0, req − 2M) × $0.40/1M + max(0, vCPU-s − 180,000) × $0.000024 +
  max(0, GiB-s − 360,000) × $0.0000025`.
- Cloud SQL on demand runs `hours + 0.5 h × sessions` (started before, stopped after each
  session): `0.0105 × hours_running + $1.70`. Always-on profiles run 730 h.
- AWS: `0.018 × 730 + 0.115 × 20 + max(0, req − 1M)/1M × $0.20` (Lambda's GB-seconds stay under
  the 400,000 free in every profile). The frontend is $0 on both clouds in every profile (the
  CloudFront Free plan and Firebase Hosting's free plan cover these volumes).

### Usage and free tiers

| Profile | Hours in use | Requests | Cloud Run vCPU-s | Cloud Run GiB-s | Cloud Run in free tier? | Lambda GB-s | Lambda in free tier? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Nobody | 0 | 0 | 0 | 0 | yes | 0 | yes |
| Class demos (10 × 2 h) | 20 | 20,000 | 4,000 | 2,000 | yes | 2,000 | yes |
| Office hours (8 h × 22 days) | 176 | 176,000 | 35,200 | 17,600 | yes | 17,600 | yes |
| Busy 24/7 | 730 | 2,628,000 | 525,600 | 262,800 | no: $8.55 | 262,800 | no: +1,628,000 req |

Cloud Run beyond the free tier:

| Profile | Requests over 2M | vCPU-s over 180k | GiB-s over 360k | Cloud Run total |
| --- | --- | --- | --- | --- |
| Nobody | $0.00 | $0.00 | $0.00 | $0.00 |
| Class demos (10 × 2 h) | $0.00 | $0.00 | $0.00 | $0.00 |
| Office hours (8 h × 22 days) | $0.00 | $0.00 | $0.00 | $0.00 |
| Busy 24/7 | $0.25 | $8.29 | $0.00 | $8.55 |

Busy 24/7: `(2,628,000 − 2,000,000) × 0.40/1M = $0.25`;
`(525,600 − 180,000) × 0.000024 = $8.29`; 262,800 GiB-s is under 360,000, so memory is free.
vCPU-seconds run out first: the free tier covers about `180,000 / 0.2 = 900,000` requests a month.
Lambda in the same profile: `(2,628,000 − 1,000,000) / 1M × $0.20 = $0.33`.

### Monthly cost

| Profile | AWS: RDS 24/7 + Lambda | GCP: Cloud SQL 24/7 + Cloud Run | GCP: Cloud SQL on demand + Cloud Run (hours running) | Cheaper (vs GCP on demand) | Break-even RDS price (actual $0.018/h) |
| --- | --- | --- | --- | --- | --- |
| Nobody | $15.44 | $9.37 | $1.70 (0 h) | GCP by $13.74 | none: AWS storage + Lambda alone cost more |
| Class demos (10 × 2 h) | $15.44 | $9.37 | $1.96 (25 h) | GCP by $13.48 | none: AWS storage + Lambda alone cost more |
| Office hours (8 h × 22 days) | $15.44 | $9.37 | $3.66 (187 h) | GCP by $11.78 | $0.00187/h |
| Busy 24/7 | $15.77 | $17.91 | $17.91 (730 h) | AWS by $2.15 | $0.02094/h |

- Class demos on demand: `0.0105 × (20 + 0.5 × 10) = $0.26` + `$1.70` = **$1.96**.
- Office hours on demand: `0.0105 × (176 + 0.5 × 22) = $1.96` + `$1.70` = **$3.66**.
- Busy 24/7: Cloud SQL cannot be stopped, so on demand = 24/7:
  `$7.67 + $1.70 + $8.55` = **$17.91**. AWS: `$13.14 + $2.30 + $0.33` = **$15.77**.
- Break-even (last column): the RDS hourly price at which AWS would cost the same as on-demand
  GCP, `(GCP total − $2.30 − Lambda overage) / 730`. For nobody and class demos the RDS storage
  ($2.30) alone already costs more than the whole GCP bill. For office hours RDS would have to cost
  $0.00187/h instead of $0.018/h. For busy 24/7 RDS at $0.018/h is under the $0.02094/h
  break-even, so AWS is cheaper.
- RDS 24/7 is the only AWS option here: the instance does not pause, and an RDS instance stopped
  by hand is started again by AWS after 7 days.

### Firestore instead of Cloud SQL

Firestore's free quota is per day, not per month. A meetings page reads about 20 documents (the
list, the participants, the user), 10% of requests write about 3 documents:

| Profile | Requests / active day | Reads / day | Writes / day | Within 50k reads, 20k writes a day? |
| --- | --- | --- | --- | --- |
| Nobody | 0 | 0 | 0 | yes |
| Class demos (10 × 2 h) | 2,000 | 40,000 | 600 | yes |
| Office hours (8 h × 22 days) | 8,000 | 160,000 | 2,400 | no: +110,000 reads/day |
| Busy 24/7 | 86,400 | 1,728,000 | 25,920 | no: +1,678,000 reads/day, +5,920 writes/day |

The price beyond the quota was not part of the lab's inputs and is not costed here. Firestore is
also a rewrite of the data layer (ADR 0008, option C), so it is shown for comparison only.

## 3. Free-tier assumptions

**Google Cloud**

- The Cloud Run free tier (2M requests, 180,000 vCPU-s, 360,000 GiB-s a month) is per billing
  account and applies in `us-central1`. Nothing else in the billing account uses it.
- Cloud Run is billed per request (`cpu_idle = true`, min instances 0): an idle service costs
  nothing. Concurrent requests overlap in reality, so the vCPU-seconds above are an upper bound.
- The Google Cloud Pricing Calculator shows **$0.05** for Cloud Run, because it does not subtract
  the free tier. With the free tier that is **$0** for the first three profiles.
- 0.2 s of billable time per request, including cold starts. The real figure is in Cloud
  Monitoring (`billable_instance_time`) once there is traffic.
- Firebase Hosting's free plan covers the site: a static export of a few MB and the transfer of
  these profiles. Rewritten `/api/**` requests are counted as Cloud Run requests.
- Secret Manager: two secrets with one version each (6 are free); the API reads
  `spry-database-url` when an instance starts, so accesses are a few hundred a month, under 10,000.
- Artifact Registry: counted as $0 within 0.5 GB. The local `spry-api` image is 735 MB
  uncompressed; the registry stores it compressed, but the repository has no cleanup policy, so a
  few pushes go over 0.5 GB and start a small storage charge (not costed here).
- Cloud Logging: the API's stdout stays within the free logging allotment.
- Cloud SQL has **no free tier**. Backups are off (`gcp/database.tf`), so no backup storage. The
  instance has a public IPv4 address (`ipv4_enabled = true`, reached through the Cloud SQL socket);
  the calculator's $9.37 includes no separate charge for it.
- Cloud SQL on demand adds 0.5 h per session for starting and stopping. Storage ($1.70) is billed
  every hour of the month, stopped or not.
- Firestore quotas are daily (50k reads, 20k writes, 20k deletes, 1 GiB stored); usage is spread
  evenly over the active days.
- Network egress from Google Cloud is not counted: these volumes are small.

**AWS**

- Lambda's free tier (1M requests and 400,000 GB-s a month) is the always-free one; beyond it,
  $0.20 per 1M requests. No profile goes over 400,000 GB-s. CloudFront is on the flat-rate Free
  plan ($0, 1M requests and 100 GB a month, no overage).
- Accounts opened after July 2025 get credits instead of the classic 12-month free tier (README);
  the S3 free tier may not apply, but the site's few MB in S3 cost under a cent either way.
- RDS storage is gp2, the RDS default: `infra/backend.yml` sets no `StorageType`. Backup storage
  up to the allocated 20 GB is free with a 1-day retention.
- The RDS estimate has no RDS Proxy, Database Insights or Extended Support (PostgreSQL 16 is in
  standard support).
- ECR is counted as $0, which assumes the images fit in 500 MB. The lifecycle policy keeps 15
  images, so this may not hold: the extra storage is not costed here.
- RDS is private and single-AZ: no public IPv4 charge, no Multi-AZ, no NAT gateway. The S3
  gateway endpoint (weekly report) is free.
- CloudWatch Logs for the API stays inside its free allotment.

**Both**

- 730 h a month, USD, without tax; the same request volume on both clouds.
- Cognito, the weekly report, the agenda parser and the model calls are outside the core, stay on
  AWS and are not counted.

## 4. Answers

### (a) Which cloud is cheaper, and which line decides it

| Profile | AWS (RDS 24/7) | GCP (Cloud SQL on demand) | Cheaper |
| --- | --- | --- | --- |
| Nobody | $15.44 | $1.70 | **GCP**, by $13.74 |
| Class demos (10 × 2 h) | $15.44 | $1.96 | **GCP**, by $13.48 |
| Office hours (176 h) | $15.44 | $3.66 | **GCP**, by $11.78 |
| Busy 24/7 | $15.77 | $17.91 | **AWS**, by $2.15 |

**For the first three profiles the deciding line is DB compute.** Every other line is $0 on both
clouds. AWS pays $13.14 because the RDS instance never stops. GCP pays $0–1.96 because we stop
Cloud SQL between sessions. Even a Cloud SQL instance left running 24/7 ($9.37) is $6.07 cheaper
than RDS, because `db-f1-micro` costs $0.0105/h against RDS's $0.018/h and its 10 GB SSD costs less
than RDS's 20 GB gp2.

**At 24/7 the deciding line is the API.** Both databases run all month (GCP $9.37, AWS $15.44, so
GCP is still $6.07 ahead on the database). But Cloud Run's vCPU-seconds go over the free tier and
cost $8.29, while Lambda stays inside its 400,000 free GB-seconds and pays only $0.33 for requests
over 1M. That turns the result: AWS is $2.15 cheaper. Cloud Run's figure is an upper bound (it
ignores concurrent requests sharing an instance), so the real gap is smaller or reversed.

Both estimates are in the calculators: Cloud SQL `db-f1-micro` + 10 GB SSD is **$9.37 a month**
in the [Google Cloud Pricing Calculator](https://cloud.google.com/products/calculator?dl=CjhDaVEyTnpRNU1XRXhZUzA1WkRRM0xUUXpPR1V0T0ROaFpDMHpaR1ptTnpFNE5XUmtNRFlRQVE9PRAcGiRENTExRDUxMy01OTY4LTQ0ODktQjVENy1BRkRGN0ExRTc4RkU),
and RDS `db.t3.micro` + 20 GB gp2 is **≈ $15.4 a month** in the
[AWS Pricing Calculator](https://calculator.aws/#/estimate?id=e85905cb9adfb80e72c0d9e50b08a9508cab2943),
with Lambda at $0 in the free tier.

### (b) The GCP trap like "Aurora that something keeps awake"

In Lab 4 the risk was Aurora Serverless v2 never reaching its pause because something kept
connecting. On GCP the same kind of bill comes from:

1. **Cloud SQL never pauses.** There is no auto-pause at all: a running `db-f1-micro` bills
   $7.67 a month whether anyone queries it or not. Only `activation_policy = NEVER` stops it.
2. **A forgotten running database.** Option B (ADR 0008) relies on stopping it by hand or by a
   schedule. Leave `db_activation_policy = "ALWAYS"` after a demo and the month costs $9.37 instead
   of $1.70–3.66.
3. **Storage is billed while stopped.** Stopped is not free: $1.70 a month for the 10 GB SSD
   until the instance is deleted.
4. **Cloud Run with min instances > 0 or instance-based billing** (`cpu_idle = false`). Either
   one bills instances while they sit idle, 24/7, not only while they handle requests (a min
   instance with request-based billing is charged at a lower idle rate, but it is never $0).
   With instance-based billing the free tier's 180,000 vCPU-s last about 50 hours of one vCPU,
   and a month of it is `730 × 3,600 = 2,628,000` vCPU-s ≈ $58.75 after the free tier, plus
   memory.
5. **A Firestore page that reads hundreds of documents.** Reads are billed per document. A page
   that lists 300 meetings with their participants reads hundreds of documents per view, so
   about 170 page views a day use up the 50k free reads; a polling page does it faster.

**The same trap already exists on AWS.** The RDS `db.t3.micro` that replaced Aurora never pauses
either, so today's AWS core bills **$15.44 every month** even with nobody using it: the "kept
awake" case, permanently, and about 50 times the $0.30 of the paused Aurora in Lab 4. The
`monthly-5usd` AWS budget only catches it after the fact, and it covers AWS only: GCP needs its
own budget alert.

## 5. Pricing calculator estimates

- **Google Cloud Pricing Calculator:**
  <https://cloud.google.com/products/calculator?dl=CjhDaVEyTnpRNU1XRXhZUzA1WkRRM0xUUXpPR1V0T0ROaFpDMHpaR1ptTnpFNE5XUmtNRFlRQVE9PRAcGiRENTExRDUxMy01OTY4LTQ0ODktQjVENy1BRkRGN0ExRTc4RkU>
  - Cloud SQL for PostgreSQL `db-f1-micro`, 10 GB SSD, us-central1: **$9.37 a month**.
  - Cloud Run is shown as **$0.05**: the calculator does not subtract the free tier. With the free
    tier it is **$0** (section 2).
- **AWS Pricing Calculator:**
  <https://calculator.aws/#/estimate?id=e85905cb9adfb80e72c0d9e50b08a9508cab2943>
  - RDS for PostgreSQL `db.t3.micro`, Single-AZ, OnDemand, 100% utilization, 20 GB gp2,
    us-east-1: **≈ $15.4 a month** ($0.018/h, $0.115/GB-month).
  - Lambda: **$0** within the free tier.
