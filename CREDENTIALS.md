# Credential and token checklist

Use this list on first install, credential rotation and disaster recovery. Do
not paste secret values into issues, commits, screenshots or validation logs.

## Required for the current installation

- [ ] **Local family config** exists at
  `$HOME/.openclaw/workspace/config/family.local.json`, is mode `0600`, and
  passes `python3 scripts/validate_config.py`. It is private metadata, not a
  credential.
- [ ] **OpenClaw provider credential** is installed through OpenClaw's supported
  login/credential flow. Verify with an exact-response smoke test; do not copy
  provider tokens into FamilyBot files.
- [ ] **Telegram bot credential** is held by OpenClaw's credential store. Verify
  `openclaw gateway health` and one deliberate message to each configured
  parent. Telegram recipient IDs belong in local family config; the bot token
  does not.
- [ ] **Mail credential** is in Himalaya's protected configuration, normally
  `~/.config/himalaya/config.toml` plus its chosen secret store. Verify
  `himalaya folder list --output json`. Prefer an app password and least-privilege
  mailbox dedicated to FamilyBot.
- [ ] **Portal parent PIN** is 4–8 digits (6–8 random digits recommended) in
  `familybot-portal/runtime/parent-pin.txt`, mode `0600`. It is copied to the
  ignored deployment runtime and rate-limited by the API.

## Required only when enabled

- [ ] **Spond username/password** are in
  `$HOME/.openclaw/workspace/secrets.env`, mode `0600`, as `SPOND_USERNAME` and
  `SPOND_PASSWORD`. The community Spond client is unofficial; use a dedicated
  account if practical and review it after upstream changes.
- [ ] **Future Home Assistant credential** uses a dedicated non-admin account
  where possible and an owner-only token stored outside Git. FamilyBot receives
  an allowlisted adapter, never an arbitrary browser-to-Home-Assistant proxy.
- [ ] **Future appliance authorizations** (Xiaomi, Nest, SmartThings,
  Electrolux/AEG, HomeWhiz or Toshiba) are entered in Home Assistant or the
  provider's local OAuth/setup flow. Do not paste them into chat, FamilyBot
  configuration or issues. See [specs/SMART_HOME.md](specs/SMART_HOME.md).

## Integrations without secrets

- Entur requires a descriptive client name and the correct stop/quay identifiers,
  not an API key. Ruter departures are consumed through Entur.
- MET Locationforecast requires an identifiable User-Agent with contact
  information, not an API key.
- Bonjour/mDNS needs no credential and must remain limited to the home LAN.

## File and backup controls

- [ ] Secret/config files and runtime directories are owned by the service user;
  files are `0600`, directories `0700`.
- [ ] No router port-forward exposes ports 3000 or 8788 to the internet.
- [ ] The Mac's guest/IoT network cannot reach the portal unless intentionally
  allowed.
- [ ] The protected backup includes credentials, config and SQLite separately
  from Git; backup media is encrypted and a restore has been tested.
- [ ] Old credentials are revoked after migration or suspected exposure.

Never test a secret by printing it. Test the capability it grants, then record
only pass/fail and a timestamp.
