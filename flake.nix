{
  description = "Claude Automation Agent — background email/calendar agent with WhatsApp approvals";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # Pin a stable nixpkgs for reproducibility — update with `nix flake update`
  };

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      # -----------------------------------------------------------------------
      # NixOS module — import this in your configuration.nix or flake
      # -----------------------------------------------------------------------
      nixosModules.default = import ./nix/module.nix;
      # Alias for explicitness
      nixosModules.claude-agent = import ./nix/module.nix;

      # -----------------------------------------------------------------------
      # Buildable packages (useful for `nix build`, CI, inspection)
      # -----------------------------------------------------------------------
      packages.${system} = {
        # whatsapp-mcp Go binary
        whatsapp-mcp = pkgs.callPackage ./nix/whatsapp-mcp.nix { };

        # Python interpreter + agent dependencies, wrapped as a runnable script
        claude-agent = pkgs.callPackage ./nix/python-env.nix { };

        # Convenience: build both
        default = self.packages.${system}.claude-agent;
      };

      # -----------------------------------------------------------------------
      # Dev shell — for working on the agent code on any machine
      # `nix develop` drops you into a shell with all deps available
      # -----------------------------------------------------------------------
      devShells.${system}.default = pkgs.mkShell {
        name = "claude-agent-dev";
        packages = with pkgs; [
          # Python with all agent deps
          (self.packages.${system}.claude-agent)
          # Node.js for running MCP servers manually during development
          nodejs_20
          # Go (for building/modifying whatsapp-mcp)
          go
          # Useful dev tools
          python3Packages.ipython
          ollama
        ];
        shellHook = ''
          echo "Claude Automation Agent dev shell"
          echo "  Agent:   python agent/claude-agent.py --help"
          echo "  Ollama:  ollama serve  (in another terminal)"
          echo "  Docs:    docs/"
          [ -f .env ] || cp .env.example .env && echo "  Created .env from template — fill in your values"
        '';
      };
    };
}
