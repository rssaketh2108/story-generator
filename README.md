# Multi-Agent Story Genesis Portal

An interactive, multi-agent comic storyboard creation application built using the Google Agent Development Kit (ADK) and the Agent-to-Agent (A2A) communication protocol.

## 🎭 The Agent Council & Pipeline
The application orchestrates a team of 4 primary A2A agents and 4 nested room agents to carry out a 5-step structured story production pipeline:
1.  **Step 1: Character & World Genesis** (Head Writer + Council of Agents)
2.  **Step 2: Room & Canvas** (Council expands arcs, Illustrator researches visual themes)
3.  **Step 3: Breaking the Story** (Council debates plot twists and synopses)
4.  **Step 4: Master Outline** (Outline Writer drafts panel breakdowns and dialogue scripts)
5.  **Step 5: Scripting & Production** (Head Writer checks continuity, Illustrator draws panels)

The Council of Agents debates are carried out by models representing **Claude, Codex, Kimi, and Minimax** (leveraging LiteLLM with fallback).

---

## 🚀 Running the Project

To run this app locally, you will run the Python backend (FastAPI) and the React frontend (Vite) concurrently.

### 1. Start the Python Backend
First, ensure you are in the `story-generator` root directory.
Install Python dependencies (if you haven't already):
```bash
agents-cli install
```

Start the FastAPI application on port `8000`:
```bash
uv run python -m app.fast_api_app
```
The A2A endpoints will be active at:
*   Head Writer: `http://localhost:8000/a2a/head_writer`
*   Council: `http://localhost:8000/a2a/council`
*   Illustrator: `http://localhost:8000/a2a/illustrator`
*   Outline Writer: `http://localhost:8000/a2a/outline_writer`

### 2. Start the React Frontend
Open a new terminal window, navigate to the `frontend/` directory, and start the development server:
```bash
cd frontend
npm run dev
```
Open `http://localhost:5173` in your browser to access the Storyboard control deck.

---

## 🛠️ Tech Stack & Architecture
*   **Backend**: Python, FastAPI, Google ADK (for Agent orchestration, Session runner, and A2A schema wrappers), LiteLLM (for multi-model support).
*   **Frontend**: React (TypeScript), Vite, custom modern CSS (cyberpunk dark-mode aesthetic).
*   **Tools**: Pillow (for rendering panel canvas mockups), Stdio connection wrappers.

