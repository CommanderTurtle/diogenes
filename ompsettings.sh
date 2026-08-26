#!/usr/bin/env bash
# Run this to apply an optimized JSON baseline to OMP only if all backends are installed.
# It only needs to be run once. Check `omp` > `/settings` afterward for verification.
#
# This script is intentionally NOT called by Diogenes Integrate. It changes OMP
# preferences only when a user runs it and confirms the operation.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./ompsettings.sh [--yes]

Apply CommanderTurtle's optimized, sovereign OMP settings baseline through
OMP's native configuration interface. This does not change models.yml,
mcp.json, credentials, sessions, or project profiles.

  --yes   Skip the interactive confirmation.
  -h      Show this help.
EOF
}

assume_yes=false
case "${1:-}" in
  "") ;;
  --yes) assume_yes=true ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

for command_name in omp bun; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'Required command is unavailable: %s\n' "$command_name" >&2
    exit 1
  fi
done

config_root="$(omp config path)"
config_file="$config_root/config.yml"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
work_dir="$(mktemp -d)"
baseline_file="$work_dir/omp-baseline.json"
schema_file="$work_dir/omp-schema.json"
entries_file="$work_dir/omp-entries.tsv"
backup_file=""
had_config=false
apply_started=false

cleanup() {
  rm -rf -- "$work_dir"
}

rollback() {
  local exit_code=$?
  if [[ "$apply_started" == true ]]; then
    if [[ "$had_config" == true && -n "$backup_file" && -f "$backup_file" ]]; then
      cp -- "$backup_file" "$config_file"
      printf '\nOMP rejected a setting. Restored %s from %s\n' "$config_file" "$backup_file" >&2
    elif [[ "$had_config" == false ]]; then
      rm -f -- "$config_file"
      printf '\nOMP rejected a setting. Removed the partially created %s\n' "$config_file" >&2
    fi
  fi
  cleanup
  exit "$exit_code"
}

trap rollback ERR
trap cleanup EXIT

cat >"$baseline_file" <<'JSON'
{
  "power.sleepPrevention": "off",
  "modelRoles": {
    "default": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "smol": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "slow": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "vision": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "plan": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "designer": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "commit": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "tiny": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "task": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym",
    "advisor": "vllm/compute1/Agents-A1-GPTQ-INT4-Sym"
  },
  "symbolPreset": "unicode",
  "theme.dark": "dark-tundra",
  "defaultThinkingLevel": "high",
  "temperature": 0.85,
  "topP": 0.95,
  "topK": 20,
  "minP": 0,
  "presencePenalty": 1.1,
  "repetitionPenalty": 1,
  "followUpMode": "all",
  "treeFilterMode": "no-tools",
  "emojiAutocomplete": false,

  "advisor.enabled": true,
  "advisor.syncBacklog": "1",
  "advisor.immuneTurns": 3,
  "prewalk.enabled": false,

  "compaction.enabled": true,
  "compaction.midTurnEnabled": true,
  "compaction.methodOrder": ["snapcompact", "soft"],
  "compaction.remoteStreamingV2Enabled": false,
  "compaction.keepRecentTokens": 20000,
  "compaction.autoContinue": true,
  "compaction.v2RetainedMessageBudget": 64000,
  "compaction.idleEnabled": true,
  "compaction.idleThresholdTokens": 100000,
  "compaction.idleTimeoutSeconds": 300,
  "compaction.supersedeReads": true,
  "compaction.dropUseless": true,
  "snapcompact.systemPrompt": "none",
  "snapcompact.toolResults": true,
  "snapcompact.shape": "auto",
  "branchSummary.enabled": true,
  "branchSummary.reserveTokens": 16384,

  "memory.backend": "mnemopi",
  "mnemopi.scoping": "per-project",
  "mnemopi.autoRecall": true,
  "mnemopi.autoRetain": true,
  "mnemopi.polyphonicRecall": false,
  "mnemopi.enhancedRecall": true,
  "mnemopi.proactiveLinking": false,
  "mnemopi.noEmbeddings": false,
  "mnemopi.embeddingVariant": "en",
  "mnemopi.llmMode": "smol",
  "mnemopi.retainEveryNTurns": 4,
  "mnemopi.recallLimit": 6,
  "mnemopi.recallContextTurns": 3,
  "mnemopi.recallMaxQueryChars": 4000,
  "mnemopi.injectionTokenLimit": 2000,

  "task.isolation.mode": "auto",
  "task.isolation.apply": true,
  "task.isolation.merge": "patch",
  "task.isolation.commits": "ai",
  "task.eager": "preferred",
  "task.batch": true,
  "task.enableEffort": false,
  "task.maxConcurrency": 7,
  "task.enableLsp": true,
  "task.maxRecursionDepth": 1,
  "task.maxRuntimeMs": 0,
  "task.agentIdleTtlMs": 420000,
  "task.softRequestBudget": 200,
  "task.softRequestBudgetNotice": true,
  "task.maxEffort": "max",
  "task.disabledAgents": [],
  "task.agentModelOverrides": {},
  "task.agentPrewalk": {},
  "task.agentAdvisor": {"task": "off"},
  "task.prewalk": false,
  "tasks.todoClearDelay": 300,

  "tools.approvalMode": "yolo",
  "tools.xdev": true,
  "tools.xdevDocs": "builtins",
  "tools.xdevInlineDevices": [],
  "tools.format": "auto",
  "tools.intentTracing": true,
  "tools.abortOnFabricatedResult": true,
  "tools.maxTimeout": 0,
  "tools.artifactSpillThreshold": 30,
  "tools.artifactTailBytes": 10,
  "tools.artifactHeadBytes": 10,
  "tools.artifactTailLines": 500,
  "tools.outputMaxColumns": 768,
  "terminal.showImages": true,
  "terminal.showProgress": true,
  "tui.renderMermaid": true,
  "tui.hyperlinks": "always",
  "display.shimmer": "disabled",
  "display.smoothStreaming": true,
  "display.showTokenUsage": true,
  "display.collapseCompacted": true,

  "ttsr.enabled": true,
  "ttsr.contextMode": "discard",
  "ttsr.interruptMode": "always",
  "ttsr.repeatMode": "after-gap",
  "ttsr.repeatGap": 10,
  "ttsr.builtinRules": true,
  "edit.mode": "hashline",
  "edit.fuzzyMatch": true,
  "edit.fuzzyThreshold": 0.95,
  "edit.streamingAbort": false,
  "edit.blockAutoGenerated": true,
  "edit.enforceSeenLines": true,
  "read.defaultLimit": 300,
  "read.renderMarkdown": true,
  "read.summarize.enabled": true,
  "read.summarize.prose": false,
  "read.summarize.minBodyLines": 4,
  "read.summarize.minCommentLines": 6,
  "read.summarize.minTotalLines": 100,
  "read.summarize.unfoldUntil": 50,
  "read.summarize.unfoldLimit": 100,
  "lsp.enabled": true,
  "lsp.lazy": true,
  "lsp.shared": true,
  "lsp.formatOnWrite": false,
  "lsp.diagnosticsOnWrite": true,
  "lsp.diagnosticsOnEdit": true,
  "lsp.diagnosticsDeduplicate": true,
  "bash.enabled": true,
  "bash.autoBackground.enabled": true,
  "bash.autoBackground.thresholdMs": 60000,
  "bashInterceptor.enabled": true,
  "bash.direnv": "auto",
  "bash.direnvLoadTimeoutMs": 30000,
  "eval.py": true,
  "eval.js": true,
  "eval.rb": true,
  "eval.jl": false,
  "python.kernelMode": "session",
  "python.interpreter": "__HOME__/.venv/bin/python",
  "ruby.interpreter": "/usr/bin/ruby",

  "todo.enabled": true,
  "todo.reminders": true,
  "todo.remindersMax": 3,
  "todo.eager": "preferred",
  "astGrep.enabled": true,
  "astEdit.enabled": true,
  "debug.enabled": true,
  "launch.enabled": true,
  "speechgen.enabled": true,
  "checkpoint.enabled": true,
  "ask.enabled": true,
  "async.enabled": true,
  "async.maxJobs": 100,
  "async.pollWaitDuration": "smart",
  "plan.enabled": true,
  "plan.defaultOnStartup": false,
  "goal.enabled": true,
  "goal.statusInFooter": true,
  "goal.continuationModes": ["interactive"],
  "title.refreshOnReplan": true,
  "features.unexpectedStopDetection": true,

  "skills.enabled": true,
  "skills.enableSkillCommands": true,
  "skills.customDirectories": [
    "__HOME__/Hermes/retrieval/skills",
    "__HOME__/Hermes/persephone/skills",
    "__HOME__/repos/firecrawl-anydoc/skills"
  ],
  "skills.ignoredSkills": [],
  "skills.includeSkills": [],
  "commands.enableClaudeProject": true,
  "commands.enableClaudeUser": false,
  "commands.enableOpencodeProject": true,
  "commands.enableOpencodeUser": false,
  "secrets.enabled": true,

  "providers.maxInFlightRequests": {"vllm": 8},
  "providers.fetch": "native",
  "providers.webSearchOrder": [],
  "providers.webSearchExclude": [
    "perplexity", "gemini", "anthropic", "codex", "xai", "zai", "exa",
    "tinyfish", "jina", "kagi", "tavily", "firecrawl", "brave", "kimi",
    "parallel", "synthetic", "searxng", "startpage", "duckduckgo",
    "ecosia", "google", "mojeek", "public"
  ],
  "providers.webSearchTimeoutSeconds": 60,
  "providers.imageOrder": [],
  "providers.openaiWebsockets": "auto",
  "provider.appendOnlyContext": "auto",
  "providers.unexpectedStopModel": "online",
  "providers.anthropic.serverSideFallback": false,
  "providers.ollama-cloud.maxConcurrency": 0,
  "exa.enabled": false,

  "startup.checkUpdate": false,
  "marketplace.autoUpdate": "off",
  "retry.enabled": true,
  "retry.maxRetries": 10,
  "retry.baseDelayMs": 500,
  "retry.maxDelayMs": 300000,
  "retry.modelFallback": false,
  "retry.usageAwareFallback": false,
  "retry.usageReservePct": 10,
  "retry.usageReservePolicy": "confirm",
  "retry.fallbackChains": {},
  "retry.fallbackRevertPolicy": "cooldown-expiry",

  "browser.enabled": false,
  "browser.headless": true,
  "browser.relay": false,
  "browser.cmux": false,
  "fetch.enabled": false,
  "web_search.enabled": false,
  "generate_image.enabled": false,
  "inspect_image.enabled": false,
  "inspect_image.mode": "auto",
  "inspect_image.timeoutMs": 300000,
  "computer.enabled": false,
  "github.enabled": false,
  "vault.enabled": false,
  "security.enabled": false,
  "mcp.enableProjectConfig": false,
  "mcp.renderMarkdownResults": true,
  "mcp.notifications": false,
  "mcp.notificationDebounceMs": 500,

  "stt.enabled": true,
  "providers.tts": "local",
  "tts.localModel": "kokoro",
  "tts.localVoice": "af_heart",
  "speech.enabled": false,
  "speech.mode": "yield",
  "speech.enhanced": true,
  "speech.voice": "af_heart",
  "share.serverUrl": "http://127.0.0.1:65535/omp-share-disabled"
}
JSON

omp config list --json >"$schema_file"

HOME="$HOME" bun -e '
  const baselinePath = process.argv[2];
  const schemaPath = process.argv[3];
  const baseline = JSON.parse(await Bun.file(baselinePath).text());
  const schema = JSON.parse(await Bun.file(schemaPath).text());
  const missing = Object.keys(baseline).filter((key) => !(key in schema));
  if (missing.length) {
    console.error("This OMP release does not recognize these baseline settings:");
    for (const key of missing) console.error(`  - ${key}`);
    console.error("No settings were changed. Update OMP or review ompsettings.sh.");
    process.exit(1);
  }
' "$baseline_file" "$schema_file"

HOME="$HOME" bun -e '
  const baseline = JSON.parse(await Bun.file(process.argv[2]).text());
  const home = process.env.HOME;
  const expand = (value) => {
    if (typeof value === "string") return value.replaceAll("__HOME__", home);
    if (Array.isArray(value)) return value.map(expand);
    if (value && typeof value === "object") {
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, expand(item)]));
    }
    return value;
  };
  for (const [key, original] of Object.entries(baseline)) {
    const value = expand(original);
    const encoded = typeof value === "string" ? value : JSON.stringify(value);
    process.stdout.write(`${key}\t${encoded}\n`);
  }
' "$baseline_file" >"$entries_file"

setting_count="$(wc -l <"$entries_file")"
printf 'OMP configuration root: %s\n' "$config_root"
printf 'Validated baseline settings: %s\n' "$setting_count"
printf 'External Camofox, Firecrawl, Retrieval, Librarian, and Persephone lanes must already be installed.\n'
printf 'This baseline also enables OMP yolo approval mode.\n'

if [[ "$assume_yes" != true ]]; then
  printf 'Apply CommanderTurtle\047s optimized OMP baseline? [y/N] '
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) printf 'No settings were changed.\n'; exit 0 ;;
  esac
fi

mkdir -p -- "$config_root"
if [[ -f "$config_file" ]]; then
  had_config=true
  backup_file="$config_file.$timestamp.bak"
  cp -- "$config_file" "$backup_file"
  printf 'Backup: %s\n' "$backup_file"
fi

apply_started=true
while IFS=$'\t' read -r setting_key setting_value; do
  omp config set "$setting_key" "$setting_value" --json >/dev/null
done <"$entries_file"
apply_started=false

trap - ERR
printf '\nApplied %s OMP settings through the native configuration interface.\n' "$setting_count"
printf 'Open omp, run /settings, and verify the result.\n'
