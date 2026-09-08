# src/deep_research.py
"""
IterResearch-style deep research engine.

Implements an iterative Think→Search→Extract→Synthesize loop where the LLM
drives every decision: what to search, what's relevant, what's missing, and
when to stop.  Inspired by Alibaba's IterResearch approach.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set
from urllib.parse import unquote, urlparse

from src.research_utils import strip_thinking, is_low_quality

from src.goal_based_extractor import EXTRACTOR_SYSTEM
from src.prompt_security import untrusted_context_message

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r'https?://[^\s<>"\'`]+', re.IGNORECASE)


def _extract_explicit_urls(text: str) -> List[str]:
    """Return deduplicated public URL strings embedded in a research prompt."""
    urls: List[str] = []
    seen: Set[str] = set()
    for match in _URL_PATTERN.finditer(text or ""):
        candidate = match.group(0)
        # Keep balanced URL delimiters (notably IPv6 brackets/parenthesized
        # paths), but leave prose punctuation and unmatched Markdown closers
        # outside the URL sent to Firecrawl.
        while candidate:
            last = candidate[-1]
            if last in ".,;:!?":
                candidate = candidate[:-1]
                continue
            pairs = {")": "(", "]": "[", "}": "{"}
            opener = pairs.get(last)
            if opener and candidate.count(last) > candidate.count(opener):
                candidate = candidate[:-1]
                continue
            break
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def current_date_context() -> str:
    """Preamble that grounds query-generation/planning LLMs in the real current
    date. Without it the model falls back to its training-cutoff year and emits
    queries like "best Python tutorials 2025" when the year is actually 2026.
    System TZ-local so it matches what the user sees. Portable strftime only."""
    now = datetime.now().astimezone()
    return (
        f"Today's date is {now.strftime('%B %d, %Y')} ({now.strftime('%Y-%m-%d')}). "
        f"When a search query needs a year or refers to 'latest'/'current'/"
        f"'this year', use {now.strftime('%Y')} or relative wording — never a "
        f"year inferred from training data.\n\n"
    )

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
RESEARCH_PLAN_PROMPT = """\
You are a research strategist. Before searching, analyze this question and create a research plan.

**Question:** {question}

Break this question down:
1. What are the key sub-topics that need to be covered for a comprehensive answer?
2. What specific data points, facts, or perspectives should we look for?
3. What would a complete, high-quality answer include?

Return a JSON object with:
- "sub_questions": Array of 3-6 specific sub-questions to investigate
- "key_topics": Array of key topics/angles to cover
- "success_criteria": One sentence describing what a complete answer looks like

Example:
{{
  "sub_questions": ["What is the cost of living in X?", "How is the healthcare system?"],
  "key_topics": ["economy", "healthcare", "safety", "culture"],
  "success_criteria": "A balanced comparison covering cost, quality of life, and practical considerations."
}}
"""

QUERY_GEN_PROMPT = """\
You are a research assistant planning web searches.

**Original question:** {question}

**Research plan:**
{research_plan}

**What we know so far:**
{report}

**Round:** {round_num}

Generate {num_queries} focused search queries that will help answer the question.
{round_instruction}

Return ONLY a JSON array of query strings, nothing else.
Example: ["query one", "query two", "query three"]
"""

SYNTHESIZE_PROMPT = """\
You are updating an evolving research report.

**Original question:** {question}

**Current report:**
{report}

**New findings from this round:**
{new_findings}

Integrate the new findings into the existing report. Produce an updated, well-organized \
report that answers the original question as completely as possible given all evidence so far. \
Remove redundancy, resolve contradictions, and maintain logical flow. \
Keep source URLs as inline citations where relevant.

Write only the updated report — no preamble or meta-commentary.
"""

STOP_PROMPT = """\
You are deciding whether a research report is comprehensive enough.

**Original question:** {question}

**Current report:**
{report}

**Rounds completed:** {round_num} of {max_rounds}

Based on the report so far, do we have enough information to answer the question \
comprehensively?  Consider:
- Are the key aspects of the question addressed?
- Are there obvious gaps or unanswered sub-questions?
- Is the evidence sufficient and from multiple sources?

If rounds completed is well below the target, prefer continuing unless the \
report is already exhaustive.

Reply with ONLY "YES" or "NO" followed by a brief one-sentence reason.
Example: "YES — The report covers all major aspects with evidence from multiple sources."
Example: "NO — We still lack information about the economic impact."
"""

FINAL_REPORT_PROMPT = """\
Write a **long, detailed, comprehensive** research report answering this question:

**Question:** {question}

**All collected evidence and analysis:**
{report}

Requirements:
- Write at MINIMUM 1500 words — this should be a thorough, magazine-quality article
- Use clear ## headings and ### subheadings to organize into logical sections
- Each section should have multiple detailed paragraphs, not just bullet points
- Synthesize and analyze the information — explain WHY things matter, draw comparisons, provide context
- Include specific data points, numbers, and statistics from the evidence
- Include source URLs as inline citations [like this](url)
- Note where sources agree and where they disagree
- Add a brief executive summary at the top
- End with a clear conclusion that directly answers the question
- Write in an engaging, informative style — not dry or robotic
"""

ARXIV_MODE_PROMPT = """\
DOCUMENT MODE — ARXIV-STYLE PAPER
- Write source Markdown for a publication-quality scholarly paper, not a magazine article.
- Use this order where applicable: title, author/affiliation lines only when supplied by the user,
  Abstract, Keywords, numbered main sections and subsections, limitations, conclusion, and References.
- Never invent an author, affiliation, experiment, measurement, dataset, citation, or result.
- Preserve mathematical notation as valid LaTeX using $...$ and $$...$$. Put diagrams in
  fenced ```mermaid blocks. Give every figure, table, equation, and algorithm a caption or label.
- Cite evidence numerically in the prose and keep a matching numbered References section with URLs.
- Sustain a complete 4,000–5,000 word paper when that scope is requested; do not collapse a
  long-form request into an abstract-length summary or pad beyond what the evidence supports.
- Treat the Current report as the published draft so far: review the whole draft, preserve sound
  passages, integrate new evidence in place, repair cross-references, and return the complete paper.
"""

NOVEL_FICTION_PROMPT = """\
DOCUMENT MODE — FICTION STORY
- Write polished continuous narrative, not a research report or outline.
- Build coherent chapters and scenes with purposeful prose, dialogue, pacing, character arcs,
  setting, viewpoint, and continuity. Do not invent citations or append a sources section.
- Sustain a complete 4,000–5,000 word manuscript when that scope is requested; do not replace
  long-form narrative with a synopsis, outline, or commentary about what remains to be written.
- Treat supplied drafts and visual references as canon unless the user asks to change them.
- Treat the Current report as the manuscript so far: review it as a whole, preserve its voice,
  reconcile continuity, and return the complete revised manuscript after each pass.
"""

NOVEL_NONFICTION_PROMPT = """\
DOCUMENT MODE — NONFICTION STORY
- Write rigorous narrative nonfiction in chapters and scenes, not a generic research report.
- Use a strong narrative through-line while keeping every factual claim grounded. Never invent
  dialogue, thoughts, chronology, people, places, or events; label uncertainty honestly.
- Use unobtrusive inline citations and a Sources / Notes section where verification matters.
- Sustain a complete 4,000–5,000 word manuscript when that scope is requested; do not replace
  long-form narrative with a synopsis, outline, or commentary about what remains to be written.
- Treat supplied drafts and visual references as source material and the Current report as the
  manuscript so far: preserve its voice, reconcile continuity, and return the complete revision.
"""

CATEGORY_PROMPTS = {
    "product": """IMPORTANT FORMAT OVERRIDE — this is a PRODUCT research report:
- Structure as a RANKED LIST of products/options (best first)
- For EACH product include: name as ### heading, approximate price, 2-3 sentence summary, **Pros:** bullet list, **Cons:** bullet list, **Where to buy:** URLs as links
- Start with a quick-compare markdown table of top picks (columns: Name, Price, Best For, Rating)
- End with a ## Verdict section picking Best Overall and Best Value
- Still include source citations inline""",

    "comparison": """IMPORTANT FORMAT OVERRIDE — this is a COMPARISON report:
- Create a ## Comparison Table as a markdown table comparing ALL options across key criteria (rows = criteria, columns = options)
- Use checkmarks, ratings, or short values in cells
- Write a ## section per option with its strengths, weaknesses, and ideal use case
- End with ## Best For verdicts (e.g., "**Best for small teams:** Option A because...")
- Include a ## Shared Considerations section for things that apply to all options""",

    "howto": """IMPORTANT FORMAT OVERRIDE — this is a HOW-TO guide:
- Start with ## Quick Guide — a super concise numbered list (one line per step, no details, just the action). Example: 1. Install X  2. Run Y  3. Configure Z
- Then ## Prerequisites listing what's needed before starting
- Then the detailed steps: ## Step 1: ..., ## Step 2: ...
- Each step should have a clear heading and detailed instructions
- Use blockquotes (> ) for tips and warnings: > **Tip:** ... or > **Warning:** ...
- End with ## Common Mistakes section
- Add estimated time and difficulty level near the top""",

    "factcheck": """IMPORTANT FORMAT OVERRIDE — this is a FACT-CHECK report:
- Start with ## The Claim restating what's being checked
- Create ## Evidence For and ## Evidence Against sections
- Each piece of evidence should be a ### with source name, what it found, and how strong the evidence is
- Include a ## Verdict section with one of: **Supported**, **Mixed Evidence**, or **Unsupported**
- End with ## Nuance & Caveats for important context and limitations
- Be balanced and cite sources for every claim""",
}

# ---------------------------------------------------------------------------
# DeepResearcher
# ---------------------------------------------------------------------------
class DeepResearcher:
    """
    Iterative research engine following the IterResearch pattern.

    Each round: LLM generates queries → configured search provider → selected
    page renderer/fetcher → LLM extraction → synthesis → continue/stop.
    """

    def __init__(
        self,
        llm_endpoint: str,
        llm_model: str,
        llm_headers: Optional[Dict] = None,
        max_rounds: int = 8,
        max_time: int = 0,
        max_urls_per_round: int = 3,
        max_content_chars: int = 15000,
        max_report_tokens: int = 8192,
        extraction_timeout: int = 90,
        planning_timeout: int = 90,
        query_timeout: int = 120,
        extraction_concurrency: int = 3,
        min_rounds: int = 2,
        max_empty_rounds: int = 2,
        synthesis_window: int = 10,
        progress_callback: Optional[Callable] = None,
        search_provider: Optional[str] = None,
        category: Optional[str] = None,
        document_mode: str = "research",
        story_kind: str = "fiction",
        source_material: str = "",
        generation_timeout: Optional[float] = None,
    ):
        self.llm_endpoint = llm_endpoint
        self.llm_model = llm_model
        self.llm_headers = llm_headers
        self.search_provider_override = search_provider
        self.document_mode = document_mode if document_mode in {"research", "arxiv", "novel"} else "research"
        self.story_kind = story_kind if story_kind in {"fiction", "nonfiction"} else "fiction"
        self.category = category if self.document_mode == "research" else None
        self.source_material = str(source_material or "").strip()[:60000]
        self.generation_timeout = generation_timeout if generation_timeout and generation_timeout > 0 else None
        self.max_rounds = max_rounds
        self.max_time = max(0, int(max_time or 0))
        self.max_urls_per_round = max_urls_per_round
        self.max_content_chars = max_content_chars
        self.max_report_tokens = max_report_tokens
        self.extraction_timeout = min(3600, max(15, int(extraction_timeout or 90)))
        self.planning_timeout = min(3600, max(15, int(planning_timeout or 90)))
        self.query_timeout = min(3600, max(15, int(query_timeout or 120)))
        self.extraction_concurrency = min(12, max(1, int(extraction_concurrency or 3)))
        self.min_rounds = min_rounds
        self.max_empty_rounds = max_empty_rounds
        self.synthesis_window = synthesis_window
        self._progress = progress_callback
        self._cancelled = False
        self._start_time: float = 0
        self.queries_used: Set[str] = set()
        self.urls_fetched: Set[str] = set()
        self.analyzed_urls: List[Dict[str, str]] = []
        self.round_count: int = 0
        # Track which search providers actually returned results during the
        # run, in arrival order — surfaced in the visual report so users can
        # see whether searxng / brave / tavily etc. carried the work.
        self.providers_used: List[str] = []
        self.findings: List[Dict] = []
        self.evolving_report: str = ""
        self.research_plan: str = ""

    def cancel(self):
        """Request cooperative cancellation of the research loop."""
        self._cancelled = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def research(
        self,
        question: str,
        prior_report: str = "",
        prior_findings: Optional[List[Dict]] = None,
        prior_urls: Optional[Set[str]] = None,
    ) -> str:
        """Run iterative research and return a final report.

        Args:
            question: The research question.
            prior_report: Previous report to continue from (for follow-up research).
            prior_findings: Previous findings to build on.
            prior_urls: URLs already visited (won't be re-fetched).
        """
        self._start_time = time.time()
        findings: List[Dict] = list(prior_findings) if prior_findings else []
        report = prior_report or ""

        # PLAN: Analyze the question and create a research strategy
        if not prior_report:
            self._emit(phase="planning")
            self.research_plan = await self._create_plan(question)
            logger.info(f"Research plan: {self.research_plan[:200]}")
        else:
            # Continuation — plan around the follow-up
            self._emit(phase="planning")
            self.research_plan = await self._create_plan(question)
            logger.info(f"Continuation plan: {self.research_plan[:200]}")
        if self.document_mode == "research" and not self.category and not prior_report:
            self.category = await self._classify_category(question)
            if self.category:
                logger.info(f"Auto-detected category: {self.category}")

        if prior_urls:
            self.urls_fetched.update(prior_urls)
        self.findings = findings  # expose for handler
        consecutive_empty_rounds = 0

        for round_num in range(1, self.max_rounds + 1):
            self.round_count = round_num
            if self._cancelled:
                logger.info(f"Research cancelled after {round_num - 1} rounds")
                break
            if self._time_exceeded():
                logger.info(f"Time limit reached after {round_num - 1} rounds")
                break

            logger.info(f"=== Research Round {round_num} ===")
            self._emit(phase="searching", round=round_num, total_sources=len(self.urls_fetched))

            # THINK: generate queries
            queries = await self._generate_queries(question, report, round_num)
            if not queries:
                logger.warning(f"Round {round_num}: no queries generated, stopping")
                break

            self._emit(phase="searching", round=round_num, queries=len(queries),
                       query_preview=queries[0] if queries else "",
                       total_sources=len(self.urls_fetched))

            # SEARCH + EXTRACT
            round_findings = await self._search_and_extract(queries, question)
            if round_findings:
                findings.extend(round_findings)
                consecutive_empty_rounds = 0
                logger.info(f"Round {round_num}: extracted {len(round_findings)} findings")
                self._emit(phase="reading", round=round_num,
                           new_sources=len(round_findings),
                           total_sources=len(self.urls_fetched),
                           total_findings=len(findings))
            else:
                consecutive_empty_rounds += 1
                logger.info(f"Round {round_num}: no new findings ({consecutive_empty_rounds} consecutive empty)")
                if consecutive_empty_rounds >= self.max_empty_rounds:
                    logger.warning(f"Search appears to be down — {self.max_empty_rounds} consecutive rounds with no results")
                    err_detail = getattr(self, '_last_search_error', 'unknown error')
                    self._emit(phase="error", message=f"Search engine unavailable: {err_detail}")
                    if not findings:
                        return (
                            f"**Search unavailable** — Web search failed after "
                            f"{round_num} rounds. Error: {err_detail}\n\n"
                            "Please check your search provider settings and ensure the service is running."
                        )
                    break

            # SYNTHESIZE
            if findings:
                self._emit(phase="analyzing", round=round_num,
                           total_sources=len(self.urls_fetched),
                           total_findings=len(findings))
                report = await self._synthesize(question, findings, report)

            # DECIDE
            if round_num >= self.min_rounds:
                should_stop = await self._should_stop(question, report, round_num)
                if should_stop:
                    logger.info(f"LLM decided to stop after round {round_num}")
                    break

        # FINAL REPORT
        self._emit(phase="writing", total_sources=len(self.urls_fetched),
                   total_findings=len(findings))
        if not report:
            # Synthesis can fail (e.g. the LLM timed out) even though the search
            # rounds did gather findings. Don't throw that work away — return the
            # gathered findings as a basic compiled report instead of claiming
            # nothing was found (#1551).
            if findings:
                logger.warning(
                    "Synthesis produced no report; returning %d gathered "
                    "finding(s) as a fallback", len(findings)
                )
                return self._fallback_report(question, findings)
            return "No information could be gathered for this question."

        self.evolving_report = report  # preserve pre-synthesis report
        final = await self._final_report(question, report)
        elapsed = time.time() - self._start_time
        logger.info(
            f"Research complete: {self.round_count} rounds, "
            f"{len(findings)} findings, {len(self.urls_fetched)} URLs, "
            f"{elapsed:.1f}s"
        )
        return final

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------
    def _mode_prompt(self) -> str:
        document_mode = getattr(self, "document_mode", "research")
        if document_mode == "arxiv":
            return ARXIV_MODE_PROMPT
        if document_mode == "novel" and getattr(self, "story_kind", "fiction") == "nonfiction":
            return NOVEL_NONFICTION_PROMPT
        if document_mode == "novel":
            return NOVEL_FICTION_PROMPT
        return ""

    def _source_prompt(self) -> str:
        source_material = getattr(self, "source_material", "")
        if not source_material:
            return ""
        return (
            "\n\nUSER-SUPPLIED SOURCE MATERIAL\n"
            "Treat this as authoritative input from the user, while still distinguishing "
            "a draft/creative reference from externally verified evidence.\n\n"
            + source_material
        )

    @staticmethod
    def _merge_continuation(existing: str, continuation: str) -> str:
        """Join a continuation without duplicating an echoed suffix/prefix."""
        left = str(existing or "")
        right = str(continuation or "")
        if not left:
            return right
        if not right:
            return left
        limit = min(len(left), len(right), 4000)
        for size in range(limit, 31, -1):
            if left[-size:] == right[:size]:
                return left + right[size:]
        return left + right

    async def _llm(self, messages: List[Dict], temperature: float = 0.3,
                   max_tokens: int = 4096,
                   timeout: Optional[float] = None) -> str:
        """Call the LLM and continue responses that end without a terminal stop.

        Deep Research uses non-streaming calls, but OpenAI-compatible responses
        still expose ``finish_reason``. A length stop, an empty completion, or a
        missing terminal reason is not success. Continue from the partial text
        until the provider reports a real terminal stop; cancellation remains
        cooperative because each request is awaited by the research task.
        """
        from src.llm_core import llm_call_async

        request_messages = list(messages)
        combined = ""
        missing_terminal_seen = False
        empty_attempts = 0
        while True:
            response, completion = await llm_call_async(
                url=self.llm_endpoint,
                model=self.llm_model,
                messages=request_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                headers=self.llm_headers,
                timeout=timeout,
                workload="background",
                return_completion_metadata=True,
            )
            raw_response = str(response or "")
            segment = strip_thinking(raw_response)
            # The shared thinking scrubber deliberately trims its result.  On
            # a continuation request that leading whitespace can be semantic
            # (", then" / ". Next"), so restore only the boundary whitespace
            # that the provider actually returned.  The first segment remains
            # normalized exactly as before.
            if combined and segment and raw_response[:1].isspace() and not segment[:1].isspace():
                segment = raw_response[:1] + segment
            before = combined
            combined = self._merge_continuation(combined, segment)
            reason = str((completion or {}).get("finish_reason") or "").strip().lower()

            if segment.strip():
                empty_attempts = 0
            else:
                empty_attempts += 1
            interrupted = reason in {
                "length", "max_tokens", "max_output_tokens", "incomplete",
                "model_length",
            }
            missing_terminal = not reason

            if not interrupted and not missing_terminal and segment.strip():
                return combined
            if self._cancelled:
                return combined
            if empty_attempts >= 2 or (combined == before and combined):
                logger.warning(
                    "Research completion could not advance after an interrupted response "
                    "(finish_reason=%r); retaining partial output",
                    reason or None,
                )
                return combined
            # Some compatibility endpoints omit finish_reason even for complete
            # generations. Nudge once so a genuinely severed response gets a
            # chance to finish, then accept a second substantive metadata-less
            # segment rather than creating an unbounded duplicate loop.
            if missing_terminal and missing_terminal_seen and segment.strip():
                return combined
            missing_terminal_seen = missing_terminal_seen or missing_terminal

            self._emit(
                phase="writing",
                message="Continuing an interrupted model response…",
                finish_reason=reason or "missing",
            )
            request_messages = list(messages)
            if combined:
                request_messages.append({"role": "assistant", "content": combined})
            request_messages.append({
                "role": "user",
                "content": (
                    "Continue exactly where the preceding response ended. Do not repeat "
                    "completed text, restart the document, summarize it, or add commentary. "
                    "Finish the requested output in the same format."
                ),
            })

    # ------------------------------------------------------------------
    # PLAN: create research strategy
    # ------------------------------------------------------------------
    async def _create_plan(self, question: str) -> str:
        """LLM analyzes the question and creates a research plan."""
        prompt = (
            current_date_context()
            + RESEARCH_PLAN_PROMPT.format(question=question)
            + "\n\n"
            + self._mode_prompt()
            + self._source_prompt()
        )
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1024,
                timeout=getattr(self, "planning_timeout", 90),
            )
            # Try to parse as JSON for structured plan
            parsed = self._parse_json_object(response)
            if parsed:
                parts = []
                if parsed.get("sub_questions"):
                    parts.append("Sub-questions: " + "; ".join(parsed["sub_questions"]))
                if parsed.get("key_topics"):
                    parts.append("Key topics: " + ", ".join(parsed["key_topics"]))
                if parsed.get("success_criteria"):
                    parts.append("Success: " + parsed["success_criteria"])
                return "\n".join(parts) if parts else response
            return response
        except Exception as e:
            logger.warning(f"Research planning failed: {e}")
            self._emit(phase="warning", message="Planning step failed, proceeding with direct search")
            return ""

    async def _classify_category(self, question: str) -> Optional[str]:
        """Fast LLM call to classify the research question into a category."""
        valid = ", ".join(CATEGORY_PROMPTS.keys())
        prompt = (
            f"Classify this research question into exactly ONE category.\n"
            f"Categories: {valid}\n"
            f"If none fit well, respond with: general\n\n"
            f"Question: {question}\n\n"
            f"Respond with ONLY the category name, nothing else."
        )
        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0, max_tokens=20, timeout=15,
            )
            cat = (result or "").strip().lower()
            # Clean one-word answer first.
            parts = cat.split()
            first = parts[0].strip(".,\"'*:") if parts else ""
            if first in CATEGORY_PROMPTS:
                return first
            # Weak local models often wrap the label in preamble ("the category
            # is product") — scan the whole reply for any known category word
            # before giving up (which would default to the generic format).
            for c in CATEGORY_PROMPTS:
                if c in cat:
                    return c
            return None
        except Exception as e:
            logger.warning(f"Category classification failed: {e}")
            return None

    # ------------------------------------------------------------------
    # THINK: generate search queries
    # ------------------------------------------------------------------
    async def _generate_queries(self, question: str, report: str,
                                round_num: int) -> List[str]:
        if round_num == 1:
            num_queries = 4
            round_instruction = (
                "This is the first round — generate broad, diverse queries "
                "that explore the key facets of the question."
            )
        else:
            num_queries = 3
            round_instruction = (
                "We already have partial findings.  Generate targeted follow-up "
                "queries to fill gaps, verify claims, or explore specific aspects "
                "that the report doesn't yet cover well."
            )

        prompt = current_date_context() + QUERY_GEN_PROMPT.format(
            question=question,
            research_plan=self.research_plan or "(No plan — search broadly.)",
            report=report or "(No findings yet.)",
            round_num=round_num,
            num_queries=num_queries,
            round_instruction=round_instruction,
        )
        prompt += "\n\n" + self._mode_prompt() + self._source_prompt()

        queries: List[str] = []
        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=4096,
                timeout=getattr(self, "query_timeout", 120),
            )
            queries = self._parse_json_array(response)
        except Exception as e:
            logger.error(f"Query generation failed: {e}")
            self._emit(phase="warning", message=f"Query generation failed: {e}")

        if not queries:
            logger.warning(
                "Round %d query response was empty or malformed; retrying with "
                "a minimal strict-JSON prompt",
                round_num,
            )
            self._emit(
                phase="warning",
                message="Search planning returned malformed output; retrying once",
            )
            retry_prompt = (
                current_date_context()
                + f"Return exactly {num_queries} useful web-search queries for the "
                "research question below. Output ONLY one valid JSON array of "
                "strings. No prose, Markdown, or code fence.\n\n"
                f"Question:\n{question}\n\nJSON array:"
            )
            try:
                response = await self._llm(
                    [{"role": "user", "content": retry_prompt}],
                    temperature=0,
                    max_tokens=1024,
                    timeout=getattr(self, "query_timeout", 120),
                )
                queries = self._parse_json_array(response)
            except Exception as e:
                logger.error(f"Query generation retry failed: {e}")

        if not queries:
            queries = self._fallback_queries(question, num_queries)
            logger.warning(
                "Round %d using deterministic fallback queries: %s",
                round_num,
                queries,
            )
            self._emit(
                phase="warning",
                message="Using deterministic search queries after planner failure",
            )

        # Normalize and deduplicate against earlier rounds.
        new_queries = []
        for query in queries:
            query = str(query).strip()
            if not query or query in self.queries_used or query in new_queries:
                continue
            new_queries.append(query)
        self.queries_used.update(new_queries)
        logger.info(f"Round {round_num} queries: {new_queries}")
        return new_queries

    @staticmethod
    def _fallback_queries(question: str, limit: int = 4) -> List[str]:
        """Build useful searches without relying on a well-formed LLM reply."""
        candidates: List[str] = []
        urls = _extract_explicit_urls(question)
        text_without_urls = _URL_PATTERN.sub(" ", question or "")

        # Repository/model identifiers are usually the most discriminating
        # terms in technical research prompts (owner/project or org/model).
        reference_pattern = re.compile(
            r"\b[A-Za-z0-9][A-Za-z0-9_.-]{1,80}/"
            r"[A-Za-z0-9][A-Za-z0-9_.:+-]{1,160}\b"
        )
        candidates.extend(reference_pattern.findall(text_without_urls))

        # Direct references are scraped separately, but a site-scoped query
        # finds related cards, docs, discussions, and lineage information.
        for url in urls:
            parsed = urlparse(url)
            path = unquote(parsed.path).strip("/")
            path_terms = re.sub(r"[/_-]+", " ", path).strip()
            query = f"site:{parsed.hostname} {path_terms}".strip()
            if query != f"site:{parsed.hostname}":
                candidates.append(query)

        # Preserve one broad question for context after removing code blocks,
        # URLs, and one-line comparison separators.
        broad = re.sub(r"```[\s\S]*?```", " ", text_without_urls)
        lines = [
            re.sub(r"\s+", " ", line).strip(" -\t")
            for line in broad.splitlines()
        ]
        broad = " ".join(line for line in lines if len(line) > 3 and line.upper() != "VS")
        if broad:
            candidates.append(broad[:320])

        queries: List[str] = []
        seen: Set[str] = set()
        for candidate in candidates:
            candidate = re.sub(r"\s+", " ", candidate).strip()
            key = candidate.casefold()
            if not candidate or key in seen:
                continue
            seen.add(key)
            queries.append(candidate)
            if len(queries) >= max(1, limit):
                break
        return queries or ["research " + re.sub(r"\s+", " ", question).strip()[:300]]

    # ------------------------------------------------------------------
    # SEARCH + EXTRACT
    # ------------------------------------------------------------------
    async def _search_and_extract(self, queries: List[str],
                                  question: str) -> List[Dict]:
        """Search each query and extract relevant info from top results."""
        all_findings: List[Dict] = []

        # Search all queries in parallel
        search_tasks = [self._search(q) for q in queries]
        search_results = await asyncio.gather(*search_tasks, return_exceptions=True)

        # Collect URLs to fetch from all search results. Explicit URLs in the
        # user's prompt are authoritative inputs, so queue them first rather
        # than hoping a search engine happens to return the same page.
        urls_to_fetch = []
        url_budget = self.max_urls_per_round * max(len(queries), 1)

        def _queue_result(result: Dict) -> None:
            if len(urls_to_fetch) >= url_budget:
                return
            url = result.get("url", "")
            if not url or url in self.urls_fetched:
                return
            queued = dict(result)
            queued["title"] = queued.get("title", "") or url
            urls_to_fetch.append(queued)
            self.urls_fetched.add(url)
            self.analyzed_urls.append({"url": url, "title": queued["title"]})

        for url in _extract_explicit_urls(question):
            _queue_result({
                "url": url,
                "title": urlparse(url).hostname or url,
                "direct_reference": True,
            })

        for result in search_results:
            if isinstance(result, Exception):
                logger.warning(f"Search error: {result}")
                continue
            if not result:
                continue
            for r in result:
                _queue_result(r)
                if len(urls_to_fetch) >= url_budget:
                    break

        if self._cancelled or self._time_exceeded():
            return all_findings

        # Fetch and extract URLs with backpressure. Local model servers often
        # serialize requests behind one GPU; flooding them makes every request
        # slower and can trip the extraction timeout.
        semaphore = asyncio.Semaphore(self.extraction_concurrency)

        async def _bounded_extract(result: Dict) -> Optional[Dict]:
            async with semaphore:
                return await self._fetch_and_extract(result["url"], question, result.get("title", ""))

        extract_tasks = [_bounded_extract(r) for r in urls_to_fetch]
        results_gathered = await asyncio.gather(*extract_tasks, return_exceptions=True)

        for result in results_gathered:
            if isinstance(result, Exception):
                logger.warning(f"Extraction error: {result}")
                continue
            if result:
                all_findings.append(result)

        return all_findings

    async def _search(self, query: str) -> List[Dict]:
        """Run a search query using the configured research search provider."""
        try:
            from src.search.core import _call_provider, _build_provider_chain
            provider = self._active_search_provider()

            if provider == "disabled":
                logger.info("Search is disabled for research")
                return []

            # Try primary provider, then fallbacks
            chain = _build_provider_chain(provider)
            raised = False
            for prov in chain:
                try:
                    results = await asyncio.to_thread(_call_provider, prov, query, 10)
                    if results:
                        logger.info(f"Research search: {prov} returned {len(results)} results")
                        if prov not in self.providers_used:
                            self.providers_used.append(prov)
                        return results
                except Exception as e:
                    raised = True
                    logger.warning(f"Research search: {prov} failed: {e}")
                    self._last_search_error = f"{prov}: {e}"
            # Every provider ran but none returned results. If none of them
            # raised, record an actionable reason here — otherwise this empty
            # path leaves `_last_search_error` unset and the caller surfaces a
            # bare "unknown error" (issue #344). This is exactly the SearXNG
            # case where the service is reachable but all its engines fail, so
            # each provider returns [] without throwing.
            if not raised:
                self._last_search_error = (
                    f"no results from search provider(s): "
                    f"{', '.join(chain) if chain else provider}"
                )
            return []
        except Exception as e:
            logger.error(f"Search failed for '{query}': {e}")
            self._last_search_error = str(e)
            return []

    def _active_search_provider(self) -> str:
        """Resolve the research provider using the same precedence as search."""
        provider = (self.search_provider_override or "").strip()
        if provider:
            return provider

        from src.search.providers import _get_search_settings

        settings = _get_search_settings()
        if not provider:
            provider = (settings.get("research_search_provider") or "").strip()
        if not provider:
            provider = settings.get("search_provider", "searxng")
        return str(provider or "searxng").strip()

    async def _fetch_and_extract(self, url: str, question: str,
                                 title: str) -> Optional[Dict]:
        """Fetch a URL's content and use LLM to extract relevant info."""
        display = title or url
        self._emit(phase="reading", url=url, title=display,
                   total_sources=len(self.urls_fetched))
        from src.search import fetch_webpage_content, firecrawl_scrape

        page = None
        if self._active_search_provider() == "firecrawl":
            scrape_timeout = min(180, max(30, self.extraction_timeout))
            page = await asyncio.to_thread(firecrawl_scrape, url, scrape_timeout)
            if not page.get("success") or not page.get("content"):
                logger.warning(
                    "Firecrawl could not scrape %s (%s); falling back to the "
                    "native bounded fetcher",
                    url,
                    page.get("error", "empty response"),
                )

        if not page or not page.get("success") or not page.get("content"):
            try:
                page = await asyncio.to_thread(fetch_webpage_content, url, 10)
            except Exception as e:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None

        if not page.get("success") or not page.get("content"):
            return None

        content = page["content"]
        # Truncate to avoid blowing up context, preferring paragraph boundary
        if len(content) > self.max_content_chars:
            truncated = content[:self.max_content_chars]
            last_para = truncated.rfind('\n\n')
            if last_para > self.max_content_chars * 0.8:
                content = truncated[:last_para]
            else:
                content = truncated

        try:
            response = await self._llm(
                [
                    {"role": "user", "content": EXTRACTOR_SYSTEM.format(goal=question)},
                    untrusted_context_message("webpage", content),
                ],
                temperature=0.2,
                max_tokens=2048,
                timeout=self.extraction_timeout,
            )
            parsed = self._parse_json_object(response)
            if parsed:
                parsed["url"] = url
                parsed["title"] = title or page.get("title", "")
                parsed["og_image"] = page.get("og_image", "")
                # Skip findings where the LLM says the page is useless
                if is_low_quality(parsed.get("summary", "")):
                    logger.info(f"Skipping low-quality extraction from {url}")
                    return None
                return parsed
            # Preserve a substantive non-JSON reply as raw evidence. An empty
            # final answer is different: reasoning models can spend their whole
            # generation inside a stripped thinking block, which previously
            # created a fake finding whose summary/evidence were both empty.
            raw_response = str(response or "").strip()
            if raw_response:
                if is_low_quality(raw_response):
                    logger.info(f"Skipping low-quality extraction from {url}")
                    return None
                return {
                    "url": url,
                    "title": title or page.get("title", ""),
                    "og_image": page.get("og_image", ""),
                    "rational": "LLM extraction (raw)",
                    "evidence": raw_response[:3000],
                    "summary": raw_response[:500],
                }

            logger.warning(
                "Structured extraction returned an empty final answer for %s; "
                "preserving bounded rendered-page evidence",
                url,
            )
            return self._rendered_page_finding(url, title, page, content)
        except Exception as e:
            logger.warning(f"LLM extraction failed for {url}: {e}")
            # Retrieval already succeeded. Retain a bounded excerpt so a
            # transient or model-specific extractor failure does not erase the
            # page, its attribution, and all useful input to synthesis.
            return self._rendered_page_finding(url, title, page, content)

    @staticmethod
    def _rendered_page_finding(
        url: str,
        title: str,
        page: Dict,
        content: str,
    ) -> Optional[Dict]:
        """Build a source-grounded fallback from successfully rendered text."""
        rendered = str(content or "").strip()
        if not rendered:
            return None

        evidence = rendered[:6000]
        if len(rendered) > 6000:
            last_para = evidence.rfind("\n\n")
            if last_para > 4800:
                evidence = evidence[:last_para]

        summary = evidence[:1200]
        if len(evidence) > 1200:
            last_para = summary.rfind("\n\n")
            if last_para > 800:
                summary = summary[:last_para]

        return {
            "url": url,
            "title": title or page.get("title", ""),
            "og_image": page.get("og_image", ""),
            "rational": (
                "The page rendered successfully, but the research model did "
                "not return a usable structured extraction. Bounded original "
                "page evidence was retained instead."
            ),
            "evidence": evidence,
            "summary": summary,
            "extraction_mode": "rendered_page_fallback",
        }

    # ------------------------------------------------------------------
    # SYNTHESIZE
    # ------------------------------------------------------------------
    async def _synthesize(self, question: str, findings: List[Dict],
                          current_report: str) -> str:
        """LLM synthesizes all findings into an updated report."""
        # Format findings for the prompt
        window = findings[-self.synthesis_window:]
        if len(findings) > self.synthesis_window:
            logger.info(f"Synthesis using last {self.synthesis_window} of {len(findings)} findings")
        findings_text = self._format_findings(window)

        prompt = SYNTHESIZE_PROMPT.format(
            question=question,
            report=current_report or "(First round — no report yet.)",
            new_findings=findings_text,
        )
        prompt += "\n\n" + self._mode_prompt() + self._source_prompt()

        try:
            return await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                # Synthesis is a heavy generation call like the final report
                # (which gets 180s); a slow local model (e.g. a 20B served from
                # LM Studio) routinely needs >60s for it. The old 60s cap timed
                # out mid-stream and discarded the round's findings (#1551).
                timeout=self.generation_timeout,
            )
        except Exception as e:
            logger.error(f"Synthesis failed: {e}")
            self._emit(phase="warning", message="Synthesis failed, keeping previous report")
            return current_report  # keep the old report on failure

    # ------------------------------------------------------------------
    # DECIDE
    # ------------------------------------------------------------------
    async def _should_stop(self, question: str, report: str,
                           round_num: int) -> bool:
        """Let the LLM decide whether the report is comprehensive enough."""
        prompt = STOP_PROMPT.format(
            question=question,
            report=report,
            round_num=round_num,
            max_rounds=self.max_rounds,
        )
        prompt += "\n\n" + self._mode_prompt()

        try:
            response = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=128,
            )
            # Reasoning models prepend a <think>...</think> block — strip it
            # before checking for YES/NO, otherwise the answer always looks
            # like it starts with "<THINK>" and the engine never stops.
            clean = strip_thinking(response).strip()
            # Tolerate "**YES**", "Yes.", quotes, etc.
            answer = re.sub(r'^[\s*_`"\'>#\-]+', '', clean).upper()
            should_stop = answer.startswith("YES")
            logger.info(f"Stop decision (round {round_num}): {clean[:120]}")
            return should_stop
        except Exception as e:
            logger.warning(f"Stop decision failed: {e}")
            return False  # continue on error

    # ------------------------------------------------------------------
    # FINAL REPORT
    # ------------------------------------------------------------------
    async def _final_report(self, question: str, report: str) -> str:
        """LLM writes a polished final report, retrying if too short."""
        if self.document_mode == "arxiv":
            prompt = f"""Write the complete final scholarly paper for this request:

{question}

CURRENT PUBLISHED DRAFT
{report}

Return only the full paper as Markdown. Preserve sound material, integrate the evidence,
repair citations and cross-references, and make every claim commensurate with its support.
Do not describe your process or wrap the paper in a code fence.

{self._mode_prompt()}{self._source_prompt()}"""
        elif self.document_mode == "novel":
            prompt = f"""Write the complete final manuscript for this request:

{question}

CURRENT MANUSCRIPT
{report}

Return only the full manuscript as Markdown. Preserve established voice and continuity,
integrate useful source material naturally, resolve unfinished transitions, and complete
the requested narrative. Do not describe your process or wrap the manuscript in a code fence.

{self._mode_prompt()}{self._source_prompt()}"""
        else:
            prompt = FINAL_REPORT_PROMPT.format(
                question=question,
                report=report,
            )
            prompt += "\n\n" + self._mode_prompt() + self._source_prompt()
        cat_extra = CATEGORY_PROMPTS.get(self.category or "", "")
        if cat_extra:
            prompt += "\n\n" + cat_extra

        try:
            result = await self._llm(
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=self.max_report_tokens,
                timeout=self.generation_timeout,
            )
            if not str(result or "").strip():
                logger.warning(
                    "Final report model returned an empty final answer; "
                    "keeping the source-grounded evolving report"
                )
                return report

            # If report is too short, ask the LLM to expand it
            if len(result.split()) < 400:
                logger.info(f"Final report too short ({len(result.split())} words), requesting expansion")
                self._emit(phase="writing", message="Expanding report...")
                if self.document_mode == "arxiv":
                    expansion_instruction = (
                        "The paper is too brief for the material available. Return the complete "
                        "expanded paper, strengthening the abstract, methods, analysis, limitations, "
                        "conclusion, mathematical detail, and source-grounded references as applicable."
                    )
                elif self.document_mode == "novel":
                    expansion_instruction = (
                        "The manuscript is too brief for the requested narrative. Return the complete "
                        "expanded manuscript with developed scenes or sections, continuity, pacing, "
                        "specific detail, and a satisfying through-line. Preserve the established voice."
                    )
                else:
                    expansion_instruction = (
                        "This report is too brief. Please expand it significantly:\n"
                        "- Add detailed paragraphs for each section (not just bullet points)\n"
                        "- Include specific data, numbers, and comparisons from the evidence\n"
                        "- Explain context and significance — don't just list facts\n"
                        "- Use ## headings and ### subheadings\n"
                        "- Target at least 1000 words\n"
                        "Write the full expanded report now."
                    )
                expanded = await self._llm(
                    [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": result},
                        {"role": "user", "content": expansion_instruction},
                    ],
                    temperature=0.4,
                    max_tokens=self.max_report_tokens,
                    timeout=self.generation_timeout,
                )
                if len(expanded.split()) > len(result.split()):
                    return expanded

            return result
        except Exception as e:
            logger.error(f"Final report generation failed: {e}")
            return report  # return the evolving report as-is

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _emit(self, **kwargs):
        """Send a progress event via the callback, if one is registered."""
        if self._progress:
            try:
                self._progress(kwargs)
            except Exception:
                pass

    def _time_exceeded(self) -> bool:
        return self.max_time > 0 and (time.time() - self._start_time) > self.max_time

    # _strip_think_tags removed — use research_utils.strip_thinking()

    @staticmethod
    def _strip_code_block(text: str) -> str:
        """Strip markdown code-block fences (```json ... ```) if present."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
        return text.strip()

    def _parse_json_array(self, text: str) -> List[str]:
        """Extract a JSON array of strings from LLM output."""
        text = self._strip_code_block(text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass

        # Handle truncated arrays — e.g. '["query one", "query two", "query thr'
        # Repair from the LAST array start so an echoed example array earlier
        # in the reply is not harvested into the real query set.
        last_start = text.rfind('[')
        truncated = last_start != -1 and ']' not in text[last_start:]
        if truncated:
            complete_items = re.findall(r'"([^"]*)"', text[last_start:])
            if complete_items:
                logger.info(f"Repaired truncated JSON array: recovered {len(complete_items)} items")
                return complete_items

        # Greedy match to capture the full outermost array
        match = re.search(r'\[[\s\S]*\]', text)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(item) for item in parsed]
            except json.JSONDecodeError:
                pass

        # Multiple complete arrays in one reply (e.g. the model echoes the
        # prompt's Example: [...] before the real array). The greedy match
        # above spans them all and fails to parse, so scan non-greedily and
        # keep the LAST parseable array, which is the model's actual answer.
        last_parsed = None
        for m in re.finditer(r'\[[\s\S]*?\]', text):
            try:
                parsed = json.loads(m.group())
                if isinstance(parsed, list):
                    last_parsed = parsed
            except json.JSONDecodeError:
                continue
        if last_parsed is not None:
            return [str(item) for item in last_parsed]

        # Last resort: harvest quoted strings from the first array start
        arr_start = text.find('[')
        if arr_start != -1:
            fragment = text[arr_start:]
            # Find the last complete quoted string
            complete_items = re.findall(r'"([^"]*)"', fragment)
            if complete_items:
                logger.info(f"Repaired truncated JSON array: recovered {len(complete_items)} items")
                return complete_items

        logger.warning(f"Could not parse JSON array from: {text[:200]}")
        return []

    def _parse_json_object(self, text: str) -> Optional[Dict]:
        """Extract a JSON object from LLM output."""
        text = self._strip_code_block(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Greedy match to capture the full outermost object
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None

    def _format_findings(self, findings: List[Dict]) -> str:
        """Format findings list into readable text for synthesis prompt."""
        parts = []
        for i, f in enumerate(findings, 1):
            url = f.get("url", "unknown")
            title = f.get("title", "")
            summary = f.get("summary", "")
            evidence = f.get("evidence", "")
            # Give synthesis both the extractor's conclusion and its actual
            # evidence. Previously a non-empty summary silently displaced the
            # evidence field, weakening source grounding even on good runs.
            if evidence:
                bounded_evidence = evidence[:4000]
                if summary and not bounded_evidence.startswith(summary):
                    content = f"Summary: {summary}\n\nEvidence:\n{bounded_evidence}"
                else:
                    content = bounded_evidence
            else:
                content = summary or "(no content)"
            parts.append(f"**Finding {i}** — [{title}]({url})\n{content}")
        return "\n\n".join(parts)

    def _fallback_report(self, question: str, findings: List[Dict]) -> str:
        """Compile gathered findings into a basic report.

        Used when the LLM synthesis step produced no report (e.g. it timed out)
        but the search rounds did collect findings — so the user still gets the
        material that was gathered instead of "No information could be gathered"
        (#1551).
        """
        return (
            f"# {question}\n\n"
            "_Automatic synthesis did not complete, so this report lists the "
            f"{len(findings)} finding(s) gathered during research._\n\n"
            f"{self._format_findings(findings)}"
        )

    def get_stats(self) -> Dict:
        """Return research statistics."""
        elapsed = time.time() - self._start_time if self._start_time else 0
        stats = {
            "Duration": f"{elapsed:.1f}s",
            "Rounds": self.round_count,
            "Queries": len(self.queries_used),
            "URLs": len(self.urls_fetched),
            "Findings": len(self.findings),
            "Model": self.llm_model,
        }
        if self.providers_used:
            stats["Search"] = ", ".join(self.providers_used)
        if self.category:
            stats["Category"] = self.category.capitalize()
        if self.document_mode != "research":
            stats["Mode"] = (
                f"Novel · {self.story_kind.capitalize()}"
                if self.document_mode == "novel"
                else "arXiv"
            )
        return stats
