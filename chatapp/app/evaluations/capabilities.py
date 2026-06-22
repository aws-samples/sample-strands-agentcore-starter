"""Ground-truth manifest of the agent's real capabilities.

Used to ground LLM-as-judge evaluators so they do not penalize the agent for
truthfully describing tools it actually has. Without this, a judge with no
knowledge of the agent's tool set assumes capability claims (weather, URL
fetching, web search, etc.) are hallucinated and fails otherwise-correct
answers.

IMPORTANT: This MUST be kept in sync with the agent definition in
agent/my_agent.py (its `tools` list and `system_prompt`). The chatapp and the
agent are deployed separately, so this cannot be imported from the agent
package and is intentionally duplicated here.
"""

# Mirrors agent/my_agent.py: tools list + system prompt capability statements.
AGENT_CAPABILITIES_MANIFEST = """\
The assistant is a helpful AI assistant with per-session conversation memory \
(it can remember earlier messages within the same session).

The assistant has access to the following tools and may truthfully describe \
any of them as its own capabilities:
- search_knowledge_base: search a curated, domain-specific Knowledge Base. \
This is the preferred first source and is checked before web tools.
- ddg_web_search: perform a DuckDuckGo web search for current or general \
internet information.
- fetch_url_content: fetch and read the content of a specific URL / webpage.
- calculator: a symbolic math engine (sympy-backed). Beyond basic arithmetic \
it supports equation solving, derivatives (including higher-order), indefinite \
integrals, limits, Taylor/Laurent series expansions, and matrix operations.
- get_current_weather: look up current weather for US locations.
- current_time: get the current date and time for any named timezone \
(e.g., UTC, US/Pacific, Europe/London, Asia/Tokyo), defaulting to UTC.

Statements by the assistant that describe any of the above capabilities are \
ACCURATE and must NOT be treated as hallucinations or false claims. Only treat \
capability claims as a problem when they contradict this list or go beyond it \
(for example, claiming to send email, book travel, or run code).\
"""
