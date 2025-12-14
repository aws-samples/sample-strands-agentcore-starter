"""
Simple Web Search Tool - Strands Native
Uses DuckDuckGo HTML scraping for web search (no external API dependencies)
"""

import json
import logging
import urllib.parse
from strands import tool

logger = logging.getLogger(__name__)


@tool
async def ddg_web_search(query: str, max_results: int = 5) -> str:
    """
    Search the web using DuckDuckGo for general information, news, and research.
    Returns search results with titles, snippets, and links.

    Args:
        query: Search query string (e.g., "Python programming tutorial", "AWS Lambda pricing")
        max_results: Maximum number of results to return (default: 5, max: 10)

    Returns:
        JSON string containing search results with title, snippet, and link

    Examples:
        # General search
        ddg_web_search("latest AI developments 2025")

        # Company research
        ddg_web_search("Amazon company culture interview")

        # Technical documentation
        ddg_web_search("React hooks tutorial")
    """
    try:
        import httpx
        from bs4 import BeautifulSoup

        # Limit max_results to prevent abuse
        max_results = min(max_results, 10)

        # Build DuckDuckGo search URL
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        # Make request
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; StrandsAgent/1.0)"
        }

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(search_url, headers=headers)
            response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract search results
        results = []
        result_divs = soup.find_all('div', class_='result')
        
        for idx, result_div in enumerate(result_divs[:max_results]):
            try:
                # Extract title and link
                title_tag = result_div.find('a', class_='result__a')
                if not title_tag:
                    continue
                    
                title = title_tag.get_text(strip=True)
                link = title_tag.get('href', '')
                
                # Extract snippet
                snippet_tag = result_div.find('a', class_='result__snippet')
                snippet = snippet_tag.get_text(strip=True) if snippet_tag else "No snippet available"
                
                results.append({
                    "index": idx + 1,
                    "title": title,
                    "snippet": snippet,
                    "link": link
                })
            except Exception as e:
                logger.warning(f"Error parsing result {idx}: {e}")
                continue

        if not results:
            return json.dumps({
                "success": False,
                "error": "No results found or unable to parse search results",
                "query": query
            })

        logger.info(f"Web search completed: {len(results)} results for '{query}'")

        return json.dumps({
            "success": True,
            "query": query,
            "result_count": len(results),
            "results": results
        }, indent=2)

    except Exception as e:
        logger.error(f"Error performing web search: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "query": query
        })
