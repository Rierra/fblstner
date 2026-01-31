# URL Cleaner - Remove Facebook tracking parameters and clean URLs

import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def clean_facebook_url(url: str) -> str:
    """
    Clean Facebook URLs by removing tracking parameters.
    Removes parameters like __cft__, __tn__, etc.
    """
    if not url:
        return url

    try:
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query, keep_blank_values=True)

        tracking_params = [
            "__cft__",
            "__tn__",
            "__xts__",
            "__dyn__",
            "__csr__",
            "__req__",
            "__hs__",
            "__hssc__",
            "__hsfp__",
            "__hstc__",
            "fbclid",
            "ref",
            "refid",
            "refsrc",
            "source",
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
        ]

        cleaned_params = {
            k: v
            for k, v in query_params.items()
            if not any(track in k.lower() for track in tracking_params)
        }

        cleaned_query = urlencode(cleaned_params, doseq=True)
        cleaned_parsed = parsed._replace(query=cleaned_query)
        cleaned_url = urlunparse(cleaned_parsed)

        if cleaned_url.endswith("?"):
            cleaned_url = cleaned_url[:-1]

        return cleaned_url

    except Exception:
        # If parsing fails, try simple regex cleanup
        cleaned = re.sub(r"[?&]__cft__\[0\]=[^&]*", "", url)
        cleaned = re.sub(r"[?&]__tn__=[^&]*", "", cleaned)
        cleaned = re.sub(r"[?&]__xts__\[0\]=[^&]*", "", cleaned)
        cleaned = re.sub(r"[?&]fbclid=[^&]*", "", cleaned)

        cleaned = re.sub(r"[&?]+", lambda m: "&" if "&" in m.group() else "?", cleaned)
        cleaned = re.sub(r"\?&", "?", cleaned)
        cleaned = re.sub(r"&$", "", cleaned)
        cleaned = re.sub(r"\?$", "", cleaned)

        return cleaned


def clean_html_entities(text: str) -> str:
    """
    Clean HTML entities and decode them properly.
    Also removes common Facebook UI noise.
    """
    if not text:
        return text

    import html

    text = html.unescape(text)

    text = re.sub(r"&__cft__\[0\]=[^\s]*", "", text)
    text = re.sub(r"&__tn__=[^\s]*", "", text)
    text = re.sub(r"&__xts__\[0\]=[^\s]*", "", text)

    text = re.sub(r"https?://[^\s]*[?&]__cft__[^\s]*", "", text)
    text = re.sub(r"https?://[^\s]*[?&]__tn__[^\s]*", "", text)

    text = re.sub(r"\s+", " ", text).strip()

    return text
# URL Cleaner - Remove Facebook tracking parameters and clean URLs

import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def clean_facebook_url(url: str) -> str:
    """
    Clean Facebook URLs by removing tracking parameters.
    Removes parameters like __cft__, __tn__, etc.
    """
    if not url:
        return url
    
    try:
        # Parse the URL
        parsed = urlparse(url)
        
        # Parse query parameters
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # List of Facebook tracking parameters to remove
        tracking_params = [
            '__cft__',
            '__tn__',
            '__xts__',
            '__dyn__',
            '__csr__',
            '__req__',
            '__hs__',
            '__hssc__',
            '__hsfp__',
            '__hstc__',
            'fbclid',
            'ref',
            'refid',
            'refsrc',
            'source',
            'utm_source',
            'utm_medium',
            'utm_campaign',
            'utm_content',
            'utm_term',
        ]
        
        # Remove tracking parameters
        cleaned_params = {k: v for k, v in query_params.items() 
                         if not any(track in k.lower() for track in tracking_params)}
        
        # Rebuild URL without tracking parameters
        cleaned_query = urlencode(cleaned_params, doseq=True)
        cleaned_parsed = parsed._replace(query=cleaned_query)
        cleaned_url = urlunparse(cleaned_parsed)
        
        # Remove trailing ? if no query params
        if cleaned_url.endswith('?'):
            cleaned_url = cleaned_url[:-1]
        
        return cleaned_url
        
    except Exception as e:
        # If parsing fails, try simple regex cleanup
        # Remove common tracking patterns
        cleaned = re.sub(r'[?&]__cft__\[0\]=[^&]*', '', url)
        cleaned = re.sub(r'[?&]__tn__=[^&]*', '', cleaned)
        cleaned = re.sub(r'[?&]__xts__\[0\]=[^&]*', '', cleaned)
        cleaned = re.sub(r'[?&]fbclid=[^&]*', '', cleaned)
        
        # Clean up multiple consecutive & or ?
        cleaned = re.sub(r'[&?]+', lambda m: '&' if '&' in m.group() else '?', cleaned)
        cleaned = re.sub(r'\?&', '?', cleaned)
        cleaned = re.sub(r'&$', '', cleaned)
        cleaned = re.sub(r'\?$', '', cleaned)
        
        return cleaned


def clean_html_entities(text: str) -> str:
    """
    Clean HTML entities and decode them properly.
    Also removes common Facebook UI noise.
    """
    if not text:
        return text
    
    import html
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Remove common Facebook tracking patterns that might leak into text
    text = re.sub(r'&__cft__\[0\]=[^&\s]*', '', text)
    text = re.sub(r'&__tn__=[^&\s]*', '', text)
    text = re.sub(r'&__xts__\[0\]=[^&\s]*', '', text)
    
    # Remove URL fragments that might appear in text
    text = re.sub(r'https?://[^\s]*[?&]__cft__[^\s]*', '', text)
    text = re.sub(r'https?://[^\s]*[?&]__tn__[^\s]*', '', text)
    
    # Clean up excessive whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

