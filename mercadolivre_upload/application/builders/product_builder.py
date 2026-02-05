class ProductBuilder:
    """Minimal compatibility shim for tests."""

    def __init__(self, *args, **kwargs):
        pass

    def build(self, *args, **kwargs):
        return {}
