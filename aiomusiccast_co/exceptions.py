class MusicCastException(Exception):
    pass


class MusicCastUnsupportedException(Exception):
    pass


class MusicCastGroupException(MusicCastException):
    pass


class MusicCastConnectionException(MusicCastException):
    pass


class MusicCastResponseException(MusicCastConnectionException):
    """The device answered a required request with a non-zero response_code."""


class MusicCastConfigurationException(MusicCastGroupException):
    pass


class MusicCastParamException(MusicCastException):
    pass
