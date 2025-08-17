# Strategy Generation Spec for External AI Agent

Audience: External AI model/agent that produces JSON strategy configs consumable by our no‑code strategy builder and backend.

Version: 1.0

Overview
- Goal: Given a natural-language prompt and bot version context, generate a valid JSON strategy configuration that our backend accepts and can execute.
- Consumer API: POST /api/bots/strategy-config/generate (internal), which forwards to your endpoint; this document defines the JSON schema you should return to us when we call your service and the shape of the config you must generate.

Key Concepts (Builder Primitives)
- Indicators (time series producers)
  - Registered by name in our registry (lowercase). Examples:
    - price: outputs the selected price series
      - NAME: "price"
      - PARAMS_SCHEMA: { source: enum[open, high, low, close, volume, tick], default: close }
      - OUTPUTS: ["default"]
  - Indicators from package indicators.definitions are also discovered dynamically and follow the protocol in core/interfaces.py:
    - Attributes: VERSION, OUTPUTS: List[str], PARAMS_SCHEMA: Dict
    - compute(ohlcv, params) -> Dict[str, pandas.Series]
- Operators (boolean/numeric combinators)
  - Names (lowercase): greaterthan, lessthan, equalto, notequalto, greaterthanorequalto, lessthanorequalto, crossesabove, crossesbelow, crosses, and, or, not, constantvalue
  - Interface: VERSION, PARAMS_SCHEMA, compute(...)
- Actions
  - enterlong, entershort, exitposition
  - Interface: VERSION, PARAMS_SCHEMA, execute(...)

Strategy Graph Model
- Directed acyclic graph (DAG)
- Nodes: indicator/operator/action instances with parameters
- Edges: connect outputs of a source node to inputs of a target node

Node Object
- id: string (unique within the graph)
- type: string (registry key, lowercase)
  - indicator types include: "price" and any discovered indicators (see discovery below)
  - operator types include: names listed above
  - action types include: enterlong, entershort, exitposition
- data:
  - params: object of parameters, validated against the node's PARAMS_SCHEMA

Edge Object
- source: string (node id)
- target: string (node id)
- sourceHandle: string (optional) name of the output when a source node has multiple outputs. For single-output nodes, may be omitted.

Top-Level Graph Envelope
- strategy_graph: { nodes: Node[], edges: Edge[] }
- metadata: optional object with free-form info (e.g., description, authoring model, prompt_hash)

Config JSON Returned by AI
You must produce a config dict optimized for our current UI, which reads from `strategy_params`:
- strategy_name: "SECTIONED_SPEC"
- strategy_params:
  - sectioned_spec:
    - strategy_graph: { nodes: [...], edges: [...] }
    - risk: {} (optional)
    - filters: {} (optional)
- indicator_configs: [] (keep empty for graph mode)
- notes: optional string

Backward compatibility
- If you also include a top-level `strategy_graph`, our backend will mirror it into `strategy_params.sectioned_spec.strategy_graph`.
- Prefer writing the graph under `strategy_params.sectioned_spec` to avoid ambiguity.

Validation Rules
- The graph must be acyclic (DAG).
- All node types must exist in our registries:
  - Indicators: price plus dynamically discovered indicators from indicators.definitions
  - Operators: the operators listed above
  - Actions: the actions listed above
- Each node's params must adhere to PARAMS_SCHEMA for that type:
  - Types include: string, number, integer, boolean
  - For enum, pick one valid option
  - Provide defaults where schema specifies
- For operators with variadic inputs (and/or), you may connect 2+ inputs; for unary operators (not), connect exactly 1.
- For crosses/crossesabove/crossesbelow: inputs must be time series (e.g., indicator outputs), not scalars.
- Actions should be driven by boolean inputs; typical pattern:
  - condition -> enterlong/entershort
  - optional exit condition -> exitposition

Registry Discovery (Indicators)
- We auto-discover indicators from the package indicators.definitions. To reference an indicator, use its class NAME (lowercase). For example:
  - If there is an EMA indicator class with NAME = "ema", outputs could be ["default"] or ["ema", ...] depending on its definition.
- You will be provided with a JSON snapshot of the response from `/api/bots/nodes/metadata/` (indicators + operators + actions). Use this snapshot as the source of truth for available node types, their PARAMS_SCHEMA, and outputs.
- Because this set may evolve, refresh the snapshot when deployments change. We recommend including a timestamp and git SHA with the snapshot to track staleness. If a snapshot is unavailable, default to core primitives like `price`.

Working with the nodes/metadata snapshot
- Use names exactly as provided (case-sensitive; typically lowercase). Do not invent new names.
- Validate all node params against the provided `PARAMS_SCHEMA`. Apply defaults where present; ensure enum values match.
- If any requested indicator/operator/action is NOT present in the snapshot, do not fabricate it. Return an explicit validation error that we will pass to the user.
  - Recommended 422 body:
    {
      "error": "unavailable_node",
      "missing": [
        { "kind": "indicator", "name": "ema" },
        { "kind": "operator", "name": "sma_crosses" }
      ],
      "message": "The following nodes are not available in this environment: indicator: ema, operator: sma_crosses"
    }
- Graph rules (recap):
  - Produce a DAG. Nodes: `{ id, type, data: { params } }`. Edges: `{ source, target, sourceHandle? }`.
  - Operators: `and`/`or` accept 2+ boolean inputs; `not` is unary; `crosses*` expect time-series inputs.
  - Actions (`enterlong`, `entershort`, `exitposition`) should receive boolean conditions.
  - `price` indicator is always available: params `{ source: open|high|low|close|volume|tick }`, output `default`.
- Treat the snapshot as authoritative for a given request. When the snapshot TTL expires or the git SHA changes, request/receive a fresh snapshot.

Example Minimal Config
{
  "strategy_name": "SECTIONED_SPEC",
  "strategy_params": {
    "sectioned_spec": {
      "strategy_graph": {
        "nodes": [
          { "id": "n1", "type": "price", "data": { "params": { "source": "close" } } },
          { "id": "n2", "type": "constantvalue", "data": { "params": { "value": 50 } } },
          { "id": "n3", "type": "greaterthan", "data": { "params": {} } },
          { "id": "n4", "type": "enterlong", "data": { "params": {} } }
        ],
        "edges": [
          { "source": "n1", "target": "n3", "sourceHandle": "default" },
          { "source": "n2", "target": "n3" },
          { "source": "n3", "target": "n4" }
        ]
      },
      "risk": {},
      "filters": {}
    }
  },
  "indicator_configs": [],
  "notes": "Enter long when close > 50"
}

Provider API Request From Our Backend
When we call your API, expect:
- POST <AI_STRATEGY_API_URL>
- Headers:
  - X-Request-ID: <uuid>
  - Content-Type: application/json
  - (No Authorization header will be sent by default.)
- Body:
  {
    "chatInput": "<prompt>",
    "session_id": "<uuid>",
    "trading_account_api_key": "<user-jwt-token>",
    "backend_url": "<our-backend-base-url>"
  }

Security
- Treat trading_account_api_key as a secret bearer token; do not log or persist it. Use only if you need to call our backend on the user’s behalf.

You may return on success (HTTP 200):
- Either:
  {
    "config": { ...config JSON... },
    "provider": "<name>",
    "model": "<model_id>",
    "request_id": "<uuid>"
  }
- Or simply the config object; our backend will wrap and normalize it.

Error Responses
- 400/422: Validation error. Body should include details.
  - For unavailable nodes, return 422 with the shape documented above (error=unavailable_node, missing=[], message).
- 401/403: Auth failures.
- 5xx: Transient errors. We will retry with exponential backoff; excessive failures trip a circuit breaker.

Best Practices for the Agent
- Ensure graph is DAG and references only registered types.
- Choose conservative defaults for indicator params where unspecified.
- Keep node ids short and unique (e.g., n1, n2...).
- Provide notes that concisely explain the strategy.
- Avoid logging sensitive content from prompts.

Extensibility
- As we add indicators under indicators.definitions, outputs and schemas can change. Query our metadata endpoints:
  - GET /api/bots/indicators/metadata/
  - GET /api/bots/nodes/metadata/  (indicators, operators, actions)
- Use these to dynamically adapt choices and produce compatible configs.

Appendix: Operator Names and Expectations
- greaterthan(a, b) -> bool
- lessthan(a, b) -> bool
- equalto(a, b) -> bool
- notequalto(a, b) -> bool
- greaterthanorequalto(a, b) -> bool
- lessthanorequalto(a, b) -> bool
- crossesabove(series_a, series_b) -> bool
- crossesbelow(series_a, series_b) -> bool
- crosses(series_a, series_b) -> bool
- and(*bools) -> bool
- or(*bools) -> bool
- not(a) -> bool
- constantvalue(value) -> float

Appendix: Indicator Example (Price)
- type: "price"
- params: { "source": "close" | "open" | "high" | "low" | "volume" | "tick" }
- outputs: ["default"]
