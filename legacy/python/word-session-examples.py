# %%
from word_session_lib import get_current_word_documents, get_word_com, goto_line_in_word_document

# %%
word_app=get_word_com(start_if_not_running=False)
session = get_current_word_documents(word_app)
print(session)

# %%
word_document_info = session[0]
print(word_document_info)

word_app=get_word_com(start_if_not_running=True)
word_app.Visible = True
word_app.Documents.Open(word_document_info["FullName"])

# %%
word_document_info = session[0]
print(word_document_info)

word_app=get_word_com(start_if_not_running=True)
word_app.Visible = True
word_app.Documents.Open(word_document_info["FullName"])

goto_line_in_word_document(word_app,word_document_info['Page'], word_document_info['Line'])

# %%
word_document_info = session[0]
print(word_document_info)

word_app=get_word_com(start_if_not_running=True)
word_app.Visible = True
word_app.Documents.Open(word_document_info["FullName"])

goto_line_in_word_document(word_app,2,2)

# %%
