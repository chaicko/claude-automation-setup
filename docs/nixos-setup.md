# NixOS Setup Guide

This is the recommended way to run the agent on NixOS. Everything is declared
in your system config — no `setup.sh`, no mutable installs, reproducible
across reboots and rebuilds.

---

## Prerequisites

- NixOS installed (nixos-unstable channel recommended)
- NVIDIA GTX 1060 drivers configured (see below)
- Flakes enabled

### Enable flakes (if not already)

In `configuration.nix`:

```nix
nix.settings.experimental-features = [ "nix-command" "flakes" ];
```

### NVIDIA driver setup

In `configuration.nix`:

```nix
# Required for Ollama CUDA inference
hardware.nvidia = {
  modesetting.enable = true;
  open = false;          # proprietary driver (needed for CUDA on GTX 1060)
  nvidiaSettings = true;
  package = config.boot.kernelPackages.nvidiaPackages.stable;
};

hardware.graphics.enable = true;   # nixos-unstable; older: hardware.opengl.enable

services.xserver.videoDrivers = [ "nvidia" ];
```

---

## Option A — Add to your existing NixOS flake (recommended)

This is the cleanest approach if your server already has a `flake.nix`.

### 1. Add the input

In your server's `flake.nix`:

```nix
inputs = {
  nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  claude-agent.url = "github:chaicko/claude-automation-setup";
};
```

### 2. Import the module

```nix
outputs = { nixpkgs, claude-agent, ... }: {
  nixosConfigurations.homeserver = nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    modules = [
      ./hardware-configuration.nix
      claude-agent.nixosModules.default   # <-- add this
      {
        services.claude-agent = {
          enable = true;
          envFile = "/etc/claude-agent/env";  # secrets file (see step 3)
          # Optional overrides (these are the defaults):
          # ollamaModel = "qwen2.5:7b";
          # ollamaAcceleration = "cuda";
          # interval = "15min";
          # maxEmailsPerCycle = 5;
          # approvalExpiryHours = 24;
        };
      }
    ];
  };
};
```

### 3. Create the secrets file

The env file lives outside the Nix store (it contains secrets):

```bash
sudo mkdir -p /etc/claude-agent
sudo tee /etc/claude-agent/env <<'EOF'
WHATSAPP_NOTIFY_NUMBER=+541112345678
# ANTHROPIC_API_KEY=sk-ant-...   # only if MODEL_PROVIDER=anthropic
# MODEL_PROVIDER=ollama           # default
EOF
sudo chmod 400 /etc/claude-agent/env
sudo chown root:root /etc/claude-agent/env
```

### 4. Create data directories and OAuth tokens

```bash
sudo mkdir -p /var/lib/claude-agent/{gmail,calendar,whatsapp}
sudo chown -R claude-agent:claude-agent /var/lib/claude-agent
```

Place your Google OAuth `credentials.json` files:

```bash
sudo cp credentials.json /var/lib/claude-agent/gmail/credentials.json
sudo cp credentials.json /var/lib/claude-agent/calendar/credentials.json
sudo chown claude-agent:claude-agent /var/lib/claude-agent/gmail/credentials.json
sudo chown claude-agent:claude-agent /var/lib/claude-agent/calendar/credentials.json
```

### 5. Fix package hashes (one-time)

Before rebuilding, you need to fill in the real hashes in `nix/whatsapp-mcp.nix`
and (if `mcp` isn't in your nixpkgs) `nix/python-env.nix`.

```bash
# Clone the repo locally to edit hashes
git clone https://github.com/chaicko/claude-automation-setup.git
cd claude-automation-setup

# Get whatsapp-mcp src hash:
nix-prefetch-url --unpack \
  https://github.com/lharries/whatsapp-mcp/archive/main.tar.gz

# Paste the hash into nix/whatsapp-mcp.nix → src.hash

# Get vendorHash: set vendorHash = lib.fakeHash in whatsapp-mcp.nix, then:
nix build .#whatsapp-mcp
# Error output will contain: got: sha256-XXXXX
# Paste that into nix/whatsapp-mcp.nix → vendorHash

# If mcp Python package is needed (check first):
nix eval nixpkgs#python3Packages.mcp.version 2>/dev/null || echo "not in nixpkgs"
# If "not in nixpkgs": get the hash and paste into nix/python-env.nix → src.hash
```

### 6. Rebuild and activate

```bash
sudo nixos-rebuild switch --flake .#homeserver
```

### 7. One-time OAuth + WhatsApp QR scan

The agent runs as a system user, so run the setup command as that user:

```bash
sudo -u claude-agent \
  DATA_DIR=/var/lib/claude-agent \
  HOME=/var/lib/claude-agent \
  /run/current-system/sw/bin/claude-agent --setup
```

This opens Gmail/Calendar OAuth in a browser (or prints a URL) and shows the
WhatsApp QR code. Scan it with your phone: WhatsApp → Linked Devices → Link a Device.

### 8. Verify

```bash
# Check timer status
systemctl status claude-agent.timer

# Run one cycle manually (without waiting for the timer)
sudo systemctl start claude-agent.service

# Watch live logs
journalctl -u claude-agent -f

# Or read the log file
sudo tail -f /var/lib/claude-agent/agent.log
```

---

## Option B — Quick start on a fresh NixOS install (no existing flake)

If your server doesn't have a flake yet:

```bash
# On the server, create a minimal flake-based config
sudo mkdir -p /etc/nixos
cd /etc/nixos

# Create flake.nix
sudo tee flake.nix <<'FLAKE'
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    claude-agent.url = "github:chaicko/claude-automation-setup";
  };

  outputs = { nixpkgs, claude-agent, ... }: {
    nixosConfigurations.homeserver = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ./configuration.nix
        claude-agent.nixosModules.default
        {
          services.claude-agent = {
            enable = true;
            envFile = "/etc/claude-agent/env";
          };
        }
      ];
    };
  };
}
FLAKE

sudo nixos-rebuild switch --flake /etc/nixos#homeserver
```

---

## Useful commands

```bash
# See all agent-related systemd units
systemctl list-units 'claude-agent*'

# Force run now (bypass timer)
sudo systemctl start claude-agent.service

# Check pending actions
sudo cat /var/lib/claude-agent/pending.json | python3 -m json.tool

# Tail audit log
sudo tail -f /var/lib/claude-agent/actions.log

# Update the flake input (pulls latest agent code)
nix flake update claude-agent
sudo nixos-rebuild switch --flake /etc/nixos#homeserver

# Check Ollama model
sudo -u ollama ollama list
```

---

## Secrets management (optional upgrade)

For a more robust setup, manage `/etc/claude-agent/env` with
[sops-nix](https://github.com/Mic92/sops-nix) or
[agenix](https://github.com/ryantm/agenix):

```nix
# Example with sops-nix
sops.secrets."claude-agent-env" = {
  path = "/etc/claude-agent/env";
  owner = "root";
  mode = "0400";
};

services.claude-agent.envFile = config.sops.secrets."claude-agent-env".path;
```

---

## Troubleshooting

**`nix build .#whatsapp-mcp` fails with hash mismatch**
→ Follow step 5 above to get the correct hashes.

**`mcp` Python package not found**
→ Run `nix eval nixpkgs#python3Packages.mcp.version`. If it errors, you need to
fill in the `hash` in `nix/python-env.nix`. Get it with:
`nix-prefetch-url --unpack https://files.pythonhosted.org/packages/source/m/mcp/mcp-<version>.tar.gz`

**OAuth browser prompt doesn't open**
→ The setup command prints a URL. Open it on any machine with a browser, authorize,
and paste the code back. The token is saved to `/var/lib/claude-agent/gmail/token.json`.

**WhatsApp QR scan expires**
→ Re-run `sudo -u claude-agent ... claude-agent --setup` immediately when the QR appears.

**Ollama not using GPU**
→ Check: `sudo systemctl status ollama` and `nvidia-smi`. Ensure `hardware.nvidia`
and `services.ollama.acceleration = "cuda"` are set. May need a reboot after
driver install.

**Agent runs but sends no WhatsApp messages**
→ Check `WHATSAPP_NOTIFY_NUMBER` in `/etc/claude-agent/env` (must be `+<country><number>`).
Check `/var/lib/claude-agent/agent.log` for errors.
