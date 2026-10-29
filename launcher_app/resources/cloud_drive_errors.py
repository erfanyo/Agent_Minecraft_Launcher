class CloudDriveError(ValueError):
    """Locally authored user-facing message; never raw HTTP/credential data."""

    def __init__(self, message, state='needs_user'):
        super().__init__(message)
        self.state = state
