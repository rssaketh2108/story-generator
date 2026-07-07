# The Writers' Room: A Comic Studio of Debating Agents

**Subtitle:** Rival LLMs debate your idea into a story, then a staged agent pipeline illustrates it into a comic with consistent characters.

**Track:** Freestyle

**Try it live:** https://story-generator-ui-352241932029.us-east1.run.app
**Code:** https://github.com/rssaketh2108/story-generator

---

## The Problem

Turning a one line idea ("a lighthouse keeper discovers the fog is alive") into a finished comic is not a single task. It is a studio. Real comics are made by a room of specialists who argue: a story editor guards theme, a world builder keeps the rules consistent, a stylist polishes the prose, an outline writer breaks the story into panels, and an illustrator draws a cast that must look the same in every frame.

A single LLM prompt collapses all of that into one voice. It produces plausible but shallow output: no genuine disagreement, no division of labor, and, critically for comics, no consistency of characters across generated images. Ask an image model for "the hero" fifteen times and you get fifteen different people.

The interesting problem is therefore twofold. First, can a collaborative creative process, where different agents genuinely critique and build on each other, produce a better story than any one model alone? Second, can an agent pipeline enforce the hard production constraints of a real comic (a consistent cast, a coherent page layout, captions that actually track the plot) automatically?

## Why Agents?

Creative production is the textbook case for a system of many agents, for three reasons.

1. **Distinct roles need distinct instructions, and ideally distinct models.** A critic that guards theme should behave differently from a world builder that invents technology. We give each role its own agent, its own system prompt, and where possible a different underlying LLM, so the debate happens between genuinely different minds rather than one model talking to itself.
2. **The workflow is a pipeline of specialists.** Genesis, world building, plot, panel outline, art direction, illustration, publishing: this is naturally a chain of agents that hand structured artifacts to one another, which is exactly what ADK agent composition and the A2A (Agent to Agent) protocol are built for.
3. **Some steps must be deterministic and some must be emergent.** The debate should be dynamic; the pipeline order must not be. Mixing model driven agents with code orchestrated control flow is where an agent framework earns its keep.

## The Solution

The Writers' Room is a web app. You type a theme and genre, press Generate, and watch a studio of agents build your comic live over a streaming feed. The output is a set of illustrated, captioned panels and a downloadable PDF comic: a cover page (title, synopsis, cast) followed by pages of panels, each with a caption box beneath it.

The pipeline runs autonomously in six stages:

1. **Genesis:** the council debates characters, flaws, and world rules.
2. **Room and Canvas:** the council expands arcs; visual and regional detail is established.
3. **Breaking the Story:** the council debates plot, twists, and ending.
4. **Master Outline:** a dedicated outline agent converts the plot into a panel by panel script.
5. **Art Direction:** a Head Writer decides the title, synopsis, cast, page and panel layout, the orientation of each panel, a plain language narration, and a matching image prompt.
6. **Illustration and Publishing:** the illustrator draws the cast first (character model sheets), then renders every panel using those sheets as references so the characters stay consistent, and finally compiles the PDF.

## Architecture

The system is built on Google ADK and exposes each major agent over the A2A protocol through FastAPI. A React (Vite, TypeScript) frontend drives it through a live stream (SSE). The full architecture diagram is attached in the Media Gallery (`architecture.png`).

**The Council** is the heart of the project. Rather than an LLM coordinator that picks who speaks (which we found simply produced handoffs with no content), the council is an ADK `SequentialAgent` wrapping a `LoopAgent`. The loop runs three debaters, Claude, Codex, and Kimi, in turn for two rounds, so each one sees and reacts to the others through the shared session. A final synthesizer distills the debate into one consensus document. Any debater can call an `ask_head_writer` tool to pull in direction when it gets stuck.

**Consistency of characters** is the standout technique. Stage 6 first generates a clean model sheet for each cast member (full body, neutral background). Then, for every panel, it looks up which characters appear and passes their model sheets as reference images into the image model, so the same faces and costumes recur across the whole comic. Panels are rendered with Nano Banana (`gemini-2.5-flash-image`), whose native multi image input is built for exactly this; the model sheets themselves are drawn with Ideogram v4.

**Alignment and clarity:** the Head Writer emits, for each panel, a plain language narration (what happens in that beat) and a matching image prompt, with an explicit rule that the picture must depict the same moment the caption describes. This fixes the failure where the words and the art disagree.

## Key Concepts Demonstrated

This submission demonstrates five of the course's key concepts.

- **Agent and multiagent system (ADK):** the council (`SequentialAgent` plus `LoopAgent` plus synthesizer), the specialized agents, and the A2A served endpoints. This is the core of the solution.
- **MCP Server:** the illustrator dynamically loads MCP toolsets when configured: a Chrome or Brave search server (over Stdio) for visual reference research, and an image generation MCP over Stdio or remote SSE. MCP integration is wired directly into the agent's tool list.
- **Security features:** a `BudgetGuard` plugin enforces a hard $15 spend cap across all model calls in a session, raising an error before any overspend; no API keys live in code (everything is read from the environment or a git ignored `.env` file); and each provider is isolated so a failing or compromised one cannot take over the run.
- **Deployability:** the project ships with an Agents CLI manifest and a Dockerfile, and deploys to Google Cloud Run; the README documents a reproducible deployment.
- **Agent skills (Agents CLI):** the project is scaffolded and managed with the ADK Agents CLI (`agents-cli-manifest.yaml`), used for install, local run, and deploy.

## The Build

**Backend:** Python, Google ADK (agents, `LoopAgent` and `SequentialAgent`, `App`, plugins), A2A (`A2AFastAPIApplication`, agent cards), LiteLLM (to route the council to Anthropic, OpenAI, and Moonshot), FastAPI, and a live stream (SSE).

**Models:** Gemini (`gemini-flash-latest`) for the coordinators, the outline writer, the synthesizer, and layout; Claude Sonnet 4.6, GPT 5.4 mini, and Kimi K2.6 as the three debaters.

**Image and publishing:** Ideogram v4 (character sheets, primary), Nano Banana (`gemini-2.5-flash-image`) for panels conditioned on references, and Pillow (both the last resort placeholder and the zero dependency multi page PDF renderer).

**Frontend:** React, TypeScript, and Vite: a live agent communication feed, artifact tabs (Genesis, Canvas, Plot, Outline), a comic gallery with caption boxes, and a Download PDF button.

**Engineering practices baked in:**

- **Provider resilience.** `get_llm_model()` probes the health of each provider at load and transparently falls back to Gemini if a key is missing, unfunded, or the model id is wrong, so one dead provider never crashes the room. It separates fatal errors (auth or not found) from benign ones (an output limit) to avoid false downgrades.
- **Isolation for every run.** Each run writes to its own folder, `artifacts/<run_id>/`, and streams the run id to the frontend, so concurrent stories never overwrite each other and no destructive "clear everything" step is needed.
- **Structured outputs.** The Head Writer returns strict JSON (title, synopsis, cast, pages, and for each panel the orientation, cast, narration, and prompt) that the pipeline parses directly.
- **Graceful degradation everywhere.** Each stage catches errors and falls back (fallback layouts, fallback captions, placeholder art) so the pipeline always produces a complete comic.

## The Journey

The most valuable lessons came from debugging real failures of a multiagent system.

- **Delegation collapse.** The first council used an LLM coordinator with sub agents and the ADK `transfer_to_agent` handoff. In practice the debaters just emitted one line meta statements and handed off, producing empty results and no content. Replacing it with a deterministic `LoopAgent` plus synthesizer turned it into a real debate where every model contributes.
- **Hidden theme bleed.** A "Tony Stark romcom" kept dragging in the idea of dharma. The cause was not memory leaking between runs; it was a hardcoded example baked into one agent's system prompt from an earlier build. A reminder that agent behavior is only as clean as its prompt.
- **Provider reality.** Mixing Anthropic, OpenAI, and Moonshot meant hitting rate limits, unfunded keys, and model ids that did not exist mid run. This drove the health probe and fallback design, so the studio degrades gracefully instead of failing.
- **Consistency and coherence.** Generating each panel independently gave inconsistent characters and captions that did not match the art. The fixes, conditioning on model sheets and forcing the narration and image prompt to describe the same moment, are what make the output read as an actual comic.

## Results and Future Work

The system reliably takes a theme to a finished comic with consistent characters and captions, plus a downloadable PDF, all while showing the agents collaborating live. It is deployed as a single public service on Google Cloud Run that serves both the UI and the API. Natural next steps: a debate that loops until the room reaches consensus rather than a fixed number of rounds, location model sheets for scene continuity, and speech balloon lettering composited onto the art.

The Writers' Room shows that when a creative task is decomposed into a room of specialized, debating agents, with the right mix of emergent collaboration and deterministic orchestration, the result is both better and genuinely producible.
