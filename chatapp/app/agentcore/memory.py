"""Memory client for AgentCore Memory operations.

This module provides the MemoryClient class for fetching event and semantic
memory from AgentCore Memory service.
"""

import json
import logging
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import get_config


logger = logging.getLogger(__name__)


def _format_event_content(raw_text, default_role):
    """Unwrap a stored Strands message envelope into (role, display_text).

    Some agents (for example a multi-agent orchestrator) persist the full
    message object as the event text, e.g.:
        {"message": {"role": "assistant", "content": [{"text": "..."},
                                                       {"toolUse": {...}}]}, ...}
    This returns the message's real role plus the concatenated human-readable
    text blocks (tool-use / tool-result blocks are dropped, so the conversation
    history shows clean narration instead of raw JSON). Plain-text events are
    returned unchanged.
    """
    if not raw_text or not isinstance(raw_text, str):
        return default_role, raw_text or ""
    if not raw_text.lstrip().startswith("{"):
        return default_role, raw_text
    try:
        obj = json.loads(raw_text)
    except (ValueError, TypeError):
        return default_role, raw_text
    if not isinstance(obj, dict) or not isinstance(obj.get("message"), dict):
        return default_role, raw_text
    msg = obj["message"]
    role = msg.get("role", default_role)
    role = role.lower() if isinstance(role, str) else default_role
    content = msg.get("content")
    if isinstance(content, str):
        return role, content
    if not isinstance(content, list):
        return role, raw_text
    texts = [
        b["text"] for b in content
        if isinstance(b, dict) and isinstance(b.get("text"), str)
    ]
    return role, "\n\n".join(texts).strip()


@dataclass
class MemoryEvent:
    """Event memory record from conversation history.
    
    Attributes:
        event_id: Unique identifier for the event
        role: Message role ('user' or 'assistant')
        content: Message content text
        timestamp: When the event occurred
    """
    event_id: str
    role: str
    content: str
    timestamp: str


@dataclass
class SemanticFact:
    """Semantic memory fact extracted from conversations.
    
    Attributes:
        fact_id: Unique identifier for the fact
        content: Fact content text
        confidence: Optional confidence score
        timestamp: When the fact was created
    """
    fact_id: str
    content: str
    confidence: Optional[float]
    timestamp: str


@dataclass
class EpisodicMemory:
    """Episodic memory record capturing a structured interaction episode.

    Attributes:
        episode_id: Unique identifier for the episode
        content: Episode content (scenario, intent, actions, outcome, etc.)
        timestamp: When the episode was recorded
    """
    episode_id: str
    content: str
    timestamp: str


class MemoryError(Exception):
    """Raised when a memory operation fails."""
    pass


class MemoryClient:
    """Client for fetching memory from AgentCore Memory service.
    
    This client handles communication with the AgentCore Memory service,
    fetching event memory (conversation history) and semantic memory (facts).
    Errors are handled gracefully to avoid affecting chat functionality.
    
    Attributes:
        memory_id: AgentCore Memory ID
        region: AWS region
    """
    
    def __init__(
        self,
        memory_id: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize the Memory client.
        
        Args:
            memory_id: AgentCore Memory ID (defaults to config)
            region: AWS region (defaults to config)
        """
        config = get_config()
        self.memory_id = memory_id or config.memory_id
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
    
    async def get_events(
        self,
        session_id: str,
        user_id: str,
        max_results: int = 50,
    ) -> List[MemoryEvent]:
        """Fetch event memory (conversation history) for a session.
        
        Args:
            session_id: Session ID for the conversation
            user_id: User ID (actor ID) for memory lookup
            max_results: Maximum number of events to return
            
        Returns:
            List of MemoryEvent objects
            
        Note:
            Errors are logged but return empty list to avoid affecting chat
        """
        if not self.memory_id:
            logger.info("Memory ID not configured, returning empty events")
            return []
        
        try:
            logger.info(
                "Fetching event memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "memory_id": self.memory_id,
                }
            )
            
            response = self._client.list_events(
                memoryId=self.memory_id,
                actorId=user_id,
                sessionId=session_id,
                maxResults=max_results,
                includePayloads=True,
            )
            
            events: List[MemoryEvent] = []
            
            for evt in response.get('events', []):
                for payload_item in evt.get('payload', []):
                    conv = payload_item.get('conversational', {})
                    if conv:
                        # Normalize role to lowercase for consistent frontend handling
                        role = conv.get('role', 'user')
                        if isinstance(role, str):
                            role = role.lower()
                        content_obj = conv.get('content', {})
                        text = content_obj.get('text', '')

                        # Unwrap stored Strands message envelopes so the UI
                        # shows clean role + text instead of raw JSON. Pure
                        # tool-use/tool-result turns yield empty text and are
                        # skipped by the `if text:` guard below.
                        role, text = _format_event_content(text, role)

                        if text:
                            # Handle timestamp
                            timestamp = evt.get('eventTimestamp')
                            if timestamp:
                                if isinstance(timestamp, datetime):
                                    timestamp = timestamp.isoformat()
                                elif not isinstance(timestamp, str):
                                    timestamp = str(timestamp)
                            else:
                                timestamp = datetime.utcnow().isoformat()
                            
                            events.append(MemoryEvent(
                                event_id=evt.get('eventId', ''),
                                role=role,
                                content=text,
                                timestamp=timestamp,
                            ))
            
            logger.info(
                "Event memory fetched successfully",
                extra={
                    "session_id": session_id,
                    "event_count": len(events),
                }
            )
            
            return events
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(
                "Failed to fetch event memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "error_code": error_code,
                    "error": str(e),
                }
            )
            return []
        except Exception as e:
            logger.error(
                "Unexpected error fetching event memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "error": str(e),
                }
            )
            return []
    
    async def get_semantic(
        self,
        session_id: str,
        user_id: str,
        memory_type: str = "facts",
        max_results: int = 50,
    ) -> List[SemanticFact]:
        """Fetch semantic memory (facts/summaries/preferences) for a session.
        
        Args:
            session_id: Session ID for the conversation
            user_id: User ID for memory lookup
            memory_type: Type of semantic memory ('facts', 'summaries', 'preferences')
            max_results: Maximum number of records to return
            
        Returns:
            List of SemanticFact objects
            
        Note:
            Errors are logged but return empty list to avoid affecting chat
        """
        if not self.memory_id:
            logger.info("Memory ID not configured, returning empty semantic memory")
            return []
        
        # Validate memory type
        valid_types = {"facts", "summaries", "preferences"}
        if memory_type not in valid_types:
            memory_type = "facts"
        
        try:
            logger.info(
                "Fetching semantic memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "memory_id": self.memory_id,
                    "memory_type": memory_type,
                }
            )
            
            # Construct namespace based on memory type (matching frontend format)
            if memory_type == "summaries":
                namespace = f"/summaries/{user_id}/{session_id}"
            elif memory_type == "preferences":
                namespace = f"/users/{user_id}/preferences"
            else:  # facts
                namespace = f"/users/{user_id}/facts"
            
            logger.info(
                "Calling list_memory_records",
                extra={
                    "memory_id": self.memory_id,
                    "namespace": namespace,
                    "max_results": max_results,
                }
            )
            
            response = self._client.list_memory_records(
                memoryId=self.memory_id,
                namespace=namespace,
                maxResults=max_results,
            )
            
            logger.info(
                "list_memory_records response",
                extra={
                    "response_keys": list(response.keys()) if response else [],
                    "record_count": len(response.get('memoryRecordSummaries', [])),
                }
            )
            
            facts: List[SemanticFact] = []
            
            for record in response.get('memoryRecordSummaries', []):
                content_obj = record.get('content', {})
                text = content_obj.get('text', '')
                
                if text:
                    # Handle timestamp
                    created_at = record.get('createdAt')
                    if created_at:
                        if isinstance(created_at, datetime):
                            created_at = created_at.isoformat()
                        elif not isinstance(created_at, str):
                            created_at = str(created_at)
                    else:
                        created_at = datetime.utcnow().isoformat()
                    
                    facts.append(SemanticFact(
                        fact_id=record.get('memoryRecordId', ''),
                        content=text,
                        confidence=None,  # AgentCore doesn't provide confidence
                        timestamp=created_at,
                    ))
            
            # Sort by timestamp (newest first)
            facts.sort(key=lambda f: f.timestamp, reverse=True)
            
            logger.info(
                "Semantic memory fetched successfully",
                extra={
                    "session_id": session_id,
                    "fact_count": len(facts),
                }
            )
            
            return facts
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = str(e)
            # ValidationException with namespace issues or ResourceNotFoundException are expected for new sessions
            if error_code in ('ResourceNotFoundException', 'NotFoundException', 'ValidationException') or 'not found' in error_message.lower():
                logger.debug(
                    "No semantic memory found or invalid namespace (new session)",
                    extra={
                        "session_id": session_id,
                        "user_id": user_id,
                        "memory_type": memory_type,
                        "error_code": error_code,
                    }
                )
            else:
                logger.warning(
                    f"Failed to fetch semantic memory (error_code={error_code})",
                    extra={
                        "session_id": session_id,
                        "user_id": user_id,
                        "error_code": error_code,
                        "error": error_message,
                    }
                )
            return []
        except Exception as e:
            logger.error(
                "Unexpected error fetching semantic memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "error": str(e),
                }
            )
            return []

    async def get_episodic(
        self,
        session_id: str,
        user_id: str,
        max_results: int = 50,
    ) -> List[EpisodicMemory]:
        """Fetch episodic memory (structured interaction episodes) for a session.

        Args:
            session_id: Session ID for the conversation
            user_id: User ID for memory lookup
            max_results: Maximum number of records to return

        Returns:
            List of EpisodicMemory objects

        Note:
            Errors are logged but return empty list to avoid affecting chat
        """
        if not self.memory_id:
            logger.info("Memory ID not configured, returning empty episodic memory")
            return []

        try:
            logger.info(
                "Fetching episodic memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "memory_id": self.memory_id,
                }
            )

            # Namespace matches CDK config: /episodes/{actorId}/{sessionId}/
            namespace = f"/episodes/{user_id}/{session_id}/"

            response = self._client.list_memory_records(
                memoryId=self.memory_id,
                namespace=namespace,
                maxResults=max_results,
            )

            episodes: List[EpisodicMemory] = []

            for record in response.get('memoryRecordSummaries', []):
                content_obj = record.get('content', {})
                text = content_obj.get('text', '')

                if text:
                    created_at = record.get('createdAt')
                    if created_at:
                        if isinstance(created_at, datetime):
                            created_at = created_at.isoformat()
                        elif not isinstance(created_at, str):
                            created_at = str(created_at)
                    else:
                        created_at = datetime.utcnow().isoformat()

                    episodes.append(EpisodicMemory(
                        episode_id=record.get('memoryRecordId', ''),
                        content=text,
                        timestamp=created_at,
                    ))

            episodes.sort(key=lambda e: e.timestamp, reverse=True)

            logger.info(
                "Episodic memory fetched successfully",
                extra={
                    "session_id": session_id,
                    "episode_count": len(episodes),
                }
            )

            return episodes

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = str(e)
            if error_code in ('ResourceNotFoundException', 'NotFoundException', 'ValidationException') or 'not found' in error_message.lower():
                logger.debug(
                    "No episodic memory found (new session)",
                    extra={
                        "session_id": session_id,
                        "user_id": user_id,
                        "error_code": error_code,
                    }
                )
            else:
                logger.warning(
                    f"Failed to fetch episodic memory (error_code={error_code})",
                    extra={
                        "session_id": session_id,
                        "user_id": user_id,
                        "error_code": error_code,
                        "error": error_message,
                    }
                )
            return []
        except Exception as e:
            logger.error(
                "Unexpected error fetching episodic memory",
                extra={
                    "session_id": session_id,
                    "user_id": user_id,
                    "error": str(e),
                }
            )
            return []
