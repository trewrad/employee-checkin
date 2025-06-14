import io
import streamlit as st
import qrcode
import json
import secrets
import base64
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime
import onetimepass
import urllib

# --- CONFIGURATION ---
EMPLOYEE_DATA_FILE = "employee_data.json"
TIME_ENTRIES_FILE = "time_entries.json"

def get_google_sheets_service():
    """Builds the Google Sheets service object using credentials from st.secrets."""
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    
    # Create credentials from the dictionary-like st.secrets object
    creds = service_account.Credentials.from_service_account_info(
        st.secrets["google_credentials"], scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

# Load employee data
def load_employee_data():
    try:
        with open(EMPLOYEE_DATA_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        st.error(f"Error decoding JSON in '{EMPLOYEE_DATA_FILE}'.")
        return {}

# Save employee data
def save_employee_data(data):
    with open(EMPLOYEE_DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)
    st.session_state["employee_data"] = data

# Load time entries
def load_time_entries():
    try:
        with open(TIME_ENTRIES_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        st.error(f"Error decoding JSON in '{TIME_ENTRIES_FILE}'.")
        return []

# Save time entries
def save_time_entries(data):
    with open(TIME_ENTRIES_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- GOOGLE SHEETS INTEGRATION ---
def get_google_sheets_service(config):
    SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
    creds = service_account.Credentials.from_service_account_file(
        config["googleSheets"]["keyFile"], scopes=SCOPES)
    return build('sheets', 'v4', credentials=creds)

def sync_to_google_sheets(config, time_entries, employee_data):
    """
    Attempts to sync a list of time entries to Google Sheets.
    Adds a header if the sheet is empty and formats the data for readability.
    This version includes robust error handling for data formatting.
    """
    try:
        service = get_google_sheets_service(config)
        spreadsheet_id = config["googleSheets"]["spreadsheetId"]
        range_name = "Sheet1"

        result = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        is_empty = not result.get('values')

        values_to_send = []
        if is_empty:
            values_to_send.append(["Employee ID", "Employee Name", "Timestamp", "Type"])

        # Prepare the formatted data rows
        for entry in time_entries:
            try:
                # This block attempts to format the data for each row
                ts_object = datetime.fromisoformat(entry["timestamp"])
                friendly_ts = ts_object.strftime("%b %d %I:%M %p")
                capitalized_type = entry["type"].capitalize()
            except (ValueError, TypeError) as e:
                # If formatting fails for any reason (e.g., unexpected timestamp format),
                # fall back to using the raw data for that specific row.
                st.warning(f"Could not format entry for Employee ID {entry.get('employeeId', 'N/A')}. Error: {e}. Syncing raw data for this row.")
                friendly_ts = entry.get("timestamp", "INVALID_TIMESTAMP")
                capitalized_type = entry.get("type", "N/A")

            row = [
                entry["employeeId"],
                employee_data.get(entry["employeeId"], {}).get("name", "Unknown"),
                friendly_ts,
                capitalized_type
            ]
            values_to_send.append(row)

        if len(values_to_send) == (1 if is_empty else 0):
             return True, "No new entries to sync."

        body = {"values": values_to_send}

        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        return True, f"Synced {len(time_entries)} entries to Google Sheets."

    except Exception as e:
        return False, f"Error syncing to Google Sheets: {e}"

def handle_entry(employee_id, entry_type, config, employee_data):
    """
    Handles a new time entry by saving it locally first, then attempting to sync.
    """
    # 1. Create the new entry dictionary
    timestamp = datetime.now().isoformat()
    entry = {"employeeId": employee_id, "timestamp": timestamp, "type": entry_type}

    # 2. Always save the new entry to the local log first
    time_entries = load_time_entries()
    time_entries.append(entry)
    save_time_entries(time_entries)

    # 3. Attempt to sync just the new entry to Google Sheets
    success, message = sync_to_google_sheets(config, [entry], employee_data)

    # 4. Report the result to the user
    if success:
        st.success("Check-in/out recorded and synced to Google Sheets.")
    else:
        st.warning("Check-in/out has been recorded locally, but the online sync failed.")
        st.error(message) # Show the specific error to the user

# --- OFFLINE FALLBACK ---
def handle_offline_entry(employee_id, timestamp, entry_type):
    time_entries = load_time_entries()
    time_entries.append({"employeeId": employee_id, "timestamp": timestamp, "type": entry_type})
    save_time_entries(time_entries)
    st.success("Entry saved locally. Will sync when online.")

# --- MAIN APP ---
def main():
    st.title("Employee Check-in System")

    # Load employee data from JSON into the session state if it's not already there
    if "employee_data" not in st.session_state:
        st.session_state["employee_data"] = load_employee_data()
    
    # Create a reference to the employee data for easier access
    employee_data = st.session_state["employee_data"]

    # --- SIDEBAR & ADMIN ACCESS ---
    st.sidebar.title("Admin Control Panel")
    admin_password_input = st.sidebar.text_input("Admin Password", type="password", key="admin_password")

    # Check if the entered password matches the one in st.secrets
    if st.session_state.get("admin_password", "") == st.secrets.get("adminPassword", "admin"):
        
        admin_page = st.sidebar.selectbox("Admin Actions", ["Add Employee", "Manual Time Entry", "View Conflicts", "Sync to Google Sheets", "Manage Employees"])

        def clear_admin_password():
            st.session_state["admin_password"] = ""

        # --- ADMIN PAGE: ADD EMPLOYEE ---
        if admin_page == "Add Employee":
            st.subheader("Add a New Employee")
            employee_id = st.text_input("Employee ID")
            employee_name = st.text_input("Employee Name")

            if "new_employee_secret" not in st.session_state:
                st.session_state.new_employee_secret = None

            if st.button("Generate TOTP Secret"):
                if employee_id and employee_name:
                    secret_bytes = secrets.token_bytes(20)
                    secret = base64.b32encode(secret_bytes).decode('utf-8')
                    st.session_state.new_employee_secret = secret
                else:
                    st.warning("Please enter an Employee ID and Name before generating a secret.")

            if st.session_state.new_employee_secret:
                secret = st.session_state.new_employee_secret
                employee_id_encoded = urllib.parse.quote(employee_id)
                otp_path = f"otpauth://totp/EmployeeCheckin:{employee_id_encoded}?secret={secret}&issuer=EmployeeCheckin"
                img = qrcode.make(otp_path)
                
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                st.image(buf.getvalue(), caption="Scan this QR code with your authenticator app")
                st.code(f"Secret: {secret}")

                if st.button("Save Employee"):
                    if not employee_id:
                        st.error("Employee ID cannot be empty.")
                    elif employee_id in employee_data:
                        st.error("Employee ID already exists.")
                    else:
                        employee_data[employee_id] = {"name": employee_name, "totpSecret": secret}
                        save_employee_data(employee_data)
                        st.success(f"Employee '{employee_name}' added successfully.")
                        st.session_state.new_employee_secret = None
                        st.rerun()

            st.sidebar.button("Log Out of Admin", on_click=clear_admin_password)

        # --- ADMIN PAGE: MANUAL TIME ENTRY ---
        elif admin_page == "Manual Time Entry":
            st.subheader("Manual Time Entry")
            employee_id = st.selectbox("Select Employee", list(employee_data.keys()), format_func=lambda x: f"{x} - {employee_data[x]['name']}")
            entry_type = st.selectbox("Entry Type", ["in", "out"])
            if st.button("Add Manual Entry"):
                handle_entry(employee_id, entry_type, employee_data)
            st.sidebar.button("Log Out of Admin", on_click=clear_admin_password)

        # --- ADMIN PAGE: VIEW CONFLICTS ---
        elif admin_page == "View Conflicts":
            st.subheader("View Conflicts")
            st.write("Conflict resolution can be implemented here.")
            st.sidebar.button("Log Out of Admin", on_click=clear_admin_password)

        # --- ADMIN PAGE: SYNC TO GOOGLE SHEETS ---
        elif admin_page == "Sync to Google Sheets":
            st.subheader("Full Re-Sync to Google Sheets")
            st.warning("This action will clear all data in the Google Sheet and replace it with the complete log from the local file. Use this for recovery if the sheet becomes out of sync.")
            
            time_entries = load_time_entries()
            if not time_entries:
                st.info("The local entry log is empty.")
            else:
                if st.button(f"Clear Sheet and Sync All {len(time_entries)} Entries"):
                    try:
                        service = get_google_sheets_service()
                        spreadsheet_id = st.secrets["googleSheets"]["spreadsheetId"]
                        
                        service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range="Sheet1").execute()
                        
                        success, message = sync_to_google_sheets(time_entries, employee_data)
                        
                        if success:
                            st.success("Successfully cleared the sheet and performed a full re-sync.")
                        else:
                            st.error(f"Full re-sync failed: {message}")
                    except Exception as e:
                        st.error(f"An error occurred during the full sync process: {e}")
            st.sidebar.button("Log Out of Admin", on_click=clear_admin_password)

        # --- ADMIN PAGE: MANAGE EMPLOYEES ---
        elif admin_page == "Manage Employees":
            st.subheader("Manage Existing Employees")
            for employee_id in list(employee_data.keys()):
                with st.expander(f"{employee_id} - {employee_data[employee_id]['name']}"):
                    new_name = st.text_input("Update Name", value=employee_data[employee_id]['name'], key=f"name_{employee_id}")
                    if st.button("Update Name", key=f"update_{employee_id}"):
                        employee_data[employee_id]['name'] = new_name
                        save_employee_data(employee_data)
                        st.success(f"Name updated for {employee_id}.")
                        st.rerun()
                    if st.button("Delete Employee", type="primary", key=f"delete_{employee_id}"):
                        del employee_data[employee_id]
                        save_employee_data(employee_data)
                        st.success(f"Employee {employee_id} has been deleted.")
                        st.rerun()
            st.sidebar.button("Log Out of Admin", on_click=clear_admin_password)

    # --- REGULAR USER VIEW (NOT ADMIN) ---
    else:
        st.header("Employee Check-in/Check-out")
        
        if not employee_data:
            st.info("No employees found. Please contact an administrator to add employees to the system.")
        else:
            employee_id = st.selectbox(
                "Select Your Name",
                options=list(employee_data.keys()),
                format_func=lambda x: f"{employee_data[x]['name']} ({x})" if x in employee_data else ""
            )
            totp_token = st.text_input("Enter 6-Digit Code from Authenticator App", max_chars=6)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Check In", type="primary", use_container_width=True):
                    if totp_token and onetimepass.valid_totp(totp_token, employee_data[employee_id]["totpSecret"]):
                        handle_entry(employee_id, "in", employee_data)
                    else:
                        st.error("Invalid or empty code.")
            with col2:
                if st.button("Check Out", use_container_width=True):
                    if totp_token and onetimepass.valid_totp(totp_token, employee_data[employee_id]["totpSecret"]):
                        handle_entry(employee_id, "out", employee_data)
                    else:
                        st.error("Invalid or empty code.")

if __name__ == "__main__":
    main()
