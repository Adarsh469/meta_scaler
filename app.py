"""
app.py — Hugging Face Spaces entry point for ClinicalTriage-Env
================================================================
Starts the FastAPI backend on port 7861 (background thread),
then launches a Gradio UI on port 7860 (HF public port).

  http://localhost:7860  ← Gradio interface (what HF Spaces exposes)
  http://localhost:7861  ← FastAPI / OpenEnv API (internal)
"""

import json
import os
import sys
import threading
import time
import uuid

import httpx
import gradio as gr
import uvicorn

# ── Make sure imports from this directory work ─────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

# ── Config ─────────────────────────────────────────────────────────────────
API_PORT  = 7860          # Unified port for both Gradio and API
GRAD_PORT = 7860
API_BASE  = f"http://localhost:{API_PORT}"

TASKS = {
    "task1_esi_assignment":  ("Task 1 — ESI Assignment",      "Easy",   "🟢"),
    "task2_queue_priority":  ("Task 2 — Queue Prioritization", "Medium", "🟡"),
    "task3_ambiguous_triage":("Task 3 — Ambiguous Triage",    "Hard",   "🔴"),
}

# Default JSON actions for each task (helpful starting template)
DEFAULT_ACTIONS = {
    "task1_esi_assignment":   json.dumps({"action_type": "assign_esi", "esi_level": 3}, indent=2),
    "task2_queue_priority":   json.dumps({"action_type": "reorder_queue", "queue_order": []}, indent=2),
    "task3_ambiguous_triage": json.dumps({"action_type": "ask_question",  "question_topic": "medications"}, indent=2),
}


# ── Setup FastAPI ──────────────────────────────────────────────────────────
from server import app as fastapi_app
fastapi_app.title = "ClinicalTriage-Env (Unified Engine)"


# ── Helpers ────────────────────────────────────────────────────────────────
def _post(path: str, payload: dict) -> dict:
    r = httpx.post(f"{API_BASE}{path}", json=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def _get(path: str) -> dict:
    r = httpx.get(f"{API_BASE}{path}", timeout=10)
    r.raise_for_status()
    return r.json()

def _fmt(d: dict) -> str:
    return json.dumps(d, indent=2, default=str)

def _session() -> str:
    return "hf-" + uuid.uuid4().hex[:8]


# ── AI agent logic (mirrors dashboard runAIAgent) ──────────────────────────
def _run_agent(task_id: str, session_id: str):
    """Generator that yields log lines while running the AI agent."""
    yield f"[START] task={task_id} session={session_id}\n"

    try:
        res = _post("/reset", {"task_id": task_id, "session_id": session_id})
        obs = res["observation"]
        yield f"[RESET] {_fmt(obs)}\n\n"
    except Exception as e:
        yield f"[ERROR] Reset failed: {e}\n"
        return

    for step in range(1, 15):
        action: dict = {}

        if task_id == "task1_esi_assignment":
            syms = obs.get("patient", {}).get("symptoms", [])
            critical = any(s in syms for s in ["chest pain", "shortness of breath", "blurred vision", "altered mental status"])
            high     = any(s in syms for s in ["severe headache", "syncope", "difficulty breathing"])
            esi      = 1 if (critical and len(syms) >= 3) else 2 if critical else 2 if high else 3 if len(syms) >= 3 else 4
            action   = {"action_type": "assign_esi", "esi_level": esi, "session_id": session_id}

        elif task_id == "task2_queue_priority":
            queue   = obs.get("queue", [])
            crit    = {"chest pain", "shortness of breath", "blurred vision", "altered mental status"}
            hi      = {"severe headache", "syncope", "difficulty breathing"}
            scored  = sorted(queue,
                             key=lambda p: (
                                 sum(1 for s in p["symptoms"] if s in crit) * 20 +
                                 sum(1 for s in p["symptoms"] if s in hi)   * 10 +
                                 p.get("symptom_count", 0)
                             ),
                             reverse=True)
            action  = {"action_type": "reorder_queue",
                       "queue_order": [p["case_id"] for p in scored],
                       "session_id": session_id}

        else:  # task3
            budget = obs.get("clarification_budget", 0)
            if budget > 0 and not obs.get("awaiting_final_esi"):
                topics = ["medications", "allergies", "current_symptoms"]
                topic  = topics[min(3 - budget, len(topics) - 1)]
                action = {"action_type": "ask_question", "question_topic": topic, "session_id": session_id}
            else:
                syms  = obs.get("patient", {}).get("symptoms", [])
                msg   = obs.get("message", "").lower()
                contra = any(k in msg for k in ["warfarin", "anticoagulant", "clopidogrel", "insulin", "prednisone"])
                crit   = any(s in syms for s in ["chest pain", "shortness of breath", "blurred vision"])
                action = {"action_type": "assign_esi",
                          "esi_level": 1 if (crit or contra) else 3,
                          "session_id": session_id}

        try:
            result = _post("/step", action)
            obs    = result["observation"]
            reward = result["reward"]
            done   = result["done"]
            yield (
                f"[STEP {step}] action={json.dumps(action)}\n"
                f"  reward={reward:.4f}  done={done}\n"
                f"  obs={_fmt(obs)}\n\n"
            )
            if done:
                yield f"[END] Final reward={reward:.4f} ({'✅ SUCCESS' if reward >= 0.5 else '❌ BELOW THRESHOLD'})\n"
                break
        except Exception as e:
            yield f"[ERROR] Step {step}: {e}\n"
            break


# ── Gradio UI ──────────────────────────────────────────────────────────────

CSS = """
#title { text-align: center; font-size: 2em; font-weight: 700; margin-bottom: 0.2em; }
#subtitle { text-align: center; color: #888; margin-bottom: 1.5em; }
.task-badge-easy   { color: #22c55e; font-weight: 600; }
.task-badge-medium { color: #eab308; font-weight: 600; }
.task-badge-hard   { color: #ef4444; font-weight: 600; }
#obs-box textarea  { font-family: monospace; font-size: 0.78em; }
#resp-box textarea { font-family: monospace; font-size: 0.78em; }
#log-box textarea  { font-family: monospace; font-size: 0.75em; background: #0d1117; color: #7ee787; }
"""

def _task_info(task_id: str) -> str:
    meta = {
        "task1_esi_assignment": (
            "**Task 1 – Single Patient ESI Assignment** 🟢 Easy\n\n"
            "Receive one patient (age, gender, symptoms) and assign the correct "
            "Emergency Severity Index level (1 = Immediate → 5 = Non-urgent).\n\n"
            "**Reward:** 1.0 for exact match · 0.4 for ±1 · 0.0 otherwise.\n"
            "**Success threshold:** ≥ 0.5"
        ),
        "task2_queue_priority": (
            "**Task 2 – Patient Queue Prioritization** 🟡 Medium\n\n"
            "Receive 5 patients simultaneously. Return them ordered from most → least urgent.\n\n"
            "**Reward:** Normalised Kendall-Tau rank correlation.\n"
            "**Success threshold:** ≥ 0.6"
        ),
        "task3_ambiguous_triage": (
            "**Task 3 – Ambiguous Triage with Hidden History** 🔴 Hard\n\n"
            "Patient has hidden risk factors (meds, allergies, contraindications). "
            "Use `ask_question` actions to uncover hidden history, then assign ESI.\n\n"
            "**Reward:** Base 1.0 + 0.3 bonus for catching contraindications.\n"
            "**Success threshold:** ≥ 0.7"
        ),
    }
    return meta.get(task_id, "")

def _code_snippet(task_id: str) -> str:
    return f"""\
from env import ClinicalTriageEnv
env = ClinicalTriageEnv()
obs = env.reset("{task_id}")
print(obs)
"""

with gr.Blocks(title="ClinicalTriage-Env") as demo:

    # ── Header ───────────────────────────────────────────────────────────
    gr.Markdown("# 🏥 ClinicalTriage-Env", elem_id="title")
    gr.Markdown(
        "Emergency Department triage simulator · OpenEnv compliant · "
        "[API docs](http://localhost:7861/docs)",
        elem_id="subtitle",
    )

    # Shared session state
    session_state = gr.State(value=_session)

    with gr.Row():
        # ── Left sidebar ────────────────────────────────────────────────
        with gr.Column(scale=1, min_width=280):
            gr.Markdown("### SELECT TASK")
            task_radio = gr.Radio(
                choices=[
                    ("🟢 Task 1 — ESI Assignment (Easy)",         "task1_esi_assignment"),
                    ("🟡 Task 2 — Queue Prioritization (Medium)", "task2_queue_priority"),
                    ("🔴 Task 3 — Ambiguous Triage (Hard)",       "task3_ambiguous_triage"),
                ],
                value="task1_esi_assignment",
                label="",
                interactive=True,
            )

            task_desc = gr.Markdown(_task_info("task1_esi_assignment"))

            gr.Markdown("---")
            gr.Markdown("### QUICK CONNECT")
            code_box = gr.Textbox(
                value=_code_snippet("task1_esi_assignment"),
                label="Python",
                lines=5,
                interactive=False,
            )

            gr.Markdown("### SERVER")
            gr.Markdown(
                f"**Base:** `http://localhost:{API_PORT}`  \n"
                f"**API docs:** [/docs](http://localhost:{API_PORT}/docs)"
            )

        # ── Main panel ──────────────────────────────────────────────────
        with gr.Column(scale=3):
            with gr.Tabs() as main_tabs:

                # ── Tab 1: Manual Play ───────────────────────────────
                with gr.Tab("🎮 Manual Play"):
                    gr.Markdown(
                        "Interact step-by-step. Edit the JSON action and click **Step**."
                    )

                    with gr.Row():
                        reset_btn = gr.Button("🔄 Reset", variant="secondary")
                        state_btn = gr.Button("📋 State", variant="secondary")
                        new_session_btn = gr.Button("🆕 New Session", variant="secondary")

                    obs_box = gr.Textbox(
                        label="Current Observation",
                        lines=12,
                        interactive=False,
                        elem_id="obs-box",
                        placeholder="Click Reset to start a new episode…",
                    )

                    action_box = gr.Textbox(
                        label="Action JSON — edit and click Step",
                        value=DEFAULT_ACTIONS["task1_esi_assignment"],
                        lines=6,
                        interactive=True,
                    )

                    step_btn = gr.Button("▶  Step", variant="primary")

                    resp_box = gr.Textbox(
                        label="Step Response",
                        lines=10,
                        interactive=False,
                        elem_id="resp-box",
                    )

                # ── Tab 2: Agent Run ─────────────────────────────────
                with gr.Tab("🤖 Agent Run"):
                    gr.Markdown(
                        "One-click AI agent run. The built-in heuristic agent "
                        "will complete the selected task and stream a live log."
                    )

                    agent_reset_btn = gr.Button("🔄 Reset + Run Agent", variant="primary")

                    agent_log = gr.Textbox(
                        label="Agent Log",
                        lines=25,
                        interactive=False,
                        elem_id="log-box",
                        placeholder="Click 'Reset + Run Agent' to start…",
                    )

    # ── Callbacks ────────────────────────────────────────────────────────────

    def on_task_change(task_id):
        return (
            _task_info(task_id),
            _code_snippet(task_id),
            DEFAULT_ACTIONS.get(task_id, "{}"),
            "",  # clear obs
            "",  # clear resp
        )

    task_radio.change(
        on_task_change,
        inputs=[task_radio],
        outputs=[task_desc, code_box, action_box, obs_box, resp_box],
    )

    def do_new_session():
        new_sid = _session()
        return new_sid, "", "", f"New session: {new_sid}"

    new_session_btn.click(
        do_new_session,
        inputs=[],
        outputs=[session_state, obs_box, resp_box, resp_box],
    )

    def do_reset(task_id, session_id):
        try:
            res = _post("/reset", {"task_id": task_id, "session_id": session_id})
            obs_str = _fmt(res["observation"])
            return obs_str, f"[RESET OK]\ntask_id={task_id}\nsession_id={session_id}"
        except Exception as e:
            return "", f"[ERROR] {e}"

    reset_btn.click(
        do_reset,
        inputs=[task_radio, session_state],
        outputs=[obs_box, resp_box],
    )

    def do_state(session_id):
        try:
            res = _get(f"/state?session_id={session_id}")
            return _fmt(res)
        except Exception as e:
            return f"[ERROR] {e}"

    state_btn.click(do_state, inputs=[session_state], outputs=[resp_box])

    def do_step(task_id, action_str, session_id):
        try:
            action = json.loads(action_str)
        except json.JSONDecodeError as e:
            return "", f"[JSON ERROR] {e}"
        try:
            action["session_id"] = session_id
            res = _post("/step", action)
            obs_str = _fmt(res["observation"])
            stat = (
                f"reward={res['reward']:.4f}  done={res['done']}\n\n"
                + _fmt(res)
            )
            return obs_str, stat
        except Exception as e:
            return "", f"[ERROR] {e}"

    step_btn.click(
        do_step,
        inputs=[task_radio, action_box, session_state],
        outputs=[obs_box, resp_box],
    )

    def do_agent_run(task_id):
        sid = _session()
        log = ""
        for chunk in _run_agent(task_id, sid):
            log += chunk
            yield log

    agent_reset_btn.click(
        do_agent_run,
        inputs=[task_radio],
        outputs=[agent_log],
    )


# ── Launch ─────────────────────────────────────────────────────────────────
# Merge Gradio UI into the FastAPI app
app = gr.mount_gradio_app(fastapi_app, demo, path="/")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=GRAD_PORT,
    )
