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
import sys
from dotenv import load_dotenv

# Load .env configurations first
load_dotenv()

import google.auth
from google.adk.agents import Agent, LoopAgent, SequentialAgent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.models.lite_llm import LiteLlm
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.genai import types

# Configure Vertex AI Env Vars if ADC credentials are present
try:
    _, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
except Exception:
    pass

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"

# Check if we should use Google AI Studio (API Key) or Vertex AI (ADC credentials)
if os.getenv("GEMINI_API_KEY"):
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"

from app.tools import (
    save_artifact_file,
    read_artifact_file,
    search_web_tool,
    generate_panel_image,
)

# Helper function to load LiteLLM models with safety fallback to Gemini
def get_llm_model(model_name: str, env_var: str):
    """Return a LiteLlm model for the given provider, or fall back to Gemini.

    LiteLlm construction never fails on a bad/underfunded key — the provider only
    rejects calls at runtime (e.g. Anthropic 400 "credit balance too low"). A single
    such failure inside the council LoopAgent crashes the whole debate, so we run a
    cheap health probe here and transparently fall back to Gemini when a provider is
    unavailable. This keeps the room running even if one model is down.
    """
    gemini_fallback = Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    )
    if not os.getenv(env_var):
        return gemini_fallback

    # Avoid blocking network calls or polluting stdout during deployment/introspection
    if os.getenv("SKIP_PROBE") or os.getenv("DEPLOYING") or os.getenv("AGENT_ENGINE_INTROSPECTION") or not sys.stdout.isatty():
        try:
            return LiteLlm(model=model_name)
        except Exception as e:
            print(f"Could not construct LiteLlm for '{model_name}' ({e}). Falling back to Gemini.", file=sys.stderr)
            return gemini_fallback

    try:
        model = LiteLlm(model=model_name)
    except Exception as e:
        print(f"Could not construct LiteLlm for '{model_name}' ({e}). Falling back to Gemini.", file=sys.stderr)
        return gemini_fallback

    import litellm
    try:
        # Probe with a small (not 1-token) budget so reasoning models don't trip the
        # output limit. We only care whether the provider accepts the request.
        litellm.completion(
            model=model_name,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=16,
            timeout=20,
        )
        print(f"Council model '{model_name}' is available.", file=sys.stderr)
    except (litellm.AuthenticationError, litellm.NotFoundError, litellm.PermissionDeniedError) as e:
        # Fatal: bad key, no access, or wrong model ID → use Gemini instead.
        print(
            f"Council model '{model_name}' unavailable ({type(e).__name__}: {str(e)[:140]}). "
            f"Falling back to Gemini for this agent.",
            file=sys.stderr
        )
        return gemini_fallback
    except Exception as e:
        # Benign (output-limit, rate limit, transient): the provider is reachable and
        # authorized, so keep the real model rather than downgrading.
        print(f"Council model '{model_name}' probe inconclusive ({type(e).__name__}); using it anyway.", file=sys.stderr)
    return model

def ask_head_writer(question: str) -> str:
    """Asks the Head Writer for feedback, direction, or clarification during the writer's room debate.
    
    Args:
        question: The question or pitch to send to the Head Writer.
        
    Returns:
        The Head Writer's feedback and direction.
    """
    print(f"\n[INTERACTION] Sub-agent asked Head Writer: {question}")
    from google.genai import Client
    client = Client(api_key=os.getenv("GEMINI_API_KEY"))
    prompt = (
        "You are the Head Writer coordinating the writer's room storyboard pipeline. "
        f"A sub-agent in the debate has asked you the following question: '{question}'.\n\n"
        "Please butt in, critique their direction, and provide guidance, recommendations, "
        "and direct creative feedback to shape the storyboard consensus."
    )
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        text = response.text if hasattr(response, "text") else str(response)
        print(f"[INTERACTION] Head Writer butt in: {text}\n")
        return text
    except Exception as e:
        err = f"Failed to get feedback from Head Writer: {e}"
        print(f"[ERROR] {err}")
        return err

# 1. Define the Council sub-agents representing different LLMs
claude_agent = Agent(
    name="claude_critic",
    model=get_llm_model("anthropic/claude-sonnet-4-6", "ANTHROPIC_API_KEY"),
    instruction=(
        "You are Claude, the critical guardian of theme and character in the writer's room. "
        "You are in a live creative debate with Codex and Kimi. "
        "You MUST read their previous suggestions in the conversation history, critique their worldbuilding and visual choices, "
        "and defend the thematic core of the specific story theme currently being developed (do NOT import themes from other stories). "
        "If you want guidance, need feedback on a key decision, or the debate stalls, call the 'ask_head_writer' tool immediately to get direction."
    ),
    tools=[ask_head_writer],
)

codex_agent = Agent(
    name="codex_worldbuilder",
    model=get_llm_model("openai/gpt-5.4-mini", "OPENAI_API_KEY"),
    instruction=(
        "You are Codex, the structural architect of the world in the writer's room. "
        "You are in a live creative debate with Claude and Kimi. "
        "You MUST read their suggestions and critiques, build out the technological systems and consistent world rules, "
        "and respond to Claude's critiques with creative structural solutions. "
        "If you want guidance, need feedback on a key decision, or the debate stalls, call the 'ask_head_writer' tool immediately to get direction."
    ),
    tools=[ask_head_writer],
)

kimi_agent = Agent(
    name="kimi_polisher",
    model=get_llm_model("moonshot/kimi-k2.6", "MOONSHOT_API_KEY"),
    instruction=(
        "You are Kimi, the narrative designer and stylist in the writer's room. "
        "You are in a live creative debate with Claude and Codex. "
        "You MUST read their ideas, polish the language, add sensory and aesthetic details, and harmonize their views. "
        "If you want guidance, need feedback on a key decision, or the debate stalls, call the 'ask_head_writer' tool immediately to get direction."
    ),
    tools=[ask_head_writer],
)

# 2. Define the main Council Agent (Head Writer's Room)
# NOTE: We do NOT use an LLM coordinator with sub_agents here. That pattern relies on
# LLM-driven `transfer_to_agent` handoffs, which caused the debaters to merely emit a
# one-line meta-statement and immediately transfer (returning {'result': None}) instead
# of producing substantive pitches. A LoopAgent invokes each debater DIRECTLY and in
# turn, so Claude, Codex, and Kimi each contribute real content every round, and each
# sees the others' prior turns via the shared session.
debate_room = LoopAgent(
    name="debate_room",
    description="Runs the interactive writer's room debate across Claude, Codex, and Kimi.",
    sub_agents=[claude_agent, codex_agent, kimi_agent],
    max_iterations=2,  # 3 agents x 2 rounds = 6 substantive debate turns
)

# A final synthesizer distills the debate into one unified, clean consensus document.
synthesizer_agent = Agent(
    name="council_synthesizer",
    model=Gemini(model="gemini-flash-latest", retry_options=types.HttpRetryOptions(attempts=3)),
    description="Synthesizes the writer's room debate into a single unified pitch.",
    instruction=(
        "You are the Head Writer. Read the ENTIRE writer's room debate above (the turns from "
        "Claude, Codex, and Kimi). Synthesize their collaboration into ONE unified, well-structured "
        "pitch in clean markdown, resolving disagreements and keeping the strongest ideas from each. "
        "Write CONCRETELY and ACCESSIBLY: a reader should clearly follow the premise, the characters, and "
        "a cause-and-effect plot. Avoid abstract, elliptical, or purely poetic fragments — favor a clear, "
        "grounded story that could be storyboarded into understandable panels. "
        "Output ONLY the final consensus document. Do NOT call any tools."
    ),
)

# The council runs the debate to completion, then synthesizes the consensus.
council_agent = SequentialAgent(
    name="council",
    description="The creative council that debates plots, characters, and structures the story.",
    sub_agents=[debate_room, synthesizer_agent],
)

# 3. Define the Illustrator Agent
illustrator_tools = [search_web_tool, generate_panel_image, save_artifact_file]

# Dynamically add Chrome/Brave Search MCP toolset if configured
chrome_mcp_cmd = os.getenv("CHROME_MCP_COMMAND")
chrome_mcp_args = os.getenv("CHROME_MCP_ARGS")
if chrome_mcp_cmd:
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters
        
        args_list = chrome_mcp_args.split(",") if chrome_mcp_args else []
        chrome_mcp = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=chrome_mcp_cmd,
                    args=args_list,
                )
            )
        )
        illustrator_tools.append(chrome_mcp)
        print("Successfully loaded Chrome MCP toolset.", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not load Chrome MCP: {e}", file=sys.stderr)

# Dynamically add Image Generator MCP toolset if configured (supports Stdio and Remote SSE)
image_mcp_cmd = os.getenv("IMAGE_MCP_COMMAND")
image_mcp_args = os.getenv("IMAGE_MCP_ARGS")
image_mcp_url = os.getenv("IMAGE_MCP_URL")

if image_mcp_url:
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import SseConnectionParams
        
        headers = {}
        api_key = os.getenv("IDEOGRAM_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            
        image_mcp = McpToolset(
            connection_params=SseConnectionParams(
                url=image_mcp_url,
                headers=headers if headers else None
            )
        )
        illustrator_tools.append(image_mcp)
        print(f"Successfully loaded Remote SSE Image Generator MCP: {image_mcp_url}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not load Remote Image Gen MCP: {e}", file=sys.stderr)
elif image_mcp_cmd:
    try:
        from google.adk.tools.mcp_tool import McpToolset
        from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
        from mcp import StdioServerParameters
        
        args_list = image_mcp_args.split(",") if image_mcp_args else []
        image_mcp = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=image_mcp_cmd,
                    args=args_list,
                )
            )
        )
        illustrator_tools.append(image_mcp)
        print("Successfully loaded Stdio Image Generator MCP toolset.", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not load Stdio Image Gen MCP: {e}", file=sys.stderr)

illustrator_agent = Agent(
    name="illustrator",
    model=Gemini(model="gemini-flash-latest"),
    description="The illustrator agent that researches themes and creates visual character designs and panel art.",
    instruction=(
        "You are the Illustrator. Your job is to research visual themes and generate visual designs. "
        "You must: "
        "1. Research appearance details and themes using available search tools or Chrome MCP. "
        "2. Create detailed visual descriptions of the characters and the world. "
        "3. Generate panel images for the script using available image generation tools or generate_panel_image. "
        "You MUST save the generated comic panel images using the exact filenames requested by the coordinator (e.g. 'panel_1.png', 'panel_2.png', 'panel_3.png', etc., sequentially). Do NOT use custom names."
    ),
    tools=illustrator_tools,
)

# 4. Define the Outline Writer Agent
outline_writer_agent = Agent(
    name="outline_writer",
    model=Gemini(model="gemini-flash-latest"),
    description="The outline writer that drafts page-by-page panel breakdowns and dialogues.",
    instruction=(
        "You are the Outline Writer. You take plot points and story synopses and convert them into "
        "a master outline containing a panel-by-panel script. "
        "A real comic book has MANY panels — you MUST produce between 12 and 20 panels total, "
        "spread across multiple pages (3-5 pages, 3-5 panels per page). "
        "\n\nYou MUST use EXACTLY this format for EVERY panel — no prose, no summaries, no markdown headers:\n"
        "Panel 1: [Detailed visual description of the shot — camera angle, characters, setting, action, lighting, mood]\n"
        "Dialogue: [Character name]: [What they say]\n\n"
        "Panel 2: [Next visual description]\n"
        "Dialogue: [Character name]: [What they say]\n\n"
        "...and so on for ALL panels.\n\n"
        "CRITICAL RULES:\n"
        "- Every panel line MUST start with 'Panel N:' where N is the sequential number\n"
        "- Every panel MUST have a 'Dialogue:' line immediately after it\n"
        "- The panels in order must tell ONE clear, followable story with cause and effect between beats\n"
        "- Write CONCRETELY and CLEARLY: the visual description and dialogue must make it obvious what is "
        "happening. Do NOT use vague, elliptical, cryptic, or purely poetic fragments\n"
        "- The visual description and the dialogue in a panel must describe the SAME moment\n"
        "- Do NOT write summaries, headers, or explanations — ONLY the panel lines\n"
        "- Do NOT call save_artifact_file — just output the panel text directly\n"
        "- Vary shot types: wide establishing, medium, close-up, over-shoulder, bird's eye, low angle, splash page"
    ),
    tools=[save_artifact_file, read_artifact_file],
)

# A2A Remote Agent declarations (referencing endpoints served on localhost:8000)
council_remote = RemoteA2aAgent(
    name="council_remote",
    agent_card="http://localhost:8000/a2a/council/.well-known/agent-card.json",
    description="The creative council that debates plots, characters, and structures the story.",
)

illustrator_remote = RemoteA2aAgent(
    name="illustrator_remote",
    agent_card="http://localhost:8000/a2a/illustrator/.well-known/agent-card.json",
    description="The illustrator agent that researches themes and creates visual character designs and panel art.",
)

outline_writer_remote = RemoteA2aAgent(
    name="outline_writer_remote",
    agent_card="http://localhost:8000/a2a/outline_writer/.well-known/agent-card.json",
    description="The outline writer that drafts page-by-page panel breakdowns and dialogues.",
)

# 5. Define the Head Writer (Root Coordinator Agent)
head_writer_agent = Agent(
    name="head_writer",
    model=Gemini(model="gemini-flash-latest"),
    instruction=(
        "You are the Head Writer, coordinating the multi-agent storyboard pipeline. "
        "You MUST run the entire 5-stage pipeline autonomously from start to finish in a single session, without stopping to ask the user questions or waiting for feedback. Do all steps sequentially: "
        "1. Character & World Genesis: Call 'council_remote' to pitch character concepts, flaws, and world rules. You MUST save this consensus exactly to 'genesis.md' using save_artifact_file. Do NOT use any other filename. "
        "2. Room & Canvas: Direct 'council_remote' to expand character arcs, and 'illustrator_remote' to research themes and create visual traits and region details. You MUST save this canvas exactly to 'canvas.md' using save_artifact_file. Do NOT use any other filename. "
        "3. Breaking the Story: Lead 'council_remote' to debate and create the main plot, twists, and ending. You MUST save this plot exactly to 'plot.md' using save_artifact_file. Do NOT use any other filename. "
        "4. Master Outline: Send the plot notes to 'outline_writer_remote' to write a page-by-page panel and dialogue script. You MUST save this outline exactly to 'outline.md' using save_artifact_file. Do NOT use any other filename. "
        "5. Production: Parse the generated 'outline.md' to extract all pages and panels. For each panel in the outline, trigger 'illustrator_remote' to generate panel images named exactly 'panel_1.png', 'panel_2.png', 'panel_3.png', etc. sequentially. You MUST compile the final panels list and save it exactly as 'comic_production.json' in this JSON format:\n"
        "{\n"
        "  \"panels\": [\n"
        "    {\n"
        "      \"filename\": \"panel_1.png\",\n"
        "      \"description\": \"detailed prompt describing visual scene for panel 1\",\n"
        "      \"dialogue\": \"narration caption/speech bubbles for panel 1\"\n"
        "    },\n"
        "    ...\n"
        "  ]\n"
        "}\n"
        "Do NOT ask the user for permission or wait for feedback between steps. Run them continuously and automatically. Output progress updates to the user at the end of each step."
    ),
    sub_agents=[council_remote, illustrator_remote, outline_writer_remote],
    tools=[save_artifact_file, read_artifact_file],
)

from google.adk.plugins.base_plugin import BasePlugin

class BudgetGuardPlugin(BasePlugin):
    """Enforces a shared dollar spend budget limit across all agent model calls in a session."""
    def __init__(self, budget_usd: float = 15.0):
        super().__init__(name="budget_guard")
        self.budget_usd = budget_usd

    async def after_model_callback(self, *, callback_context, llm_response):
        if not llm_response or not llm_response.usage_metadata:
            return None

        prompt_tokens = llm_response.usage_metadata.prompt_token_count or 0
        output_tokens = llm_response.usage_metadata.candidates_token_count or 0

        # Get the model name being used via the invocation context agent
        agent = None
        if hasattr(callback_context, "_invocation_context") and callback_context._invocation_context:
            agent = callback_context._invocation_context.agent
            
        if agent and hasattr(agent, "model") and agent.model:
            model = agent.model
            model_name = getattr(model, "model", str(model))
        else:
            model_name = "gemini-flash"

        # Cost rates per 1,000,000 tokens
        input_rate = 0.075 / 1_000_000   # default: Gemini Flash
        output_rate = 0.30 / 1_000_000  # default: Gemini Flash

        lower_model = model_name.lower()
        if "claude-5" in lower_model:
            # Estimate Claude 5 Sonnet rates (assuming standard Sonnet tier)
            input_rate = 3.00 / 1_000_000
            output_rate = 15.00 / 1_000_000
        elif "claude" in lower_model:
            input_rate = 3.00 / 1_000_000
            output_rate = 15.00 / 1_000_000
        elif "mini" in lower_model:
            # Low cost mini tier (e.g. gpt-5.4-mini)
            input_rate = 0.15 / 1_000_000
            output_rate = 0.60 / 1_000_000
        elif "gpt-4" in lower_model or "gpt-3.5" in lower_model:
            input_rate = 2.50 / 1_000_000
            output_rate = 10.00 / 1_000_000
        elif "instant" in lower_model:
            # Fast/low-cost instant tier (e.g. kimi-k2.6-instant)
            input_rate = 0.50 / 1_000_000
            output_rate = 0.50 / 1_000_000
        elif "moonshot" in lower_model or "kimi" in lower_model:
            input_rate = 1.65 / 1_000_000
            output_rate = 1.65 / 1_000_000

        # Calculate transaction cost
        cost = (prompt_tokens * input_rate) + (output_tokens * output_rate)

        # Accumulate in shared session state
        state = callback_context.state
        current_spent = state.get("budget_guard:spent", 0.0)
        new_spent = current_spent + cost
        state["budget_guard:spent"] = new_spent

        if new_spent > self.budget_usd:
            raise ValueError(
                f"Budget Limit Exceeded! Session accumulated ${new_spent:.4f} USD, "
                f"which exceeds the safety budget limit of ${self.budget_usd:.2f} USD."
            )
        return None

# Define ADK App wrappers with BudgetGuard enabled
budget_guard = BudgetGuardPlugin(budget_usd=15.0)

head_writer_app = App(root_agent=head_writer_agent, name="head_writer", plugins=[budget_guard])
council_app = App(root_agent=council_agent, name="council", plugins=[budget_guard])
illustrator_app = App(root_agent=illustrator_agent, name="illustrator", plugins=[budget_guard])
outline_writer_app = App(root_agent=outline_writer_agent, name="outline_writer", plugins=[budget_guard])

# Maintain CLI entry point compatibility by assigning root app to 'app'
app = head_writer_app

# ADK CLI / test convention: expose the top-level coordinator as `root_agent`
root_agent = head_writer_agent
