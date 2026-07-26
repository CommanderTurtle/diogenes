# Ɗiogenēs release validation

This is the operator checklist for a reviewed runtime copy. It deliberately
contains no host names, process IDs, benchmark claims, or historical machine
state.

## Before switchover

1. Commit the development checkout on `dev`.
2. Fetch `upstream/dev` and confirm that it is an ancestor of the candidate.
3. Run `scripts/diogenes-deploy inspect`; resolve every blocked item.
4. Prepare the sibling `Diogenes-prod` once with `scripts/diogenes-deploy
   prepare`; use `scripts/diogenes-deploy update` for later fast-forwards.
5. Run `./uvsetup.sh` for the initial runtime environment. Start Chroma
   separately with `docker compose up -d chromadb` only when it is wanted;
   source updates never recreate it.
6. Run the static, focused, and full validation commands reported by the
   release commit.

The live application, model server, Docker services, and Hermes gateway remain
unchanged throughout these steps.

## Maintenance window

Only after the candidate is ready:

1. stop the existing application and model tmux sessions;
2. stop or migrate any Compose workload whose host ports would conflict;
3. start Ɗiogenēs manually from `Diogenes-prod`;
4. sign in and inspect **Cookbook**, **Services**, **Active**, and **Settings**;
5. create and inspect lifecycle plans before executing them;
6. launch exactly one model engine and validate its health endpoint before
   starting dependent agents.

Provider builds and model downloads are independent operations. A source
checkout, CUDA build, and model artifact must all report ready before a Colibri
or Prism launch is offered.

## Required observations

- The web UI binds only to the address selected by the operator.
- No implicit Playwright server is registered; Camofox is the default browser
  backend when configured.
- Sandwich reports Bun and its compatibility commands as ready without a
  system Node, npm, pnpm, or yarn dependency.
- Managed services expose their real state: tools are not labelled stopped,
  disabled integrations are not labelled failed, and crashed jobs remain
  visible as failed.
- Chroma data stays inside the runtime tree's configured data directory.
- Hermes, Librarian, Retrieval, and MCP registries remain separate from the
  Ɗiogenēs agent registry.
- Configuration writes are confirmation-gated, atomic, and scoped to catalogued
  project files.

## Rollback

Stop the candidate and restart the previous runtime tree. Do not delete the
previous `.env`, `.venv`, or `data/` until the operator has accepted the new
deployment. `scripts/diogenes-deploy` never removes or overwrites an existing
runtime tree.
