# NixOS module for the Claude Automation Agent.
#
# Usage in your NixOS flake:
#
#   inputs.claude-agent.url = "github:chaicko/claude-automation-setup";
#
#   outputs = { nixpkgs, claude-agent, ... }: {
#     nixosConfigurations.myserver = nixpkgs.lib.nixosSystem {
#       modules = [
#         claude-agent.nixosModules.default
#         {
#           services.claude-agent = {
#             enable = true;
#             envFile = "/run/secrets/claude-agent-env";
#           };
#         }
#       ];
#     };
#   };

{ config, lib, pkgs, ... }:

let
  cfg = config.services.claude-agent;

  # Build the packages inline so the module is self-contained
  # (can be overridden via cfg.package / cfg.whatsappMcpPackage)
  defaultPythonEnv = pkgs.callPackage ./python-env.nix { };
  defaultWhatsappMcp = pkgs.callPackage ./whatsapp-mcp.nix { };
in
{
  # ---------------------------------------------------------------------------
  # Options
  # ---------------------------------------------------------------------------
  options.services.claude-agent = {

    enable = lib.mkEnableOption "Claude Automation Agent";

    user = lib.mkOption {
      type = lib.types.str;
      default = "claude-agent";
      description = "System user the agent runs as.";
    };

    group = lib.mkOption {
      type = lib.types.str;
      default = "claude-agent";
      description = "System group the agent runs as.";
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/lib/claude-agent";
      description = ''
        Directory for OAuth tokens, WhatsApp session, pending actions, and logs.
        Not in the Nix store — persists across rebuilds.
      '';
    };

    envFile = lib.mkOption {
      type = lib.types.path;
      description = ''
        Path to a file containing secret environment variables.
        Must contain at least WHATSAPP_NOTIFY_NUMBER.
        Optionally ANTHROPIC_API_KEY if MODEL_PROVIDER=anthropic.
        See .env.example in the repo.

        Recommended: use agenix or sops-nix to manage this file.
        Quick start: write it manually to /etc/claude-agent/env (mode 0400, root:root).
      '';
      example = "/etc/claude-agent/env";
    };

    interval = lib.mkOption {
      type = lib.types.str;
      default = "15min";
      description = "How often to run the agent (systemd OnUnitActiveSec value).";
    };

    ollamaModel = lib.mkOption {
      type = lib.types.str;
      default = "qwen2.5:7b";
      description = "Ollama model to pull and use for inference.";
    };

    ollamaAcceleration = lib.mkOption {
      type = lib.types.nullOr (lib.types.enum [ "cuda" "rocm" ]);
      default = "cuda";
      description = ''
        GPU acceleration backend for Ollama.
        Use "cuda" for NVIDIA (GTX 1060), "rocm" for AMD, null for CPU-only.
      '';
    };

    maxEmailsPerCycle = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "Max emails to process per agent cycle.";
    };

    approvalExpiryHours = lib.mkOption {
      type = lib.types.int;
      default = 24;
      description = "Hours before a pending WhatsApp approval expires.";
    };

    enablePlaywright = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable Playwright MCP server for web tasks.";
    };

    package = lib.mkOption {
      type = lib.types.package;
      default = defaultPythonEnv;
      description = "The claude-agent Python package (override to use a local build).";
    };

    whatsappMcpPackage = lib.mkOption {
      type = lib.types.package;
      default = defaultWhatsappMcp;
      description = "The whatsapp-mcp binary package.";
    };

  };

  # ---------------------------------------------------------------------------
  # Implementation
  # ---------------------------------------------------------------------------
  config = lib.mkIf cfg.enable {

    # --- Ollama local LLM ---------------------------------------------------
    services.ollama = {
      enable = true;
      acceleration = cfg.ollamaAcceleration;
      # Ollama listens on localhost:11434 by default
    };

    # Pull the model once after Ollama starts (idempotent — ollama pull is a no-op if present)
    systemd.services.claude-agent-model-pull = {
      description = "Pull Ollama model for Claude agent";
      after = [ "ollama.service" ];
      requires = [ "ollama.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.ollama}/bin/ollama pull ${cfg.ollamaModel}";
        Environment = "OLLAMA_HOST=http://localhost:11434";
        # Run as root is fine for model pull; model stored in ollama's state dir
      };
    };

    # --- System user & group ------------------------------------------------
    users.users.${cfg.user} = {
      isSystemUser = true;
      group = cfg.group;
      home = cfg.dataDir;
      createHome = false; # tmpfiles handles this
      description = "Claude Automation Agent service user";
    };
    users.groups.${cfg.group} = { };

    # --- Data directories ---------------------------------------------------
    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir}           0750 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataDir}/gmail     0750 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataDir}/calendar  0750 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataDir}/whatsapp  0750 ${cfg.user} ${cfg.group} -"
      "d ${cfg.dataDir}/.npm      0750 ${cfg.user} ${cfg.group} -"
    ];

    # --- Agent systemd service (oneshot, triggered by timer) ----------------
    systemd.services.claude-agent = {
      description = "Claude Automation Agent — single cycle";
      after = [ "network-online.target" "ollama.service" "claude-agent-model-pull.service" ];
      wants = [ "network-online.target" ];
      requires = [ "ollama.service" ];

      serviceConfig = {
        Type = "oneshot";
        User = cfg.user;
        Group = cfg.group;

        # Load secrets from the env file (not in the Nix store)
        EnvironmentFile = cfg.envFile;

        # Non-secret environment (safe to be in the store / journal)
        Environment = [
          "DATA_DIR=${cfg.dataDir}"
          "OLLAMA_BASE_URL=http://localhost:11434/v1"
          "OLLAMA_MODEL=${cfg.ollamaModel}"
          "WHATSAPP_MCP_BIN=${cfg.whatsappMcpPackage}/bin/whatsapp-mcp"
          "MAX_EMAILS_PER_CYCLE=${toString cfg.maxEmailsPerCycle}"
          "APPROVAL_EXPIRY_HOURS=${toString cfg.approvalExpiryHours}"
          "ENABLE_PLAYWRIGHT=${if cfg.enablePlaywright then "true" else "false"}"
          # Writable home for npx cache (Gmail/Calendar MCP servers use npx)
          "HOME=${cfg.dataDir}"
          "npm_config_cache=${cfg.dataDir}/.npm"
          # Ensure Node.js binaries are available in PATH for npx
          "PATH=${lib.makeBinPath [ pkgs.nodejs_20 pkgs.coreutils ]}:/run/current-system/sw/bin"
        ];

        ExecStart = "${cfg.package}/bin/claude-agent";

        # Safety limits
        TimeoutStartSec = "5min";
        MemoryMax = "2G";
        PrivateTmp = true;
        NoNewPrivileges = true;

        # Restart on failure but not on clean exit (oneshot pattern)
        Restart = "on-failure";
        RestartSec = "30s";
      };
    };

    # --- Timer (every N minutes) --------------------------------------------
    systemd.timers.claude-agent = {
      description = "Run Claude Automation Agent periodically";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2min";           # first run 2 min after boot
        OnUnitActiveSec = cfg.interval;
        AccuracySec = "30s";
        Persistent = true;            # catch up missed runs after sleep/reboot
      };
    };

    # --- Playwright Chromium (optional) -------------------------------------
    environment.systemPackages = lib.optionals cfg.enablePlaywright [
      pkgs.playwright-driver.browsers
    ];

  };
}
