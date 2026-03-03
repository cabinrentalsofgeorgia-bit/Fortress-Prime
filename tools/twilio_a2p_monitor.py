#!/usr/bin/env python3
"""
Twilio A2P 10DLC Campaign Monitor
Polls campaign status until VERIFIED, then sends a test SMS.
Run: python tools/twilio_a2p_monitor.py [--once]
"""

import os, sys, time, logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [A2P-MONITOR] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("a2p")
for noisy in ("twilio", "twilio.http_client", "urllib3", "urllib3.connectionpool"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
MS_SID = "MGc6c8b6c84f60d2b5223520d5e9eb2c23"
CAMPAIGN_SID = "QE2c6890da8086d771620e9b13fadeba0b"
TEST_TO = os.getenv("OWNER_PHONE", "+16785493680")


def get_client():
    from twilio.rest import Client
    return Client(ACCOUNT_SID, AUTH_TOKEN)


def check_campaign():
    client = get_client()
    campaign = client.messaging.v1.services(MS_SID).us_app_to_person(CAMPAIGN_SID).fetch()
    return {
        "sid": campaign.sid,
        "status": campaign.campaign_status,
        "campaign_id": campaign.campaign_id,
        "use_case": campaign.us_app_to_person_usecase,
        "updated": str(campaign.date_updated),
    }


def send_test_sms():
    client = get_client()
    msg = client.messages.create(
        messaging_service_sid=MS_SID,
        to=TEST_TO,
        body="Cabin Rentals of Georgia: A2P campaign APPROVED. SMS system is now fully operational. Reply STOP to opt out.",
    )
    return {"sid": msg.sid, "status": msg.status, "error_code": msg.error_code}


def check_delivery(msg_sid):
    client = get_client()
    msg = client.messages(msg_sid).fetch()
    return {"status": msg.status, "error_code": msg.error_code}


def main():
    once = "--once" in sys.argv
    poll_interval = 60
    max_polls = 1440  # 24 hours at 60s intervals

    log.info("=" * 60)
    log.info("  TWILIO A2P 10DLC CAMPAIGN MONITOR")
    log.info(f"  Campaign: {CAMPAIGN_SID}")
    log.info(f"  Messaging Service: {MS_SID}")
    log.info(f"  Test phone: {TEST_TO}")
    log.info("=" * 60)

    for attempt in range(1, max_polls + 1):
        try:
            result = check_campaign()
            status = result["status"]
            log.info(f"[{attempt}] Status: {status} | Campaign ID: {result['campaign_id']} | Updated: {result['updated']}")

            if status == "VERIFIED":
                log.info("CAMPAIGN APPROVED — sending test SMS...")
                test = send_test_sms()
                log.info(f"Test SMS sent: {test['sid']} (status={test['status']}, error={test['error_code']})")

                time.sleep(10)
                delivery = check_delivery(test["sid"])
                log.info(f"Delivery check: status={delivery['status']}, error={delivery['error_code']}")

                if delivery["error_code"] is None or delivery["status"] in ("sent", "delivered", "queued"):
                    log.info("SUCCESS — A2P SMS is fully operational!")
                else:
                    log.warning(f"Test message had error {delivery['error_code']} — may still be propagating")
                return True

            elif status == "FAILED":
                log.error(f"Campaign FAILED. Check Twilio Console for details.")
                return False

            if once:
                return status == "VERIFIED"

        except Exception as e:
            log.error(f"Poll error: {e}")

        if not once:
            time.sleep(poll_interval)

    log.warning("Timed out waiting for campaign approval (24h)")
    return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
