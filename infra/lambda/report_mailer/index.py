"""Email each new report: S3 ObjectCreated on reports/*.csv -> SES."""

import csv
import io
import logging
import os
import posixpath
import urllib.parse
from email.message import EmailMessage

import boto3

log = logging.getLogger("meetings.mailer")
log.setLevel(logging.INFO)
s3 = boto3.client("s3")
ses = boto3.client("sesv2")


def summary_line(text):
    """One sentence from the CSV's summary section (a header row, then values)."""
    rows = list(csv.reader(io.StringIO(text)))
    start = rows.index(["section", "summary"])
    s = dict(zip(rows[start + 1], rows[start + 2]))
    return (
        f"{s['meetings']} meetings, {s['hours']} hours. "
        f"Previous week {s['previous_week']}: {s['previous_meetings']} meetings, "
        f"{s['previous_hours']} hours (change {s['change_meetings']} meetings, "
        f"{s['change_hours']} hours)."
    )


def handler(event, context):
    sender = os.environ["SENDER"]
    recipients = [a.strip() for a in os.environ["RECIPIENTS"].split(",") if a.strip()]
    sent = []
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        log.info(
            "report-mailer triggered",
            extra={
                "trigger": "s3",
                "bucket": bucket,
                "key": key,
                "eventName": record["eventName"],
                "sequencer": record["s3"]["object"].get("sequencer"),
            },
        )
        data = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        filename = posixpath.basename(key)
        week = filename.removesuffix(".csv")

        msg = EmailMessage()
        msg["Subject"] = f"Weekly meetings report {week}"
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg.set_content(
            f"The meetings report for {week} is attached.\n\n"
            f"{summary_line(data.decode('utf-8'))}\n"
        )
        msg.add_attachment(data, maintype="text", subtype="csv", filename=filename)

        response = ses.send_email(
            FromEmailAddress=sender,
            Destination={"ToAddresses": recipients},
            Content={"Raw": {"Data": msg.as_bytes()}},
        )
        log.info(
            "report emailed",
            extra={"trigger": "s3", "key": key, "sesMessageId": response["MessageId"]},
        )
        sent.append({"key": key, "messageId": response["MessageId"]})
    return {"sent": sent}
