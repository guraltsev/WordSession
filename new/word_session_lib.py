import win32com.client

def get_current_word_documents(word_app):
    """
    Returns a list of dictionaries containing the information of the documents in the current session of Word.

    Each dictionary in the list provides the following information about a document:
        * FullName: The full path of the document.
        * Line: The line number where the user is currently located in the document.
        * Page: The page number where the user is currently located in the document.

    The function iterates over all open documents in the provided Word application instance.
    It activates each document to ensure that the Selection object refers to it, then retrieves
    and prints the current line and page numbers where the user is located.

    How to get the COM object:
        1. Open Word.
        2. Install the Python library: `pip install pywin32`
        3. Import the win32com.client module: `import win32com.client`
        4. Make sure Word is already running: `win32com.client.GetActiveObject("Word.Application")`
        5. Get the COM object: `word_app = win32com.client.gencache.EnsureDispatch("Word.Application")`
        6. Call this function passing the `word_app` variable as the argument.

    Args:
        word_app: A COM object that represents the Microsoft Word application.

    Returns:
        A list of dictionaries, each containing the 'FullName', 'Line', and
        'Page' of the documents within the current Word session.
    """
    session = []
    for doc in word_app.Documents:
        word_document_info = {}
        doc.Activate()
        word_document_info["FullName"] = doc.FullName
        selection = word_app.Selection
        word_document_info["Line"] = selection.Information(
            win32com.client.constants.wdFirstCharacterLineNumber
        )
        word_document_info["Page"] = selection.Information(
            win32com.client.constants.wdActiveEndPageNumber
        )
        # print(word_document_info)
        session.append(word_document_info)
    return session

def goto_line_in_word_document(word_app, page_number=1, line_number=1):
    """
    Navigates to a specified line on a specified page within an open Word document.

    Args:
        word_app: A COM object representing the Microsoft Word application. 
                  This is required to interact with the Word document.
        page_number (int): The page number to navigate to. It is 1-indexed, meaning
                           page 1 is the first page. Default is 1.
        line_number (int): The line number to navigate to on the specified page. It is 
                           1-indexed, meaning line 1 is the first line on the page. Default is 1.
    """
    selection = word_app.Selection
    # Navigate to the specified page
    selection.GoTo(
        What=win32com.client.constants.wdGoToPage,
        Which=win32com.client.constants.wdGoToAbsolute,
        Count=page_number,
    )
    # Navigate to the specified line if line_number is greater than 1
    if line_number > 1:
        selection.GoTo(
            What=win32com.client.constants.wdGoToLine,
            Which=win32com.client.constants.wdGoToRelative,
            Count=line_number - 1,
        )

def get_word_com(start_if_not_running: bool = False):
    """
    Tries to get a running instance of Microsoft Word. If there is no
    running instance, and start_if_not_running is True, this function
    will start a new instance of Word.

    If you want to make the started instance visible, once started, run:
        word_app = get_word_com(start_if_not_running=True)
        word_app.Visible = True

    Args:
        start_if_not_running (bool): If True, starts a new instance of
            Word if there is no running instance. If False, it will not
            start a new instance. Defaults to False.

    Returns:
        A COM object of the running Word instance. If there is no running instance, and
        start_if_not_running is False, it will return None.
    """
    if not start_if_not_running:
        win32com.client.GetActiveObject("Word.Application")
        return win32com.client.gencache.EnsureDispatch("Word.Application")
    else:
        return win32com.client.gencache.EnsureDispatch("Word.Application")
