# whatsapp-mcp Go binary — built from source via lharries/whatsapp-mcp
#
# To get the correct hashes after pinning a commit:
#
#   # 1. Find the latest commit hash on GitHub:
#   #    https://github.com/lharries/whatsapp-mcp/commits/main
#
#   # 2. Get the src hash:
#   nix-prefetch-url --unpack \
#     https://github.com/lharries/whatsapp-mcp/archive/<COMMIT>.tar.gz
#
#   # 3. Set vendorHash = lib.fakeHash, then run:
#   nix build .#whatsapp-mcp
#   #    The error will print the correct vendorHash — paste it below.

{ pkgs, lib ? pkgs.lib }:

pkgs.buildGoModule {
  pname = "whatsapp-mcp";
  version = "unstable-2025-01-01";

  src = pkgs.fetchFromGitHub {
    owner = "lharries";
    repo = "whatsapp-mcp";
    # Pin to a specific commit for reproducibility.
    # Replace with the latest commit SHA from:
    # https://github.com/lharries/whatsapp-mcp/commits/main
    rev = "main";
    hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    # ^^^ Replace with output of:
    # nix-prefetch-url --unpack https://github.com/lharries/whatsapp-mcp/archive/main.tar.gz
  };

  # Replace with the real vendor hash after the first failed build:
  #   nix build .#whatsapp-mcp  →  error prints the correct hash
  vendorHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";

  # CGO is required for the SQLite dependency used by whatsmeow
  nativeBuildInputs = [ pkgs.gcc ];
  buildInputs = [ pkgs.sqlite ];
  CGO_ENABLED = "1";

  meta = {
    description = "WhatsApp MCP server (multi-device protocol, bidirectional)";
    homepage = "https://github.com/lharries/whatsapp-mcp";
    mainProgram = "whatsapp-mcp";
  };
}
