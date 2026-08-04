import re
from typing import Optional, Dict, Any
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def normalize_label(label: Any) -> Optional[str]:
    """
    Normalizes an energy label string to a standard format (e.g., 'A', 'B', 'G').
    Handles A+, A++, etc. by grouping them under 'A' for now.
    
    Args:
        label: Raw label string (e.g. "  A ", "A++++", "G"). Can be non-string (returns None).
        
    Returns:
        Normalized label (A-G) or None if invalid.
    """
    if not isinstance(label, str):
        return None
        
    clean = label.strip().upper()
    
    if not clean:
        return None
        
    # Handle A++++ etc -> Normalize to A+, A++, etc.
    if clean.startswith('A') and ('+' in clean): 
        # Ensure we capture A+, A++, A+++, A++++
        # Just return the clean string if it looks like A followed by plusses
        if all(c == '+' for c in clean[1:]):
            return clean
            
    # Basic A-G check
    if clean in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
        return clean
        
    return None

def get_proxy_label_from_year(year: float) -> str:
    """
    Returns a proxy Energy Label based on construction year.
    Based on typical Dutch building standards evolution.
    """
    if pd.isna(year) or year < 1000 or year > 2100:
        return 'G' # Conservative fallback for unknown age
        
    if year < 1965: return 'G'
    if year < 1975: return 'F'
    if year < 1983: return 'E' # Preliminary double glazing era
    if year < 1992: return 'C' # Improved insulation standards
    if year < 2006: return 'B' # EPC introduction/tightening
    return 'A' # Modern standards

def get_intensity_from_config(label: str, config: Dict, is_residential: bool = True) -> float:
    """Helper to look up intensity for a valid label."""
    heat_cfg = config.get('heat', {})
    options = heat_cfg.get('options', {})
    all_intensities = options.get('label_intensities', {})
    
    # Select archetype section
    archetype_key = 'residential' if is_residential else 'non_residential'
    intensities = all_intensities.get(archetype_key, {})
    
    # Look up label
    if label in intensities:
        return float(intensities[label])
        
    # Fallback logic
    fallbacks = options.get('fallback_intensity', {})
    if isinstance(fallbacks, dict):
        return float(fallbacks.get(archetype_key, 270.0))
    else:
        return float(fallbacks)

def estimate_intensity(label: Any, build_year: Any, config: Dict, is_residential: bool = True) -> float:
    """
    Estimates heat intensity (kWh_th/m2/yr) using the hierarchy:
    1. Valid Energy Label
    2. Construction Year (Proxy Label)
    3. Fallback Default
    
    Args:
        label: Raw energy label.
        build_year: Construction year (float/int).
        config: App configuration.
        is_residential: True if residential archetype, False otherwise.
        
    Returns:
        Intensity value.
    """
    # 1. Try Label
    norm_label = normalize_label(label)
    if norm_label:
        return get_intensity_from_config(norm_label, config, is_residential)
        
    # 2. Try Year
    # Ensure year is valid number
    try:
        y = float(build_year)
        if not pd.isna(y):
            proxy = get_proxy_label_from_year(y)
            return get_intensity_from_config(proxy, config, is_residential)
    except (ValueError, TypeError):
        pass

    # 3. Default
    heat_cfg = config.get('heat', {})
    options = heat_cfg.get('options', {})
    fallbacks = options.get('fallback_intensity', {})
    
    archetype_key = 'residential' if is_residential else 'non_residential'
    if isinstance(fallbacks, dict):
        return float(fallbacks.get(archetype_key, 270.0))
    return float(fallbacks)

def get_heat_intensity(label: Optional[str], config: Dict) -> float:
    """Deprecated/Simple wrapper for direct label lookup."""
    return get_intensity_from_config(label, config, is_residential=True) if label else estimate_intensity(None, None, config, is_residential=True)
