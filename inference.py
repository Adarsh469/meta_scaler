"""
inference.py — Baseline Agent for ClinicalTriage-Env
======================================================
Runs an LLM agent against all 3 tasks of the ClinicalTriage-Env.

MANDATORY ENVIRONMENT VARIABLES:
  HF_TOKEN       Your Hugging Face / API key (required, no default)
  API_BASE_URL   LLM endpoint (default: https://router.huggingface.co/v1)
  MODEL_NAME     Model identifier (default: Qwen/Qwen2.5-72B-Instruct)

STDOUT FORMAT (competition spec):
  [START] task=<task_id> env=clinical-triage-env model=<model_name>
  [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
  [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

Run:
  HF_TOKEN=<your_token> python inference.py
"""

import json
import os
import textwrap
from typing import Any, Dict, List, Optional

from openai import OpenAI

from env import ClinicalTriageEnv, TriageAction

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY: str = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "")
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")
BENCHMARK: str = "clinical-triage-env"

MAX_STEPS_TASK1: int = 5
MAX_STEPS_TASK2: int = 3
MAX_STEPS_TASK3: int = 10

TEMPERATURE: float = 0.2
MAX_TOKENS: int = 512
SUCCESS_THRESHOLD: float = 0.5

# ---------------------------------------------------------------------------
# Logging helpers (competition mandatory format)
# ---------------------------------------------------------------------------


def log_start(task: str, env: str, model: str) -> None:
    print(f"[START] task={task} env={env} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool, error: Optional[str]) -> None:
    error_val = error if error else "null"
    done_val = str(done).lower()
    print(
        f"[STEP] step={step} action={action} reward={reward:.2f} done={done_val} error={error_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float, rewards: List[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# LLM call helper
# ---------------------------------------------------------------------------

def call_llm(client: OpenAI, system_prompt: str, user_prompt: str) -> str:
    """Call the LLM and return the content string."""
    try:
        completion = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            stream=False,
        )
        return (completion.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[DEBUG] LLM call failed: {exc}", flush=True)
        return ""


# ---------------------------------------------------------------------------
# Action parsers
# ---------------------------------------------------------------------------

def parse_esi_from_response(text: str) -> int:
    """Extract ESI integer (1–5) from LLM response."""
    import re
    matches = re.findall(r"\b([1-5])\b", text)
    if matches:
        return int(matches[0])
    # Keyword fallback
    text_lower = text.lower()
    if "immediate" in text_lower or "resuscitat" in text_lower:
        return 1
    if "emergent" in text_lower:
        return 2
    if "urgent" in text_lower:
        return 3
    if "less urgent" in text_lower:
        return 4
    if "non-urgent" in text_lower or "routine" in text_lower:
        return 5
    return 3  # fallback to ESI 3 (middle ground)


def parse_queue_order(text: str, valid_ids: List[str]) -> List[str]:
    """Extract ordered case IDs from LLM response."""
    import re
    found = []
    for match in re.finditer(r"MTG-\d{5}", text):
        cid = match.group(0)
        if cid in valid_ids and cid not in found:
            found.append(cid)
    # If we didn't get all IDs, append any missing at the end
    for cid in valid_ids:
        if cid not in found:
            found.append(cid)
    return found


def parse_question_topic(text: str) -> str:
    """Extract question_topic from LLM response."""
    text_lower = text.lower()
    if "medic" in text_lower or "drug" in text_lower or "prescription" in text_lower:
        return "medications"
    if "allerg" in text_lower:
        return "allergies"
    if "history" in text_lower or "past" in text_lower or "chronic" in text_lower:
        return "past_medical_history"
    return "medications"  # default: medications reveals contraindications


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SYSTEM_TASK1 = textwrap.dedent("""
    You are an expert Emergency Department triage nurse.
    You will receive a patient presentation and must assign the correct
    Emergency Severity Index (ESI) level.

    ESI Scale:
      1 = Immediate (Resuscitation) — life-threatening, e.g., cardiac arrest, active seizure
      2 = Emergent (High Risk) — serious condition, should not wait, e.g., chest pain + diaphoresis
      3 = Urgent — stable but needs multiple resources, e.g., fever + vomiting + rash
      4 = Less Urgent — needs one resource, e.g., simple laceration, mild rash
      5 = Non-Urgent — no resources needed, e.g., routine follow-up, minor complaint

    Red flags that always elevate urgency:
      - Chest pain → ESI 1 or 2
      - Shortness of breath → ESI 1 or 2
      - Blurred vision (sudden) → ESI 1 or 2
      - High risk context (age extremes, sudden onset) → escalate by 1

    Respond with ONLY a JSON object:
    {"esi_level": <1-5>, "reasoning": "<brief clinical justification>"}
""").strip()

SYSTEM_TASK2 = textwrap.dedent("""
    You are an expert Emergency Department charge nurse managing patient intake.
    You will receive 5 patients who arrived simultaneously. Order them from
    MOST URGENT (ESI 1) to LEAST URGENT (ESI 5).

    Prioritization rules:
      1. Airway/breathing/circulation threats → always first
      2. Chest pain, shortness of breath, sudden blurred vision → very high priority
      3. Multiple red flags beat single red flags
      4. Sudden onset > gradual onset at same symptom severity
      5. Extreme ages (infants, elderly 75+) with symptoms → escalate priority

    Respond with ONLY a JSON object:
    {"ordered_ids": ["MTG-XXXXX", "MTG-XXXXX", "MTG-XXXXX", "MTG-XXXXX", "MTG-XXXXX"],
     "reasoning": "<brief justification>"}
""").strip()

SYSTEM_TASK3 = textwrap.dedent("""
    You are an expert Emergency Department physician performing a detailed triage.
    You have a patient with an incomplete history. You can ask up to 3 questions
    to uncover hidden information (medications, allergies, past history, current symptoms).

    CRITICAL: ALWAYS ask about medications first — drug interactions can fundamentally
    change the ESI level (e.g., warfarin + chest pain = ESI 1).

    After gathering information, assign the final ESI level.

    To ask a question, respond with:
    {"action": "ask_question", "topic": "medications|allergies|past_medical_history|current_symptoms"}

    To assign ESI, respond with:
    {"action": "assign_esi", "esi_level": <1-5>, "reasoning": "<clinical justification>"}

    Red flags: chest pain, shortness of breath, blurred vision, anticoagulants,
    cardiac medications, diabetic emergencies.
""").strip()


# ---------------------------------------------------------------------------
# Task runners
# ---------------------------------------------------------------------------

def run_task1(client: OpenAI) -> float:
    """Run Task 1: Single Patient ESI Assignment."""
    task_id = "task1_esi_assignment"
    env = ClinicalTriageEnv(task_id)
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    try:
        reset_result = env.reset()
        obs = reset_result.observation

        for step in range(1, MAX_STEPS_TASK1 + 1):
            if obs.message and "done" in obs.message.lower() and step > 1:
                break

            # Build prompt
            patient = obs.patient
            user_prompt = textwrap.dedent(f"""
                Patient Presentation:
                  Case ID : {patient.case_id}
                  Age     : {patient.age} years old, {patient.gender}
                  Symptoms: {', '.join(patient.symptoms)}
                  Duration: {patient.duration}
                  Onset   : {patient.onset}
                  Context : {patient.context}

                {obs.message}

                Assign the correct ESI level (1-5) for this patient.
            """).strip()

            llm_response = call_llm(client, SYSTEM_TASK1, user_prompt)

            # Parse ESI
            esi = 3  # fallback
            error_msg = None
            try:
                data = json.loads(llm_response)
                esi = int(data.get("esi_level", 3))
                esi = max(1, min(5, esi))
            except Exception:
                esi = parse_esi_from_response(llm_response)
                if not llm_response:
                    error_msg = "empty_llm_response"

            action = TriageAction(action_type="assign_esi", esi_level=esi)
            action_str = f"assign_esi(esi_level={esi})"

            step_result = env.step(action)
            reward = step_result.reward
            done = step_result.done
            rewards.append(reward)
            steps_taken = step
            obs = step_result.observation

            log_step(step=step, action=action_str, reward=reward, done=done, error=error_msg)

            if done:
                break

        score = sum(rewards)  # Task 1 max = 1.0 from single step
        score = max(0.0, min(1.0, score))
        success = score >= SUCCESS_THRESHOLD

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


def run_task2(client: OpenAI) -> float:
    """Run Task 2: Patient Queue Prioritization."""
    task_id = "task2_queue_priority"
    env = ClinicalTriageEnv(task_id)
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    try:
        reset_result = env.reset()
        obs = reset_result.observation

        for step in range(1, MAX_STEPS_TASK2 + 1):
            queue = obs.queue or []
            valid_ids = [p.case_id for p in queue]

            # Build prompt
            patients_text = "\n".join(
                f"  {i+1}. {p.case_id}: {p.age}y {p.gender}, "
                f"symptoms=[{', '.join(p.symptoms)}], "
                f"onset={p.onset}, duration={p.duration}, context={p.context}"
                for i, p in enumerate(queue)
            )
            user_prompt = textwrap.dedent(f"""
                Five patients arrived simultaneously:

                {patients_text}

                Order these patients from MOST URGENT to LEAST URGENT.
                Return their case IDs in priority order.
            """).strip()

            llm_response = call_llm(client, SYSTEM_TASK2, user_prompt)

            ordered_ids = valid_ids  # fallback: keep as-is
            error_msg = None
            try:
                data = json.loads(llm_response)
                ordered_ids = data.get("ordered_ids", valid_ids)
            except Exception:
                ordered_ids = parse_queue_order(llm_response, valid_ids)
                if not llm_response:
                    error_msg = "empty_llm_response"

            action = TriageAction(action_type="reorder_queue", queue_order=ordered_ids)
            action_str = f"reorder_queue(order={ordered_ids})"

            step_result = env.step(action)
            reward = step_result.reward
            done = step_result.done
            rewards.append(reward)
            steps_taken = step
            obs = step_result.observation

            log_step(step=step, action=action_str, reward=reward, done=done, error=error_msg)

            if done:
                break

        score = sum(rewards)
        score = max(0.0, min(1.0, score))
        success = score >= SUCCESS_THRESHOLD

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


def run_task3(client: OpenAI) -> float:
    """Run Task 3: Ambiguous Triage with Hidden History."""
    task_id = "task3_ambiguous_triage"
    env = ClinicalTriageEnv(task_id)
    log_start(task=task_id, env=BENCHMARK, model=MODEL_NAME)

    rewards: List[float] = []
    steps_taken = 0
    score = 0.0
    success = False
    conversation_history: List[str] = []

    try:
        reset_result = env.reset()
        obs = reset_result.observation

        for step in range(1, MAX_STEPS_TASK3 + 1):
            patient = obs.patient
            budget = obs.clarification_budget if obs.clarification_budget is not None else 0
            awaiting = obs.awaiting_final_esi or False

            # Build conversation context
            history_text = "\n".join(conversation_history[-6:]) if conversation_history else "None"

            if patient:
                patient_text = textwrap.dedent(f"""
                    Patient: {patient.case_id}, {patient.age}y {patient.gender}
                    Symptoms: {', '.join(patient.symptoms)}
                    Onset: {patient.onset}, Duration: {patient.duration}, Context: {patient.context}
                """).strip()
            else:
                patient_text = "See previous patient info."

            user_prompt = textwrap.dedent(f"""
                {patient_text}

                Previous Information Gathered:
                {history_text}

                Latest Response: {obs.message}

                Clarification questions remaining: {budget}
                Must assign ESI now: {awaiting}

                {"You MUST now assign the ESI level." if awaiting or budget == 0
                 else "Ask a question to gather more information OR assign ESI if ready."}
            """).strip()

            llm_response = call_llm(client, SYSTEM_TASK3, user_prompt)

            action: Optional[TriageAction] = None
            action_str = ""
            error_msg = None

            try:
                data = json.loads(llm_response)
                act_type = data.get("action", "")
                if act_type == "ask_question" and not awaiting and budget > 0:
                    topic = data.get("topic", "medications")
                    action = TriageAction(action_type="ask_question", question_topic=topic)
                    action_str = f"ask_question(topic={topic})"
                elif act_type == "assign_esi" or awaiting or budget == 0:
                    esi = int(data.get("esi_level", 3))
                    esi = max(1, min(5, esi))
                    action = TriageAction(action_type="assign_esi", esi_level=esi)
                    action_str = f"assign_esi(esi_level={esi})"
                else:
                    # Default: ask medications first
                    action = TriageAction(action_type="ask_question", question_topic="medications")
                    action_str = "ask_question(topic=medications)"
            except Exception:
                # Parse fallback
                if not awaiting and budget > 0 and "assign" not in llm_response.lower():
                    topic = parse_question_topic(llm_response)
                    action = TriageAction(action_type="ask_question", question_topic=topic)
                    action_str = f"ask_question(topic={topic})"
                    if not llm_response:
                        error_msg = "empty_llm_response"
                else:
                    esi = parse_esi_from_response(llm_response)
                    action = TriageAction(action_type="assign_esi", esi_level=esi)
                    action_str = f"assign_esi(esi_level={esi})"

            step_result = env.step(action)
            reward = step_result.reward
            done = step_result.done
            rewards.append(reward)
            steps_taken = step
            obs = step_result.observation

            # Update conversation history
            conversation_history.append(f"Step {step} [{action_str}]: {obs.message}")

            log_step(step=step, action=action_str, reward=reward, done=done, error=error_msg)

            if done:
                break

        score = sum(rewards)
        score = max(0.0, min(1.0, score))
        success = score >= SUCCESS_THRESHOLD

    finally:
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not API_KEY:
        raise EnvironmentError(
            "HF_TOKEN environment variable is not set. "
            "Set it to your Hugging Face API key before running."
        )

    client = OpenAI(base_url=API_BASE_URL, api_key=API_KEY)

    print(f"[DEBUG] API_BASE_URL={API_BASE_URL}", flush=True)
    print(f"[DEBUG] MODEL_NAME={MODEL_NAME}", flush=True)
    print(f"[DEBUG] Running 3 tasks against {BENCHMARK}", flush=True)

    scores: Dict[str, float] = {}

    scores["task1_esi_assignment"] = run_task1(client)
    scores["task2_queue_priority"] = run_task2(client)
    scores["task3_ambiguous_triage"] = run_task3(client)

    avg_score = sum(scores.values()) / len(scores)
    print(f"\n[DEBUG] === Final Scores ===", flush=True)
    for task_id, s in scores.items():
        print(f"[DEBUG]   {task_id}: {s:.3f}", flush=True)
    print(f"[DEBUG]   Average: {avg_score:.3f}", flush=True)


if __name__ == "__main__":
    main()
