# Strategy Generation Spec for External AI Agent

Audience: External AI model/agent that produces JSON strategy configs consumable by our no‑code SECTIONED strategy builder and backend.

Version: 1.2

Overview
- Goal: Given a natural-language prompt, generate a valid JSON strategy configuration for the SECTIONED builder that our backend accepts and the UI renders directly.
- Consumer API: POST /api/bots/strategy-config/generate. This document defines the configuration format the agent must output in the `config` object.

What you MUST return (SECTIONED format only)
- strategy_name: "SECTIONED_SPEC"
- strategy_params:
  - sectioned_spec: object with the following optional sections (include only what’s needed):
    - risk: object
    - filters: object
- indicator_configs: [] (keep empty for SECTIONED mode)
- notes: optional string

Important
- The UI reads only from `strategy_params.sectioned_spec`.
- Do not rely on any graph format. Do not add a top-level `strategy_graph`.

Nodes and Parameters Catalog (for naming and validation)
- Use our metadata endpoints as the source of truth for available nodes (indicators, operators, actions) and their parameter schemas:
  - GET /api/bots/nodes/metadata/ (public)
  - GET /api/bots/nodes/schema/ (public; JSON Schema for programmatic validation)
- Names are exact and case-sensitive. Do not invent new nodes.
- Validate any referenced parameters against each node’s PARAMS_SCHEMA. Apply defaults where provided.
- If a requested node isn’t available, respond with 422 and body:
  {
    "error": "unavailable_node",
    "missing": [ { "kind": "indicator", "name": "ema" } ],
    "message": "The following nodes are not available in this environment: indicator: ema"
  }

SECTIONED examples
Minimal
{
  "strategy_name": "SECTIONED_SPEC",
  "strategy_params": {
    "sectioned_spec": {
      "risk": {},
      "filters": {}
    }
  },
  "indicator_configs": [],
  "notes": "Simple template"
}

With risk and filters
{
  "strategy_name": "SECTIONED_SPEC",
  "strategy_params": {
    "sectioned_spec": {
      "risk": { "risk_per_trade": 0.5, "max_open_trades": 3 },
      "filters": {
        "time_window": { "start": "09:00", "end": "16:00", "timezone": "UTC" },
        "min_volume": 100000
      }
    }
  },
  "indicator_configs": [],
  "notes": "Daytime-only trading with conservative risk"
}

Provider API Request From Our Backend
- POST <AI_STRATEGY_API_URL>
- Headers:
  - X-Request-ID: <uuid>
  - Content-Type: application/json
  - (No Authorization header by default)
- Body:
  {
    "chatInput": "<prompt>",
    "session_id": "<uuid>",
    "trading_account_api_key": "<user-jwt-token>",
    "backend_url": "<our-backend-base-url>"
  }

Error Responses
- 400/422: Validation error. Include details; for missing nodes use the shape above.
- 5xx: Transient errors.

Best Practices
- Output SECTIONED format only.
- Keep fields minimal and consistent.
- Use the JSON Schema endpoint to validate any parameter shapes you include.
- Do not log or store secrets (trading_account_api_key).
