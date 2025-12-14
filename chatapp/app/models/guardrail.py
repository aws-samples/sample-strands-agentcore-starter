"""Guardrail violation data models for DynamoDB storage.

This module defines dataclasses for storing and querying guardrail violation
records. Records are stored in DynamoDB with user_id as partition key and
timestamp as sort key.
"""

import json
from dataclasses import dataclass, asdict
from typing import Dict, Any, List


@dataclass
class GuardrailRecord:
    """Record of a guardrail evaluation for analytics.
    
    Stored in DynamoDB with user_id as partition key and timestamp as sort key.
    A GSI on session_id enables session-based lookups.
    
    Attributes:
        user_id: Partition key - user who triggered the evaluation
        timestamp: Sort key - ISO 8601 timestamp
        session_id: GSI partition key - chat session identifier
        source: "INPUT" or "OUTPUT"
        action: "GUARDRAIL_INTERVENED" or "NONE"
        assessments: Full assessment response from ApplyGuardrail
        content_preview: First 100 chars of evaluated content (for debugging)
    """
    user_id: str
    timestamp: str
    session_id: str
    source: str
    action: str
    assessments: List[Dict[str, Any]]
    content_preview: str = ""
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format.
        
        Returns:
            Dictionary suitable for DynamoDB put_item operation
        """
        # Serialize assessments to JSON string
        assessments_json = json.dumps(self.assessments)
        
        item = {
            "user_id": {"S": self.user_id},
            "timestamp": {"S": self.timestamp},
            "session_id": {"S": self.session_id},
            "source": {"S": self.source},
            "action": {"S": self.action},
            "assessments": {"S": assessments_json},
            "content_preview": {"S": self.content_preview},
        }
        
        return item
    
    @classmethod
    def from_dynamodb_item(cls, item: Dict[str, Any]) -> "GuardrailRecord":
        """Create instance from DynamoDB item.
        
        Args:
            item: DynamoDB item with typed attribute values
            
        Returns:
            GuardrailRecord instance
        """
        # Parse assessments from JSON string
        assessments_json = item.get("assessments", {}).get("S", "[]")
        assessments = json.loads(assessments_json)
        
        return cls(
            user_id=item.get("user_id", {}).get("S", ""),
            timestamp=item.get("timestamp", {}).get("S", ""),
            session_id=item.get("session_id", {}).get("S", ""),
            source=item.get("source", {}).get("S", ""),
            action=item.get("action", {}).get("S", ""),
            assessments=assessments,
            content_preview=item.get("content_preview", {}).get("S", ""),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to plain dictionary.
        
        Returns:
            Dictionary representation of the record
        """
        return {
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "source": self.source,
            "action": self.action,
            "assessments": self.assessments,
            "content_preview": self.content_preview,
        }
    
    def get_policy_types(self) -> List[str]:
        """Extract policy types that triggered violations.
        
        Returns:
            List of policy type names (e.g., ["content", "topic"])
        """
        policy_types = []
        
        for assessment in self.assessments:
            # Check content policy
            content_policy = assessment.get("contentPolicy", {})
            if content_policy.get("filters"):
                for filter_result in content_policy["filters"]:
                    if filter_result.get("action") == "BLOCKED":
                        policy_types.append("content")
                        break
            
            # Check topic policy
            topic_policy = assessment.get("topicPolicy", {})
            if topic_policy.get("topics"):
                for topic in topic_policy["topics"]:
                    if topic.get("action") == "BLOCKED":
                        policy_types.append("topic")
                        break
            
            # Check word policy
            word_policy = assessment.get("wordPolicy", {})
            if word_policy.get("customWords") or word_policy.get("managedWordLists"):
                policy_types.append("word")
            
            # Check sensitive information policy
            sensitive_policy = assessment.get("sensitiveInformationPolicy", {})
            if sensitive_policy.get("piiEntities") or sensitive_policy.get("regexes"):
                policy_types.append("sensitive_information")
        
        return list(set(policy_types))  # Remove duplicates
    
    def get_filter_types(self) -> List[Dict[str, str]]:
        """Extract specific filter types that triggered violations.
        
        Returns:
            List of dicts with 'policy' and 'type' keys (e.g., [{"policy": "content", "type": "INSULTS"}])
        """
        filter_types = []
        
        for assessment in self.assessments:
            # Check content policy filters
            content_policy = assessment.get("contentPolicy", {})
            if content_policy.get("filters"):
                for filter_result in content_policy["filters"]:
                    if filter_result.get("action") == "BLOCKED":
                        filter_type = filter_result.get("type", "UNKNOWN")
                        filter_types.append({"policy": "content", "type": filter_type})
            
            # Check topic policy
            topic_policy = assessment.get("topicPolicy", {})
            if topic_policy.get("topics"):
                for topic in topic_policy["topics"]:
                    if topic.get("action") == "BLOCKED":
                        topic_name = topic.get("name", "UNKNOWN")
                        filter_types.append({"policy": "topic", "type": topic_name})
            
            # Check word policy
            word_policy = assessment.get("wordPolicy", {})
            if word_policy.get("customWords"):
                for word in word_policy["customWords"]:
                    filter_types.append({"policy": "word", "type": word.get("match", "CUSTOM_WORD")})
            if word_policy.get("managedWordLists"):
                for word_list in word_policy["managedWordLists"]:
                    filter_types.append({"policy": "word", "type": word_list.get("type", "MANAGED_LIST")})
            
            # Check sensitive information policy
            sensitive_policy = assessment.get("sensitiveInformationPolicy", {})
            if sensitive_policy.get("piiEntities"):
                for pii in sensitive_policy["piiEntities"]:
                    filter_types.append({"policy": "sensitive_information", "type": pii.get("type", "PII")})
            if sensitive_policy.get("regexes"):
                for regex in sensitive_policy["regexes"]:
                    filter_types.append({"policy": "sensitive_information", "type": regex.get("name", "REGEX")})
        
        # Remove duplicates while preserving order
        seen = set()
        unique_filters = []
        for f in filter_types:
            key = (f["policy"], f["type"])
            if key not in seen:
                seen.add(key)
                unique_filters.append(f)
        
        return unique_filters
    
    def get_filter_details(self) -> Dict[str, Any]:
        """Extract filter strength and confidence from assessments.
        
        Returns:
            Dict with 'strength' and 'confidence' keys (highest values found)
        """
        max_strength = None
        max_confidence = None
        
        for assessment in self.assessments:
            # Check content policy filters for strength and confidence
            content_policy = assessment.get("contentPolicy", {})
            if content_policy.get("filters"):
                for filter_result in content_policy["filters"]:
                    if filter_result.get("action") == "BLOCKED":
                        strength = filter_result.get("filterStrength")
                        confidence = filter_result.get("confidence")
                        if strength:
                            max_strength = strength
                        if confidence:
                            max_confidence = confidence
            
            # Check topic policy for confidence
            topic_policy = assessment.get("topicPolicy", {})
            if topic_policy.get("topics"):
                for topic in topic_policy["topics"]:
                    if topic.get("action") == "BLOCKED":
                        confidence = topic.get("confidence")
                        if confidence:
                            max_confidence = confidence
        
        return {
            "strength": max_strength or "—",
            "confidence": max_confidence or "—",
        }
