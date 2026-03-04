# Python environment for the Claude agent.
# Produces a derivation with a `bin/claude-agent` wrapper script.
#
# The `mcp` package (Anthropic MCP Python SDK) may or may not be in your
# nixpkgs snapshot. This file tries pkgs.python3Packages.mcp first, and
# falls back to building it from PyPI if absent.

{ pkgs, lib ? pkgs.lib }:

let
  # ---------------------------------------------------------------------------
  # mcp Python package — build from PyPI if not already in nixpkgs
  # Check with: nix eval nixpkgs#python3Packages.mcp.version
  # ---------------------------------------------------------------------------
  mcpPackage =
    if pkgs.python3Packages ? mcp
    then pkgs.python3Packages.mcp
    else
      pkgs.python3Packages.buildPythonPackage rec {
        pname = "mcp";
        version = "1.9.0";
        pyproject = true;

        src = pkgs.fetchPypi {
          inherit pname version;
          hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
          # ^^^ Run this to get the real hash:
          # nix-prefetch-url --unpack https://files.pythonhosted.org/packages/source/m/mcp/mcp-1.9.0.tar.gz
        };

        build-system = with pkgs.python3Packages; [ hatchling ];

        propagatedBuildInputs = with pkgs.python3Packages; [
          anyio
          httpx
          pydantic
          starlette
          uvicorn
          sse-starlette
          httpx-sse
          python-multipart
        ];

        # Skip tests (network-dependent)
        doCheck = false;
      };

  # ---------------------------------------------------------------------------
  # Python interpreter with all agent dependencies
  # ---------------------------------------------------------------------------
  pythonEnv = pkgs.python3.withPackages (ps: [
    ps.openai          # OpenAI-compatible client (used for both Ollama and Anthropic)
    ps.python-dotenv   # .env file loading
    mcpPackage         # MCP Python SDK (subprocess management)
  ]);

  # ---------------------------------------------------------------------------
  # Wrapped script: python claude-agent.py, with Node.js in PATH for npx
  # ---------------------------------------------------------------------------
in
pkgs.stdenv.mkDerivation {
  pname = "claude-agent";
  version = "1.0.0";

  # Copy the agent source from the repo
  src = ../agent;

  nativeBuildInputs = [ pkgs.makeWrapper ];

  installPhase = ''
    runHook preInstall

    # Install agent source
    mkdir -p $out/agent
    cp -r . $out/agent/

    # Create wrapper script
    mkdir -p $out/bin
    makeWrapper ${pythonEnv}/bin/python $out/bin/claude-agent \
      --add-flags "$out/agent/claude-agent.py" \
      --prefix PATH : ${lib.makeBinPath [ pkgs.nodejs_20 pkgs.coreutils ]}

    runHook postInstall
  '';

  meta = {
    description = "Claude Automation Agent — email/calendar background agent";
    mainProgram = "claude-agent";
  };
}
