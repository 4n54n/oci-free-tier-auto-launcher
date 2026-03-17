# OCI Free Tier ARM Instance Auto-Launcher

A Python script that continuously monitors Oracle Cloud Infrastructure (OCI) for available **free tier ARM (A1.Flex) capacity** in your configured region and automatically launches an instance the moment one becomes available. Sends Telegram notifications on key events.

---

## Features

- Automatically detects and polls **all** Availability Domains in your chosen region
- Auto-launches the instance the moment capacity is detected
- Dynamically fetches the latest matching OS image (defaults to Ubuntu 22.04 ARM)
- Telegram bot notifications for start, capacity found, success, and errors
- Clean table output showing per-AD availability status
- All credentials stored in `.env` — safe to share code publicly

---

## Project Structure

```
oci-free-tier-auto-launcher/
├── check_oci_availability.py   # Main script
├── .env                        # Your credentials (git-ignored, create from .env.example)
├── .env.example                # Safe template — commit this
├── oci_api_key.pem             # Your OCI private key (git-ignored)
├── id_rsa.pub                  # Your SSH public key (git-ignored)
└── requirements.txt
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

```bash
cp .env.example .env
```

Then fill in `.env` with your values (see sections below for how to find each one).

### 3. Add your OCI private key

Place your private key file as `oci-free-tier-auto-launcher/oci_api_key.pem`.

### 4. Add your SSH public key *(optional but recommended)*

Place your SSH public key as `oci-free-tier-auto-launcher/id_rsa.pub` so it's injected into the instance on launch.

Generate one if you don't have it:
```bash
ssh-keygen -t rsa -b 4096
```

### 5. Run the script

```bash
cd oci-free-tier-auto-launcher
python check_oci_availability.py

# Or to run it continuously in the background (Linux/Mac):
# nohup python -u check_oci_availability.py > bot_log.txt 2>&1 &
```

### Example Output

```text
  ╔══════════════════════════════════════════════════╗
  ║    OCI Free Tier Instance Availability Checker   ║
  ╚══════════════════════════════════════════════════╝
[18:16:38]  Region : us-ashburn-1
[18:16:38]  Shape  : VM.Standard.A1.Flex (4 OCPUs, 24GB RAM)
[18:16:38]  Mode   : AUTO-LAUNCH when found
[18:16:38]  SSH key loaded from id_rsa.pub

[18:16:42]  Found 3 Availability Domains in us-ashburn-1.
[18:16:45]  Looking up latest Canonical Ubuntu 22.04 image...
[18:16:47]  Found image: Canonical-Ubuntu-22.04-aarch64-...
[18:16:47]  Image OCID : ocid1.image.oc1.iad.aaaaaaaahk7...
[18:16:47]  ━━━ Scan #1 — checking all zones within us-ashburn-1 ━━━
[18:16:48]  Shape found in SIny:US-ASHBURN-AD-1 — attempting launch...
[18:16:50]  Shape found in SIny:US-ASHBURN-AD-2 — attempting launch...
[18:16:54]  Shape found in SIny:US-ASHBURN-AD-3 — attempting launch...

  ┌─────────────────────────────────┬──────────────────┐
  │  Availability Domain            │  Free ARM Space  │
  ├─────────────────────────────────┼──────────────────┤
  │  US-ASHBURN-AD-1                │  NO CAPACITY     │
  │  US-ASHBURN-AD-2                │  NO CAPACITY     │
  │  US-ASHBURN-AD-3                │  NO CAPACITY     │
  └─────────────────────────────────┴──────────────────┘

[18:16:56] ⏳  No free slots found. Retrying in 60s...
```

---

## How to Get Your Credentials

### `OCI_USER_OCID` and `OCI_TENANCY_OCID`

1. Log in to [OCI Console](https://cloud.oracle.com)
2. Click your **Profile icon** (top-right) → **My Profile**
3. Copy **OCID** → this is your `OCI_USER_OCID`
4. Click **Profile icon** → **Tenancy: \<name\>**
5. Copy **OCID** → this is your `OCI_TENANCY_OCID`

---

### `OCI_FINGERPRINT` and `OCI_KEY_FILE` (API Key)

1. Go to **Profile** → **My Profile** → **API Keys** (left sidebar)
2. Click **Add API Key** → **Generate API Key Pair**
3. Download the **Private Key** → save as `oci-free-tier-auto-launcher/oci_api_key.pem`
4. After adding, the **Fingerprint** is shown in the table — copy it to `OCI_FINGERPRINT`

---

### `OCI_COMPARTMENT_ID`

This is typically your **root tenancy OCID** for free-tier accounts (same as `OCI_TENANCY_OCID`).

To use a sub-compartment:
1. Go to **Identity & Security** → **Compartments**
2. Click your compartment → copy its **OCID**

---

### `OCI_SUBNET_ID`

1. Go to **Networking** → **Virtual Cloud Networks**
2. Open your VCN → click **Subnets**
3. Click your subnet → copy its **OCID**

If you don't have a VCN yet:
- Go to **Networking** → **Virtual Cloud Networks** → **Start VCN Wizard** → **Create VCN with Internet Connectivity**

---

### IAM Policy (Required!)

Your OCI user needs permission to list and launch instances. Create a policy:

1. Go to **Identity & Security** → **Policies**
2. Click **Create Policy**
3. Set scope to your **root compartment** (or the relevant one)
4. Add these statements (replace `<group-name>` with your user's group, e.g. `Administrators`):

```
Allow group <group-name> to manage instance-family in tenancy
Allow group <group-name> to use subnets in tenancy
Allow group <group-name> to use vnics in tenancy
Allow group <group-name> to manage volumes in tenancy
Allow group <group-name> to read images in tenancy
```

> **Tip:** If your account is the tenancy admin, you likely already have all permissions via the `Administrators` group. You can verify by running the script — if you see `AUTH ERROR`, the policy is missing.

---

### Telegram Notifications *(optional)*

**Get Bot Token:**
1. Open Telegram → search for **@BotFather**
2. Send `/newbot` → follow prompts → copy the **token**

**Get Chat ID:**
1. Open Telegram → search for **@userinfobot**
2. Send `/start` → it replies with your **Chat ID**

Leave `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` blank in `.env` to disable notifications.

---

## Security Notes

- `.env`, `*.pem`, `id_rsa.pub`, and `config` are all listed in `.gitignore` — they will never be committed to git
- Only commit `.env.example` (the template with no real values)
- Rotate your OCI API key immediately if you accidentally push it

---

## Environment Variables Reference

| Variable | Required | Description |
|---|---|---|
| `OCI_USER_OCID` | Yes | Your OCI user OCID |
| `OCI_TENANCY_OCID` | Yes | Your tenancy OCID |
| `OCI_FINGERPRINT` | Yes | API key fingerprint |
| `OCI_KEY_FILE` | Yes | Path to your `.pem` private key |
| `OCI_REGION` | Yes | OCI region (e.g., `us-ashburn-1`, `eu-frankfurt-1`) |
| `OCI_COMPARTMENT_ID` | Yes | Compartment OCID to launch the instance in |
| `OCI_SUBNET_ID` | Yes | Subnet OCID for the instance's network |
| `SHAPE` | optional | Instance shape (default: `VM.Standard.A1.Flex`) |
| `OCPUS` | optional | Number of OCPUs (default: `4`) |
| `MEMORY_GB` | optional | RAM in GB (default: `24`) |
| `OS_NAME` | optional | OS Image Name (default: `Canonical Ubuntu`) |
| `OS_VERSION` | optional | OS Version (default: `22.04`) |
| `POLL_SECONDS` | optional | Polling interval in seconds (default: `60`) |
| `LAUNCH_IF_FOUND` | optional | `true` to auto-launch, `false` to monitor only (default: `true`) |
| `TELEGRAM_BOT_TOKEN` | optional | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | optional | Your Telegram chat/user ID |

---

## License

MIT — free to use, modify, and share.
