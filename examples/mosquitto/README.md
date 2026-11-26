# Mosquitto add-on: dedicated user and ACL for Qingping monitors

1. Add-on **Configuration**:

   ```yaml
   logins:
     - username: qingping
       password: "use-a-long-random-password"
   customize:
     active: true
     folder: mosquitto
   ```

2. Copy `acl.conf` and `accesscontrollist` from this folder to `/share/mosquitto/`
   (Samba share `share`, or the File editor / SSH add-on).
3. Replace `homeassistant` in `accesscontrollist` with the username your MQTT integration uses
   (Settings → Devices & services → MQTT → Configure → Re-configure MQTT).
4. Restart the add-on and check its log for `Not authorized` lines.

Why: the device accepts unsigned firmware updates on its down topic. Only Home Assistant should be
able to write `qingping/+/down` (see docs/PRIVACY.md).
