"""AgentCore agent with memory support."""
import json
import os
import time
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands import Agent
from strands.hooks import AgentInitializedEvent, HookProvider, HookRegistry, MessageAddedEvent
from strands.models.openai import OpenAIModel
from strands.models.openai_responses import OpenAIResponsesModel
from strands.models.anthropic import AnthropicModel
from strands_tools import calculator, current_time
from aws_bedrock_token_generator import provide_token

from config import AgentConfig
from guardrails import NotifyOnlyGuardrailsHook
from logger import setup_logger
from telemetry import setup_telemetry, is_telemetry_initialized
from tools.knowledge_base import search_knowledge_base
from tools.url_fetcher import fetch_url_content
from tools.weather import get_current_weather
from tools.web_search import ddg_web_search

app = BedrockAgentCoreApp()

# Generic reasoning-delimiter stripping (provider-agnostic)
REASONING_DELIMITERS = [("<thinking>", "</thinking>")]


def strip_reasoning(text: str) -> str:
    """Remove reasoning content wrapped in known delimiter tags.

    Generic delimiter stripping for any model that emits reasoning wrapped in
    tags. Not tied to any specific provider.
    """
    import re
    for open_tag, close_tag in REASONING_DELIMITERS:
        pattern = re.escape(open_tag) + r"[\s\S]*?" + re.escape(close_tag) + r"\s*"
        text = re.sub(pattern, "", text)
    return text.strip()

# Default model when no modelId is supplied in the payload.
# Must match `default_model_id` in chatapp/app/static/models.json.
DEFAULT_MODEL_ID = "anthropic.claude-haiku-4-5"

# Global config and logger - will be initialized on first invoke
_config = None
_logger = None
_memory_client = None
_memory_id = None

def get_config():
    """Get or initialize configuration."""
    global _config, _logger, _memory_client, _memory_id
    if _config is None:
        _config = AgentConfig.from_env()
        _logger = setup_logger(__name__, _config.log_level)
        _memory_client = MemoryClient(region_name=_config.aws_region)
        _memory_id = _config.memory_id
        
        # Setup OpenTelemetry if not already initialized
        if not is_telemetry_initialized():
            setup_telemetry(
                enabled=_config.otel_enabled,
                otlp_endpoint=_config.otel_endpoint,
                console_export=_config.otel_console_export,
                service_name="agentcore-chat-agent"
            )
            if _config.otel_enabled:
                _logger.info(
                    f"OpenTelemetry initialized - "
                    f"endpoint: {_config.otel_endpoint or 'default'}, "
                    f"console: {_config.otel_console_export}"
                )
    return _config, _logger, _memory_client, _memory_id


class MemoryHook(HookProvider):
    """Automatically handles memory operations for conversation persistence.
    
    This hook integrates with AgentCore Memory to:
    - Load previous conversation history when the agent initializes
    - Save each message after it's processed
    
    Memory operations are non-blocking - failures are logged but don't prevent
    the agent from functioning.
    """

    def on_agent_initialized(self, event):
        """Load conversation history when agent starts.
        
        Retrieves recent events from AgentCore Memory for the current session
        and injects them into the agent's system prompt as context.
        
        Args:
            event: AgentInitializedEvent containing agent instance and state
        """
        config, log, mem_client, mem_id = get_config()
        
        if not mem_id:
            log.warning("No MEMORY_ID configured - agent will run without memory")
            return

        # Access state directly as a dictionary
        session_id = event.agent.state.get("session_id") or "default"
        user_id = event.agent.state.get("user_id") or "anonymous"
        log.info(f"Loading memory for user: {user_id}, session: {session_id}")
        
        try:
            # List recent events for this user session
            events = mem_client.list_events(
                memory_id=mem_id,
                actor_id=user_id,
                session_id=session_id,
                max_results=50,  # Get last 50 events
                include_payload=True
            )

            log.debug(f"Retrieved {len(events) if events else 0} events from memory")
            
            # Extract messages from events and build context
            if events:
                messages = []
                # Reverse events so most recent is first
                for evt in reversed(events):
                    for payload_item in evt.get("payload", []):
                        if "conversational" in payload_item:
                            conv = payload_item["conversational"]
                            role = conv.get("role", "")
                            text = conv.get("content", {}).get("text", "")
                            if text:
                                messages.append(f"{role}: {text}")
                
                if messages:
                    # Take first 30 messages (most recent, since we reversed the events)
                    context = "\n".join(messages[:30])
                    event.agent.system_prompt += f"\n\nPrevious conversation history:\n{context}"
                    log.info(f"Loaded {len(messages)} messages from memory into context (showing most recent 30)")
                    log.info(f"Full system prompt with history: {event.agent.system_prompt}")
                else:
                    log.debug("No messages found in retrieved events")
            else:
                log.info("No previous conversation found in memory for this session")
        except Exception as e:
            log.error(f"Error loading memory (agent will continue without history): {e}", exc_info=True)

    def on_message_added(self, event):
        """Save message to memory after it's processed.
        
        Persists each message (user and assistant) to AgentCore Memory
        for future retrieval in the same session.
        
        This hook is non-blocking - any errors are logged but do not
        prevent the agent from continuing to process and return responses.
        
        Args:
            event: MessageAddedEvent containing agent instance and new message
        """
        # Wrap entire method in try/except to ensure it never blocks the agent
        try:
            config, log, mem_client, mem_id = get_config()
            
            if not mem_id:
                log.debug("No MEMORY_ID configured - skipping memory save")
                return

            # Access state directly as a dictionary
            session_id = event.agent.state.get("session_id") or "default"
            user_id = event.agent.state.get("user_id") or "anonymous"
            
            # Save the latest message to memory
            msg = event.agent.messages[-1]
            content = msg.get("content", "")
            role = msg.get("role", "user")
            
            # Skip messages that contain tool results or tool uses
            if isinstance(content, list):
                # Check if any content block is a tool result or tool use
                has_tool_content = any(
                    "toolResult" in block or "toolUse" in block 
                    for block in content 
                    if isinstance(block, dict)
                )
                if has_tool_content:
                    log.debug(f"Skipping tool message from memory save: role={role}")
                    return
                
                # Extract text content only
                text_content = ""
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_content += block["text"]
                
                if not text_content:
                    log.debug(f"Skipping message with no text content: role={role}")
                    return
            else:
                text_content = str(content)
            
            # Strip reasoning delimiters from model responses before saving to memory
            text_content = strip_reasoning(text_content)
            
            # Skip if text is empty after cleaning
            if not text_content:
                log.debug(f"Skipping message with empty content after cleaning: role={role}")
                return
            
            log.debug(f"Saving to memory: user={user_id}, role={role}, session={session_id}, content_length={len(text_content)}")
            
            mem_client.create_event(
                memory_id=mem_id,
                actor_id=user_id,
                session_id=session_id,
                messages=[(text_content, role)]
            )
            log.info(f"Saved {role} message to memory (session: {session_id})")
        except Exception as e:
            # Log error but do not re-raise - memory failures should not block agent responses
            log.error(f"Error saving to memory (message will not be persisted): {e}", exc_info=True)

    def register_hooks(self, registry: HookRegistry):
        """Register memory hooks with the agent.
        
        Registers callbacks for agent initialization and message events
        to enable automatic memory loading and saving.
        
        Args:
            registry: Hook registry to register callbacks with
        """
        registry.add_callback(AgentInitializedEvent, self.on_agent_initialized)
        registry.add_callback(MessageAddedEvent, self.on_message_added)


@app.entrypoint
async def invoke(payload, context):
    """Your AI agent function with memory support and streaming.
    
    Processes user messages through the AI agent with conversation memory.
    Streams events when possible, falls back to simple response otherwise.
    
    Args:
        payload: Request payload containing 'prompt' field with user message
        context: Runtime context containing session_id and other metadata
        
    Yields:
        Dictionary events containing agent lifecycle and response data
        
    Raises:
        ValueError: If required configuration is missing or invalid
    """
    # Start timing
    start_time = time.time()
    
    # Ensure config is loaded and validated
    try:
        config, log, _, _ = get_config()
        log.debug(f"Configuration loaded: memory_id={config.memory_id}, region={config.aws_region}, log_level={config.log_level}")
    except ValueError as e:
        # Re-raise configuration errors with clear context
        raise ValueError(f"Configuration validation failed: {e}") from e
    except Exception as e:
        # Catch any other initialization errors
        raise RuntimeError(f"Failed to initialize agent configuration: {e}") from e
    
    # Get session ID from runtime context
    session_id = "default"
    if hasattr(context, 'session_id') and context.session_id:
        session_id = context.session_id
        log.info(f"Using session ID: {session_id}")
    else:
        log.warning("No session_id provided in context, using default")
    
    # Get user ID from payload (passed from Lambda/Cognito)
    user_id = payload.get("userId", "anonymous")
    log.info(f"Using user ID: {user_id}")
    
    # Get model ID and API type from payload with default fallback
    model_id = payload.get("modelId") or DEFAULT_MODEL_ID
    # Default API must match DEFAULT_MODEL_ID's catalog entry. The default model
    # (anthropic.claude-haiku-4-5) is served via the Anthropic Messages API.
    model_api = payload.get("modelApi", "messages")  # "chat", "responses", or "messages"
    log.info(f"Using model: {model_id} (api: {model_api})")
    
    # Mint a fresh short-term Bedrock token for THIS invocation.
    # The optional config override short-circuits token generation for local/advanced use.
    try:
        api_key = config.openai_api_key or provide_token(region=config.mantle_region)
    except Exception as e:
        raise ValueError(
            "Failed to mint a Bedrock Mantle token. Verify AWS credentials are "
            "available to the AgentCore Runtime role."
        ) from e
    
    # NOTE: The token (valid ≤12h) must be refreshed if the model/agent is ever
    # cached across requests. Currently, the model is constructed per invoke so
    # every request gets a fresh token.
    #
    # Provider routing based on the model's supported API:
    # - "messages" → AnthropicModel (Anthropic Messages API at /v1)
    # - "responses" → OpenAIResponsesModel (Responses API at /openai/v1)
    # - "chat" → OpenAIModel (Chat Completions at /v1)
    mantle_base = config.openai_base_url.rstrip('/')  # e.g. https://bedrock-mantle.us-east-1.api.aws/v1

    if model_api == "messages":
        # Anthropic models use the Messages API.
        #
        # Base URL: Mantle serves the Anthropic Messages API under the
        # "/anthropic" prefix (analogous to "/openai/v1" for the Responses API).
        # The Anthropic SDK appends "/v1/messages" to its base_url itself, so
        # the base must end at ".../anthropic" to produce the working endpoint
        # ".../anthropic/v1/messages". `mantle_base` ends in "/v1" (the
        # OpenAI-style base), so strip that and append "/anthropic".
        # Verified: POST .../anthropic/v1/messages returns 200; .../v1/messages
        # and .../v1/v1/messages both 404.
        anthropic_base = mantle_base
        if anthropic_base.endswith("/v1"):
            anthropic_base = anthropic_base[: -len("/v1")]
        anthropic_base = anthropic_base.rstrip("/") + "/anthropic"
        #
        # Auth: Mantle authenticates with `Authorization: Bearer <token>` (the
        # same scheme the OpenAI-compatible client uses). The Anthropic SDK
        # sends `api_key` as the `x-api-key` header instead, which Mantle
        # rejects. Passing the minted token as `auth_token` makes the SDK send
        # it as a Bearer token.
        model = AnthropicModel(
            model_id=model_id,
            client_args={
                "auth_token": api_key,
                "base_url": anthropic_base,
            },
            max_tokens=4096,
        )
    elif model_api == "responses":
        # GPT-5.x, Gemma 4, Grok use the Responses API on /openai/v1 path
        responses_base = mantle_base.replace("/v1", "/openai/v1")
        model = OpenAIResponsesModel(
            model_id=model_id,
            client_args={
                "api_key": api_key,
                "base_url": responses_base,
                "project": config.mantle_project,
            },
        )
    else:
        # Default: Chat Completions API (majority of models)
        model = OpenAIModel(
            client_args={
                "api_key": api_key,
                "base_url": mantle_base,
                "project": config.mantle_project,
            },
            model_id=model_id,
        )
    
    # Get guardrail config from payload (passed from chatapp) or fall back to env/config
    guardrail_id = payload.get("guardrailId") or config.guardrail_id
    guardrail_version = payload.get("guardrailVersion") or config.guardrail_version
    guardrail_enabled = payload.get("guardrailEnabled", config.guardrail_enabled)
    # Handle string "true"/"false" from payload
    if isinstance(guardrail_enabled, str):
        guardrail_enabled = guardrail_enabled.lower() in ("true", "1", "yes")
    
    log.info(f"Guardrail config: id={guardrail_id}, version={guardrail_version}, enabled={guardrail_enabled}")
    
    # Create agent with session-specific state, hooks, tools, and trace attributes
    # Initialize hooks - memory and guardrails (shadow mode)
    hooks = [MemoryHook()]
    
    # Add guardrails hook if configured - pass config values from payload
    guardrails_hook = NotifyOnlyGuardrailsHook(
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        region=config.aws_region,
        enabled=guardrail_enabled,
    )
    hooks.append(guardrails_hook)
    
    # Build tools list
    tools = [
        search_knowledge_base,
        ddg_web_search,
        fetch_url_content,
        calculator, 
        get_current_weather,
        current_time
    ]    
    log.info(f"Knowledge Base tool enabled: kb_id={config.kb_id}")
    
    # System prompt
    system_prompt = (
        "You are a helpful AI assistant with memory. You can remember previous conversations within the same session. "
        "You have access to a Knowledge Base containing curated domain-specific information. "
        "IMPORTANT: When answering questions, ALWAYS check the Knowledge Base first using the search_knowledge_base tool "
        "to find relevant context before using web search or other internet-based tools. "
        "Only fall back to web search (ddg_web_search) or URL fetching if the Knowledge Base does not contain relevant information. "
        "You also have access to: weather information for US locations, calculator for math, and current time/date."
    )
    
    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        hooks=hooks,
        tools=tools,
        state={"session_id": session_id, "user_id": user_id},
        trace_attributes={
            "session.id": session_id,
            "user.id": user_id,
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "production"),
            "memory.id": config.memory_id
        }
    )
    
    user_message = payload.get("prompt", "Hello! How can I help you today?")
    log.debug(f"Processing user message: {user_message[:50]}...")
    
    try:
        # Stream agent events for detailed visibility
        agent_stream = agent.stream_async(user_message)
        
        # Track seen tool uses to avoid duplicates
        seen_tool_uses = set()
        
        async for event in agent_stream:
            # Check if event is a dict with messages (Strands format)
            if isinstance(event, dict) and 'messages' in event:
                # Extract tool use and tool result from messages
                for message in event.get('messages', []):
                    if message.get('role') == 'assistant':
                        for content_block in message.get('content', []):
                            # Tool use
                            if 'toolUse' in content_block:
                                tool_use = content_block['toolUse']
                                tool_id = tool_use.get('toolUseId')
                                if tool_id and tool_id not in seen_tool_uses:
                                    seen_tool_uses.add(tool_id)
                                    tool_name = tool_use.get('name', 'unknown')
                                    log.info(f"Tool use: {tool_name}")
                                    yield {
                                        "type": "tool_use",
                                        "tool_name": tool_name,
                                        "tool_input": tool_use.get('input', {}),
                                        "tool_use_id": tool_id,
                                    }
                    elif message.get('role') == 'user':
                        for content_block in message.get('content', []):
                            # Tool result
                            if 'toolResult' in content_block:
                                tool_result = content_block['toolResult']
                                tool_id = tool_result.get('toolUseId')
                                if tool_id:
                                    log.info(f"Tool result for: {tool_id}")
                                    # Capture ALL content blocks (text and json),
                                    # not just the first text block. Tools that
                                    # return structured data (e.g. the weather
                                    # tool's dict) surface as a json block; only
                                    # reading text dropped that data from the UI
                                    # and from evaluation grounding.
                                    result_parts = []
                                    for result_content in tool_result.get('content', []):
                                        if 'text' in result_content:
                                            result_parts.append(result_content['text'])
                                        elif 'json' in result_content:
                                            result_parts.append(
                                                json.dumps(result_content['json'], default=str)
                                            )
                                    result_text = '\n'.join(result_parts)
                                    yield {
                                        "type": "tool_result",
                                        "tool_name": tool_id,
                                        "tool_result": result_text,
                                        "tool_use_id": tool_id,
                                    }
            
            # Yield the original event
            yield event
        
        # Yield any guardrail violations detected during the invocation
        guardrail_violations = guardrails_hook.get_and_clear_violations()
        for violation in guardrail_violations:
            log.info(f"Yielding guardrail violation: source={violation.get('source')}")
            yield violation
        
        # Log completion
        end_time = time.time()
        total_duration = end_time - start_time
        log.info(f"Invocation complete - Duration: {total_duration:.2f}s, Session: {session_id}")
        
    except Exception as e:
        log.error(f"Error processing message: {e}", exc_info=True)
        yield {"error": True, "message": str(e)}
        raise


if __name__ == "__main__":
    app.run()