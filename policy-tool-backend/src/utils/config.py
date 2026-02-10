import yaml
from pathlib import Path
from typing import Dict, Any, Optional

_CONFIG_OVERRIDE: Optional[Dict[str, Any]] = None

def set_config_override(config: Dict[str, Any]):
    """
    Set a global configuration override. 
    Useful for sensitivity analysis or testing without changing files.
    """
    global _CONFIG_OVERRIDE
    _CONFIG_OVERRIDE = config

def clear_config_override():
    """Clear the global configuration override."""
    global _CONFIG_OVERRIDE
    _CONFIG_OVERRIDE = None

def load_config(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """
    Load configuration from a YAML file.
    
    Args:
        config_path (str): Path to the YAML configuration file. Defaults to 'config/settings.yaml'.
        
    Returns:
        Dict[str, Any]: Dictionary containing the configuration.
        
    Raises:
        FileNotFoundError: If the config file does not exist.
        yaml.YAMLError: If the config file is invalid YAML.
    """
    if _CONFIG_OVERRIDE is not None:
        return _CONFIG_OVERRIDE

    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found at: {path.absolute()}")
    
    with open(path, "r") as f:
        return yaml.safe_load(f)

if __name__ == "__main__":
    # Quick test
    try:
        conf = load_config()
        print("Config loaded successfully:")
        print(conf)
    except Exception as e:
        print(f"Error loading config: {e}")
