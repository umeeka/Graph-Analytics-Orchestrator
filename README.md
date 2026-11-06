# Course Project: Graph Analytics Orchestrator

An autonomous, LLM-based multi-agent orchestrator that answers natural-language questions over network graphs by dynamically discovering, curating, and chaining algorithmic tools from the shared class registry[cite: 1].

---

## 1. System Overview

The orchestrator adheres strictly to the project specification and tool contract[cite: 1]:
- **Dynamic Discovery & Curation**: Reads manifests at startup and evaluates implementations across edge-case benchmarks to populate a verified registry (`curated_registry/`).
- **Strict Grounding (Rule 3)**: Every factual claim is derived directly from an executed tool result in the trace[cite: 1].
- **Subgraph Chaining (Rule 4)**: Automatically captures `result_graph_id` from subgraph-generating operations (e.g., `filter_nodes`, `k_core`, `girvan_newman`, `ego_network`) and propagates it as `graph_id` into downstream tools.
- **Autonomous Disambiguation (Rule 5)**: Identifies queries that lack necessary metrics or parameters (`clarification_needed`) or that request data/algorithms outside the tool contract (`unsupported`) without invoking tools.
- **Auditable Traces (Rule 6)**: Generates a JSONL execution log per query under `traces/` tracking all LLM prompts, tool invocations, parameters, and outputs[cite: 12, 13, 15, 16].
- **Minimal Tool Calls (Rule 8)**: Executes queries efficiently within a strict call budget ($\le 5$ calls).

---

## 2. Directory Structure

The repository maintains the directory layout from Assignment 3[cite: 1]:

```text
.
├── curated_registry/          # Curated, verified tool implementations (1 per algorithm)
│   ├── betweenness_centrality/
│   ├── degree_centrality/
│   ├── filter_nodes/
│   ├── pagerank/
│   └── ...
├── data/                      # Graph datasets (airports, karate, lesmis, courses, projects)
├── graphkit/                  # Shared framework: store, loader, schemas, and trace logger
├── infra_tools/               # Base tools (list_graphs, lookup_node, node_attributes, filter_nodes)
├── orchestrator/              # Orchestrator core package
│   ├── __init__.py
│   ├── agent.py               # Main tool-calling loop, auto-structuring, backoff logic
│   ├── parser.py              # Schema normalization, type casting, validation
│   └── prompts.py             # System prompts, dataset context, disambiguation heuristics
├── registry/                  # Raw student tool submissions
├── traces/                    # Per-query execution trace logs (q01.jsonl – q30.jsonl)
├── answers_public.json        # Output predictions for the public test set
├── curate_tools.py            # Automated tool testing and curation suite
├── public_expected.json       # Ground truth expected outputs for the public set
├── public_queries.json        # Public evaluation questions
├── README.md                  # System setup and execution instructions
├── requirements.txt           # Python package dependencies
└── run_queries.py             # CLI runner entrypoint
```
---

## 3. Environment Setup & Configuration

Prerequisites
Python 3.10 or higher
Standard virtual environment tools (venv)

Installation
Bash
# 1. Create and activate virtual environment
python -m venv .venv

# On Linux / macOS:
source .venv/bin/activate
# On Windows (Command Prompt):
.venv\Scripts\activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt


Environment Variables
The orchestrator reads LLM credentials directly from the environment. 
Do not hardcode or commit API keys to version control.
Configure the following variables in your shell or inside a local .env file:
Bash
# For Google Gemini:
export LLM_API_KEY="your-api-key-here"
export LLM_BASE_URL="[https://generativelanguage.googleapis.com/v1beta/openai/](https://generativelanguage.googleapis.com/v1beta/openai/)"
export LLM_MODEL="gemini-2.5-flash"

# For Groq OpenAI-compatible endpoint:
export LLM_API_KEY="gsk_your-groq-api-key-here"
export LLM_BASE_URL="[https://api.groq.com/openai/v1](https://api.groq.com/openai/v1)"
export LLM_MODEL="openai/gpt-oss-20b"
(On Windows CMD use set LLM_API_KEY=...; on PowerShell use $env:LLM_API_KEY="...".)

---

## 4. How to Run

Step 1: Tool CurationBefore running queries on a clean environment, execute the curation script to discover, benchmark, and stage valid tools from registry/ into curated_registry/:   
Bash
python curate_tools.py

Step 2: Running Queries (Single CLI Command)
To execute queries, run the entrypoint script:   
Bash
python run_queries.py --queries public_queries.json --out answers_public.json

For evaluation on hidden query sets, point --queries and --out to the desired paths:Bashpython run_queries.py --queries <path_to_queries.json> --out <path_to_answers.json>
Selective Execution (Optional debugging helper)To execute specific queries without re-running the full batch:
Bash
python run_queries.py --queries public_queries.json --out answers_public.json --only q04 q16 q23

---

## 5. Structured Output & Answer Schema

The orchestrator writes a structured JSON list to --out conforming to the project specification:  

 JSON{
  "query_id": "q08",
  "status": "answered",
  "answer_text": "The top three brokers in the karate club network are members 1, 34, and 33.",
  "answer": {
    "type": "node_list",
    "value": ["m1", "m34", "m33"],
    "ordered": true
  },
  "tools_used": ["betweenness_centrality.f897d4c5"],
  "trace_file": "traces/q08.jsonl"
}
status: "answered", "clarification_needed", "unsupported", or "error".   answer.type: "number", "boolean", "node", "node_list", "path", or "text".   answer.ordered: Set to true strictly for ranked lists (top-$k$, broker rankings, paths).   Ambiguous and unsupported questions return type: "text" with an empty string value ("").   

---
