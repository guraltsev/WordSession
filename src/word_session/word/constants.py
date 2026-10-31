"""Word object-model constants and COM HRESULTs used by the Word backends.

Values come from the Word object model and the Windows COM error tables. The
module has no dependencies and imports on every platform.
"""

wdActiveEndPageNumber = 3  # Range.Information: page number of the range end
wdFirstCharacterLineNumber = 10  # Range.Information: line number on its page
wdGoToPage = 1  # Range.GoTo What: a page
wdGoToLine = 3  # Range.GoTo What: a line
wdGoToAbsolute = 1  # Range.GoTo Which: absolute position
wdGoToRelative = 2  # Range.GoTo Which: relative to the current position
wdAlertsNone = 0  # Application.DisplayAlerts: suppress all alerts
wdAlertsAll = -1  # Application.DisplayAlerts: show all alerts
wdWindowStateNormal = 0  # Window.WindowState: normal
wdWindowStateMaximize = 1  # Window.WindowState: maximized
wdWindowStateMinimize = 2  # Window.WindowState: minimized
wdDoNotSaveChanges = 0  # Document.Close SaveChanges: discard changes

RPC_E_CALL_REJECTED = -2147418111  # Word rejected the call (busy, modal dialog)
RPC_E_SERVERCALL_RETRYLATER = -2147417846  # Word asks the caller to retry later
MK_E_UNAVAILABLE = -2147221021  # GetActiveObject: Word is not running
