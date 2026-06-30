"""AgentCore client for invoking the Bedrock AgentCore Runtime.

This module provides the AgentCoreClient class for streaming responses
from the AgentCore Runtime and converting them to typed SSE events.
"""

import asyncio
import json
import re
import threading
from typing import AsyncGenerator, Generator, Optional, Dict, Any

import boto3
from botocore.config import Config

from app.config import get_config
from app.models.events import (
    SSEEvent,
    MessageEvent,
    ReasoningEvent,
    ToolUseEvent,
    ToolResultEvent,
    ErrorEvent,
    MetadataEvent,
    DoneEvent,
    GuardrailEvent,
)


class ThinkingFilter:
    """Stateful filter for removing <thinking> tags and tool XML from streamed content.
    
    This filter accumulates content and removes thinking blocks and tool call XML,
    handling partial tags that may span multiple chunks. It also extracts tool calls
    from Nova's XML format and stores them for emission as proper events.
    """
    
    def __init__(self):
        self._full_content = ""
        self._sent_length = 0
        self._extracted_tools: list = []  # Store extracted tool calls
        self._seen_tool_ids: set = set()  # Track emitted tools to avoid duplicates
    
    def filter(self, text: str) -> Optional[str]:
        """Filter out thinking tags and tool XML from streamed content.
        
        Args:
            text: Raw text chunk from the stream
            
        Returns:
            Filtered text without thinking tags or tool XML, or None if no new content
        """
        self._full_content += text
        
        # Remove complete thinking blocks
        filtered = re.sub(r'<thinking>[\s\S]*?</thinking>', '', self._full_content)
        
        # Extract tool calls from Nova XML format before removing them
        self._extract_tool_calls(self._full_content)
        
        # Remove tool call XML - Nova model uses <__function=name> format (double underscore)
        filtered = re.sub(r'<__function=[^>]*>[\s\S]*?</__function>', '', filtered)
        # Also handle incomplete/malformed function tags
        filtered = re.sub(r'<__function=[^>]*>[\s\S]*?</', '', filtered)
        # Remove standalone function tags that might be partial
        filtered = re.sub(r'<__function=[^>]*>[^<]*$', '', filtered)
        # Remove partial opening function tags at end of content
        filtered = re.sub(r'<__function=[^>]*$', '', filtered)
        
        # Also handle single underscore format just in case
        filtered = re.sub(r'<function=[^>]*>[\s\S]*?</function>', '', filtered)
        filtered = re.sub(r'<function=[^>]*>[^<]*$', '', filtered)
        
        # Remove parameter tags (Nova model format: <__parameter=name>value</__parameter>)
        filtered = re.sub(r'<__parameter=[^>]*>[\s\S]*?</__parameter>', '', filtered)
        # Remove partial parameter tags and standalone tags
        filtered = re.sub(r'<__parameter=[^>]*>[^<]*$', '', filtered)
        filtered = re.sub(r'<__parameter=[^>]*>$', '', filtered)
        filtered = re.sub(r'</__parameter>', '', filtered)
        
        # Remove incomplete opening tag at the end (pattern: <thinking> followed by anything until end)
        open_tag_pattern = r'<thinking>[\s\S]*$'
        open_tag_match = re.search(open_tag_pattern, filtered)
        if open_tag_match:
            filtered = filtered[:len(filtered) - len(open_tag_match.group(0))]
        
        # Check for partial opening tags (pattern: < followed by non-> chars at end)
        partial_tag_pattern = r'<[^>]*$'
        partial_tag_match = re.search(partial_tag_pattern, filtered)
        if partial_tag_match:
            partial = partial_tag_match.group(0)
            if '<thinking>'.startswith(partial):
                filtered = filtered[:len(filtered) - len(partial)]
        
        # Return only new content
        if len(filtered) > self._sent_length:
            new_content = filtered[self._sent_length:]
            self._sent_length = len(filtered)
            return new_content
        
        return None
    
    def _extract_tool_calls(self, content: str) -> None:
        """Extract tool calls from Nova's XML format.
        
        Parses <__function=name>...</__function> blocks and extracts
        tool name and parameters for emission as ToolUseEvent.
        """
        # Match complete function blocks: <__function=name>params</__function>
        pattern = r'<__function=([^>]+)>([\s\S]*?)</__function>'
        matches = re.findall(pattern, content)
        
        for tool_name, params_block in matches:
            # Generate a unique ID for this tool call
            tool_id = f"nova-{tool_name}-{hash(params_block) & 0xFFFFFFFF}"
            
            if tool_id in self._seen_tool_ids:
                continue
            
            self._seen_tool_ids.add(tool_id)
            
            # Extract parameters from <__parameter=name>value</__parameter> tags
            param_pattern = r'<__parameter=([^>]+)>([^<]*)</__parameter>'
            param_matches = re.findall(param_pattern, params_block)
            
            tool_input = {}
            for param_name, param_value in param_matches:
                # Try to parse as JSON if it looks like JSON
                try:
                    if param_value.strip().startswith(('{', '[', '"')):
                        tool_input[param_name] = json.loads(param_value)
                    else:
                        tool_input[param_name] = param_value
                except json.JSONDecodeError:
                    tool_input[param_name] = param_value
            
            self._extracted_tools.append({
                'tool_name': tool_name,
                'tool_input': tool_input,
                'tool_use_id': tool_id,
            })
    
    def get_extracted_tools(self) -> list:
        """Get and clear extracted tool calls.
        
        Returns:
            List of tool call dicts with tool_name, tool_input, tool_use_id
        """
        tools = self._extracted_tools.copy()
        self._extracted_tools.clear()
        return tools


class AgentCoreClient:
    """Client for invoking AgentCore Runtime and streaming responses.
    
    This client handles communication with the Bedrock AgentCore Runtime,
    parsing NDJSON responses and converting them to typed SSE events.
    
    Attributes:
        runtime_arn: ARN of the AgentCore Runtime
        region: AWS region
    """
    
    def __init__(
        self,
        runtime_arn: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the AgentCore client.
        
        Args:
            runtime_arn: AgentCore Runtime ARN (defaults to config)
            region: AWS region (defaults to config)
        """
        config = get_config()
        self.runtime_arn = runtime_arn or config.agentcore_runtime_arn
        self.region = region or config.aws_region
        
        # Configure boto3 client with retry settings
        boto_config = Config(
            region_name=self.region,
            retries={'max_attempts': 3, 'mode': 'adaptive'},
        )
        
        self._client = boto3.client(
            'bedrock-agentcore',
            config=boto_config,
        )
    
    def _parse_ndjson_line(
        self,
        line: str,
        thinking_filter: ThinkingFilter,
    ) -> Optional[SSEEvent]:
        """Parse a single NDJSON line from AgentCore response.
        
        Args:
            line: Raw JSON line from the response
            thinking_filter: Filter instance for removing thinking tags
            
        Returns:
            Parsed SSE event or None if line should be skipped
        """
        if not line.strip():
            return None
        
        try:
            # Handle SSE format: "data: {...}" or plain JSON
            json_str = line
            if line.startswith('data: '):
                json_str = line[6:]
            
            data: Dict[str, Any] = json.loads(json_str)
            
            # Handle error events emitted by the agent entrypoint
            # (e.g. {"error": True, "message": "..."}). Without this branch the
            # agent's failure is silently dropped and the user just sees an
            # empty response with no explanation.
            if data.get('error'):
                return ErrorEvent(
                    message=data.get('message') or 'The agent failed to generate a response',
                    details=data.get('details'),
                )
            
            # Handle reasoningContent streaming events (thinking models)
            reasoning_delta = data.get('event', {}).get('contentBlockDelta', {}).get('delta', {}).get('reasoningContent')
            if reasoning_delta:
                reasoning_text = reasoning_delta.get('text', '')
                if reasoning_text:
                    return ReasoningEvent(content=reasoning_text)
                return None
            
            # Handle contentBlockDelta streaming events
            if data.get('event', {}).get('contentBlockDelta', {}).get('delta', {}).get('text'):
                text = data['event']['contentBlockDelta']['delta']['text']
                filtered = thinking_filter.filter(text)
                if filtered:
                    return MessageEvent(content=filtered)
                return None
            
            # Handle TextStreamEvent
            if data.get('type') == 'TextStreamEvent' and data.get('text'):
                filtered = thinking_filter.filter(data['text'])
                if filtered:
                    return MessageEvent(content=filtered)
                return None
            
            # Handle Strands tool events - direct format
            if data.get('type') == 'tool_use':
                tool_name = data.get('tool_name') or data.get('name') or 'unknown'
                return ToolUseEvent(
                    tool_name=tool_name,
                    tool_input=data.get('tool_input') or data.get('input'),
                    tool_use_id=data.get('tool_use_id') or data.get('id') or f"tool-{id(data)}",
                    status=data.get('status', 'started'),
                )
            
            if data.get('type') == 'tool_result':
                tool_name = data.get('tool_name') or data.get('name') or 'unknown'
                return ToolResultEvent(
                    tool_name=tool_name,
                    tool_result=data.get('tool_result') or data.get('result'),
                    tool_use_id=data.get('tool_use_id') or data.get('id') or f"tool-{id(data)}",
                    status=data.get('status', 'completed'),
                )
            
            # Handle guardrail events from agent
            if data.get('type') == 'guardrail':
                return GuardrailEvent(
                    source=data.get('source', 'INPUT'),
                    action=data.get('action', 'NONE'),
                    assessments=data.get('assessments', []),
                )
            
            # Handle nested content blocks (Bedrock format)
            content = data.get('content', [])
            if isinstance(content, list):
                for block in content:
                    if block.get('toolUse'):
                        tool_use = block['toolUse']
                        return ToolUseEvent(
                            tool_name=tool_use['name'],
                            tool_input=tool_use.get('input'),
                            tool_use_id=tool_use.get('toolUseId'),
                            status='started',
                        )
                    if block.get('toolResult'):
                        tool_result = block['toolResult']
                        return ToolResultEvent(
                            tool_name=tool_result.get('name', 'unknown'),
                            tool_result=tool_result.get('content'),
                            tool_use_id=tool_result.get('toolUseId'),
                            status=tool_result.get('status', 'completed'),
                        )
            
            # Skip final message event to avoid duplication
            if data.get('message', {}).get('content'):
                return None
            
            # Handle legacy message format
            if data.get('type') == 'message' and isinstance(data.get('content'), list):
                text_content = ''
                for block in data['content']:
                    if block.get('text'):
                        text_content += block['text']
                if text_content:
                    filtered = thinking_filter.filter(text_content)
                    if filtered:
                        return MessageEvent(content=filtered)
                return None
            
            # Handle Strands ModelMetadataEvent format (usage at top level)
            usage = data.get('usage', {})
            metrics_data = data.get('metrics', {})
            if usage or metrics_data:
                return MetadataEvent(data={
                    'inputTokens': usage.get('inputTokens', 0),
                    'outputTokens': usage.get('outputTokens', 0),
                    'totalTokens': usage.get('totalTokens', 0),
                    'latencyMs': metrics_data.get('latencyMs', 0),
                })
            
            # Extract metadata from legacy format (event.metadata.usage)
            metadata = data.get('event', {}).get('metadata', {})
            if metadata:
                usage = metadata.get('usage', {})
                metrics = metadata.get('metrics', {})
                if usage or metrics:
                    return MetadataEvent(data={
                        'inputTokens': usage.get('inputTokens'),
                        'outputTokens': usage.get('outputTokens'),
                        'latencyMs': metrics.get('latencyMs'),
                    })
            
            return None
            
        except json.JSONDecodeError:
            return None
        except Exception:
            return None


    async def invoke_stream(
        self,
        prompt: str,
        session_id: str,
        user_id: str,
        model_id: str = "anthropic.claude-haiku-4-5",
        model_api: str = "messages",
    ) -> AsyncGenerator[SSEEvent, None]:
        """Invoke AgentCore Runtime and stream the response.

        The underlying boto3 ``invoke_agent_runtime`` call and its streaming body
        are fully synchronous and blocking. Iterating that body directly on the
        asyncio event loop freezes the loop between chunks, which prevents
        already-produced SSE bytes from being flushed to the browser and, in
        compare mode, serializes the per-lane streams so the UI only paints once
        everything has arrived.

        To keep the event loop free, the blocking read+parse runs in a worker
        thread (``_invoke_stream_sync``) and the parsed events are bridged back
        to this coroutine over a thread-safe queue. The loop can then flush each
        token as it arrives and genuinely interleave multiple concurrent lanes.

        Args:
            prompt: User message to send to the agent
            session_id: Session ID for conversation context
            user_id: User ID for memory operations
            model_id: Model identifier for LLM selection
            model_api: Which Mantle API the model uses (chat/responses/messages)

        Yields:
            SSE events as they are received from AgentCore
        """
        loop = asyncio.get_running_loop()
        queue: "asyncio.Queue[Any]" = asyncio.Queue()
        stop_event = threading.Event()
        _DONE = object()

        def _pump() -> None:
            # Runs on a worker thread: drive the blocking sync generator and hand
            # each event to the loop. call_soon_threadsafe is the supported way to
            # touch loop/Queue state from another thread.
            try:
                for ev in self._invoke_stream_sync(
                    prompt=prompt,
                    session_id=session_id,
                    user_id=user_id,
                    model_id=model_id,
                    model_api=model_api,
                    stop_event=stop_event,
                ):
                    loop.call_soon_threadsafe(queue.put_nowait, ev)
            except Exception as exc:  # noqa: BLE001 - safety net; sync gen maps known errors
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    ErrorEvent(message='Failed to invoke AgentCore', details=str(exc)),
                )
                loop.call_soon_threadsafe(queue.put_nowait, DoneEvent())
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, _DONE)

        # Keep a reference so the executor future isn't GC'd mid-flight.
        pump_future = loop.run_in_executor(None, _pump)
        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    break
                yield item
        finally:
            # On client disconnect / early close, signal the worker to stop after
            # its current (uninterruptible) read so it unwinds the boto3 stream.
            # We intentionally don't await the future here: this finally can run
            # during generator finalization/cancellation, where awaiting risks a
            # GeneratorExit/CancelledError clash. The thread observes the flag and
            # exits on its own after the in-flight read returns.
            stop_event.set()

    def _invoke_stream_sync(
        self,
        prompt: str,
        session_id: str,
        user_id: str,
        model_id: str = "anthropic.claude-haiku-4-5",
        model_api: str = "messages",
        stop_event: Optional[threading.Event] = None,
    ) -> Generator[SSEEvent, None, None]:
        """Blocking AgentCore invocation + NDJSON parse, as a sync generator.

        Intended to be driven from a worker thread by :meth:`invoke_stream`.
        Yields the same typed SSE events; checks ``stop_event`` between chunks so
        a disconnected client unwinds the read promptly (a chunk already in
        flight cannot be interrupted).
        """
        import codecs
        
        thinking_filter = ThinkingFilter()
        
        try:
            # Prepare the payload - boto3 streaming body expects a file-like object
            from io import BytesIO
            
            # Get guardrail config from app config
            config = get_config()
            
            payload_dict = {
                'prompt': prompt,
                'userId': user_id,
                'sessionId': session_id,  # Include session ID in payload for usage logs
                'modelId': model_id,
                'modelApi': model_api,
                'guardrailId': config.guardrail_id,
                'guardrailVersion': config.guardrail_version,
                'guardrailEnabled': config.guardrail_enabled,
            }
            payload_bytes = json.dumps(payload_dict).encode('utf-8')
            
            # Invoke the agent runtime
            response = self._client.invoke_agent_runtime(
                runtimeSessionId=session_id,
                agentRuntimeArn=self.runtime_arn,
                payload=BytesIO(payload_bytes),
            )
            
            if 'response' not in response:
                yield ErrorEvent(message='No response from AgentCore')
                return
            
            # Process the streaming response
            stream = response['response']
            buffer = ''
            
            # Use incremental decoder to handle partial UTF-8 sequences
            utf8_decoder = codecs.getincrementaldecoder('utf-8')('replace')
            
            # Read chunks from the stream - StreamingBody yields bytes directly
            for chunk in stream:
                # Stop early if the consumer (client) has gone away. The current
                # in-flight read cannot be interrupted, but we won't start
                # parsing/yielding more once cancellation is signalled.
                if stop_event is not None and stop_event.is_set():
                    break
                # Handle different chunk formats and get raw bytes
                raw_bytes = None
                if isinstance(chunk, bytes):
                    raw_bytes = chunk
                elif isinstance(chunk, str):
                    # Already decoded, use directly
                    buffer += chunk
                    raw_bytes = None
                elif isinstance(chunk, dict):
                    # Handle wrapped chunk format
                    if 'chunk' in chunk:
                        chunk_data = chunk['chunk']
                        if isinstance(chunk_data, dict):
                            raw_bytes = chunk_data.get('bytes', b'')
                        elif isinstance(chunk_data, bytes):
                            raw_bytes = chunk_data
                        else:
                            buffer += str(chunk_data)
                            raw_bytes = None
                    elif 'bytes' in chunk:
                        raw_bytes = chunk['bytes']
                    else:
                        continue
                else:
                    continue
                
                # Decode bytes using incremental decoder (handles partial UTF-8)
                if raw_bytes is not None:
                    text = utf8_decoder.decode(raw_bytes, final=False)
                    buffer += text
                
                # Process complete lines
                lines = buffer.split('\n')
                buffer = lines.pop()  # Keep incomplete line in buffer
                
                for line in lines:
                    if not line.strip():
                        continue
                    event = self._parse_ndjson_line(line, thinking_filter)
                    if event:
                        yield event
                    
                    # Emit any tool events extracted from Nova XML format
                    for tool in thinking_filter.get_extracted_tools():
                        yield ToolUseEvent(
                            tool_name=tool['tool_name'],
                            tool_input=tool['tool_input'],
                            tool_use_id=tool['tool_use_id'],
                            status='started',
                        )
            
            # Flush any remaining bytes in the decoder
            final_text = utf8_decoder.decode(b'', final=True)
            if final_text:
                buffer += final_text
            
            # Process remaining buffer
            if buffer.strip():
                event = self._parse_ndjson_line(buffer, thinking_filter)
                if event:
                    yield event
                
                # Emit any remaining tool events
                for tool in thinking_filter.get_extracted_tools():
                    yield ToolUseEvent(
                        tool_name=tool['tool_name'],
                        tool_input=tool['tool_input'],
                        tool_use_id=tool['tool_use_id'],
                        status='started',
                    )
            
            # Send completion event
            yield DoneEvent()
            
        except self._client.exceptions.ValidationException as e:
            yield ErrorEvent(
                message='Invalid request to AgentCore',
                details=str(e),
            )
            yield DoneEvent()
        except self._client.exceptions.ThrottlingException as e:
            yield ErrorEvent(
                message='Request throttled by AgentCore',
                details=str(e),
            )
            yield DoneEvent()
        except self._client.exceptions.InternalServerException as e:
            yield ErrorEvent(
                message='AgentCore internal error',
                details=str(e),
            )
            yield DoneEvent()
        except Exception as e:
            yield ErrorEvent(
                message='Failed to invoke AgentCore',
                details=str(e),
            )
            yield DoneEvent()
