# LangChain Concurrent Multi-Task Agent

This project runs **multiple agent tasks concurrently at the exact same time** using LangChain and `asyncio.gather()`.

All tool schemas are stored **strictly in JSON format** in `tools.json`.

---

## 📁 Files

- `tools.json`: **Single source of truth containing all tool schemas strictly in JSON format.**
- `multitask_agent.py`: LangChain multi-task agent script dynamically loading `tools.json` and running tasks simultaneously.
- `README.md`: This documentation.

---

## 🛠️ Tools Defined in `tools.json`

The tools (`calculator`, `web_search`, `date_time`) are completely defined in JSON:

```json
[
  {
    "name": "calculator",
    "description": "Performs basic mathematical operations between two numbers: addition, subtraction, multiplication, division, modulo, and power.",
    "parameters": {
      "type": "OBJECT",
      "properties": {
        "operation": {
          "type": "STRING",
          "description": "The mathematical operation to perform.",
          "enum": ["add", "subtract", "multiply", "divide", "modulo", "power"]
        },
        "a": { "type": "NUMBER", "description": "The first number." },
        "b": { "type": "NUMBER", "description": "The second number." }
      },
      "required": ["operation", "a", "b"]
    }
  },
  {
    "name": "web_search",
    "description": "Searches the web for facts, information, current data, definitions, and knowledge on any topic.",
    "parameters": {
      "type": "OBJECT",
      "properties": {
        "query": { "type": "STRING", "description": "The search query keywords." }
      },
      "required": ["query"]
    }
  },
  {
    "name": "date_time",
    "description": "Gets the current date, time, day of the week, year, and timezone.",
    "parameters": {
      "type": "OBJECT",
      "properties": {
        "timezone": { "type": "STRING", "description": "Optional timezone name." }
      }
    }
  }
]
```

---

## 🚀 How to Run

```powershell
cd C:\Users\Admin\.gemini\antigravity\scratch\langchain_multitask
python multitask_agent.py
```

Type `demo` then `run` to execute multiple tasks concurrently!
