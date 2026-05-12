{
  description = "Development shell for k8s-guideline-bench";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-25.11-darwin";
  };

  outputs =
    { self, nixpkgs }:
    let
      system = "aarch64-darwin";
      pkgs = import nixpkgs { inherit system; };
      quietClaude = pkgs.writeShellApplication {
        name = "claude";
        text = ''
          real_claude="''${REAL_CLAUDE:-}"
          profile_claude="/etc/profiles/per-user/$USER/bin/claude"
          if [ -z "$real_claude" ] && [ -x "$profile_claude" ]; then
            real_claude="$profile_claude"
          fi

          if [ -z "$real_claude" ]; then
            IFS=: read -r -a path_entries <<< "$PATH"
            for path_entry in "''${path_entries[@]}"; do
              candidate="$path_entry/claude"
              if [ -x "$candidate" ] && [ "$candidate" != "$0" ] && [[ "$candidate" != /Applications/cmux.app/* ]]; then
                real_claude="$candidate"
                break
              fi
            done
          fi

          if [ -z "$real_claude" ]; then
            echo "Could not find the real claude CLI outside the quiet wrapper." >&2
            exit 127
          fi

          mkdir -p "$PWD/.claude-home"
          export HOME="$PWD/.claude-home"
          exec "$real_claude" "$@"
        '';
      };
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [
          quietClaude
          commitlint
          lefthook
          uv
        ];

        env = {
          UV_MANAGED_PYTHON = "1";
        };

        shellHook = ''
          if [ -d .venv/bin ]; then
            export PATH="$PWD/.venv/bin:$PATH"
          fi
        '';
      };
    };
}
