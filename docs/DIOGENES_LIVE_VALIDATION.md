# Ɗiogenēs live validation

This is the short operator pass for the canonical checkout.

1. Confirm the application and owned model/service sessions are stopped.
2. Fast-forward or merge the reviewed `dev` source.
3. Run `./uvsetup.sh` when Python requirements changed.
4. Start optional Chroma with `docker compose up -d chromadb`.
5. Start the application with `./startwithuv.sh`.
6. Sign in and inspect **Cookbook**, **Services**, **Active**, and **Settings**.
7. In **Services**, confirm:
   - Docker projects and resources report real Docker state;
   - Camofox, Bifrost, and signal-cli start as owned `bash start.sh` tmux
     sessions and expose individual plus grouped shutdown;
   - dependency actions show their native Git/install/update/integration
     results;
   - completed command output can be scrolled, jumped to the latest entry, and
     hidden from the current browser;
   - Skills auditor separates Hermes prompt-active skills from Retrieval’s
     indexed library.
8. In **Cookbook**, confirm native engines expose independent source, model,
   build, profile, editable command, launch, and stop flows.
9. Launch at most one GPU engine at a time and inspect its health endpoint
   before attaching an agent.

The expected browser backend is Camofox. Playwright is not registered as an
implicit built-in MCP. Sandwich reports Bun compatibility without requiring a
system Node, npm, pnpm, or yarn installation.

All user settings, databases, auth state, caches, and runtime logs remain under
ignored local paths in this checkout. A source rollback is a normal Git
operation; it must not delete `.env`, `.venv`, `data/`, model caches, service
configuration, or Docker volumes.
