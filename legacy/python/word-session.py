# %%
from word_session_lib import (
    get_current_word_documents,
    get_word_com,
    goto_line_in_word_document,
)

import argparse
import os
from datetime import datetime
import json


def main():
    parser = argparse.ArgumentParser(
        prog="word-session",
        description="Session management for word",
    )
    session_dir = os.path.join(os.path.expanduser("~"), ".word-session")

    parser.add_argument("action", choices=["load", "save"], help="Action to perform")
    parser.add_argument(
        "--do-not-start",
        action="store_true",
        help="When loading session, do not start Word if it not already running",
    )
    parser.add_argument(
        "--filename",
        type=str,
        help=f"Filename to save or load session from. When loading session, if not specified, the most recent session file in {session_dir} will be used. When saving, if not specified, will used a time-stamped file",
    )

    try:
        override_args # type: ignore
        args = parser.parse_args(override_args) # type: ignore
    except NameError:
        args = parser.parse_args()

    if args.action == "save":
        print("Saving session...")

        if args.filename:
            dest_path = args.filename
        else:
            filename = (
                datetime.now().strftime("%Y%m%dT%H%M%S") + " word-session" + ".json"
            )
            dest_path = os.path.join(session_dir, filename)
        print(f"    to {dest_path}")

        os.makedirs(session_dir, exist_ok=True)
        action_save(dest_path)

    if args.action == "load":
        print("Loading session...")
        if args.filename:
            dest_path = args.filename
        else:
            files = sorted(os.listdir(session_dir), key=lambda x: os.path.getctime(os.path.join(session_dir, x)), reverse=True)
            if len(files)>0:
                dest_path = os.path.join(session_dir, files[0])
            else:
                print(f"""   No sessions found in {session_dir}""")
                return 0

        print(f"   from {dest_path}")
        start_if_not_running=not args.do_not_start
        action_load(dest_path,start_if_not_running)


def action_save(dest_path):
    """
    Saves the current Word session to a file.

    Saves the currently open documents in the running Word instance to a JSON file.

    Args:
        dest_path (str): The path to the file to save the session to.

    Returns:
        None
    """
    print("    Getting Word COM interface...")
    try:
        word_app = get_word_com(start_if_not_running=False)
    except Exception as e:
        print("""     ERROR: Could not get Word instance
    Is Word running?""")
        raise e
    print("    Reading all open files...")
    session = get_current_word_documents(word_app)
    print(f"    Writing {dest_path}...")
    with open(dest_path, "w") as f:
        json.dump({"word-session:": session}, f, indent=4)
    print("    ...Done")


def action_load(dest_path, start_if_not_running=True):
    """
    Loads the Word session from a file.

    Loads a session from a JSON file and loads all the documents in the session into Word.

    Args:
        dest_path (str): The path to the JSON file to load the session from
    
    Returns:
        None
    """
    with open(dest_path, "r") as f:
        session = json.load(f)["word-session:"]
    print(f"""   Session contents:
-------------------
{json.dumps(session, indent=4)}
-------------------""")
    try:
        word_app = get_word_com(start_if_not_running)
    except Exception as e:
        print("""     ERROR: Could not get Word instance
    Is Word running?""")
        if not start_if_not_running:
            print("""   You specified not to start Word.""")
            print("""   Not loading session.""")
            return 
        else:
            raise e
    word_app.Visible = True
    for doc in session:
        word_app.Documents.Open(doc["FullName"])
        goto_line_in_word_document(
            word_app, doc["Page"], doc["Line"]
        )


# %%
if __name__ == "__main__":
    main()

# %%
