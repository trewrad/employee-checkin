import streamlit as st
import qrcode
import json
import secrets
import base64
from googleapiclient.discovery import build
from google.oauth2 import service_account
from datetime import datetime
import onetimepass

# --- CONFIGURATION ---
CONFIG_FILE = "config.json"
EMPLOYEE_DATA_FILE = "employee_data.json"
TIME_ENTRIES_FILE = "time_entries.json"

# Load configuration
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        st.error(f"Configuration file '{CONFIG_FILE}' not found.")
        return None
    except json.JSONDecodeError:
        st.error(f"Error decoding JSON in '{CONFIG_FILE}'.")
        return None

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

def sync_to_google_sheets(config, time_entries):
    try:
        service = get_google_sheets_service(config)
        spreadsheet_id = config["googleSheets"]["spreadsheetId"]
        range_name = "Sheet1"  # Adjust if needed

        values = [[entry["employeeId"], entry["timestamp"], entry["type"]] for entry in time_entries]
        body = {"values": values}

        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            body=body
        ).execute()

        st.success(f"Synced {len(values)} entries to Google Sheets.")

    except Exception as e:
        st.error(f"Error syncing to Google Sheets: {e}")

# --- OFFLINE FALLBACK ---
def handle_offline_entry(employee_id, timestamp, entry_type):
    time_entries = load_time_entries()
    time_entries.append({"employeeId": employee_id, "timestamp": timestamp, "type": entry_type})
    save_time_entries(time_entries)
    st.success("Entry saved locally. Will sync when online.")

# --- MAIN APP ---
def main():
    st.title("Employee Check-in System")

    config = load_config()
    if not config:
        return

    if "employee_data" not in st.session_state:
        st.session_state["employee_data"] = load_employee_data()

    # --- SIDEBAR ---
    st.sidebar.title("Admin Control Panel")
    admin_password = st.sidebar.text_input("Admin Password", type="password", key="admin_password")

    if st.session_state.get("admin_password", "") == config.get("adminPassword", "admin"):
        # --- ADMIN PAGE ---
        admin_page = st.sidebar.selectbox("Admin Actions", ["Add Employee", "Manual Time Entry", "View Conflicts", "Sync to Google Sheets", "Manage Employees"])

        if admin_page == "Add Employee":
            employee_id = st.text_input("Employee ID")
            employee_name = st.text_input("Employee Name")
            if st.button("Generate TOTP Secret"):
                def generate_otp_secret():
                    # Generate 20 random bytes
                    secret_bytes = secrets.token_bytes(20)
                    
                    # Encode to base32
                    secret_base32 = base64.b32encode(secret_bytes).decode('utf-8')
                    
                    return secret_base32

                secret = generate_otp_secret()
                import urllib.parse
                employee_id_encoded = urllib.parse.quote(employee_id)
                secret_encoded = urllib.parse.quote(secret)
                otp_path = f"otpauth://totp/EmployeeCheckin:${employee_id_encoded}?secret={secret_encoded}&issuer=EmployeeCheckin"
                img = qrcode.make(otp_path)
                import io
                buffer = io.BytesIO()
                img.save(buffer, format="PNG")
                st.image(buffer.getvalue(), caption="Scan this QR code with your authenticator app")
                st.write(f"Secret: {secret}")

                if st.button("Save Employee"):
                    if employee_id in st.session_state["employee_data"]:
                        st.error("Employee ID already exists.")
                    else:
                        st.session_state["employee_data"][employee_id] = {"name": employee_name, "totpSecret": secret}
                        st.write(f"Adding employee {employee_id} to session state: {st.session_state['employee_data']}")
                        save_employee_data(st.session_state["employee_data"])
                        st.write(f"Employee data after save: {st.session_state['employee_data']}")
                        st.success(f"Employee '{employee_name}' added successfully.")
            def clear_admin_password():
                st.session_state["admin_password"] = ""
            st.button("Back to Time Logging", on_click=clear_admin_password)

        elif admin_page == "Manual Time Entry":
            employee_id = st.selectbox("Employee ID", list(st.session_state["employee_data"].keys()))
            entry_type = st.selectbox("Entry Type", ["in", "out"])
            if st.button("Add Manual Entry"):
                timestamp = datetime.now().isoformat()
                handle_offline_entry(employee_id, timestamp, entry_type)
            def clear_admin_password():
                st.session_state["admin_password"] = ""
            st.button("Back to Time Logging", on_click=clear_admin_password)

        elif admin_page == "View Conflicts":
            st.write("Conflict resolution will be implemented here.")
            def clear_admin_password():
                st.session_state["admin_password"] = ""
            st.button("Back to Time Logging", on_click=clear_admin_password)

        elif admin_page == "Sync to Google Sheets":
            time_entries = load_time_entries()
            sync_to_google_sheets(config, time_entries)
            def clear_admin_password():
                st.session_state["admin_password"] = ""
            st.button("Back to Time Logging", on_click=clear_admin_password)
        
        elif admin_page == "Manage Employees":
            st.subheader("Manage Employees")
            employee_data = st.session_state["employee_data"].copy()
            for employee_id in list(employee_data.keys()):
                employee = employee_data[employee_id]
                st.write(f"Employee ID: {employee_id}")
                new_name = st.text_input("New Name", value=employee["name"], key=f"name_{employee_id}")
                if st.button("Update Name", key=f"update_{employee_id}"):
                    st.session_state["employee_data"][employee_id]["name"] = new_name
                    st.session_state["employee_data"] = st.session_state["employee_data"] # Trigger update
                    save_employee_data(st.session_state["employee_data"])
                    st.success("Employee name updated")
                if st.button("Delete Employee", key=f"delete_{employee_id}"):
                    del st.session_state["employee_data"][employee_id]
                    st.session_state["employee_data"] = st.session_state["employee_data"] # Trigger update
                    save_employee_data(st.session_state["employee_data"])
                    st.success("Employee deleted")
            def clear_admin_password():
                st.session_state["admin_password"] = ""
            st.button("Back to Time Logging", on_click=clear_admin_password)

    if st.session_state.get("admin_password", "") != config.get("adminPassword", "admin"):
        # --- EMPLOYEE CHECK-IN PAGE ---
        st.header("Employee Check-in/Check-out")
        employee_id = st.selectbox(
            "Select Employee",
            options=list(st.session_state["employee_data"].keys()),
            format_func=lambda x: f"{x} - {st.session_state['employee_data'][x]['name']}" if x else ""
        )
        totp_token = st.text_input("Enter TOTP Token")
        check_in_button = st.button("Check In")
        check_out_button = st.button("Check Out")

        if check_in_button:
            is_valid = onetimepass.valid_totp(totp_token, employee_data[employee_id]["totpSecret"])
            if is_valid:
                timestamp = datetime.now().isoformat()
                handle_offline_entry(employee_id, timestamp, "in")
            else:
                st.error("Invalid TOTP token.")

        if check_out_button:
            is_valid = onetimepass.valid_totp(totp_token, employee_data[employee_id]["totpSecret"])
            if is_valid:
                timestamp = datetime.now().isoformat()
                handle_offline_entry(employee_id, timestamp, "out")
            else:
                st.error("Invalid TOTP token.")

if __name__ == "__main__":
    main()
