# %%
import wx
try:
    app  # type: ignore
except NameError:
    app = wx.App(False)

#%%

# Sample dictionary
sessions = {
    1: {"name": "Session 1", "date": "2023-01-01", "duration": "1 hour"},
    2: {"name": "Session 2", "date": "2023-01-02", "duration": "2 hours"},
    3: {"name": "Session 3", "date": "2023-01-03", "duration": "1.5 hours"}
}

# %%

def on_populate(event):
    list_ctrl.DeleteAllItems()
    for key, value in sessions.items():
        index = list_ctrl.InsertItem(list_ctrl.GetItemCount(), "")
        list_ctrl.CheckItem(index, True)
        list_ctrl.SetItem(index, 1, str(key))
        list_ctrl.SetItem(index, 2, value["name"])
        list_ctrl.SetItem(index, 3, value["date"])
        list_ctrl.SetItem(index, 4, value["duration"])

def on_create_dict(event):
    selected_sessions = {}
    for index in range(list_ctrl.GetItemCount()):
        if list_ctrl.IsChecked(index):
            session_id = int(list_ctrl.GetItemText(index, 1))
            selected_sessions[session_id] = sessions[session_id]
    
    print("Selected Sessions Dictionary:")
    print(selected_sessions)
#%% 

frame = wx.Frame(None, title="Sessions App", size=(600, 400))
panel = wx.Panel(frame)

list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN| wx.LC_EDIT_LABELS)
list_ctrl.EnableCheckBoxes()
list_ctrl.InsertColumn(0, '', width=30)
list_ctrl.InsertColumn(1, 'ID', width=50)
list_ctrl.InsertColumn(2, 'Name', width=150)
list_ctrl.InsertColumn(3, 'Date', width=150)
list_ctrl.InsertColumn(4, 'Duration', width=100)


populate_button = wx.Button(panel, label="Populate List")
create_dict_button = wx.Button(panel, label="Create Dictionary")

populate_button.Bind(wx.EVT_BUTTON, on_populate)
create_dict_button.Bind(wx.EVT_BUTTON, on_create_dict)

sizer = wx.BoxSizer(wx.VERTICAL)
sizer.Add(list_ctrl, 1, wx.ALL | wx.EXPAND, 5)
sizer.Add(populate_button, 0, wx.ALL | wx.CENTER, 5)
sizer.Add(create_dict_button, 0, wx.ALL | wx.CENTER, 5)
panel.SetSizer(sizer)

frame.Show()
app.MainLoop()
#%% 
