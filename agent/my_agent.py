"""AgentCore agent with memory support."""
import os
import time
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands import Agent
from strands.hooks import AgentInitializedEvent, HookProvider, HookRegistry, MessageAddedEvent
from strands_tools import calculator, current_time

from config import AgentConfig
from guardrails import NotifyOnlyGuardrailsHook
from logger import setup_logger
from telemetry import setup_telemetry, is_telemetry_initialized
from tools.knowledge_base import search_knowledge_base
from tools.url_fetcher import fetch_url_content
from tools.weather import get_current_weather
from tools.web_search import ddg_web_search

app = BedrockAgentCoreApp()

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
            
            # Remove <thinking> tags from Nova Pro responses before saving to memory
            import re
            text_content = re.sub(r'<thinking>[\s\S]*?</thinking>\s*', '', text_content).strip()
            
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
    
    # Get model ID from payload with default fallback (Requirement 10.7)
    model_id = payload.get("modelId", "global.amazon.nova-2-lite-v1:0")
    log.info(f"Using model: {model_id}")
    
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
    
    # Build tools list - conditionally include KB search if configured
    tools = [
        ddg_web_search,
        fetch_url_content,
        calculator, 
        get_current_weather,
        current_time
    ]
    
    # Add Knowledge Base search tool if KB is configured
    if config.kb_id:
        tools.insert(0, search_knowledge_base)  # Insert at beginning for priority
        log.info(f"Knowledge Base tool enabled: kb_id={config.kb_id}")
    else:
        log.warning("KB_ID not configured - agent will operate without Knowledge Base tool")
    
    # Build system prompt - include KB-first instruction if KB is configured
    base_system_prompt = "You are a helpful AI assistant with memory. You can remember previous conversations within the same session."
    
    if config.kb_id:
        system_prompt = (
            f"{base_system_prompt} "
            "You have access to a Knowledge Base containing curated domain-specific information. "
            "IMPORTANT: When answering questions, ALWAYS check the Knowledge Base first using the search_knowledge_base tool "
            "to find relevant context before using web search or other internet-based tools. "
            "Only fall back to web search (ddg_web_search) or URL fetching if the Knowledge Base does not contain relevant information. "
            "You also have access to: weather information for US locations, calculator for math, and current time/date."
        )
    else:
        system_prompt = (
            f"{base_system_prompt} "
            "You have access to various tools: web search via DuckDuckGo, URL content fetching, "
            "weather information for US locations, calculator for math, and current time/date."
        )
    
    agent = Agent(
        model=model_id,
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
                                    # Extract text from result content
                                    result_text = ''
                                    for result_content in tool_result.get('content', []):
                                        if 'text' in result_content:
                                            result_text = result_content['text']
                                            break
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