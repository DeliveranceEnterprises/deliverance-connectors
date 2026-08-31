# InOrbit Agent Core, running physically on the WDC tablet (Android 5.1)

Goal: get InOrbit's real Agent Core running ON the tablet itself, not on a dev
machine reached over VPN. This satisfies the requirement that the code
"se ejecute en el robot" for objective 1.

Full reasoning trail (why Linux Deploy instead of Termux, why not Edge SDK,
ROS1-on-ARM32 confirmation) lives in this directory's `CLAUDE.md`. This file
is just the practical steps for whoever has the tablet physically in front
of them.

## 1. Install Linux Deploy

Download from F-Droid or the developer's own site (search "Linux Deploy" by
meefik). Current version (2.6.0) officially supports Android 5.0+, no need
to hunt for an old build.

## 2. Configure it: Ubuntu, armhf, no-root (PRoot) mode

Open Linux Deploy, go into its settings (gear icon):
- **Distribution**: Ubuntu
- **Suite**: focal (20.04) if it lets you pick -- matches ROS Noetic. If
  Focal has problems on this old a device, bionic (18.04, matches ROS
  Melodic) is the fallback, also has official armhf ROS packages.
- **Architecture**: armhf (32-bit ARM) -- the tablet's real architecture,
  confirmed from the manufacturer's own SDK build config.
- **Installation method**: look specifically for a PRoot-based option, NOT
  chroot -- chroot needs root, this tablet should not be rooted. The exact
  wording varies by Linux Deploy version, look for "PRoot" in the method or
  container type selector.

Then tap "Install" (or the down-arrow button) and let it download/build the
Ubuntu image. This needs real internet access (tablet already has this via
office WiFi) and will take a while the first time.

## 3. Start it and get a shell inside

Tap "Start". Once running, use the app's own terminal/SSH shortcut to get a
shell inside the Ubuntu environment. Confirm you're really inside Ubuntu:

```bash
cat /etc/os-release
```

Should show Ubuntu, not Android/Termux.

## 4. Run InOrbit's real installer, unmodified

This is the same installer already used for the earlier (VPN-based) version
of this work -- a saved copy is at `inorbit_installer.sh` in this same
directory, but running it fresh from InOrbit directly is fine too:

```bash
curl -fsSL https://space.inorbit.ai/liftoff/<INORBIT_INSTALL_KEY> | sh
```

Follow its prompts. It should now correctly detect a real Ubuntu system
(that was the whole point of this detour) and proceed with its normal
install flow -- installing ROS if needed, setting up the agent, etc.

## 5. What "success" looks like

The robot should appear/come online in InOrbit's fleet using this tablet's
own connection, no VPN or dev machine involved at all. Confirm via InOrbit
Control (pose/battery visible) the same way objective 1 was originally
validated, but this time the agent's traffic is coming straight from the
tablet's own WiFi.

## If it fails

Note exactly where it fails (which step, what error) rather than giving up
silently -- that tells us whether the problem is PRoot's own limitations,
ROS's install process, or something else, and whether it's worth debugging
further or worth revisiting the "Deliverance's own agent app" path
(`deliverance_wdc_agent_app/`, currently parked) instead.
