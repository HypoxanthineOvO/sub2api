# Native App Blue-Green Release

This procedure changes only the Sub2API App process and Nginx upstream. It does
not restart or modify PostgreSQL, Redis, proxy allocator, Selected Node, or the
five proxy slots.

## One-time installation

Install the app-only unit and Nginx files, preserving blue (`19821`) as the
initial active upstream:

```bash
sudo bash /home/heyx/Workspace/VSP/VSP-Sub2API/deploy/native/install-blue-green-nginx.sh
```

`sites-enabled/api.vsplab.cn` is the active production file on this host. Do not
copy the divergent `sites-available` file over it.

## Stage and verify a release

Build the candidate, install it into the inactive slot with autonomous workers
disabled, and start the slot:

```bash
bash deploy/native/build.sh
sudo env VSP_NATIVE_RELEASE=<release> VSP_NATIVE_SLOT=green \
  VSP_NATIVE_SLOT_MODE=canary bash deploy/native/install.sh
sudo systemctl start vsp-sub2api-app-slot@green.service
for _ in $(seq 1 30); do
  curl --noproxy '*' --fail http://127.0.0.1:19822/health && break
  sleep 1
done
curl --noproxy '*' --fail http://127.0.0.1:19822/health
```

Use `switch-app-slot.sh green` to expose the candidate for application-level
checks. The script changes one symlink, validates Nginx, reloads it, verifies the
HTTPS health endpoint, and waits for connections to the old port to drain. It
does not stop either App process.

## Promote without duplicate workers

The canary starts with `SUB2API_DISABLE_AUTONOMOUS_WORKERS=1`. After its checks:

This existing switch disables the uncoordinated scheduled tests, channel
monitors, expiry sweeps, refreshers, and similar autonomous jobs. A few queue
consumers still start, but their work claims are coordinated through the shared
database or Redis.

1. Switch traffic back to blue.
2. Re-run `install.sh` for green with `VSP_NATIVE_SLOT_MODE=active`.
3. Restart green while blue is serving traffic and verify green health.
4. Switch traffic to green and wait for blue to drain.
5. After the switch script reports that port `19821` is drained, install the
   target definition that no longer hard-codes the legacy App, enable green,
   disable the old App unit, and then stop the old App:

   ```bash
   sudo install -m 0644 ops/systemd/vsp-sub2api-production.target /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable vsp-sub2api-app-slot@green.service
   sudo systemctl disable vsp-sub2api-app@production.service
   sudo systemctl stop vsp-sub2api-app@production.service
   ```

For the first release, the old service is `vsp-sub2api-app@production.service`.
Later releases stop `vsp-sub2api-app-slot@blue.service` or
`vsp-sub2api-app-slot@green.service`, whichever is inactive.

Rollback before stopping the old App is the same switch command pointed at the
old slot. No database or proxy rollback is involved.

Only the active slot is enabled. When deploying in the other direction, enable
the promoted slot and disable the retired slot before stopping it; this makes a
host reboot start the same release that Nginx serves.
