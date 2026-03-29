import os
import re
import json
import logging
from math import cos, asin, sqrt
from configparser import ConfigParser
from typing import Any, Dict

def ensure_output_directory(path: str) -> None:
    """Ensure the output directory exists."""
    try:
        os.makedirs(path, exist_ok=True)
        logging.info(f"Output directory ensured: {path}")
    except OSError as e:
        logging.error(f"Error creating folder: {e}")
        raise

def load_settings(script_dir: str, filename: str) -> ConfigParser:
    """Load configuration from the settings file."""
    config = ConfigParser()
    secrets_file = os.path.join(script_dir, filename)
    config.read(secrets_file)
    return config

def load_config(script_dir: str, filename: str = 'secrets.ini') -> ConfigParser:
    """
    Load configuration from environment variables or secrets file.
    Supports security_keys, api_keys, and location sections.

    Args:
        script_dir (str): Directory containing the secrets file
        filename (str): Name of the secrets file (default: 'secrets.ini')

    Returns:
        ConfigParser: Configuration with either environment variables or file contents

    Raises:
        RuntimeError: If neither environment variables nor secrets file are available
    """
    config = ConfigParser()

    # Check for environment variables
    api_env_vars = {
        'ENTSOE_API_KEY': os.getenv('ENTSOE_API_KEY'),
        'OPENWEATHER_API_KEY': os.getenv('OPENWEATHER_API_KEY'),
        'METEO_API_KEY': os.getenv('METEO_API_KEY')
    }

    security_env_vars = {
        'ENCRYPTION_KEY': os.getenv('ENCRYPTION_KEY'),
        'HMAC_KEY': os.getenv('HMAC_KEY')
    }

    # If API environment variables are present, use them
    if all(api_env_vars.values()):
        logging.info("Using configuration from environment variables")
        config['api_keys'] = {
            'entsoe': api_env_vars['ENTSOE_API_KEY'],
            'openweather': api_env_vars['OPENWEATHER_API_KEY'],
            'meteo': api_env_vars['METEO_API_KEY']
        }

        # Add optional security keys if present
        if all(security_env_vars.values()):
            config['security_keys'] = {
                'encryption': security_env_vars['ENCRYPTION_KEY'],
                'hmac': security_env_vars['HMAC_KEY']
            }

        # Set default location if not provided in environment
        config['location'] = {
            'latitude': os.getenv('LATITUDE', '51.9851'),  # Default to Arnhem
            'longitude': os.getenv('LONGITUDE', '5.8987')
        }
        return config

    # Fall back to secrets file if environment variables aren't available
    secrets_file = os.path.join(script_dir, filename)
    if os.path.exists(secrets_file):
        logging.info(f"Using configuration from {filename}")
        config.read(secrets_file)
        return config

    # If neither source is available, raise an error with clear message
    raise RuntimeError(
        "No configuration found. Either:\n"
        "1. Set environment variables (ENTSOE_API_KEY, OPENWEATHER_API_KEY, METEO_API_KEY), or\n"
        f"2. Create a {filename} file in {script_dir}"
    )

def distance(lat1, lon1, lat2, lon2):
    p = 0.017453292519943295
    a = (
        0.5
        - cos((lat2 - lat1) * p) / 2
        + cos(lat1 * p) * cos(lat2 * p) * (1 - cos((lon2 - lon1) * p)) / 2
    )
    distance = 12742 * asin(sqrt(a))
    return distance

def closest(data, v):
    return min(
        data,
        key=lambda p: distance(
            v["latitude"], v["longitude"], p["latitude"], p["longitude"]
        ),
    )

def detect_file_type(content: str) -> str:
    """
    Detect whether file content is JSON or encrypted Base64.
    
    Args:
        content (str): The file content to analyze
        
    Returns:
        str: 'json' or 'encrypted'
    """
    # Try to detect if it's base64 encoded
    base64_pattern = r'^[A-Za-z0-9+/=]+$'
    if re.match(base64_pattern, content.strip()):
        return 'encrypted'
    
    # Try to detect if it's JSON
    try:
        json.loads(content)
        return 'json'
    except json.JSONDecodeError:
        raise ValueError("File content is neither valid JSON nor base64 encoded")
    
def save_data_file(
    data: Dict[str, Any],
    file_path: str,
    handler: Any = None,
    encrypt: bool = False
) -> None:
    """
    Save data to a file, optionally encrypting it.
    
    Args:
        data (dict): The data to save
        file_path (str): Path where to save the file
        handler (SecureDataHandler, optional): Handler for encrypting data
        encrypt (bool): Whether to encrypt the data
    """
    try:
        if encrypt:
            if handler is None:
                raise ValueError("Encryption requested but no handler provided")
            encrypted_data = handler.encrypt_and_sign(data.to_dict())
            with open(file_path, 'w') as f:
                f.write(encrypted_data)
        else:
            data.write_to_json(file_path)
    except Exception as e:
        logging.error(f"Error saving file {file_path}: {e}")
        raise
    
def load_data_file(file_path: str, handler: Any = None) -> Dict[str, Any]:
    """
    Load data from a file, automatically detecting if it's encrypted or plain JSON.
    
    Args:
        file_path (str): Path to the file to load
        handler (SecureDataHandler, optional): Handler for decrypting data
        
    Returns:
        dict: The loaded data
    """
    try:
        with open(file_path, 'r') as f:
            content = f.read().strip()
        
        file_type = detect_file_type(content)
        
        if file_type == 'encrypted':
            if handler is None:
                raise ValueError("Encrypted file found but no handler provided")
            return handler.decrypt_and_verify(content)
        else:
            return json.loads(content)
            
    except Exception as e:
        logging.error(f"Error loading file {file_path}: {e}")
        raise
