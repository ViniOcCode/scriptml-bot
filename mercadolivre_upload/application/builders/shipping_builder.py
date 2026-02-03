"""Shipping builder for ML items."""
from typing import Optional


class ShippingBuilder:
    """Builds shipping configuration for ML items."""
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
    
    def build(self, mode: Optional[str] = None) -> dict:
        """Build shipping config."""
        defaults = self.config.get('shipping', {})
        
        return {
            'mode': mode or defaults.get('mode', 'me2'),
            'local_pick_up': defaults.get('local_pick_up', False),
            'free_shipping': defaults.get('free_shipping', False),
        }
