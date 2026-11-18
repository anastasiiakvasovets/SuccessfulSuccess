"""Lab 9 cost comparison: Spry's core on AWS (us-east-1) vs GCP (us-central1).

Prints the markdown tables used in docs/cost-comparison.md. Standard library only:

    python docs/cost-comparison.py

All prices are USD per month without tax, 730 hours a month. AWS prices that are not in the
repo are None: they print as symbols (P_rds_h, ...) until filled in from the AWS Pricing
Calculator. Fill them in below and run the script again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HOURS = 730  # hours in a billing month

# --- AWS prices to fill in from the AWS Pricing Calculator (us-east-1) ---------------------
# Source: AWS Pricing Calculator estimate
# https://calculator.aws/#/estimate?id=e85905cb9adfb80e72c0d9e50b08a9508cab2943
P_RDS_H = 0.018  # RDS PostgreSQL db.t3.micro, single-AZ, on-demand, $ per hour
P_RDS_GB = 0.115  # RDS gp2 storage (the default: backend.yml sets no StorageType), $ per GB-month
P_LAMBDA_REQ_M = 0.20  # Lambda, $ per 1M requests beyond the free tier
P_LAMBDA_GBS = None  # Lambda x86_64, $ per GB-second beyond the free tier (no profile reaches it)

# --- AWS facts from the repo --------------------------------------------------------------
RDS_GB = 20  # infra/backend.yml: AllocatedStorage "20"
LAMBDA_GB = 0.5  # infra/backend.yml: MemorySize 512
LAMBDA_FREE_REQ = 1_000_000  # README "Cost": always free
LAMBDA_FREE_GBS = 400_000
AURORA_LAB4_REFERENCE = 0.30  # Lab 4: Aurora Serverless v2 that pauses, idle month

# --- GCP prices (given for the lab, us-central1) ------------------------------------------
CR_FREE_REQ = 2_000_000  # Cloud Run free tier per month
CR_FREE_VCPU_S = 180_000
CR_FREE_GIB_S = 360_000
CR_P_REQ = 0.40 / 1_000_000  # $ per request beyond the free tier
CR_P_VCPU_S = 0.000024
CR_P_GIB_S = 0.0000025
CR_VCPU = 1  # gcp/run.tf: cpu = "1"
CR_GIB = 0.5  # gcp/run.tf: memory = "512Mi"

SQL_P_H = 0.0105  # Cloud SQL db-f1-micro, $ per hour while running
SSD_P_GB = 0.17  # Cloud SQL SSD, $ per GB-month, billed while stopped too
SQL_GB = 10  # gcp/database.tf: disk_size = 10

FS_FREE_READS_DAY = 50_000  # Firestore free quota, per day
FS_FREE_WRITES_DAY = 20_000

# --- Usage model (assumptions; see "Free-tier assumptions" in the doc) ----------------------
SECONDS_PER_REQUEST = 0.2  # billable time per API request (rounding, DB round trips, cold starts)
START_STOP_BUFFER_H = 0.5  # Cloud SQL started this long before / stopped after each session
DOCS_READ_PER_REQUEST = 20  # Firestore: a meetings page reads the list, participants, the user
WRITE_SHARE = 0.10  # share of requests that write
DOCS_WRITTEN_PER_WRITE = 3  # meeting + participants


@dataclass
class Profile:
    name: str
    hours: float  # hours a month the app is in use
    sessions: int  # separate start/stop sessions (0 = always on)
    req_per_hour: int  # API requests per hour while in use
    days: float  # days a month with usage (Firestore quotas are daily)


PROFILES = [
    Profile("Nobody", 0, 0, 0, 0),
    Profile("Class demos (10 × 2 h)", 10 * 2, 10, 1_000, 10),
    Profile("Office hours (8 h × 22 days)", 8 * 22, 22, 1_000, 22),
    Profile("Busy 24/7", HOURS, 0, 3_600, HOURS / 24),
]


# --- Cost with symbolic AWS terms ---------------------------------------------------------
SYMBOLS = {
    "P_rds_h": P_RDS_H,
    "P_rds_gb": P_RDS_GB,
    "P_lambda_req_M": P_LAMBDA_REQ_M,
    "P_lambda_gbs": P_LAMBDA_GBS,
}


@dataclass
class Cost:
    """A dollar amount plus terms whose price is still unknown (coefficient × symbol)."""

    usd: float = 0.0
    terms: dict[str, float] = field(default_factory=dict)

    @classmethod
    def price(cls, quantity: float, symbol: str) -> Cost:
        value = SYMBOLS[symbol]
        if quantity == 0:
            return cls()
        if value is None:
            return cls(0.0, {symbol: quantity})
        return cls(quantity * value)

    def __add__(self, other: Cost) -> Cost:
        terms = dict(self.terms)
        for k, v in other.terms.items():
            terms[k] = terms.get(k, 0) + v
        return Cost(self.usd + other.usd, terms)

    def __str__(self) -> str:
        parts = [f"${self.usd:,.2f}"] if self.usd or not self.terms else []
        parts += [f"{q:,.4g} × {s}" for s, q in self.terms.items()]
        return " + ".join(parts)


def money(x: float) -> str:
    return f"${x:,.2f}"


# --- Calculations -------------------------------------------------------------------------
def requests(p: Profile) -> float:
    return p.hours * p.req_per_hour


def cloud_run(p: Profile) -> dict[str, float]:
    req = requests(p)
    vcpu_s = req * SECONDS_PER_REQUEST * CR_VCPU
    gib_s = req * SECONDS_PER_REQUEST * CR_GIB
    c_req = max(0, req - CR_FREE_REQ) * CR_P_REQ
    c_cpu = max(0, vcpu_s - CR_FREE_VCPU_S) * CR_P_VCPU_S
    c_mem = max(0, gib_s - CR_FREE_GIB_S) * CR_P_GIB_S
    return {
        "req": req, "vcpu_s": vcpu_s, "gib_s": gib_s,
        "c_req": c_req, "c_cpu": c_cpu, "c_mem": c_mem, "total": c_req + c_cpu + c_mem,
    }


def lambda_(p: Profile) -> tuple[dict[str, float], Cost]:
    req = requests(p)
    gbs = req * SECONDS_PER_REQUEST * LAMBDA_GB
    over_req = max(0, req - LAMBDA_FREE_REQ)
    over_gbs = max(0, gbs - LAMBDA_FREE_GBS)
    cost = Cost.price(over_req / 1_000_000, "P_lambda_req_M") + Cost.price(over_gbs, "P_lambda_gbs")
    return {"req": req, "gbs": gbs, "over_req": over_req, "over_gbs": over_gbs}, cost


def sql_hours_on_demand(p: Profile) -> float:
    if p.sessions == 0:
        return p.hours
    return min(HOURS, p.hours + START_STOP_BUFFER_H * p.sessions)


def sql_storage() -> float:
    return SQL_GB * SSD_P_GB


def aws_rds(p: Profile) -> Cost:
    _, lam = lambda_(p)
    return Cost.price(HOURS, "P_rds_h") + Cost.price(RDS_GB, "P_rds_gb") + lam


def gcp_sql_24_7(p: Profile) -> float:
    return SQL_P_H * HOURS + sql_storage() + cloud_run(p)["total"]


def gcp_sql_on_demand(p: Profile) -> float:
    return SQL_P_H * sql_hours_on_demand(p) + sql_storage() + cloud_run(p)["total"]


def break_even(p: Profile, gcp_total: float) -> str:
    """RDS hourly price at which AWS costs the same as the given GCP total."""
    _, lam = lambda_(p)
    known = gcp_total - lam.usd
    rest = []
    if P_RDS_GB is None:
        rest.append(f"{RDS_GB / HOURS:.4f} × P_rds_gb")
    else:
        known -= RDS_GB * P_RDS_GB
    for s, q in lam.terms.items():
        rest.append(f"{q / HOURS:,.4g} × {s}")
    if not rest and known <= 0:
        return "none: AWS storage + Lambda alone cost more"
    head = f"${known / HOURS:.5f}/h"
    return head + "".join(f" − {r}" for r in rest)


def firestore(p: Profile) -> dict[str, float]:
    per_day = requests(p) / p.days if p.days else 0
    reads = per_day * DOCS_READ_PER_REQUEST
    writes = per_day * WRITE_SHARE * DOCS_WRITTEN_PER_WRITE
    return {"req_day": per_day, "reads": reads, "writes": writes,
            "over_reads": max(0, reads - FS_FREE_READS_DAY)}


# --- Output -------------------------------------------------------------------------------
def table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def idle_table() -> str:
    nobody = PROFILES[0]
    rds_compute = Cost.price(HOURS, "P_rds_h")
    rds_storage = Cost.price(RDS_GB, "P_rds_gb")
    run_c, stop_c = SQL_P_H * HOURS, 0.0
    st = sql_storage()
    aws_total = aws_rds(nobody)
    rows = [
        ["Frontend + CDN + HTTPS", "$0 (CloudFront Free plan, S3)", "$0 (Firebase Hosting)", "$0", "$0"],
        ["API", "$0 (Lambda, no requests)", "$0 (Cloud Run, min 0)", "$0", "$0"],
        ["DB compute", f"{rds_compute}", money(run_c), money(stop_c), "$0 (Firestore)"],
        ["DB storage", f"{rds_storage}", money(st), money(st), "$0 (< 1 GiB)"],
        ["Registry / secrets / logs", "$0 (in free tiers)", "$0", "$0", "$0"],
        ["**Total**", f"**{aws_total}**", f"**{money(run_c + st)}**", f"**{money(stop_c + st)}**",
         "**$0**"],
    ]
    t = table(["Line", "AWS (RDS db.t3.micro)", "GCP Cloud SQL running", "GCP Cloud SQL stopped",
               "GCP with Firestore"], rows)
    return t + (f"\n\nReference: AWS with Aurora Serverless v2 (Lab 4), paused while idle ≈ "
                f"{money(AURORA_LAB4_REFERENCE)}/month.")


def usage_table() -> str:
    rows = []
    for p in PROFILES:
        cr = cloud_run(p)
        lam, _ = lambda_(p)
        fit_cr = "yes" if cr["total"] == 0 else f"no: {money(cr['total'])}"
        fit_l = "yes" if lam["over_req"] == 0 and lam["over_gbs"] == 0 else (
            f"no: +{lam['over_req']:,.0f} req" + (f", +{lam['over_gbs']:,.0f} GB-s" if lam["over_gbs"] else ""))
        rows.append([p.name, f"{p.hours:g}", f"{cr['req']:,.0f}", f"{cr['vcpu_s']:,.0f}",
                     f"{cr['gib_s']:,.0f}", fit_cr, f"{lam['gbs']:,.0f}", fit_l])
    return table(["Profile", "Hours in use", "Requests", "Cloud Run vCPU-s", "Cloud Run GiB-s",
                  "Cloud Run in free tier?", "Lambda GB-s", "Lambda in free tier?"], rows)


def cost_table() -> str:
    rows = []
    for p in PROFILES:
        od_h = sql_hours_on_demand(p)
        aws = aws_rds(p)
        gcp_od = gcp_sql_on_demand(p)
        if aws.terms:
            cheaper = "—"
        else:
            diff = aws.usd - gcp_od
            cheaper = f"GCP by {money(diff)}" if diff > 0 else f"AWS by {money(-diff)}"
        rows.append([p.name, str(aws), money(gcp_sql_24_7(p)),
                     f"{money(gcp_od)} ({od_h:g} h)", cheaper, break_even(p, gcp_od)])
    return table(["Profile", "AWS: RDS 24/7 + Lambda", "GCP: Cloud SQL 24/7 + Cloud Run",
                  "GCP: Cloud SQL on demand + Cloud Run (hours running)",
                  "Cheaper (vs GCP on demand)", "Break-even RDS price (actual $0.018/h)"], rows)


def cloud_run_detail() -> str:
    rows = []
    for p in PROFILES:
        cr = cloud_run(p)
        rows.append([p.name, money(cr["c_req"]), money(cr["c_cpu"]), money(cr["c_mem"]),
                     money(cr["total"])])
    return table(["Profile", "Requests over 2M", "vCPU-s over 180k", "GiB-s over 360k",
                  "Cloud Run total"], rows)


def firestore_table() -> str:
    rows = []
    for p in PROFILES:
        f = firestore(p)
        over = []
        if f["over_reads"]:
            over.append(f"+{f['over_reads']:,.0f} reads/day")
        if f["writes"] > FS_FREE_WRITES_DAY:
            over.append(f"+{f['writes'] - FS_FREE_WRITES_DAY:,.0f} writes/day")
        fits = "no: " + ", ".join(over) if over else "yes"
        rows.append([p.name, f"{f['req_day']:,.0f}", f"{f['reads']:,.0f}", f"{f['writes']:,.0f}", fits])
    return table(["Profile", "Requests / active day", "Reads / day", "Writes / day",
                  "Within 50k reads, 20k writes a day?"], rows)


def main() -> None:
    filled = {k: v for k, v in SYMBOLS.items() if v is not None}
    print(f"Prices filled in: {filled or 'none (AWS terms stay symbolic)'}\n")
    print("## 1. Idle month\n")
    print(idle_table())
    print("\n## 2a. Usage per profile\n")
    print(usage_table())
    print("\n## 2b. Cloud Run cost per profile\n")
    print(cloud_run_detail())
    print("\n## 2c. Monthly cost per profile\n")
    print(cost_table())
    print("\n## 2d. Firestore daily quota per profile\n")
    print(firestore_table())


if __name__ == "__main__":
    main()
