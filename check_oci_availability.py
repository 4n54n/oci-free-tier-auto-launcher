import os
import oci
import time
import requests
import traceback
from datetime import datetime
from dotenv import load_dotenv


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

COMPARTMENT_ID = os.environ["OCI_COMPARTMENT_ID"]
SUBNET_ID = os.environ["OCI_SUBNET_ID"]

SHAPE = os.getenv("SHAPE", "VM.Standard.A1.Flex")
OCPUS = int(os.getenv("OCPUS", 4))
MEMORY_GB = int(os.getenv("MEMORY_GB", 24))
REGION = os.getenv("OCI_REGION", "us-ashburn-1")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", 60))
LAUNCH_IF_FOUND = os.getenv("LAUNCH_IF_FOUND", "true").lower() == "true"

OS_NAME = os.getenv("OS_NAME", "Canonical Ubuntu")
OS_VERSION = os.getenv("OS_VERSION", "22.04")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# ─────────────────────────────────────────
# Logging
# ─────────────────────────────────────────

def log(msg, prefix="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{prefix}] {msg}")


# ─────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────

def send_telegram_message(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:

        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message[:4000],
                "parse_mode": "HTML",
            },
            timeout=5,
        )

    except Exception:
        pass


def send_exception(prefix, e):

    tb = traceback.format_exc()

    msg = (
        f"[ERROR] {prefix}\n\n"
        f"<code>{str(e)}</code>\n\n"
        f"<code>{tb[-2000:]}</code>"
    )

    send_telegram_message(msg)


# ─────────────────────────────────────────
# SSH Key
# ─────────────────────────────────────────

def load_ssh_key():

    path = os.path.join(os.path.dirname(__file__), "id_rsa.pub")

    if os.path.exists(path):

        with open(path) as f:
            return f.read().strip()

    return ""


# ─────────────────────────────────────────
# Fetch Image
# ─────────────────────────────────────────

def fetch_ubuntu_arm_image(compute, compartment_id):

    for i in range(3):

        try:

            images = compute.list_images(
                compartment_id=compartment_id,
                operating_system=OS_NAME,
                operating_system_version=OS_VERSION,
                shape=SHAPE,
                sort_by="TIMECREATED",
                sort_order="DESC",
            ).data

            if images:

                log("Image found")
                return images[0].id

        except Exception as e:

            log(f"Image fetch error {i+1}/3: {e}", "WARN")
            send_exception("ImageFetch", e)

            time.sleep(3)

    return None


# ─────────────────────────────────────────
# Check Shape
# ─────────────────────────────────────────

def check_shape_availability(compute, compartment_id, ad):

    try:

        shapes = compute.list_shapes(
            compartment_id=compartment_id,
            availability_domain=ad,
        ).data

        return any(s.shape == SHAPE for s in shapes)

    except Exception as e:

        log(f"Shape check error {ad}: {e}", "WARN")
        send_exception(f"ShapeCheck {ad}", e)

        return False


# ─────────────────────────────────────────
# Launch Instance (retry + error safe)
# ─────────────────────────────────────────

def try_launch_instance(compute, image_id, ad, ssh_key):

    details = oci.core.models.LaunchInstanceDetails(

        availability_domain=ad,

        compartment_id=COMPARTMENT_ID,

        shape=SHAPE,

        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCPUS,
            memory_in_gbs=MEMORY_GB,
        ),

        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id,
            source_type="image",
            boot_volume_size_in_gbs=50,
        ),

        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=SUBNET_ID,
            assign_public_ip=True,
        ),

        display_name=f"free-arm-{datetime.now().strftime('%H%M%S')}",

        metadata={"ssh_authorized_keys": ssh_key} if ssh_key else {},
    )

    for i in range(3):

        try:

            result = compute.launch_instance(details)

            return result.data, None

        except oci.exceptions.ServiceError as e:
        
            msg = str(e)
        
            # ignore frequent free-tier error
            if "Out of host capacity" in msg:
                log("Out of host capacity", "INFO")
                return None, e
        
            send_exception("ServiceError", e)
            return None, e

        except oci.exceptions.RequestException as e:

            log(f"Timeout {i+1}/3", "WARN")
            send_exception("RequestException", e)

            time.sleep(3)

        except Exception as e:

            log(f"Launch exception {i+1}/3: {e}", "WARN")
            send_exception("LaunchException", e)

            time.sleep(3)

    return None, "TIMEOUT"


# ─────────────────────────────────────────
# Main
# ─────────────────────────────────────────

def run():

    ssh_key = load_ssh_key()

    config = {
        "user": os.environ["OCI_USER_OCID"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "tenancy": os.environ["OCI_TENANCY_OCID"],
        "region": REGION,
        "key_file": os.path.join(
            os.path.dirname(__file__),
            os.getenv("OCI_KEY_FILE", "oci_api_key.pem"),
        ),
    }

    try:

        oci.config.validate_config(config)

    except Exception as e:

        log(f"Config error: {e}", "ERROR")
        send_exception("ConfigError", e)

        return

    compute = oci.core.ComputeClient(
        config,
        timeout=(10, 180),
    )

    identity = oci.identity.IdentityClient(config)

    try:

        ads = identity.list_availability_domains(
            os.environ["OCI_TENANCY_OCID"]
        ).data

    except Exception as e:

        log("Failed to fetch AD list", "ERROR")
        send_exception("ADFetch", e)

        return

    ad_names = [a.name for a in ads]

    log(f"Region {REGION}")
    log(f"AD count {len(ad_names)}")

    send_telegram_message(
        f"OCI Launcher started\nRegion: {REGION}\nAD count: {len(ad_names)}"
    )

    image_id = fetch_ubuntu_arm_image(compute, COMPARTMENT_ID)

    if not image_id:

        log("No image found", "ERROR")
        send_telegram_message("ERROR: No image found")

        return

    attempt = 0

    while True:

        try:

            attempt += 1

            log(f"SCAN {attempt}", "SCAN")

            for ad in ad_names:

                shape_ok = check_shape_availability(
                    compute,
                    COMPARTMENT_ID,
                    ad,
                )

                if not shape_ok:
                    continue

                log(f"Attempt launch in {ad}", "LAUNCH")

                inst, err = try_launch_instance(
                    compute,
                    image_id,
                    ad,
                    ssh_key,
                )

                if inst:

                    log("INSTANCE CREATED", "SUCCESS")

                    send_telegram_message(
                        f"Instance created\nAD: {inst.availability_domain}\nID: {inst.id}"
                    )

                    return

                if err:

                    msg = str(err)

                    if "Out of host capacity" in msg:

                        log("No capacity")

                    elif "LimitExceeded" in msg:

                        log("Free tier limit reached", "STOP")

                        send_telegram_message(
                            "Free tier limit exceeded"
                        )

                        return

                    else:

                        log(msg, "ERROR")

            time.sleep(POLL_SECONDS)

        except Exception as e:

            log(f"Main loop crash: {e}", "CRASH")

            send_exception("MainLoop", e)

            time.sleep(5)


if __name__ == "__main__":
    run()
