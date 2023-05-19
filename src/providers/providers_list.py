from typing import Dict
from ..models.Provider import Provider
from .AppImageProvider import AppImageProvider

# A list containing all the "Providers"
providers: Dict[str, Provider] = { 
    'appimage': AppImageProvider()
}