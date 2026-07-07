# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env configurations first
load_dotenv()

import google.auth
from a2a.server.apps import A2AFastAPIApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.artifacts import GcsArtifactService, InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.cloud import logging as google_cloud_logging

from app.agent import (
    head_writer_app,
    council_app,
    illustrator_app,
    outline_writer_app,
)
from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from app.tools import ARTIFACTS_DIR, ensure_artifacts_dir

# Enable telemetry and logging if GCP credentials are present
logger = None
try:
    setup_telemetry()
    _, project_id = google.auth.default()
    logging_client = google_cloud_logging.Client()
    logger = logging_client.logger(__name__)
except Exception as e:
    print(f"Notice: Google Cloud ADC credentials not found ({e}). Running in local-only mode.")
    class MockLogger:
        def log_struct(self, data, severity="INFO"):
            print(f"[{severity}] Mock Log: {data}")
    logger = MockLogger()

# Ensure static artifacts directory exists
ensure_artifacts_dir()

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")
artifact_service = (
    GcsArtifactService(bucket_name=logs_bucket_name)
    if logs_bucket_name
    else InMemoryArtifactService()
)

# Build runners and request handlers globally for all 4 agents
runner_head_writer = Runner(
    app=head_writer_app,
    artifact_service=artifact_service,
    session_service=InMemorySessionService(),
)
handler_head_writer = DefaultRequestHandler(
    agent_executor=A2aAgentExecutor(runner=runner_head_writer), task_store=InMemoryTaskStore()
)

runner_council = Runner(
    app=council_app,
    artifact_service=artifact_service,
    session_service=InMemorySessionService(),
)
handler_council = DefaultRequestHandler(
    agent_executor=A2aAgentExecutor(runner=runner_council), task_store=InMemoryTaskStore()
)

runner_illustrator = Runner(
    app=illustrator_app,
    artifact_service=artifact_service,
    session_service=InMemorySessionService(),
)
handler_illustrator = DefaultRequestHandler(
    agent_executor=A2aAgentExecutor(runner=runner_illustrator), task_store=InMemoryTaskStore()
)

runner_outline_writer = Runner(
    app=outline_writer_app,
    artifact_service=artifact_service,
    session_service=InMemorySessionService(),
)
handler_outline_writer = DefaultRequestHandler(
    agent_executor=A2aAgentExecutor(runner=runner_outline_writer), task_store=InMemoryTaskStore()
)

async def build_card(agent, path_prefix) -> AgentCard:
    """Builds the Agent Card dynamically for a specific path prefix."""
    base_url = os.getenv("APP_URL", "http://localhost:8000")
    agent_card_builder = AgentCardBuilder(
        agent=agent,
        capabilities=AgentCapabilities(streaming=True),
        rpc_url=f"{base_url}{path_prefix}",
        agent_version=os.getenv("AGENT_VERSION", "0.1.0"),
    )
    return await agent_card_builder.build()

@asynccontextmanager
async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
    # 1. Register head_writer
    card_head_writer = await build_card(head_writer_app.root_agent, "/a2a/head_writer")
    a2a_head_writer = A2AFastAPIApplication(agent_card=card_head_writer, http_handler=handler_head_writer)
    a2a_head_writer.add_routes_to_app(
        app_instance,
        agent_card_url=f"/a2a/head_writer{AGENT_CARD_WELL_KNOWN_PATH}",
        rpc_url="/a2a/head_writer",
        extended_agent_card_url=f"/a2a/head_writer{EXTENDED_AGENT_CARD_PATH}",
    )
    
    # 2. Register council
    card_council = await build_card(council_app.root_agent, "/a2a/council")
    a2a_council = A2AFastAPIApplication(agent_card=card_council, http_handler=handler_council)
    a2a_council.add_routes_to_app(
        app_instance,
        agent_card_url=f"/a2a/council{AGENT_CARD_WELL_KNOWN_PATH}",
        rpc_url="/a2a/council",
        extended_agent_card_url=f"/a2a/council{EXTENDED_AGENT_CARD_PATH}",
    )
    
    # 3. Register illustrator
    card_illustrator = await build_card(illustrator_app.root_agent, "/a2a/illustrator")
    a2a_illustrator = A2AFastAPIApplication(agent_card=card_illustrator, http_handler=handler_illustrator)
    a2a_illustrator.add_routes_to_app(
        app_instance,
        agent_card_url=f"/a2a/illustrator{AGENT_CARD_WELL_KNOWN_PATH}",
        rpc_url="/a2a/illustrator",
        extended_agent_card_url=f"/a2a/illustrator{EXTENDED_AGENT_CARD_PATH}",
    )
    
    # 4. Register outline_writer
    card_outline_writer = await build_card(outline_writer_app.root_agent, "/a2a/outline_writer")
    a2a_outline_writer = A2AFastAPIApplication(agent_card=card_outline_writer, http_handler=handler_outline_writer)
    a2a_outline_writer.add_routes_to_app(
        app_instance,
        agent_card_url=f"/a2a/outline_writer{AGENT_CARD_WELL_KNOWN_PATH}",
        rpc_url="/a2a/outline_writer",
        extended_agent_card_url=f"/a2a/outline_writer{EXTENDED_AGENT_CARD_PATH}",
    )
    
    yield

app = FastAPI(
    title="story-generator",
    description="Multi-agent A2A Story Generation System",
    lifespan=lifespan,
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated artifacts statically
app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")

from google.genai import types
import json
import asyncio
from fastapi.responses import StreamingResponse

@app.get("/api/story_stream")
async def story_stream(theme: str, session_id: str = None):
    import uuid
    if not session_id:
        session_id = f"session_{uuid.uuid4().hex}"
    # Each run writes to its own artifacts subfolder so concurrent stories never collide.
    run_id = f"run_{uuid.uuid4().hex[:12]}"

    def parse_outline_panels(outline_text: str) -> list[dict]:
        import re
        panels = []
        lines = outline_text.split('\n')
        current_panel = None
        
        # Regex patterns that match panel header lines:
        # "Panel 1:", "Panel 1.", "Panel 1 -", "**Panel 1:**", "Page 1, Panel 2:"
        panel_re = re.compile(
            r'^[\s*#]*(?:page\s*\d+[,:\s]*)?panel\s*\d+\s*[:.\.\-\u2013\u2014]\s*(.*)',
            re.IGNORECASE
        )
        dialogue_re = re.compile(
            r'^[\s*]*(?:dialogue|caption|speech|narration|sfx)\s*:\s*(.*)',
            re.IGNORECASE
        )
        
        for line in lines:
            line_strip = line.strip().strip('*').strip('#').strip()
            if not line_strip:
                continue
            
            m = panel_re.match(line_strip)
            if m:
                if current_panel:
                    panels.append(current_panel)
                panel_num = len(panels) + 1
                current_panel = {
                    "filename": f"panel_{panel_num}.png",
                    "description": m.group(1).strip().strip('*').strip(),
                    "dialogue": ""
                }
                continue
            
            if current_panel:
                dm = dialogue_re.match(line_strip)
                if dm:
                    current_panel["dialogue"] = dm.group(1).strip().strip('"').strip("'")
                elif line_strip.startswith(('-', '*', '\u2022')):
                    current_panel["description"] += " " + line_strip.lstrip('-*\u2022 ').strip()
                elif not current_panel["dialogue"] and (line_strip.startswith('"') or line_strip.startswith("'")):
                    current_panel["dialogue"] = line_strip.strip('"').strip("'")
                    
        if current_panel:
            panels.append(current_panel)
            
        # Fallback: 12 panels covering a full comic-book arc
        if not panels:
            panels = [
                {"filename": "panel_1.png", "description": "Wide cinematic establishing shot of the world from above, showing the city skyline at dawn with dramatic lighting", "dialogue": "In the age that followed the last silence..."},
                {"filename": "panel_2.png", "description": "Medium shot of the protagonist standing at a threshold, backlit, expression determined", "dialogue": "I was born for this moment."},
                {"filename": "panel_3.png", "description": "Close-up of the mentor figure handing over an ancient artifact, warm lighting", "dialogue": "Take this. You will need it before the end."},
                {"filename": "panel_4.png", "description": "Wide shot of the protagonist departing the city gates alone, long shadow stretching behind", "dialogue": "The road ahead is longer than any map can show."},
                {"filename": "panel_5.png", "description": "Dynamic action panel, protagonist leaping across a chasm, debris flying, motion blur", "dialogue": "No turning back!"},
                {"filename": "panel_6.png", "description": "Over-the-shoulder shot revealing the antagonist for the first time, seated on a dark throne", "dialogue": "So, the prophecy sends another fool."},
                {"filename": "panel_7.png", "description": "Close-up split panel showing protagonist and antagonist's eyes, mirrored composition", "dialogue": "We are not so different, you and I."},
                {"filename": "panel_8.png", "description": "Bird's eye view of a massive army assembling on a barren plain, banners fluttering", "dialogue": "The war begins at dawn."},
                {"filename": "panel_9.png", "description": "Medium shot of the ally making a sacrifice, dramatic side-lighting, emotion on face", "dialogue": "Promise me you will finish this."},
                {"filename": "panel_10.png", "description": "Full-page splash of the climactic battle, energy blasts and clashing forces, dynamic composition", "dialogue": "FOR EVERYTHING WE HAVE LOST!"},
                {"filename": "panel_11.png", "description": "Quiet medium shot of the protagonist standing over the fallen antagonist, rain falling", "dialogue": "It did not have to end this way."},
                {"filename": "panel_12.png", "description": "Wide panoramic closing shot of the rebuilt world at sunset, figures silhouetted in the golden light", "dialogue": "And so a new chapter begins..."}
            ]
        return panels

    async def event_generator():
        # Each run gets its own artifacts subfolder (created lazily by the tools), so we
        # no longer delete anything globally — concurrent/previous stories are preserved.
        os.makedirs(os.path.join(ARTIFACTS_DIR, run_id), exist_ok=True)

        from app.tools import save_artifact_file, generate_panel_image, generate_character_sheet, build_comic_pdf

        # Tell the frontend which subfolder to read this run's artifacts from.
        yield f"data: {json.dumps({'event': 'run_started', 'run_id': run_id})}\n\n"

        try:
            # ── Helper to run a stage safely ──────────────────────────────────
            async def run_stage(runner, sid, prompt, stage_label, fallback_text):
                """Run a runner stage, catch empty-output errors, return accumulated text."""
                content = ""
                try:
                    async for event in runner.run_async(
                        user_id="user_1",
                        session_id=sid,
                        new_message=types.Content(
                            parts=[types.Part.from_text(text=prompt)]
                        )
                    ):
                        if event.content and event.content.parts:
                            text = event.content.parts[0].text or ""
                            content += text
                            if text.strip():
                                yield text, event.author or stage_label
                except Exception as stage_err:
                    err_msg = f"Warning: {stage_label} encountered an error: {stage_err}"
                    yield err_msg, "System"
                
                if not content.strip():
                    content = fallback_text
                    yield f"(Using fallback content for {stage_label})", "System"
                
                # Yield a sentinel with the final content
                yield f"__STAGE_RESULT__{content}", "__RESULT__"
            
            # ── Stage 1: Character & World Genesis ────────────────────────────
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 1/5: Character & World Genesis (Council Debate)...'})}\n\n"
            
            await runner_council.session_service.create_session(
                app_name=runner_council.app.name,
                user_id="user_1",
                session_id=session_id
            )
            
            council_prompt = (
                f"Pitch character concepts, flaws, and world rules for the theme: '{theme}'. "
                "Claude Critic, Codex Worldbuilder, and Kimi Polisher must debate collaboratively, critique each other's ideas, "
                "and reach a unified consensus. You MUST run a dynamic debate. Call the tool 'ask_head_writer' if you need guidance."
            )
            
            genesis_content = ""
            async for text, author in run_stage(
                runner_council, session_id, council_prompt, "Council",
                f"# Genesis: {theme}\n\nCharacters and world rules for a story about {theme}."
            ):
                if author == "__RESULT__":
                    genesis_content = text.replace("__STAGE_RESULT__", "", 1)
                else:
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': author, 'message': text, 'tool_calls': []})}\n\n"
                
            save_artifact_file("genesis.md", genesis_content, subdir=run_id)
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': 'Saved genesis.md', 'tool_calls': []})}\n\n"
            
            # ── Stage 2: Room & Canvas ────────────────────────────────────────
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 2/5: Expanding Character Arcs & Canvas...'})}\n\n"
            
            canvas_prompt = (
                f"Based on the following genesis pitch, expand the character arcs and establish visual traits and regional details:\n\n{genesis_content}"
            )
            canvas_content = ""
            async for text, author in run_stage(
                runner_council, session_id, canvas_prompt, "Council",
                f"# Canvas: {theme}\n\nDetailed character arcs, region descriptions, and visual guides."
            ):
                if author == "__RESULT__":
                    canvas_content = text.replace("__STAGE_RESULT__", "", 1)
                else:
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': author, 'message': text, 'tool_calls': []})}\n\n"
                
            save_artifact_file("canvas.md", canvas_content, subdir=run_id)
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': 'Saved canvas.md', 'tool_calls': []})}\n\n"
            
            # ── Stage 3: Breaking the Story ───────────────────────────────────
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 3/5: Breaking the Story (Plot & Climax)...'})}\n\n"
            
            plot_prompt = (
                f"Based on the genesis and canvas, debate and outline the main plot, twists, and ending:\n\nGenesis:\n{genesis_content}\n\nCanvas:\n{canvas_content}"
            )
            plot_content = ""
            async for text, author in run_stage(
                runner_council, session_id, plot_prompt, "Council",
                f"# Plot: {theme}\n\nThe detailed storyline, twists, and resolution."
            ):
                if author == "__RESULT__":
                    plot_content = text.replace("__STAGE_RESULT__", "", 1)
                else:
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': author, 'message': text, 'tool_calls': []})}\n\n"
                
            save_artifact_file("plot.md", plot_content, subdir=run_id)
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': 'Saved plot.md', 'tool_calls': []})}\n\n"
            
            # ── Stage 4: Master Outline (Panel Script) ────────────────────────
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 4/5: Writing Master Script Outline (Panel-by-Panel)...'})}\n\n"
            
            await runner_outline_writer.session_service.create_session(
                app_name=runner_outline_writer.app.name,
                user_id="user_1",
                session_id=session_id
            )
            
            outline_prompt = (
                f"Based on the plot notes below, write a comic book panel script with 12 to 20 panels.\n"
                f"You MUST output ONLY lines in this exact format — no prose, no headers, no markdown:\n\n"
                f"Panel 1: [Detailed visual description — camera angle, characters, setting, action, lighting]\n"
                f"Dialogue: [Character]: [Line of dialogue or narration caption]\n\n"
                f"Panel 2: [Next shot description]\n"
                f"Dialogue: [Character]: [Line]\n\n"
                f"...continue for ALL 12-20 panels. Vary shot types (wide, medium, close-up, splash, bird's eye).\n"
                f"A real comic book tells a FULL story across many panels — not just 4!\n\n"
                f"PLOT NOTES:\n{plot_content}"
            )
            
            # Build a proper 12-panel theme-aware fallback
            outline_fallback = (
                f"Panel 1: Wide cinematic establishing shot of the world from above, showing the city skyline at dawn with dramatic lighting\n"
                "Dialogue: Narration: In the age that followed the last silence...\n\n"
                "Panel 2: Medium shot of the protagonist standing at a threshold, backlit, expression determined\n"
                "Dialogue: Hero: I was born for this moment.\n\n"
                "Panel 3: Close-up of the mentor figure handing over an ancient artifact, warm golden lighting\n"
                "Dialogue: Mentor: Take this. You will need it before the end.\n\n"
                "Panel 4: Wide shot of the protagonist departing the city gates alone, long shadow stretching behind\n"
                "Dialogue: Narration: The road ahead is longer than any map can show.\n\n"
                "Panel 5: Dynamic action panel, protagonist leaping across a chasm, debris flying, motion blur\n"
                "Dialogue: Hero: No turning back!\n\n"
                "Panel 6: Over-the-shoulder shot revealing the antagonist for the first time, seated on a dark throne\n"
                "Dialogue: Villain: So, the prophecy sends another fool.\n\n"
                "Panel 7: Close-up split panel showing protagonist and antagonist's eyes, mirrored composition\n"
                "Dialogue: Villain: We are not so different, you and I.\n\n"
                "Panel 8: Bird's eye view of a massive army assembling on a barren plain, banners fluttering\n"
                "Dialogue: Narration: The war begins at dawn.\n\n"
                "Panel 9: Medium shot of the ally making a sacrifice, dramatic side-lighting, emotion on face\n"
                "Dialogue: Ally: Promise me you will finish this.\n\n"
                "Panel 10: Full-page splash of the climactic battle, energy blasts and clashing forces, dynamic composition\n"
                "Dialogue: Hero: FOR EVERYTHING WE HAVE LOST!\n\n"
                "Panel 11: Quiet medium shot of the protagonist standing over the fallen antagonist, rain falling\n"
                "Dialogue: Hero: It did not have to end this way.\n\n"
                "Panel 12: Wide panoramic closing shot of the rebuilt world at sunset, figures silhouetted in golden light\n"
                "Dialogue: Narration: And so a new chapter begins..."
            )
            
            outline_content = ""
            async for text, author in run_stage(
                runner_outline_writer, session_id, outline_prompt, "Outline Writer",
                outline_fallback
            ):
                if author == "__RESULT__":
                    outline_content = text.replace("__STAGE_RESULT__", "", 1)
                else:
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': author, 'message': text, 'tool_calls': []})}\n\n"
                
            save_artifact_file("outline.md", outline_content, subdir=run_id)
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': 'Saved outline.md', 'tool_calls': []})}\n\n"
            
            # ── Stage 5: Comic Panel Production (Image Generation) ────────────
            # ── Stage 5a: Head Writer Plans Comic Layout & Art Prompts ─────
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 5/6: Head Writer planning comic layout (pages, panels, art direction)...'})}\n\n"
            
            import google.genai
            gemini_client = google.genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            
            layout_prompt = (
                "You are the Head Writer of a comic book studio. Based on the outline below, decide:\n"
                "1. A short, evocative 'title' for the comic, and a 3-4 sentence 'synopsis' that sets up the story "
                "for a reader (spoiler-light — establish premise, protagonist, and stakes). Also write a "
                "'cover_prompt': a detailed image prompt for the FRONT COVER that dramatizes the central hook or "
                "conflict of THIS story (the single most striking moment or image that would make someone pick up "
                "the comic), featuring the protagonist and the key tension/antagonist/setting. It must read like a "
                "real comic cover, not a generic hero pose, and must contain NO words, letters, or lettering.\n"
                "2. The CAST: identify the 2-5 main recurring CHARACTERS. For each, give a unique "
                "'name' and a highly detailed 'visual_description' (face, hair, build, clothing, colors, "
                "distinguishing features) — these descriptions will be used to draw character model sheets "
                "that keep the characters consistent across every panel.\n"
                "3. How many PAGES the comic should have (typically 3-6 pages)\n"
                "4. How many PANELS per page (typically 3-5 panels per page, varying for pacing)\n"
                "5. For EACH panel, choose an ORIENTATION — 'landscape', 'portrait', or 'square' — "
                "based on the shot (wide establishing/action shots suit landscape; tall figures, "
                "towers, or dramatic reveals suit portrait; balanced close-ups suit square).\n"
                "6. For EACH panel, list 'characters_present' — the exact names (from the CAST above) of the "
                "characters who appear in that panel (empty list if none).\n"
                "7. For EACH panel, write a clear one-sentence 'narration' in plain language stating exactly what "
                "is happening in that beat (who is doing what, where). A first-time reader must be able to follow "
                "the whole story just from the narration boxes in order.\n"
                "8. For EACH panel, optionally write one short line of 'dialogue' (a character's spoken line) that "
                "fits the beat — leave it empty if the panel needs no speech.\n"
                "9. For EACH panel, write a detailed 'image_prompt' that depicts EXACTLY the moment described in "
                "that panel's 'narration' (and 'dialogue' if any). The picture and the words MUST show the same "
                "moment — never describe a different scene than the narration.\n\n"
                "STORYTELLING RULES (critical):\n"
                "- The panels in order must tell ONE clear, followable story with cause and effect between beats.\n"
                "- Narration and dialogue must be CONCRETE and CLEAR — plain, grounded language. Do NOT write vague, "
                "elliptical, cryptic, or purely poetic fragments; a reader should always understand what is happening.\n\n"
                "Each image_prompt must be self-contained, including: art style (e.g. 'digital comic art, cinematic "
                "lighting, cel-shaded'), camera angle, characters present and their appearance, setting/background, "
                "mood/lighting/color, and the action.\n"
                "IMPORTANT: Do NOT render any words, letters, captions, speech bubbles, or text of any kind IN the "
                "artwork — keep the image clean. Dialogue and narration are shown separately in a caption box.\n\n"
                "You MUST respond with ONLY valid JSON in this exact format, no markdown, no explanation:\n"
                '{"title": "...", "synopsis": "...", "cover_prompt": "...",\n'
                '  "characters": [\n'
                '    {"name": "Elias", "visual_description": "..."},\n'
                '    {"name": "Ragna", "visual_description": "..."}\n'
                '  ],\n'
                '  "pages": [\n'
                '  {"page_number": 1, "panels": [\n'
                '    {"panel_number": 1, "shot_type": "wide establishing", "orientation": "landscape", "characters_present": ["Elias"], "narration": "Elias lights the lamp as the fog rolls in.", "dialogue": "...", "image_prompt": "..."},\n'
                '    {"panel_number": 2, "shot_type": "medium", "orientation": "square", "characters_present": ["Elias", "Ragna"], "narration": "...", "dialogue": "...", "image_prompt": "..."}\n'
                '  ]},\n'
                '  {"page_number": 2, "panels": [...]}\n'
                ']}\n\n'
                f"OUTLINE:\n{outline_content}\n\n"
                f"STORY THEME: {theme}\n"
                f"CHARACTER/WORLD DETAILS:\n{genesis_content[:2000]}"
            )
            
            layout_json = None
            try:
                layout_response = gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=layout_prompt
                )
                raw_text = layout_response.text.strip()
                # Strip markdown code fences if present
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3].strip()
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:].strip()
                
                layout_json = json.loads(raw_text)
                
                total_panels = sum(len(p.get("panels", [])) for p in layout_json.get("pages", []))
                total_pages = len(layout_json.get("pages", []))
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Head Writer', 'message': f'Comic layout decided: {total_pages} pages, {total_panels} panels total.', 'tool_calls': []})}\n\n"
                
                # Log the layout
                for page in layout_json.get("pages", []):
                    page_num = page.get("page_number", "?")
                    panel_count = len(page.get("panels", []))
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Head Writer', 'message': f'  Page {page_num}: {panel_count} panels', 'tool_calls': []})}\n\n"
                    
            except Exception as layout_err:
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': f'Warning: Layout planning failed ({layout_err}). Using fallback layout.', 'tool_calls': []})}\n\n"
            
            # Build fallback layout from parsed outline if Gemini layout failed
            if not layout_json or not layout_json.get("pages"):
                panels_list = parse_outline_panels(outline_content)
                # Distribute into pages of 3-4 panels each
                pages = []
                panels_per_page = 4
                for i in range(0, len(panels_list), panels_per_page):
                    page_panels = []
                    for j, p in enumerate(panels_list[i:i+panels_per_page]):
                        page_panels.append({
                            "panel_number": j + 1,
                            "shot_type": "medium",
                            "orientation": "landscape",
                            "narration": p.get("description", ""),
                            "image_prompt": f"Digital comic art, cinematic lighting. {p['description']}",
                            "dialogue": p.get("dialogue", ""),
                            "caption": ""
                        })
                    pages.append({"page_number": len(pages) + 1, "panels": page_panels})
                layout_json = {"pages": pages}
                
                total_panels = sum(len(p["panels"]) for p in pages)
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': f'Fallback layout: {len(pages)} pages, {total_panels} panels total.', 'tool_calls': []})}\n\n"
            
            # Save layout plan
            save_artifact_file("comic_layout.json", json.dumps(layout_json, indent=2), subdir=run_id)

            # ── Stage 5b: Illustrator draws the CAST first (character model sheets) ──
            # These reference sheets are fed into every panel so characters stay consistent.
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 5b: Illustrator drawing character model sheets...'})}\n\n"

            import re as _re
            characters = layout_json.get("characters", []) or []
            char_sheets = {}   # character name -> reference image filename (in artifacts)
            characters_out = []
            for idx, ch in enumerate(characters, start=1):
                cname = (ch.get("name") or f"character_{idx}").strip()
                cdesc = ch.get("visual_description", "") or ""
                slug = _re.sub(r"[^a-z0-9]+", "_", cname.lower()).strip("_") or f"character_{idx}"
                cfilename = f"char_{slug}.png"
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Illustrator', 'message': f'Drawing character sheet: {cname}...', 'tool_calls': []})}\n\n"
                try:
                    generate_character_sheet(name=cname, description=cdesc, filename=cfilename, subdir=run_id)
                    char_sheets[cname] = cfilename
                    characters_out.append({"name": cname, "filename": cfilename, "visual_description": cdesc})
                except Exception as ch_err:
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': f'Warning: character sheet failed for {cname}: {ch_err}', 'tool_calls': []})}\n\n"
            save_artifact_file("characters.json", json.dumps({"characters": characters_out}, indent=2), subdir=run_id)
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Illustrator', 'message': f'Drew {len(char_sheets)} character sheet(s). Now rendering panels with consistent characters.', 'tool_calls': []})}\n\n"

            # ── Stage 5c: Illustrator renders panels, conditioned on the character sheets ──
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 5c: Illustrator rendering panels (character-consistent)...'})}\n\n"

            all_panels_flat = []
            global_panel_idx = 0
            total_panels = sum(len(p.get("panels", [])) for p in layout_json.get("pages", []))
            
            for page in layout_json.get("pages", []):
                page_num = page.get("page_number", 1)
                page_panels = page.get("panels", [])
                
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Illustrator', 'message': f'Starting Page {page_num} ({len(page_panels)} panels)...', 'tool_calls': []})}\n\n"
                
                for panel in page_panels:
                    global_panel_idx += 1
                    panel_num_in_page = panel.get("panel_number", 1)
                    shot_type = panel.get("shot_type", "medium")
                    orientation = panel.get("orientation", "landscape")
                    image_prompt = panel.get("image_prompt", "Comic panel scene")
                    narration = panel.get("narration", "")
                    dialogue = panel.get("dialogue", "")
                    caption = panel.get("caption", "")
                    characters_present = panel.get("characters_present", []) or []

                    # Look up the character model sheets for the cast in this panel.
                    reference_images = [char_sheets[n] for n in characters_present if n in char_sheets]

                    # Sequential global filenames (panel_1.png, panel_2.png, ...) so the
                    # frontend, startup cleanup, and comic_production.json all stay in sync.
                    filename = f"panel_{global_panel_idx}.png"

                    cast_note = f" [cast: {', '.join(characters_present)}]" if characters_present else ""
                    prompt_snippet = image_prompt[:70]
                    yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Illustrator', 'message': f'[{global_panel_idx}/{total_panels}] Page {page_num}, Panel {panel_num_in_page} ({shot_type}, {orientation}){cast_note}: {prompt_snippet}...', 'tool_calls': []})}\n\n"

                    try:
                        generate_panel_image(filename=filename, prompt=image_prompt,
                                             orientation=orientation, reference_images=reference_images,
                                             subdir=run_id)
                    except Exception as img_err:
                        yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': f'Warning: Image generation failed for {filename}: {img_err}', 'tool_calls': []})}\n\n"

                    yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Illustrator', 'message': f'Completed {filename}', 'tool_calls': []})}\n\n"

                    all_panels_flat.append({
                        "page": page_num,
                        "panel": panel_num_in_page,
                        "filename": filename,
                        "shot_type": shot_type,
                        "orientation": orientation,
                        "characters_present": characters_present,
                        "description": image_prompt,
                        "narration": narration,
                        "dialogue": dialogue,
                        "caption": caption
                    })
            
            # Derive title / synopsis / genre for the cover page.
            import re as _re2
            genre_match = _re2.search(r"\(genre:\s*([^)]+)\)", theme, _re2.IGNORECASE)
            genre = genre_match.group(1).strip() if genre_match else ""
            comic_title = (layout_json.get("title") or theme).strip()
            comic_synopsis = (layout_json.get("synopsis") or "").strip()

            # ── Cover art: a splash that dramatizes THIS story's central hook ──
            # Always attempt a cover (even when the fallback layout produced no cast).
            cover_image = ""
            hero = characters_out[0]["name"] if characters_out else ""
            hero_sheet = char_sheets.get(hero) if hero else None
            head_cover = (layout_json.get("cover_prompt") or "").strip()
            if head_cover:
                # Use the Head Writer's story-specific cover concept.
                cover_prompt = (
                    f"Comic book front cover for '{comic_title}', a {genre or 'story'}. "
                    f"{head_cover} "
                    f"Dramatic cinematic splash composition, vivid saturated colors, high detail, "
                    f"portrait cover art. Absolutely no words, letters, logos, or lettering in the image."
                )
            else:
                # Fallback: build a cover concept from the synopsis so it still depicts the story.
                hero_bit = f", featuring the hero {hero}" if hero else ""
                cover_prompt = (
                    f"Comic book front cover for '{comic_title}', a {genre or 'story'}{hero_bit}. "
                    f"Dramatize the central hook of this story: {comic_synopsis[:320]} "
                    f"Dramatic cinematic splash composition, vivid colors, portrait cover art. "
                    f"Absolutely no words, letters, or lettering in the image."
                )
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'Illustrator', 'message': 'Painting the comic cover...', 'tool_calls': []})}\n\n"
            try:
                generate_panel_image(filename="cover_art.png", prompt=cover_prompt,
                                     orientation="portrait",
                                     reference_images=[hero_sheet] if hero_sheet else None,
                                     subdir=run_id)
                cover_image = "cover_art.png"
            except Exception as cov_err:
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': f'Cover art skipped: {cov_err}', 'tool_calls': []})}\n\n"

            # Write final comic_production.json with full page/panel structure
            comic_data = {
                "title": comic_title,
                "synopsis": comic_synopsis,
                "genre": genre,
                "cover_image": cover_image,
                "total_pages": len(layout_json.get("pages", [])),
                "total_panels": len(all_panels_flat),
                "characters": characters_out,
                "pages": layout_json.get("pages", []),
                "panels": all_panels_flat
            }
            save_artifact_file("comic_production.json", json.dumps(comic_data, indent=2), subdir=run_id)
            num_pages = len(layout_json.get("pages", []))
            save_msg = f'Saved comic_production.json ({len(all_panels_flat)} panels across {num_pages} pages)'
            yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': save_msg, 'tool_calls': []})}\n\n"

            # ── Stage 6: Compile the comic into a downloadable PDF ──
            yield f"data: {json.dumps({'event': 'start', 'message': 'Stage 6: Compiling comic PDF...'})}\n\n"
            try:
                pdf_result = build_comic_pdf("comic.pdf", subdir=run_id)
                if pdf_result.get("status") == "success":
                    pdf_pages = pdf_result.get("pages")
                    pdf_msg = f"Compiled comic.pdf ({pdf_pages} pages)."
                else:
                    pdf_msg = f"PDF build skipped: {pdf_result.get('message')}"
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': pdf_msg, 'tool_calls': []})}\n\n"
            except Exception as pdf_err:
                yield f"data: {json.dumps({'event': 'agent_message', 'author': 'System', 'message': f'Warning: PDF compilation failed: {pdf_err}', 'tool_calls': []})}\n\n"

            yield f"data: {json.dumps({'event': 'complete', 'message': 'Story storyboard generation complete!'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': f'Error during pipeline execution: {str(e)}'})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/comic_pdf")
def comic_pdf(run_id: str = None, rebuild: bool = False):
    """Return the compiled comic PDF for a run. Set ?rebuild=true to regenerate from artifacts."""
    from fastapi.responses import FileResponse, JSONResponse
    from app.tools import build_comic_pdf
    base = os.path.join(ARTIFACTS_DIR, run_id) if run_id else ARTIFACTS_DIR
    pdf_path = os.path.join(base, "comic.pdf")
    if rebuild or not os.path.exists(pdf_path):
        result = build_comic_pdf("comic.pdf", subdir=run_id)
        if result.get("status") != "success":
            return JSONResponse(status_code=404, content=result)
    if not os.path.exists(pdf_path):
        return JSONResponse(status_code=404, content={"status": "error", "message": "comic.pdf not found"})
    return FileResponse(pdf_path, media_type="application/pdf", filename="comic.pdf")

@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.log_struct(feedback.model_dump(), severity="INFO")
    return {"status": "success"}

# Serve built frontend static files
if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")

# Main execution
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
