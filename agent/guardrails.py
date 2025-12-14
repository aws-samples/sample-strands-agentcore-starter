"""Guardrails hook for shadow-mode content evaluation using Amazon Bedrock.

This module implements a NotifyOnlyGuardrailsHook that evaluates user inputs
and assistant responses against Bedrock guardrails without blocking content.
Violations are logged for monitoring and analytics purposes.
"""
import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from strands.hooks import (
    AfterInvocationEvent,
    HookProvider,
    HookRegistry,
    MessageAddedEvent,
)

from logger import setup_logger


class NotifyOnlyGuardrailsHook(HookProvider):
    """Evaluates content against Bedrock guardrails in shadow mode.
    
    This hook registers callbacks for MessageAddedEvent and AfterInvocationEvent
    to evaluate user inputs and assistant responses respectively. Violations are
    logged and yielded as events but never block content.
    
    Attributes:
        guardrail_id: Bedrock guardrail identifier
        guardrail_version: Guardrail version to use
        bedrock_client: boto3 bedrock-runtime client
        enabled: Whether guardrail evaluation is enabled
        pending_violations: List of violations detected during current invocation
    """
    
    def __init__(
        self,
        guardrail_id: Optional[str] = None,
        guardrail_version: Optional[str] = None,
        region: str = "us-east-1",
        enabled: Optional[bool] = None,
    ):
        """Initialize the guardrails hook.
        
        Args:
            guardrail_id: Guardrail ID (defaults to GUARDRAIL_ID env var)
            guardrail_version: Version (defaults to GUARDRAIL_VERSION env var)
            region: AWS region for Bedrock client
            enabled: Whether to enable evaluation (defaults to GUARDRAIL_ENABLED env var)
        """
        self.guardrail_id = guardrail_id or os.getenv("GUARDRAIL_ID")
        self.guardrail_version = guardrail_version or os.getenv("GUARDRAIL_VERSION", "DRAFT")
        
        # Determine if enabled from parameter or environment
        if enabled is not None:
            self.enabled = enabled
        else:
            enabled_env = os.getenv("GUARDRAIL_ENABLED", "true").lower()
            self.enabled = enabled_env in ("true", "1", "yes")
        
        self._logger = setup_logger(__name__)
        self._bedrock_client = None
        self._region = region
        self._warned_missing_config = False
        
        # Store pending violations to be yielded by the invoke function
        self.pending_violations: list = []
        
        # Log configuration status
        if not self.guardrail_id:
            self._logger.warning(
                "GUARDRAIL_ID not configured - guardrail evaluation will be skipped"
            )
        elif not self.enabled:
            self._logger.info(
                "Guardrail evaluation disabled via GUARDRAIL_ENABLED=false"
            )
        else:
            self._logger.info(
                f"Guardrails hook initialized: id={self.guardrail_id}, "
                f"version={self.guardrail_version}, enabled={self.enabled}"
            )
    
    @property
    def bedrock_client(self):
        """Lazy initialization of bedrock-runtime client."""
        if self._bedrock_client is None:
            self._bedrock_client = boto3.client(
                "bedrock-runtime",
                region_name=self._region
            )
        return self._bedrock_client
    
    def _should_evaluate(self) -> bool:
        """Check if guardrail evaluation should be performed.
        
        Returns:
            True if evaluation should proceed, False otherwise
        """
        if not self.guardrail_id:
            if not self._warned_missing_config:
                self._logger.debug("Skipping guardrail evaluation - no GUARDRAIL_ID configured")
                self._warned_missing_config = True
            return False
        
        if not self.enabled:
            return False
        
        return True
    
    def evaluate_content(
        self,
        content: str,
        source: str,
        user_id: str = "unknown",
        session_id: str = "unknown",
    ) -> Optional[dict]:
        """Evaluate content using ApplyGuardrail API.
        
        Args:
            content: Text content to evaluate
            source: "INPUT" for user messages, "OUTPUT" for assistant
            user_id: User identifier for analytics
            session_id: Session identifier for analytics
            
        Returns:
            Assessment dict if violation detected, None otherwise
        """
        if not self._should_evaluate():
            return None
        
        if not content or not content.strip():
            self._logger.debug("Skipping guardrail evaluation - empty content")
            return None
        
        try:
            response = self.bedrock_client.apply_guardrail(
                guardrailIdentifier=self.guardrail_id,
                guardrailVersion=self.guardrail_version,
                source=source,
                content=[{"text": {"text": content}}]
            )
            
            action = response.get("action", "NONE")
            assessments = response.get("assessments", [])
            
            if action == "GUARDRAIL_INTERVENED":
                # Log violation details
                self._log_violation(source, assessments, user_id, session_id)
                
                violation = {
                    "type": "guardrail",
                    "source": source,
                    "action": action,
                    "assessments": assessments,
                    "user_id": user_id,
                    "session_id": session_id,
                }
                
                # Store violation for yielding by invoke function
                self.pending_violations.append(violation)
                
                return violation
            
            self._logger.debug(
                f"Guardrail evaluation passed: source={source}, action={action}"
            )
            return None
            
        except ClientError as e:
            self._logger.error(
                f"Guardrail API error (continuing without blocking): {e}",
                exc_info=True
            )
            return None
        except Exception as e:
            self._logger.error(
                f"Unexpected error during guardrail evaluation (continuing): {e}",
                exc_info=True
            )
            return None
    
    def _log_violation(
        self,
        source: str,
        assessments: list,
        user_id: str,
        session_id: str,
    ) -> None:
        """Log guardrail violation details.
        
        Args:
            source: "INPUT" or "OUTPUT"
            assessments: List of assessment results from ApplyGuardrail
            user_id: User identifier
            session_id: Session identifier
        """
        for assessment in assessments:
            # Log content policy violations
            content_policy = assessment.get("contentPolicy", {})
            for filter_result in content_policy.get("filters", []):
                if filter_result.get("action") == "BLOCKED":
                    self._logger.warning(
                        f"Guardrail violation detected: "
                        f"source={source}, "
                        f"policy=content, "
                        f"type={filter_result.get('type')}, "
                        f"confidence={filter_result.get('confidence')}, "
                        f"user={user_id}, "
                        f"session={session_id}"
                    )
            
            # Log topic policy violations
            topic_policy = assessment.get("topicPolicy", {})
            for topic in topic_policy.get("topics", []):
                if topic.get("action") == "BLOCKED":
                    self._logger.warning(
                        f"Guardrail violation detected: "
                        f"source={source}, "
                        f"policy=topic, "
                        f"name={topic.get('name')}, "
                        f"user={user_id}, "
                        f"session={session_id}"
                    )
            
            # Log word policy violations
            word_policy = assessment.get("wordPolicy", {})
            for word in word_policy.get("customWords", []):
                if word.get("action") == "BLOCKED":
                    self._logger.warning(
                        f"Guardrail violation detected: "
                        f"source={source}, "
                        f"policy=word, "
                        f"user={user_id}, "
                        f"session={session_id}"
                    )
            
            # Log sensitive information policy violations
            sensitive_policy = assessment.get("sensitiveInformationPolicy", {})
            for pii in sensitive_policy.get("piiEntities", []):
                if pii.get("action") == "BLOCKED":
                    self._logger.warning(
                        f"Guardrail violation detected: "
                        f"source={source}, "
                        f"policy=sensitive_information, "
                        f"type={pii.get('type')}, "
                        f"user={user_id}, "
                        f"session={session_id}"
                    )
    
    def check_user_input(self, event: MessageAddedEvent) -> None:
        """Check user input when message is added.
        
        Evaluates user messages against guardrails with source="INPUT".
        Only processes messages with role="user".
        
        Args:
            event: MessageAddedEvent containing agent instance and new message
        """
        try:
            message = event.message
            role = message.get("role", "")
            
            # Only evaluate user messages
            if role != "user":
                return
            
            # Extract text content
            content = message.get("content", "")
            if isinstance(content, list):
                # Handle content blocks format
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                content = " ".join(text_parts)
            
            if not content:
                return
            
            # Get user context from agent state
            user_id = event.agent.state.get("user_id") or "unknown"
            session_id = event.agent.state.get("session_id") or "unknown"
            
            # Evaluate content
            result = self.evaluate_content(
                content=content,
                source="INPUT",
                user_id=user_id,
                session_id=session_id,
            )
            
            if result:
                self._logger.info(
                    f"User input would have triggered guardrail: user={user_id}, session={session_id}"
                )
                
        except Exception as e:
            self._logger.error(
                f"Error in check_user_input (continuing): {e}",
                exc_info=True
            )
    
    def check_assistant_response(self, event: AfterInvocationEvent) -> None:
        """Check assistant response after invocation completes.
        
        Evaluates the final assistant response against guardrails with source="OUTPUT".
        
        Args:
            event: AfterInvocationEvent containing agent instance
        """
        try:
            # Get the last assistant message
            messages = event.agent.messages
            if not messages:
                return
            
            # Find the last assistant message
            assistant_content = None
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                text_parts.append(block["text"])
                        assistant_content = " ".join(text_parts)
                    else:
                        assistant_content = str(content)
                    break
            
            if not assistant_content:
                return
            
            # Get user context from agent state
            user_id = event.agent.state.get("user_id") or "unknown"
            session_id = event.agent.state.get("session_id") or "unknown"
            
            # Evaluate content
            result = self.evaluate_content(
                content=assistant_content,
                source="OUTPUT",
                user_id=user_id,
                session_id=session_id,
            )
            
            if result:
                self._logger.info(
                    f"Assistant response would have triggered guardrail: user={user_id}, session={session_id}"
                )
                
        except Exception as e:
            self._logger.error(
                f"Error in check_assistant_response (continuing): {e}",
                exc_info=True
            )
    
    def get_and_clear_violations(self) -> list:
        """Get pending violations and clear the list.
        
        This method is called by the invoke function to retrieve violations
        detected during the current invocation and yield them as events.
        
        Returns:
            List of violation dictionaries
        """
        violations = self.pending_violations.copy()
        self.pending_violations.clear()
        return violations
    
    def register_hooks(self, registry: HookRegistry) -> None:
        """Register memory hooks with the agent.
        
        Registers callbacks for message events and invocation completion
        to enable automatic guardrail evaluation.
        
        Args:
            registry: Hook registry to register callbacks with
        """
        registry.add_callback(MessageAddedEvent, self.check_user_input)
        registry.add_callback(AfterInvocationEvent, self.check_assistant_response)
