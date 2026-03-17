"""
OCI Free Tier Instance Availability Checker & Auto-Launcher
============================================================
Checks all Availability Domains in your region for free ARM capacity
and automatically launches an instance when one becomes available.

Setup:
  pip install -r requirements.txt
  cp .env.example .env        # then fill in your values
  python check_oci_availability.py
"""

import os
import oci
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load credentials from .env file in the same directory
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# ─────────────────────────────────────────
# Config — loaded from .env
# ─────────────────────────────────────────
COMPARTMENT_ID = os.environ["OCI_COMPARTMENT_ID"]
SUBNET_ID      = os.environ["OCI_SUBNET_ID"]

SHAPE      = os.getenv("SHAPE", "VM.Standard.A1.Flex")
OCPUS      = int(os.getenv("OCPUS", 4))
MEMORY_GB  = int(os.getenv("MEMORY_GB", 24))
REGION     = os.getenv("OCI_REGION", "us-ashburn-1")
POLL_SECONDS   = int(os.getenv("POLL_SECONDS", 60))
LAUNCH_IF_FOUND = os.getenv("LAUNCH_IF_FOUND", "true").lower() == "true"

OS_NAME    = os.getenv("OS_NAME", "Canonical Ubuntu")
OS_VERSION = os.getenv("OS_VERSION", "22.04")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
# ─────────────────────────────────────────


def send_telegram_message(message):
    """Send a message via Telegram Bot."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        log(f"Failed to send Telegram message: {e}")


def log(msg, prefix="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{prefix}]  {msg}")


def load_ssh_key():
    """Load the SSH public key from the same directory as the script."""
    key_path = os.path.join(os.path.dirname(__file__), "id_rsa.pub")
    if os.path.exists(key_path):
        with open(key_path, "r") as f:
            return f.read().strip()
    return ""


def fetch_ubuntu_arm_image(compute, compartment_id):
    """Dynamically fetch the latest image OCID matching OS and Shape."""
    try:
        images = compute.list_images(
            compartment_id=compartment_id,
            operating_system=OS_NAME,
            operating_system_version=OS_VERSION,
            shape=SHAPE,
            sort_by="TIMECREATED",
            sort_order="DESC"
        ).data
        if images:
            img = images[0]
            log(f"Found image: {img.display_name}")
            log(f"Image OCID : {img.id}", "KEY")
            return img.id
        else:
            log(f"No {OS_NAME} {OS_VERSION} {SHAPE} images found in your tenancy!", "ERROR")
            return None
    except Exception as e:
        log(f"Failed to fetch image list: {e}", "ERROR")
        return None


def check_shape_availability(compute, compartment_id, availability_domain):
    """Check if the ARM shape is listed for this Availability Domain."""
    try:
        shapes = compute.list_shapes(
            compartment_id=compartment_id,
            availability_domain=availability_domain
        ).data
        return any(s.shape == SHAPE for s in shapes)
    except Exception as e:
        log(f"Shape check error for {availability_domain}: {e}", "WARN")
        return False


def try_launch_instance(compute, image_id, availability_domain, ssh_public_key):
    """Attempt to launch a free ARM instance."""
    details = oci.core.models.LaunchInstanceDetails(
        availability_domain=availability_domain,
        compartment_id=COMPARTMENT_ID,
        shape=SHAPE,
        shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=OCPUS,
            memory_in_gbs=MEMORY_GB
        ),
        source_details=oci.core.models.InstanceSourceViaImageDetails(
            image_id=image_id,
            source_type="image",
            boot_volume_size_in_gbs=50
        ),
        create_vnic_details=oci.core.models.CreateVnicDetails(
            subnet_id=SUBNET_ID,
            assign_public_ip=True,
            assign_private_dns_record=True
        ),
        agent_config=oci.core.models.LaunchInstanceAgentConfigDetails(
            is_monitoring_disabled=False,
            is_management_disabled=True,
            are_all_plugins_disabled=False,
            plugins_config=[
                oci.core.models.InstanceAgentPluginConfigDetails(name="Vulnerability Scanning",       desired_state="DISABLED"),
                oci.core.models.InstanceAgentPluginConfigDetails(name="Compute Instance Monitoring",  desired_state="ENABLED"),
                oci.core.models.InstanceAgentPluginConfigDetails(name="Bastion",                      desired_state="DISABLED"),
                oci.core.models.InstanceAgentPluginConfigDetails(name="Custom Logs Monitoring",       desired_state="ENABLED"),
                oci.core.models.InstanceAgentPluginConfigDetails(name="Cloud Guard Workload Protection", desired_state="ENABLED"),
                oci.core.models.InstanceAgentPluginConfigDetails(name="Block Volume Management",      desired_state="DISABLED"),
            ]
        ),
        availability_config=oci.core.models.LaunchInstanceAvailabilityConfigDetails(
            recovery_action="RESTORE_INSTANCE"
        ),
        instance_options=oci.core.models.InstanceOptions(
            are_legacy_imds_endpoints_disabled=False
        ),
        display_name=f"free-arm-{datetime.now().strftime('%Y%m%d-%H%M')}",
        metadata={"ssh_authorized_keys": ssh_public_key} if ssh_public_key else {}
    )
    try:
        result = compute.launch_instance(details)
        return result.data, None
    except oci.exceptions.ServiceError as e:
        return None, e


def print_availability_summary(results: dict):
    """Print a clean availability table after each full scan."""
    print()
    print("  ┌─────────────────────────────────┬──────────────────┐")
    print("  │  Availability Domain            │  Free ARM Space  │")
    print("  ├─────────────────────────────────┼──────────────────┤")
    for ad, status in results.items():
        ad_short = ad.replace("SIny:", "")
        if status == "AVAILABLE":
            status_str = "AVAILABLE      "
        elif status == "NO CAPACITY":
            status_str = "NO CAPACITY    "
        elif status == "NOT LISTED":
            status_str = "NOT LISTED     "
        else:
            status_str = f"{status[:14]:<14}"
        print(f"  │  {ad_short:<31}│  {status_str}│")
    print("  └─────────────────────────────────┴──────────────────┘")
    print()


def run():
    ssh_public_key = load_ssh_key()
    start_time = datetime.now()

    print()
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║    OCI Free Tier Instance Availability Checker   ║")
    print("  ╚══════════════════════════════════════════════════╝")
    log(f"Region : {REGION}")
    log(f"Shape  : {SHAPE} ({OCPUS} OCPUs, {MEMORY_GB}GB RAM)")
    log(f"Mode   : {'AUTO-LAUNCH when found' if LAUNCH_IF_FOUND else 'CHECK ONLY (no launch)'}")
    if ssh_public_key:
        log("SSH key loaded from id_rsa.pub", "KEY")
    else:
        log("No id_rsa.pub found — instance will launch without SSH key!", "WARN")
    print()

    # Load OCI config from the .env values
    try:
        config = {
            "user":        os.environ["OCI_USER_OCID"],
            "fingerprint": os.environ["OCI_FINGERPRINT"],
            "tenancy":     os.environ["OCI_TENANCY_OCID"],
            "region":      REGION,
            "key_file":    os.path.join(os.path.dirname(__file__), os.getenv("OCI_KEY_FILE", "oci_api_key.pem")),
        }
        oci.config.validate_config(config)
    except KeyError as e:
        print(f"\n[ERROR] Missing required environment variable: {e}")
        print("   Copy .env.example → .env and fill in all required values.")
        return
    except Exception as e:
        print(f"\n[ERROR] OCI config error: {e}")
        return

    compute = oci.core.ComputeClient(config)
    identity = oci.identity.IdentityClient(config)

    # Dynamically fetch Availability Domains for the region
    try:
        ads = identity.list_availability_domains(compartment_id=os.environ["OCI_TENANCY_OCID"]).data
        ad_names = [ad.name for ad in ads]
        log(f"Found {len(ad_names)} Availability Domains in {REGION}.")
    except Exception as e:
        print(f"\n[ERROR] Failed to fetch Availability Domains: {e}")
        return

    send_telegram_message(
        f"[START] <b>OCI Auto-Launcher Started</b>\n"
        f"Monitoring <b>{REGION}</b> ({len(ad_names)} ADs) for Free Tier shape string <code>{SHAPE}</code>.\n"
        f"Checking every <b>{POLL_SECONDS}s</b> — status update every "
        f"<b>{POLL_SECONDS * 200 // 3600}h {(POLL_SECONDS * 200 % 3600) // 60}m</b>."
    )

    # Dynamically fetch the correct image OCID
    log(f"Looking up latest {OS_NAME} {OS_VERSION} image...")
    image_id = fetch_ubuntu_arm_image(compute, COMPARTMENT_ID)
    if not image_id:
        print(f"\n[ERROR] Could not find a valid {OS_NAME} {OS_VERSION} image. Check your OCI permissions or region.")
        return

    attempt = 0
    while True:
        attempt += 1
        log(f"━━━ Scan #{attempt} — checking all zones within {REGION} ━━━", "SCAN")

        # Send a status ping every 200 scans
        if attempt % 200 == 0:
            elapsed = datetime.now() - start_time
            total_secs = int(elapsed.total_seconds())
            hours, remainder = divmod(total_secs, 3600)
            minutes = remainder // 60
            elapsed_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
            send_telegram_message(
                f"[STATUS] <b>OCI Status Update</b>\n"
                f"Scan <b>#{attempt}</b> completed ({elapsed_str} elapsed).\n"
                f"Still looking for free capacity in <b>{REGION}</b> — will keep trying!"
            )

        ad_results = {}

        for ad in ad_names:
            shape_ok = check_shape_availability(compute, COMPARTMENT_ID, ad)

            if not shape_ok:
                ad_results[ad] = "NOT LISTED"
                continue

            if not LAUNCH_IF_FOUND:
                ad_results[ad] = "AVAILABLE"
                continue

            log(f"Shape found in {ad} — attempting launch...", "LAUNCH")

            instance, error = try_launch_instance(compute, image_id, ad, ssh_public_key)

            if instance:
                ad_results[ad] = "AVAILABLE"
                print_availability_summary(ad_results)
                print("  " + "="*48)
                print("  [SUCCESS] FREE INSTANCE SUCCESSFULLY CREATED!")
                print(f"  ID       : {instance.id}")
                print(f"  Zone     : {instance.availability_domain}")
                print(f"  Status   : {instance.lifecycle_state}")
                print("  Console  : OCI Console → Compute → Instances")
                print("  " + "="*48 + "\n")
                send_telegram_message(
                    f"[SUCCESS] <b>Instance Created!</b>\n\n"
                    f"<b>Region:</b> {REGION}\n<b>AD:</b> <code>{instance.availability_domain}</code>\n"
                    f"<b>ID:</b> <code>{instance.id}</code>\n\nCheck your OCI Console!"
                )
                return

            elif error:
                msg = str(error.message) if hasattr(error, "message") else str(error)
                if "Out of host capacity" in msg:
                    ad_results[ad] = "NO CAPACITY"
                elif "LimitExceeded" in msg:
                    ad_results[ad] = "LIMIT EXCEEDED"
                    print_availability_summary(ad_results)
                    print("  [WARN] Limit Exceeded: You may already have a free instance running.")
                    print("         Check: OCI Console → Compute → Instances\n")
                    send_telegram_message("[ERROR] <b>Limit Exceeded</b>\nOracle says you already hit your free tier limit. Script stopping.")
                    return
                elif "NotAuthorizedOrNotFound" in msg:
                    ad_results[ad] = "AUTH ERROR"
                    print_availability_summary(ad_results)
                    print("  [ERROR] Auth Error: Check your credentials in .env\n")
                    send_telegram_message("[ERROR] <b>Auth Error</b>\nCheck OCI API credentials in your .env file. Script stopping.")
                    return
                else:
                    ad_results[ad] = "ERROR"
                    log(f"Unexpected error in {ad}: {msg}", "ERROR")

        print_availability_summary(ad_results)

        any_available = any(v == "AVAILABLE" for v in ad_results.values())
        if not any_available:
            log(f"No free slots found. Retrying in {POLL_SECONDS}s...", "WAIT")
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    run()
