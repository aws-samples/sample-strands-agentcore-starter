"""
Knowledge Base Search Tool - Strands Native
Searches Amazon Bedrock Knowledge Base for relevant information
"""

import json
import logging
import os
from typing import Optional
from strands import tool

logger = logging.getLogger(__name__)


def _get_kb_client():
    """Get boto3 bedrock-agent-runtime client."""
    import boto3
    region = os.getenv("AWS_REGION", "us-east-1")
    return boto3.client("bedrock-agent-runtime", region_name=region)


def _parse_retrieve_response(response: dict) -> list[dict]:
    """
    Parse the Bedrock KB retrieve API response into result dictionaries.
    
    Args:
        response: Raw response from bedrock-agent-runtime retrieve API
        
    Returns:
        List of result dictionaries with text, score, and source fields
    """
    results = []
    retrieval_results = response.get("retrievalResults", [])
    
    for result in retrieval_results:
        content = result.get("content", {})
        text = content.get("text", "")
        
        score = result.get("score", 0.0)
        
        # Extract source from location
        location = result.get("location", {})
        source = ""
        if location.get("type") == "S3":
            s3_location = location.get("s3Location", {})
            source = s3_location.get("uri", "")
        elif location.get("type") == "WEB":
            web_location = location.get("webLocation", {})
            source = web_location.get("url", "")
        
        results.append({
            "text": text,
            "score": score,
            "source": source
        })
    
    return results


@tool
def search_knowledge_base(
    query: str,
    max_results: int = 5,
    min_score: float = 0.5
) -> str:
    """
    Search the Knowledge Base for relevant information.
    Use this tool first to find domain-specific context before using web search.
    
    Args:
        query: The search query to find relevant documents
        max_results: Maximum number of results to return (default: 5)
        min_score: Minimum relevance score threshold 0-1 (default: 0.5)
    
    Returns:
        JSON string containing search results with text, score, and source
    
    Examples:
        # Search for company policies
        search_knowledge_base("vacation policy")
        
        # Search with custom limits
        search_knowledge_base("security guidelines", max_results=3, min_score=0.7)
    """
    # Get KB ID from environment
    kb_id = os.getenv("KB_ID", "")
    
    if not kb_id:
        logger.warning("KB_ID not configured, Knowledge Base search unavailable")
        return json.dumps({
            "success": False,
            "error": "Knowledge Base not configured",
            "query": query,
            "results": []
        })
    
    # Validate query
    if not query or not query.strip():
        return json.dumps({
            "success": True,
            "query": query,
            "result_count": 0,
            "results": []
        })
    
    try:
        client = _get_kb_client()
        
        # Call retrieve API
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query.strip()},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": max_results
                }
            }
        )
        
        # Parse response
        results = _parse_retrieve_response(response)
        
        # Filter by min_score
        filtered_results = [r for r in results if r["score"] >= min_score]
        
        # Limit to max_results (API should handle this, but ensure)
        filtered_results = filtered_results[:max_results]
        
        logger.info(f"KB search completed: {len(filtered_results)} results for '{query}'")
        
        return json.dumps({
            "success": True,
            "query": query,
            "result_count": len(filtered_results),
            "results": filtered_results
        }, indent=2)
        
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        
        # Handle specific error types gracefully
        if "ResourceNotFoundException" in error_type or "ResourceNotFoundException" in error_msg:
            logger.warning(f"Knowledge Base not found: {kb_id}")
            return json.dumps({
                "success": False,
                "error": f"Knowledge Base '{kb_id}' not found",
                "query": query,
                "results": []
            })
        
        if "AccessDeniedException" in error_type or "AccessDeniedException" in error_msg:
            logger.warning(f"Access denied to Knowledge Base: {kb_id}")
            return json.dumps({
                "success": False,
                "error": "Access denied to Knowledge Base",
                "query": query,
                "results": []
            })
        
        if "ThrottlingException" in error_type or "ThrottlingException" in error_msg:
            logger.warning(f"Knowledge Base API rate limited for query: {query}")
            return json.dumps({
                "success": False,
                "error": "Knowledge Base API rate limited, please retry",
                "query": query,
                "results": []
            })
        
        # Log other errors
        logger.error(f"Error searching Knowledge Base: {error_type} - {e}")
        
        return json.dumps({
            "success": False,
            "error": error_msg,
            "query": query,
            "results": []
        })
