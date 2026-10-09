class OutOfAreaError(ValueError):
    pass


class NotNearStreetError(OutOfAreaError):
    """Inside the area but too far from any street; `end` is "start" or "destination"."""

    def __init__(self, end: str, message: str):
        super().__init__(message)
        self.end = end


class NoRouteError(ValueError):
    pass
