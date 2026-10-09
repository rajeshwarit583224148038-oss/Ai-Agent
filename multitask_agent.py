# -*- coding: utf-8 -*-
"""
LangChain Concurrent Multi-Task Agent
======================================
Demonstrates running MULTIPLE independent tasks at the SAME TIME using:
  - LangChain 1.4 (new create_agent API -- no AgentExecutor needed)
  - ChatGoogleGenerativeAI (Gemini backend)
  - asyncio.gather() for TRUE parallel execution

Concepts covered:
  1. Defining LangChain tools with @tool decorator + JSON schema
  2. Building a multi-tool agent with create_agent (LangGraph-backed)
  3. Running multiple separate tasks CONCURRENTLY with asyncio.gather()
  4. Comparing sequential vs concurrent execution time
  5. Extracting clean text output from LangGraph message responses
"""

import os
import sys
import io
import json
import re
import asyncio
import time
import urllib.request
import urllib.parse

# Fix Windows terminal encoding (prevents UnicodeEncodeError on cp1252 terminals)
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path

try:
    import zoneinfo
except ImportError:
    zoneinfo = None

# =====================================================================
# 1. GEMINI API KEY
# =====================================================================
GEMINI_API_KEY = "AQ.Ab8RN6IGGOV66Xj-KfUMlWsQST6mDGCGQRTw3GxE7GbC5t2jmA"  # ← Paste your AI Studio key here

# Fallback models -- agent tries these in order if one hits 429 quota
FALLBACK_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-3.8-flash",
]

# =====================================================================
# 2. LANGCHAIN 1.4 IMPORTS
# =====================================================================
try:
    from langchain.agents import create_agent
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.tools import StructuredTool
except ImportError as e:
    print(f"[Import Error] {e}")
    print("Run: pip install langchain langchain-google-genai")
    sys.exit(1)


# =====================================================================
# 3. LLM FACTORY
# =====================================================================
def get_llm(model: str = FALLBACK_MODELS[0]) -> ChatGoogleGenerativeAI:
    """Returns a Gemini LLM via LangChain's ChatGoogleGenerativeAI."""
    api_key = GEMINI_API_KEY
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
        raise ValueError(
            "Gemini API Key is missing!\n"
            "Please open multitask_agent.py and set GEMINI_API_KEY = 'your_key_here'\n"
            "or export GEMINI_API_KEY in your terminal."
        )
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=0.0
    )


# =====================================================================
# 4. LOAD TOOLS STRICTLY FROM JSON (tools.json)
# =====================================================================
TOOLS_JSON_FILE = Path(__file__).parent / "tools.json"

if not TOOLS_JSON_FILE.exists():
    raise FileNotFoundError(f"tools.json not found at: {TOOLS_JSON_FILE}")

with open(TOOLS_JSON_FILE, "r", encoding="utf-8") as f:
    ALL_TOOLS_SCHEMAS = json.load(f)


def execute_calculator(operation: str, a: float, b: float) -> str:
    try:
        a, b = float(a), float(b)
        ops = {
            "add":      lambda: a + b,
            "subtract": lambda: a - b,
            "multiply": lambda: a * b,
            "divide":   lambda: a / b if b != 0 else None,
            "modulo":   lambda: a % b if b != 0 else None,
            "power":    lambda: a ** b,
        }
        if operation not in ops:
            return json.dumps({"error": f"Unknown operation: '{operation}'."})
        if operation in ("divide", "modulo") and b == 0:
            return json.dumps({"error": f"Cannot {operation} by zero."})
        res = ops[operation]()
        if isinstance(res, float) and res.is_integer():
            res = int(res)
        return json.dumps({"operation": operation, "a": a, "b": b, "result": res})
    except Exception as e:
        return json.dumps({"error": str(e)})


def execute_web_search(query: str) -> str:
    try:
        encoded = urllib.parse.quote(query.strip())
        url = (
            f"https://en.wikipedia.org/w/api.php?"
            f"action=query&list=search&srsearch={encoded}"
            f"&utf8=&format=json&srlimit=3"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "LangChain-MultiTask-Agent/1.0 (Educational)"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = [
            {
                "title": item.get("title", ""),
                "snippet": re.sub(r"<[^>]+>", "", item.get("snippet", ""))
            }
            for item in data.get("query", {}).get("search", [])
        ]
        return json.dumps(
            {"query": query, "results": results} if results
            else {"query": query, "message": "No results found."}
        )
    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})


def execute_datetime(timezone: str = "local") -> str:
    try:
        tz_str = (timezone or "local").strip()
        if tz_str.lower() in ["local", "default", "system", ""]:
            now = datetime.now().astimezone()
            tz_name = "local"
        elif zoneinfo:
            try:
                now = datetime.now(zoneinfo.ZoneInfo(tz_str))
                tz_name = tz_str
            except Exception:
                now = datetime.now().astimezone()
                tz_name = f"local ('{tz_str}' not recognized)"
        else:
            now = datetime.now().astimezone()
            tz_name = "local"

        return json.dumps({
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "year": now.year,
            "month": now.strftime("%B"),
            "day": now.day,
            "day_of_week": now.strftime("%A"),
            "iso_timestamp": now.isoformat(),
            "timezone": tz_name
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


def execute_retrieve_student_info(query: str) -> str:
    """
    RAG Document Retrieval engine for Student Database.
    Searches and returns matching student records from students_database.json document.
    """
    try:
        db_file = Path(__file__).parent / "students_database.json"
        if not db_file.exists():
            return json.dumps({"error": "students_database.json document not found."})

        with open(db_file, "r", encoding="utf-8") as f:
            students = json.load(f)

        q = query.lower().strip()

        # Specific criteria checks
        if "highest overall" in q or "top overall" in q or "max overall" in q:
            top_student = max(students, key=lambda s: s["overall"])
            return json.dumps({"criteria": "highest overall mark", "results": [top_student]})

        if "highest attendance" in q or "top attendance" in q or "max attendance" in q:
            top_att = max(students, key=lambda s: int(s["attendance"].replace("%", "")))
            return json.dumps({"criteria": "highest attendance", "results": [top_att]})

        if "below 75" in q or "< 75" in q:
            matched = [s for s in students if int(s["attendance"].replace("%", "")) < 75]
            return json.dumps({"criteria": "attendance below 75%", "count": len(matched), "results": matched})

        if "above 90 in ai" in q or "ai above 90" in q or "ai > 90" in q:
            matched = [s for s in students if s["ai"] > 90]
            return json.dumps({"criteria": "AI score above 90", "count": len(matched), "results": matched})

        if "aids" in q and ("above 80" in q or "> 80" in q):
            matched = [s for s in students if s["dept"].upper() == "AIDS" and s["overall"] > 80]
            return json.dumps({"criteria": "AIDS students with overall > 80", "count": len(matched), "results": matched})

        if "placement eligible" in q or "eligible for placement" in q:
            matched = [s for s in students if s["placement"].lower() == "eligible"]
            return json.dumps({"criteria": "placement eligible", "count": len(matched), "results": matched})

        if "not eligible" in q:
            matched = [s for s in students if s["placement"].lower() == "not eligible"]
            return json.dumps({"criteria": "not placement eligible", "count": len(matched), "results": matched})

        # Match by department
        for dept in ["cse", "it", "aids", "ece", "eee"]:
            if f"dept" in q and dept in q or q == dept or f"{dept} department" in q or f"{dept} students" in q:
                matched = [s for s in students if s["dept"].lower() == dept]
                return json.dumps({"department": dept.upper(), "count": len(matched), "results": matched})

        # Match by name or ID
        matched = []
        for s in students:
            s_id = s["student_id"].lower()
            s_name = s["name"].lower()
            if s_id in q or s_name in q or any(part in q for part in s_name.split() if len(part) > 2):
                matched.append(s)

        if matched:
            return json.dumps({"query": query, "count": len(matched), "results": matched})

        # Fallback search across all fields
        tokens = [w for w in re.findall(r"\w+", q) if len(w) > 2]
        fallback_matches = []
        for s in students:
            row_text = " ".join(str(v) for v in s.values()).lower()
            if any(t in row_text for t in tokens):
                fallback_matches.append(s)

        if fallback_matches:
            return json.dumps({"query": query, "count": len(fallback_matches), "results": fallback_matches[:5]})

        return json.dumps({"query": query, "message": "No matching student records found in document.", "results": []})
    except Exception as e:
        return json.dumps({"error": f"RAG retrieval error: {str(e)}"})


# Mapping tool names defined in tools.json to execution functions
FUNCTION_MAPPING = {
    "calculator": execute_calculator,
    "web_search": execute_web_search,
    "date_time": execute_datetime,
    "retrieve_student_info": execute_retrieve_student_info
}

# Construct LangChain StructuredTools dynamically strictly using schemas from tools.json
TOOLS = [
    StructuredTool.from_function(
        func=FUNCTION_MAPPING[spec["name"]],
        name=spec["name"],
        description=spec["description"]
    )
    for spec in ALL_TOOLS_SCHEMAS
    if spec["name"] in FUNCTION_MAPPING
]

# System prompt (injected into the agent as system instruction)
SYSTEM_PROMPT = (
    "You are an AI assistant built strictly around the ReAct (Reasoning + Acting) pattern.\n\n"
    "In EVERY step before invoking a tool, you MUST articulate your reasoning as a Thought:\n"
    "- Thought (Reason): State clearly what you know, what piece of information or computation is missing, and why you are choosing a specific tool.\n"
    "- Action: Call the appropriate tool ('retrieve_student_info', 'calculator', 'web_search', or 'date_time') with JSON arguments.\n"
    "- Observation: Review the tool execution output.\n"
    "- Repeat as needed until all facts or calculations are collected.\n"
    "- Conclude with your final response starting with 'Final Answer:'.\n\n"
    "Available tools:\n"
    "1. 'retrieve_student_info': RAG tool to search/retrieve student records from the Student Database document.\n"
    "2. 'calculator': Arithmetic operations (add, subtract, multiply, divide, modulo, power).\n"
    "3. 'web_search': Factual lookups, definitions, populations, history.\n"
    "4. 'date_time': Current date, time, year, day of week, timezone.\n\n"
    "Never calculate mentally or guess document data -- always query the tools!"
)


# =====================================================================
# 5. AGENT BUILDER
# =====================================================================
def build_agent(model: str = FALLBACK_MODELS[0]):
    """Builds a LangGraph-backed ReAct agent (LangChain 1.4 API)."""
    llm = get_llm(model)
    return create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )


def extract_final_answer(result: dict) -> str:
    """Extracts the final text answer from a LangGraph agent result dict."""
    messages = result.get("messages", [])
    if not messages:
        return "No answer returned."
    last = messages[-1]
    content = getattr(last, "content", "")
    if isinstance(content, list):
        # Gemini returns structured content list -- extract text parts
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and "text" in c]
        return " ".join(texts).strip() or "No text in response."
    return str(content).strip()


# =====================================================================
# 6. CONCURRENT MULTI-TASK RUNNER
# =====================================================================

async def run_single_task(agent, task_id: int, query: str) -> dict:
    """Runs one task asynchronously, printing the full ReAct (Reason + Action) trace."""
    print(f"\n{'='*60}")
    print(f"  [Task {task_id}] Query: {query}")
    print(f"{'='*60}")
    start = time.perf_counter()
    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": query}]}
        )

        # Print full ReAct trace (Reason + Action + Observation)
        messages = result.get("messages", [])
        step = 0
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                step += 1
                print(f"\n  --- [Task {task_id} | ReAct Step {step}] ---")
                
                # 1. Thought / Reason
                thought_str = ""
                if getattr(msg, "content", None):
                    c = msg.content
                    if isinstance(c, list):
                        thought_str = " ".join(part.get("text", "") for part in c if isinstance(part, dict) and "text" in part)
                    elif isinstance(c, str):
                        thought_str = c
                
                if thought_str.strip():
                    print(f"  Thought (Reason): {thought_str.strip()}")
                else:
                    tools_called = ", ".join(tc.get("name", "") for tc in msg.tool_calls)
                    print(f"  Thought (Reason): Need to invoke '{tools_called}' to obtain required data.")

                # 2. Action
                for tc in msg.tool_calls:
                    args_repr = json.dumps(tc.get("args", {}))
                    print(f"  Action: {tc.get('name')}({args_repr})")

            elif getattr(msg, "type", "") == "tool" or msg.__class__.__name__ == "ToolMessage":
                # 3. Observation
                obs_content = getattr(msg, "content", "")
                print(f"  Observation: {obs_content}")

        answer = extract_final_answer(result)
        elapsed = time.perf_counter() - start
        print(f"\n  Final Answer: {answer}")
        print(f"  [Task {task_id} completed in {elapsed:.2f}s]")
        return {"task_id": task_id, "query": query, "answer": answer, "time_sec": round(elapsed, 2)}
    except Exception as e:
        elapsed = time.perf_counter() - start
        print(f"\n  [Task {task_id} failed after {elapsed:.2f}s]: {e}")
        return {"task_id": task_id, "query": query, "error": str(e), "time_sec": round(elapsed, 2)}


async def run_all_concurrently(queries: list, model: str = FALLBACK_MODELS[0]) -> list:
    """
    Runs ALL tasks at the SAME TIME using asyncio.gather().
    
    How it works:
    - Each task gets its own coroutine launched with agent.ainvoke()
    - asyncio.gather() fires all coroutines simultaneously
    - Python's event loop manages I/O switching between them
    - All complete faster together than one-by-one (sequential)
    """
    print(f"\n{'#'*60}")
    print(f"  [>>] LangChain CONCURRENT MULTI-TASK EXECUTION")
    print(f"  Model     : {model}")
    print(f"  Tasks     : {len(queries)}")
    print(f"  Strategy  : asyncio.gather() -- all at the SAME TIME")
    print(f"{'#'*60}")
    for i, q in enumerate(queries, 1):
        print(f"  Task {i}: {q}")

    agent = build_agent(model)
    wall_start = time.perf_counter()

    # ↓ This is the core: all tasks fire at the same time
    results = await asyncio.gather(
        *[run_single_task(agent, i + 1, q) for i, q in enumerate(queries)]
    )

    wall_elapsed = time.perf_counter() - wall_start
    total_serial = sum(r["time_sec"] for r in results)

    print(f"\n{'='*60}")
    print(f"  [SUM] EXECUTION SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status = "[OK]" if "error" not in r else "[ERR]"
        print(f"  Task {r['task_id']} {status} ({r['time_sec']}s) | {r['query'][:50]}")
    print(f"\n  [T]  Total concurrent time : {wall_elapsed:.2f}s")
    print(f"  [DOWN] Would take (serial)   : ~{total_serial:.2f}s")
    print(f"  [FAST] Speed-up              : {total_serial / wall_elapsed:.1f}x faster")
    print(f"{'='*60}\n")
    return results


def run_concurrent(queries: list, model: str = FALLBACK_MODELS[0]) -> list:
    """Synchronous wrapper so you can call from non-async code."""
    return asyncio.run(run_all_concurrently(queries, model))


# =====================================================================
# 7. DEMO TASKS
# =====================================================================
DEMO_TASKS = [
    "What is Priya Sharma's attendance and overall mark?",
    "Who has the highest overall mark?",
    "Which students belong to the CSE department?",
    "List students whose attendance is below 75%.",
    "Who scored above 90 in AI?",
    "How many students are placement eligible?",
    "What is Arjun Kumar's DSA mark?",
    "Which student has the highest attendance?",
    "Find all AIDS students with an overall mark above 80.",
    "What is the phone number of Fathima N?",
]


# =====================================================================
# 8. INTERACTIVE CLI
# =====================================================================
def main():
    print("=" * 60)
    print("  LangChain CONCURRENT MULTI-TASK AGENT (ReAct Pattern)  ")
    print("=" * 60)
    print(f"  Tools loaded strictly from tools.json: {[t['name'] for t in ALL_TOOLS_SCHEMAS]}")
    print("  Execution: asyncio.gather() -- all tasks run at SAME TIME")
    print("=" * 60)
    print()
    print("Commands:")
    print("  Type any question and press Enter → adds it to the queue")
    print("  'run'   → fire all queued tasks concurrently NOW")
    print("  'demo'  → load 5 built-in demo tasks and run them")
    print("  'list'  → show queued tasks")
    print("  'clear' → clear the queue")
    print("  'exit'  → quit")
    print()

    model = FALLBACK_MODELS[0]

    # Validate API key and LLM
    try:
        get_llm(model)
    except ValueError as e:
        print(f"[Configuration Error] {e}")
        sys.exit(1)

    queue: list[str] = []

    while True:
        try:
            cmd = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not cmd:
            continue

        if cmd.lower() == "exit":
            print("Goodbye!")
            break
        elif cmd.lower() == "demo":
            queue = list(DEMO_TASKS)
            print(f"\nLoaded {len(queue)} demo tasks:")
            for i, t in enumerate(queue, 1):
                print(f"  {i}. {t}")
            print("\nType 'run' to execute all concurrently.")
        elif cmd.lower() == "list":
            if not queue:
                print("  Queue is empty. Type a question to add tasks.")
            else:
                print(f"\n  Queued tasks ({len(queue)}):")
                for i, t in enumerate(queue, 1):
                    print(f"  {i}. {t}")
        elif cmd.lower() == "clear":
            queue.clear()
            print("  Queue cleared.")
        elif cmd.lower() == "run":
            if not queue:
                print("  Queue is empty. Add tasks first, or type 'demo'.")
            else:
                run_concurrent(queue, model)
                queue.clear()
        else:
            queue.append(cmd)
            print(f"  [OK] Added! Queue size: {len(queue)}. Type 'run' when ready.")


if __name__ == "__main__":
    main()
